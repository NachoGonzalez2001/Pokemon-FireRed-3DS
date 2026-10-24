#ifndef CTR_SOFTVIDEO_H
#define CTR_SOFTVIDEO_H

#include <stdbool.h>
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
/* The 3D battle: the world drawn as the battle's scenery under the UI layer,
 * the scenery sliding in, and the shake of a hit (BG3's scroll, GBA pixels). */
void CtrSoftVideo_SetBattle(bool on, bool sliding, float shakeX, float shakeY);
/* This frame is the world as it stands, neither fading nor faded: the one a
 * menu that opens later leaves on the top screen. */
void CtrSoftVideo_SetClean(bool clean);
/* A menu runs on the bottom screen: the top keeps the last clean frame - in
 * 3D when that was the 3D world, else the frame SetFrame gives. */
void CtrSoftVideo_HoldTop(bool hold);
/* A field move's banner crosses the UI layer: its rows carried out to the
 * screen's edges, past the GBA picture's. */
void CtrSoftVideo_SetBanner(bool banner);

#endif
