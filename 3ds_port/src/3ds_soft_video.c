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
