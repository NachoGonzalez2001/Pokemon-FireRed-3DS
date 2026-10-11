#ifndef CTR_SOFTVIDEO_H
#define CTR_SOFTVIDEO_H

#include <stdint.h>

/*
 * The FireRed port's first renderer: the game's frame drawn in software by
 * the platform layer (src/platform/gba_fast_draw.c DrawFrame, line by line
 * with its HBlank effects), handed to the native side, scaled onto the top
 * screen. Free of game headers on both sides of the boundary.
 */
#define CTR_SOFT_WIDTH 240
#define CTR_SOFT_HEIGHT 160

/* Game side, after the VBlank handler has drawn the frame: the GBA BGR555
 * pixels (bit 15 ignored) the next present shows. */
void CtrSoftVideo_SetFrame(const uint16_t *pixels);
/* The 3D overworld frame's UI layer (bit 15 marks drawn pixels), or NULL. */
void CtrSoftVideo_SetUi(const uint16_t *pixels);

#endif
