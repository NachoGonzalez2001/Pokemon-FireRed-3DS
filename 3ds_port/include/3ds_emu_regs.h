#ifndef CTR_EMU_REGS_H
#define CTR_EMU_REGS_H

#if !defined(PORTABLE) || !defined(PLATFORM_3DS)
#error Invalid platform configuration for ARM11
#endif

/* Reuse the portable register bank and aligned PLTT/VRAM/OAM in bios.c.
 * These four registers share storage with GetGpuReg/SetGpuReg; there is no
 * physical register overlay that needs separate globals. */
#include "global.h"

void CtrEmu_Reset(void);
void CtrEmu_BeginVBlank(void);
void CtrEmu_EndVBlank(void);

#endif
