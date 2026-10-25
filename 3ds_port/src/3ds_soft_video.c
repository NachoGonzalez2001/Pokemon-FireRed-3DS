/*
 * Native presenter for the software-rendered GBA frame (3ds_softvideo.h).
 *
 * The FireRed port starts without the Emerald port's GPU compositor
 * (3ds_video.c), whose screen modes are laid out for Emerald's own scenes:
 * the game draws its whole 240x160 picture through the platform layer's
 * scanline renderer, and this file puts it on the top screen. It implements
 * the part of the CtrVideo_* interface (3ds_video.h) the rest of the backend
 * calls; the voxel interface it answers as "off".
 *
 * The top screen is set to RGB565 and written directly. Its framebuffer is
 * column-major and rotated: screen pixel (x, y) is fb[x * 240 + 239 - y].
 * The picture is scaled by 1.5 to 360x240, centred, nearest neighbour: every
 * other source pixel is doubled along each axis.
 */
#include <3ds.h>
#if CTR_GPU_PRESENT
#include <citro3d.h>
#include <citro2d.h>
#endif
#include <string.h>

#include "3ds_log.h"
#include "3ds_platform.h"
#include "3ds_softvideo.h"
#include "3ds_video.h"
#include "voxel/ctr_voxel.h"
#include "voxel/voxel_battle.h"
#include <math.h>

#define TOP_WIDTH 400
#define TOP_HEIGHT 240
#define OUT_WIDTH (CTR_SOFT_WIDTH * 3 / 2)   /* 360 */
#define OUT_X ((TOP_WIDTH - OUT_WIDTH) / 2)  /* 20 */

static uint16_t sLut[32768];                 /* BGR555 -> RGB565 */
static const uint16_t *sFrame;
static CtrVideoStats sStats;
static CtrVideoMemory sMemory;
/* Source coordinate of every output column and row. */
static uint8_t sSrcX[OUT_WIDTH];
static uint8_t sSrcY[TOP_HEIGHT];

void CtrSoftVideo_SetFrame(const uint16_t *pixels) { sFrame = pixels; }
static const uint16_t *sUi;
void CtrSoftVideo_SetUi(const uint16_t *pixels) { sUi = pixels; }
static struct { bool on, sliding; float shakeX, shakeY; } sBattle;
static bool sClean, sHold, sBanner;
static bool sDrewVoxel, sFrameDrawn = true;
void CtrSoftVideo_SetBanner(bool banner) { sBanner = banner; }
bool CtrSoftVideo_DrewVoxel(void) { return sDrewVoxel; }
void CtrSoftVideo_SetFrameDrawn(bool drawn) { sFrameDrawn = drawn; }
void CtrSoftVideo_SetClean(bool clean) { sClean = clean; }
void CtrSoftVideo_HoldTop(bool hold)
{
    if (hold != sHold)
        CtrLog_Write(CTR_LOG_VIDEO, "top screen %s at frame %lu", hold ? "held" : "released",
                     (unsigned long)sStats.frames);
    sHold = hold;
}
void CtrSoftVideo_SetBattle(bool on, bool sliding, float shakeX, float shakeY)
{
    sBattle.on = on;
    sBattle.sliding = sliding;
    sBattle.shakeX = shakeX;
    sBattle.shakeY = shakeY;
}
#if CTR_GPU_PRESENT
static bool GpuInit(void);
#endif
static unsigned sVoxelUploads;

