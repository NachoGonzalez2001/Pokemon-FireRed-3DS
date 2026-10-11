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
#if CTR_GPU_PRESENT
static bool GpuInit(void);
#endif

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
#define TEX_DIM 256
static C3D_RenderTarget *sTop;
static C3D_Tex sFrameTex;
static Tex3DS_SubTexture sFrameSub;
static uint16_t *sLinear;

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
    C3D_TexSetFilter(&sFrameTex, GPU_NEAREST, GPU_NEAREST);
    /* Without a flip the transfer leaves line 0 of the frame at the top of
     * the texture (v = 1). A subtexture whose top is below its bottom would
     * be taken for a rotated one, so the data is laid out to match instead. */
    sFrameSub = (Tex3DS_SubTexture){ CTR_SOFT_WIDTH, CTR_SOFT_HEIGHT, 0.0f, 1.0f,
                                     CTR_SOFT_WIDTH / (float)TEX_DIM, 1.0f - CTR_SOFT_HEIGHT / (float)TEX_DIM };
    return true;
}

static void GpuUpload(void)
{
    for (unsigned y = 0; y < CTR_SOFT_HEIGHT; ++y)
    {
        const uint16_t *src = sFrame + y * CTR_SOFT_WIDTH;
        uint16_t *dst = sLinear + y * TEX_DIM;

        for (unsigned x = 0; x < CTR_SOFT_WIDTH; ++x)
            dst[x] = sLut[src[x] & 0x7FFF];
    }
    GSPGPU_FlushDataCache(sLinear, TEX_DIM * TEX_DIM * sizeof(uint16_t));
    C3D_SyncDisplayTransfer((u32 *)sLinear, GX_BUFFER_DIM(TEX_DIM, TEX_DIM),
                            (u32 *)sFrameTex.data, GX_BUFFER_DIM(TEX_DIM, TEX_DIM), TILE_TRANSFER_FLAGS);
}

static void GpuPresent(void)
{
    uint64_t start = svcGetSystemTick(), drawStart;
    C2D_Image image = { &sFrameTex, &sFrameSub };

    if (sFrame)
        GpuUpload();
    drawStart = svcGetSystemTick();
    /* Begin waits for the previous frame and paces to the screen's 60 Hz. */
    C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
    sStats.waitMs = (svcGetSystemTick() - drawStart) * 1000.0f / SYSCLOCK_ARM11;
    C2D_TargetClear(sTop, C2D_Color32(0, 0, 0, 255));
    C2D_SceneBegin(sTop);
    C2D_DrawImageAt(image, (float)OUT_X, 0.0f, 0.5f, NULL, 1.5f, 1.5f);
    C3D_FrameEnd(0);
    /* The game advances one frame per VBlank, as on the GBA: FrameBegin only
     * waits for the GPU, which a light frame finishes well before that. */
    {
        uint64_t waitStart = svcGetSystemTick();

        gspWaitForVBlank();
        sStats.waitMs += (svcGetSystemTick() - waitStart) * 1000.0f / SYSCLOCK_ARM11;
    }
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
void CtrVideo_NotifyTilesetAnimWrite(const void *dest, unsigned bytes) { (void)dest; (void)bytes; }

/* No voxel world in this build. */
static const CtrVoxelStats sVoxelStats;
const CtrVoxelStats *CtrVoxel_GetStats(void) { return &sVoxelStats; }
const char *CtrVoxel_Status(void) { return "off"; }
