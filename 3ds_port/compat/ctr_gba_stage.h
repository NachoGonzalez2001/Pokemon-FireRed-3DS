/*
 * Force-included into the translation units staged as a whole GBA picture
 * (full.mk, CTR_GBA_STAGE_SRCS): the intro, the title screen and the credits.
 *
 * Those screens are one 240x160 composition each, so they are compiled with
 * the GBA geometry (include/gba/defines.h) and the compositor has to know when
 * one of them is on screen to present it as a stage. Their VBlank callbacks
 * are the marker: every one they install goes through the bridge, which
 * remembers it, and the stage lasts while one of those is the active callback.
 * Renaming the call here keeps the game sources untouched; main.h declares the
 * renamed function, so the prototype still matches.
 */
#ifndef CTR_GBA_STAGE_H
#define CTR_GBA_STAGE_H

#define SetVBlankCallback CtrStage_SetVBlankCallback

#endif