bool CtrVideo_Init(void)
{
    for (unsigned c = 0; c < 32768; ++c)
    {
        unsigned r = c & 31, g = (c >> 5) & 31, b = (c >> 10) & 31;
        sLut[c] = (uint16_t)((r << 11) | (((g << 1) | (g >> 4)) << 5) | b);
    }
    for (unsigned x = 0; x < OUT_WIDTH; ++x)
        sSrcX[x] = (uint8_t)(x * 2 / 3);
    for (unsigned y = 0; y < TOP_HEIGHT; ++y)
        sSrcY[y] = (uint8_t)(y * 2 / 3);
#if CTR_GPU_PRESENT
    gfxSet3D(false);
    if (!GpuInit())
        return false;
    CtrLog_Write(CTR_LOG_VIDEO, "software video: %dx%d frame at x1.5 on the top screen, by the GPU",
                 CTR_SOFT_WIDTH, CTR_SOFT_HEIGHT);
    return true;
#endif
    gfxSetScreenFormat(GFX_TOP, GSP_RGB565_OES);
    gfxSet3D(false);
    for (int i = 0; i < 2; ++i)
    {
        uint16_t *fb = (uint16_t *)gfxGetFramebuffer(GFX_TOP, GFX_LEFT, NULL, NULL);
        memset(fb, 0, TOP_WIDTH * TOP_HEIGHT * sizeof(uint16_t));
        gfxFlushBuffers();
        gfxSwapBuffers();
    }
    CtrLog_Write(CTR_LOG_VIDEO, "software video: %dx%d frame at x1.5 on the top screen",
                 CTR_SOFT_WIDTH, CTR_SOFT_HEIGHT);
    return true;
}

void CtrVideo_Shutdown(void) {}

void CtrVideo_Bind(CtrVideoMemory memory) { sMemory = memory; }

#if CTR_GPU_PRESENT
/*
 * The GPU path: the frame is converted to RGB565 into a linear buffer, tiled
 * into a 256x256 texture by a display transfer, and drawn by citro2d scaled
 * by 1.5 into the top screen's render target. The 3D overworld draws into the
 * same target before the frame's 2D parts go over it.
 */
/*
 * The GBA picture at 1.5 is not drawn at 1.5: nearest sampling at a
 * fractional scale makes GBA pixels alternately one and two screen pixels
 * wide, which reads as jagged edges on text and sprites on hardware. It is
 * uploaded at 2 - every GBA pixel an exact 2x2 block - and drawn at 0.75 with
 * bilinear filtering: every pixel the same size, edges a pixel soft ("sharp
 * bilinear", as the Emerald port draws its battle scene). Only the rows the
 * picture fills are written and flushed; the rest stay the zeros of Init.
 */
#define TEX_DIM 512
#define UP 2
#define UP_W (CTR_SOFT_WIDTH * UP)    /* 480 */
#define UP_H (CTR_SOFT_HEIGHT * UP)   /* 320 */
#define DRAW_SCALE (1.5f / UP)
static C3D_RenderTarget *sTop;
static C3D_Tex sFrameTex;
static Tex3DS_SubTexture sFrameSub;
static uint16_t *sLinear;
/* The UI over the 3D overworld: RGBA5551, alpha 0 where nothing is drawn. */
static C3D_Tex sUiTex;
static uint16_t *sUiLinear;
static bool sVoxelReady;
/* The world is drawn upright into this landscape surface, which is then laid
 * on the (rotated) top screen as any image is: the voxel projection knows
 * nothing of the screen's rotation. */
static C3D_Tex sSurface;
static C3D_RenderTarget *sLogical;
static Tex3DS_SubTexture sLogicalSub;
/*
 * The top screen held under a menu (CtrSoftVideo_HoldTop): the last clean 3D
 * frame - the world surface as it was drawn, and its UI layer - kept when the
 * frames stop being clean (a fade, a menu). Only the world's: once a clean
 * frame is the 2D picture, the hold is the game side's copy of that.
 */
static C3D_Tex sHoldTex;
static uint16_t sLastUi[CTR_SOFT_WIDTH * CTR_SOFT_HEIGHT];
static uint16_t sHoldUi[CTR_SOFT_WIDTH * CTR_SOFT_HEIGHT];
static bool sHoldReady, sHoldValid, sSurfaceClean;

#define UI_TRANSFER_FLAGS \
    (GX_TRANSFER_FLIP_VERT(0) | GX_TRANSFER_OUT_TILED(1) | GX_TRANSFER_RAW_COPY(0) | \
     GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGB5A1) | GX_TRANSFER_OUT_FORMAT(GX_TRANSFER_FMT_RGB5A1) | \
     GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_NO))

#define TILE_TRANSFER_FLAGS \
    (GX_TRANSFER_FLIP_VERT(0) | GX_TRANSFER_OUT_TILED(1) | GX_TRANSFER_RAW_COPY(0) | \
     GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGB565) | GX_TRANSFER_OUT_FORMAT(GX_TRANSFER_FMT_RGB565) | \
     GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_NO))

