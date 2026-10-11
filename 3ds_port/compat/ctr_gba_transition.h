/*
 * Force-included into the battle transitions (full.mk, CTR_GBA_TRANSITION_SRCS).
 *
 * The transitions are drawn for the GBA screen: their windows are 8-bit edges
 * (WIN0H), and at 400 pixels a full-width window no longer fits in one, so
 * they are compiled with the GBA geometry and the compositor shows them over
 * the field at the battle scene's scale. Their VBlank callbacks go through the
 * bridge, which is how the compositor knows one is on screen; main.h declares
 * the renamed function, so the prototype still matches.
 */
#ifndef CTR_GBA_TRANSITION_H
#define CTR_GBA_TRANSITION_H

#define SetVBlankCallback CtrTransition_SetVBlankCallback

#endif
