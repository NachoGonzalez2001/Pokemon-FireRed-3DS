#ifndef GUARD_PORT_PROF_H
#define GUARD_PORT_PROF_H

/*
 * Frame profiler: where a frame's time goes, by section. Each section adds
 * the ticks between its begin and end to this frame's total; sections nest,
 * so the figures are inclusive (the I/O inside a decompression counts in
 * both). The platform reports the frame and clears it at present.
 * Reachable from game translation units: no SDK header here.
 */

#include <stdint.h>

enum
{
    PORT_PROF_TASKS,      /* RunTasks */
    PORT_PROF_SPRITES,    /* AnimateSprites + BuildOamBuffer */
    PORT_PROF_FADE,       /* UpdatePaletteFade */
    PORT_PROF_VBLANK,     /* the game's VBlank handler */
    PORT_PROF_VBLANK_CB,  /* gMain.vblankCallback */
    PORT_PROF_DMA3,       /* ProcessDma3Requests */
    PORT_PROF_MIX,        /* m4aSoundMain */
    PORT_PROF_IO,         /* asset payloads read from storage */
    PORT_PROF_LZ,         /* LZ77 / RL decompression */
    PORT_PROF_COPY,       /* CpuSet, CpuFastSet, DMA */
    PORT_PROF_LINES,      /* scanline registers played through */
    PORT_PROF_PALETTE,    /* compositor: palette and fade detection */
    PORT_PROF_LAYERS,     /* compositor: layer textures */
    PORT_PROF_DRAW,       /* compositor: geometry for the frame */
    PORT_PROF_FRAMEEND,   /* C3D_FrameEnd */
    PORT_PROF_COUNT
};

uint32_t Port_ProfTick(void);
void Port_ProfAdd(unsigned section, uint32_t start);
/* The screen the frame belongs to, named in the log by its callback. */
void Port_ProfScene(const void *callback2);

#define PORT_PROF_BEGIN(name) uint32_t portProf_##name = Port_ProfTick()
#define PORT_PROF_END(name, section) Port_ProfAdd((section), portProf_##name)

#endif