static bool GpuInit(void)
{
    if (!C3D_Init(C3D_DEFAULT_CMDBUF_SIZE) || !C2D_Init(C2D_DEFAULT_MAX_OBJECTS))
        return false;
    C2D_Prepare();
    sTop = C2D_CreateScreenTarget(GFX_TOP, GFX_LEFT);
    sLinear = linearAlloc(TEX_DIM * TEX_DIM * sizeof(uint16_t));
    if (sTop == NULL || sLinear == NULL || !C3D_TexInit(&sFrameTex, TEX_DIM, TEX_DIM, GPU_RGB565))
        return false;
    memset(sLinear, 0, TEX_DIM * TEX_DIM * sizeof(uint16_t));
    C3D_TexSetFilter(&sFrameTex, GPU_LINEAR, GPU_LINEAR);
    sUiLinear = linearAlloc(TEX_DIM * TEX_DIM * sizeof(uint16_t));
    if (sUiLinear == NULL || !C3D_TexInit(&sUiTex, TEX_DIM, TEX_DIM, GPU_RGBA5551))
        return false;
    memset(sUiLinear, 0, TEX_DIM * TEX_DIM * sizeof(uint16_t));
    C3D_TexSetFilter(&sUiTex, GPU_LINEAR, GPU_LINEAR);
#if CTR_VOXEL_ENABLED
    sVoxelReady = CtrVoxel_Init();
    /* After the world's own VRAM, which wants it in one piece. */
    if (sVoxelReady && C3D_TexInitVRAM(&sSurface, 512, 256, GPU_RGBA8))
    {
        C3D_TexSetFilter(&sSurface, GPU_NEAREST, GPU_NEAREST);
        C3D_TexSetWrap(&sSurface, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
        sLogical = C3D_RenderTargetCreateFromTex(&sSurface, GPU_TEXFACE_2D, 0, GPU_RB_DEPTH16);
        sLogicalSub = (Tex3DS_SubTexture){ TOP_WIDTH, TOP_HEIGHT, 0.0f, 1.0f,
                                           TOP_WIDTH / 512.0f, 1.0f - TOP_HEIGHT / 256.0f };
    }
    sVoxelReady = sVoxelReady && sLogical != NULL;
    /* In linear memory: it is only read, a quad's worth a frame. */
    sHoldReady = sVoxelReady && C3D_TexInit(&sHoldTex, 512, 256, GPU_RGBA8);
    if (sHoldReady)
    {
        C3D_TexSetFilter(&sHoldTex, GPU_NEAREST, GPU_NEAREST);
        C3D_TexSetWrap(&sHoldTex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    }
    CtrLog_Write(CTR_LOG_VIDEO, "voxel overworld %s", sVoxelReady ? "ready" : "unavailable");
#endif
    /* Without a flip the transfer leaves line 0 of the frame at the top of
     * the texture (v = 1). A subtexture whose top is below its bottom would
     * be taken for a rotated one, so the data is laid out to match instead. */
    sFrameSub = (Tex3DS_SubTexture){ UP_W, UP_H, 0.0f, 1.0f,
                                     UP_W / (float)TEX_DIM, 1.0f - UP_H / (float)TEX_DIM };
    return true;
}

/* One GBA row, every pixel twice, into two rows of the linear buffer. */
static inline void DoubleRow(uint16_t *dst, const uint16_t *row)
{
    uint32_t *out = (uint32_t *)dst;

    for (unsigned x = 0; x < CTR_SOFT_WIDTH; ++x)
        out[x] = row[x] | ((uint32_t)row[x] << 16);
    memcpy(dst + TEX_DIM, dst, UP_W * sizeof(uint16_t));
}

static void GpuUpload(void)
{
    uint16_t row[CTR_SOFT_WIDTH];

    for (unsigned y = 0; y < CTR_SOFT_HEIGHT; ++y)
    {
        const uint16_t *src = sFrame + y * CTR_SOFT_WIDTH;

        for (unsigned x = 0; x < CTR_SOFT_WIDTH; ++x)
            row[x] = sLut[src[x] & 0x7FFF];
        DoubleRow(sLinear + y * UP * TEX_DIM, row);
    }
    GSPGPU_FlushDataCache(sLinear, TEX_DIM * UP_H * sizeof(uint16_t));
    C3D_SyncDisplayTransfer((u32 *)sLinear, GX_BUFFER_DIM(TEX_DIM, TEX_DIM),
                            (u32 *)sFrameTex.data, GX_BUFFER_DIM(TEX_DIM, TEX_DIM), TILE_TRANSFER_FLAGS);
}

static void GpuUploadUi(void)
{
    uint16_t row[CTR_SOFT_WIDTH];

    for (unsigned y = 0; y < CTR_SOFT_HEIGHT; ++y)
    {
        const uint16_t *src = sUi + y * CTR_SOFT_WIDTH;

        for (unsigned x = 0; x < CTR_SOFT_WIDTH; ++x)
        {
            uint16_t c = src[x];

            row[x] = (c & 0x8000) ? (uint16_t)(((c & 31) << 11) | (((c >> 5) & 31) << 6) | (((c >> 10) & 31) << 1) | 1)
                                  : 0;
        }
        DoubleRow(sUiLinear + y * UP * TEX_DIM, row);
    }
    GSPGPU_FlushDataCache(sUiLinear, TEX_DIM * UP_H * sizeof(uint16_t));
    C3D_SyncDisplayTransfer((u32 *)sUiLinear, GX_BUFFER_DIM(TEX_DIM, TEX_DIM),
                            (u32 *)sUiTex.data, GX_BUFFER_DIM(TEX_DIM, TEX_DIM), UI_TRANSFER_FLAGS);
}

#if CTR_VOXEL_ENABLED
/*
 * The 3D battle's shadows under the battlers (VoxelBattle_Shadows): an
 * ellipse of the world's shadow blue fading out from its middle, one small
 * texture stretched to each, between the world and the battle's picture.
 */
#define BATTLE_SHADOW_W 64
#define BATTLE_SHADOW_H 16
#define BATTLE_SHADOW_ALPHA 0.50f
static C3D_Tex sShadowTex;
static bool sShadowFailed;

static bool ShadowTexture(void)
{
    uint32_t *texels;

    if (sShadowTex.data || sShadowFailed)
        return sShadowTex.data != NULL;
    if (!C3D_TexInit(&sShadowTex, BATTLE_SHADOW_W, BATTLE_SHADOW_H, GPU_RGBA8))
    {
        memset(&sShadowTex, 0, sizeof(sShadowTex));
        sShadowFailed = true;
        return false;
    }
    C3D_TexSetFilter(&sShadowTex, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(&sShadowTex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    texels = sShadowTex.data;
    for (unsigned y = 0; y < BATTLE_SHADOW_H; ++y)
        for (unsigned x = 0; x < BATTLE_SHADOW_W; ++x)
        {
            float u = (x + 0.5f) / (BATTLE_SHADOW_W / 2) - 1.0f, v = (y + 0.5f) / (BATTLE_SHADOW_H / 2) - 1.0f;
            float d = 1.0f - (u * u + v * v), a = d > 0.0f ? BATTLE_SHADOW_ALPHA * d * sqrtf(d) : 0.0f;
            /* 8x8 Morton tiles, top row first as the GPU reads them */
            unsigned ty = BATTLE_SHADOW_H - 1 - y;
            unsigned m = 0;

            for (unsigned bit = 0; bit < 3; ++bit)
                m |= ((x >> bit) & 1u) << (2 * bit) | ((ty >> bit) & 1u) << (2 * bit + 1);
            texels[((ty / 8) * (BATTLE_SHADOW_W / 8) + x / 8) * 64 + m] =
                8u << 24 | 20u << 16 | 40u << 8 | (uint32_t)(a * 255.0f + 0.5f);
        }
    C3D_TexFlush(&sShadowTex);
    return true;
}

static void BattleShadows(void)
{
    static const Tex3DS_SubTexture whole = { BATTLE_SHADOW_W, BATTLE_SHADOW_H, 0.0f, 1.0f, 1.0f, 0.0f };
    VoxelBattleShadow shadows[4];
    unsigned count = VoxelBattle_Shadows(shadows, 4);

    if (count == 0 || !ShadowTexture())
        return;
    for (unsigned i = 0; i < count; ++i)
    {
        /* GBA pixels to the top screen: the picture at 1.5, OUT_X across */
        float x = shadows[i].x * 1.5f + OUT_X, y = shadows[i].y * 1.5f;
        float rx = shadows[i].rx * 1.5f, ry = shadows[i].ry * 1.5f;

        C2D_DrawImageAt((C2D_Image){ &sShadowTex, &whole }, x - rx, y - ry, 0.45f, NULL,
                        rx * 2.0f / BATTLE_SHADOW_W, ry * 2.0f / BATTLE_SHADOW_H);
    }
}
#endif

#if CTR_VOXEL_ENABLED
/* The banner's rows, out from the UI layer's edges to the screen's: each
 * row's edge pixel, drawn over the margins at the layer's scale. */
static void BannerEdges(void)
{
    for (unsigned y = 0; y < CTR_SOFT_HEIGHT; ++y)
    {
        for (unsigned side = 0; side < 2; ++side)
        {
            uint16_t c = sUi[y * CTR_SOFT_WIDTH + (side ? CTR_SOFT_WIDTH - 1 : 0)];

            if (!(c & 0x8000))
                continue;
            C2D_DrawRectSolid(side ? (float)(OUT_X + OUT_WIDTH) : 0.0f, y * 1.5f, 0.5f, (float)OUT_X, 1.5f,
                              C2D_Color32((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3, 255));
        }
    }
}
#endif

static void GpuPresent(void)
{
    uint64_t start = svcGetSystemTick(), drawStart, beginTick;
    C2D_Image image = { &sFrameTex, &sFrameSub };
    C2D_Image ui = { &sUiTex, &sFrameSub };
    bool voxel = false;

#if CTR_VOXEL_ENABLED
    /* The field with the 3D world on: the game's side asked for the UI layer.
     * In a battle the same, the world framed by the battle's camera
     * (ctr_voxel.c), the scenery the game would have drawn left out of it. */
    if (sHold)
        voxel = false;
    else if (sVoxelReady && sUi != NULL && sBattle.on && CtrVoxel_IsAvailableForBattle())
    {
        if (!CtrVoxel_InBattle())
            CtrVoxel_BeginBattle();
        CtrVoxel_SetBattleFrame(sBattle.sliding, sBattle.shakeX, sBattle.shakeY);
        voxel = true;
    }
    else
        voxel = sVoxelReady && sUi != NULL && CtrVoxel_IsAvailable();
#endif
    /* Held on the 3D world's last clean frame, or on the picture given. */
    bool held = sHold && sHoldValid;
    /* A new map's world still being built: black under the UI meanwhile, not
     * the 2D picture - it flashed in for a moment as a warp faded in. */
    bool warming = false;

    if (held)
    {
        const uint16_t *ui = sUi;

        sUi = sHoldUi;
        GpuUploadUi();
        sUi = ui;
    }
    else if (sFrame && !voxel && sFrameDrawn)
        GpuUpload();
    else if (!voxel && sUi != NULL)
        warming = true;     /* no picture this frame: black under the UI */
    if (voxel || warming)
        GpuUploadUi();
    drawStart = svcGetSystemTick();
    /* Begin waits for the previous frame and paces to the screen's 60 Hz. */
    C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
    beginTick = svcGetSystemTick();
    sStats.waitMs = (beginTick - drawStart) * 1000.0f / SYSCLOCK_ARM11;
    sVoxelUploads = 0;
#if CTR_VOXEL_ENABLED
    /* The world's chunks and atlas may not be ready yet (a new map): the 2D
     * picture stands in until they are. */
    if (voxel && !CtrVoxel_Update())
    {
        voxel = false;
        /* without this frame's picture (the world was to stand in for it),
         * black under the UI as while warming up */
        warming = CtrVoxel_IsWarmingUp() || !sFrameDrawn;
        if (sFrame && !warming)
            GpuUpload();
    }
    {
        static unsigned warmFrames;

        if (warming)
            ++warmFrames;
        else if (warmFrames != 0)
        {
            CtrLog_Write(CTR_LOG_VIDEO, "3D world built after %u black frames", warmFrames);
            warmFrames = 0;
        }
    }
    /* The surface still holds the last frame's world: kept if that was the
     * last clean one, before this frame draws over it. Queued inside the
     * frame, the copy runs ahead of the clear below. */
    if (sSurfaceClean && sHoldReady && !(voxel && sClean))
    {
        C3D_SyncTextureCopy((u32 *)sSurface.data, 0, (u32 *)sHoldTex.data, 0, sSurface.size, 8);
        memcpy(sHoldUi, sLastUi, sizeof(sHoldUi));
        sHoldValid = true;
    }
    sSurfaceClean = false;
#endif
    C2D_TargetClear(sTop, C2D_Color32(0, 0, 0, 255));
#if CTR_VOXEL_ENABLED
    if (voxel)
    {
        C2D_Image world = { &sSurface, &sLogicalSub };

        C2D_TargetClear(sLogical, C2D_Color32(0, 0, 0, 255));
        CtrVoxel_Draw(sLogical, 0.0f);
        if (sClean)
        {
            sSurfaceClean = true;
            memcpy(sLastUi, sUi, sizeof(sLastUi));
        }
        /* The world leaves its own shader and state bound, and indoors a
         * blend and fragment mode under which the UI's see-through pixels
         * came out black: back to plain alpha blending. */
        C2D_Prepare();
        C3D_FragOpMode(GPU_FRAGOPMODE_GL);
        C3D_StencilTest(false, GPU_ALWAYS, 0, 0, 0);
        C3D_AlphaTest(true, GPU_GREATER, 0);
        C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA, GPU_ONE_MINUS_SRC_ALPHA,
                       GPU_SRC_ALPHA, GPU_ONE_MINUS_SRC_ALPHA);
        C2D_SceneBegin(sTop);
        C2D_DrawImageAt(world, 0.0f, 0.0f, 0.4f, NULL, 1.0f, 1.0f);
        if (sBattle.on && CtrVoxel_InBattle() && !sBattle.sliding)
            BattleShadows();
#ifndef CTR_NO_UI_OVERLAY
        C2D_DrawImageAt(ui, (float)OUT_X, 0.0f, 0.5f, NULL, DRAW_SCALE, DRAW_SCALE);
        if (sBanner)
            BannerEdges();
#else
        (void)ui;
#endif
    }
    else if (warming)
    {
        C2D_SceneBegin(sTop);
        C2D_DrawImageAt(ui, (float)OUT_X, 0.0f, 0.5f, NULL, DRAW_SCALE, DRAW_SCALE);
    }
    else if (held)
    {
        C2D_Image world = { &sHoldTex, &sLogicalSub };

        C2D_SceneBegin(sTop);
        C2D_DrawImageAt(world, 0.0f, 0.0f, 0.4f, NULL, 1.0f, 1.0f);
        C2D_DrawImageAt(ui, (float)OUT_X, 0.0f, 0.5f, NULL, DRAW_SCALE, DRAW_SCALE);
    }
    else
#endif
    {
        /* A clean 2D picture: the hold is the game side's copy of it now. */
        if (sClean && !sHold)
            sHoldValid = false;
        C2D_SceneBegin(sTop);
        C2D_DrawImageAt(image, (float)OUT_X, 0.0f, 0.5f, NULL, DRAW_SCALE, DRAW_SCALE);
    }
    C3D_FrameEnd(0);
    sDrewVoxel = voxel;
#if CTR_VOXEL_ENABLED
    if (voxel)
        CtrVoxel_AfterSubmit(beginTick);
#endif
    /* C3D_FrameBegin paces the frames to the screen's 60 Hz (its frame rate
     * limit); a second wait here would halve that. */
    sStats.cpuMs = (drawStart - start) * 1000.0f / SYSCLOCK_ARM11;
    ++sStats.frames;
}
#endif

static void Blit(uint16_t *fb)
{
    for (unsigned x = 0; x < OUT_WIDTH; ++x)
    {
        uint16_t *column = fb + (OUT_X + x) * TOP_HEIGHT + (TOP_HEIGHT - 1);
        const uint16_t *src = sFrame + sSrcX[x];

        for (unsigned y = 0; y < TOP_HEIGHT; ++y)
            column[-(int)y] = sLut[src[sSrcY[y] * CTR_SOFT_WIDTH] & 0x7FFF];
    }
}

void CtrVideo_Present(void)
{
#if CTR_GPU_PRESENT
    GpuPresent();
    return;
#endif
    uint64_t start = svcGetSystemTick(), waitStart;
    uint16_t *fb = (uint16_t *)gfxGetFramebuffer(GFX_TOP, GFX_LEFT, NULL, NULL);

    if (sFrame && fb)
        Blit(fb);
    gfxFlushBuffers();
    gfxSwapBuffers();
    waitStart = svcGetSystemTick();
    gspWaitForVBlank();
    sStats.waitMs = (svcGetSystemTick() - waitStart) * 1000.0f / SYSCLOCK_ARM11;
    sStats.cpuMs = (waitStart - start) * 1000.0f / SYSCLOCK_ARM11;
    ++sStats.frames;
}

const CtrVideoStats *CtrVideo_GetStats(void) { return &sStats; }

/* The compositor's scene modes have nothing to do: the frame is whole. */
void CtrVideo_HoldTop(bool hold) { (void)hold; }
void CtrVideo_SetStage(bool stage) { (void)stage; }
void CtrVideo_SetCentred(unsigned screen) { (void)screen; }
void CtrVideo_SetBattle(bool battle) { (void)battle; }
void CtrVideo_SetTransition(bool transition) { (void)transition; }
void CtrVideo_SetFieldBanner(bool banner) { (void)banner; }
void CtrVideo_SetFieldLight(bool on, int x, int y, int radius) { (void)on; (void)x; (void)y; (void)radius; }
void CtrVideo_SetLineWindow(const uint16_t *values, unsigned lines, bool both)
{
    (void)values; (void)lines; (void)both;
}
void CtrVideo_SetLineScroll(unsigned reg, bool wide, const void *values, unsigned lines)
{
    (void)reg; (void)wide; (void)values; (void)lines;
}
void CtrVideo_SetLineRegisters(const uint16_t *regs, unsigned lines) { (void)regs; (void)lines; }
void CtrVideo_NotifyTilesetAnimWrite(const void *dest, unsigned bytes)
{
#if CTR_VOXEL_ENABLED
    uintptr_t base = (uintptr_t)sMemory.vram, address = (uintptr_t)dest;
    unsigned offset;

    if (base == 0 || address < base || address - base >= 0x8000 || bytes == 0)
        return;
    offset = (unsigned)(address - base);
    if (bytes > 0x8000 - offset)
        bytes = 0x8000 - offset;
    CtrVoxel_NotifyTilesetAnimWrite(offset / 32, (offset % 32 + bytes + 31) / 32);
#else
    (void)dest;
    (void)bytes;
#endif
}

#if !CTR_VOXEL_ENABLED
/* No voxel world in this build. */
static const CtrVoxelStats sVoxelStats;
const CtrVoxelStats *CtrVoxel_GetStats(void) { return &sVoxelStats; }
const char *CtrVoxel_Status(void) { return "off"; }
#endif

/*
 * What the voxel renderer (ctr_voxel.c) asks of the presenter: room in this
 * frame's GPU queue for its uploads (a budget per frame), the background VRAM
 * its atlas reads, and the compositor's planes, which this presenter has none
 * of to release.
 */
#define VOXEL_UPLOADS_PER_FRAME 8

bool CtrVideo_TryVoxelUpload(void)
{
    if (sVoxelUploads >= VOXEL_UPLOADS_PER_FRAME)
        return false;
    ++sVoxelUploads;
    return true;
}

unsigned CtrVideo_VoxelUploadsLeft(void)
{
    return VOXEL_UPLOADS_PER_FRAME - sVoxelUploads;
}

const uint8_t *CtrVideo_GetBgVram(void) { return sMemory.vram; }

void CtrVideo_RequestPlaneRelease(void) {}
