/*
 * The engine's own work, timed from outside it: the linker routes every call
 * from another translation unit through these (--wrap, see full.mk), so the
 * game's sources stay as they are. Calls inside the defining unit are not
 * seen, which only matters for decompress.c's own helpers.
 */
#include "global.h"
#include "port_prof.h"

#define PROF_WRAP_VOID(name, section, params, args)   \
    void __real_##name params;                        \
    void __wrap_##name params                         \
    {                                                 \
        PORT_PROF_BEGIN(call);                        \
        __real_##name args;                           \
        PORT_PROF_END(call, section);                 \
    }

PROF_WRAP_VOID(RunTasks, PORT_PROF_TASKS, (void), ())
PROF_WRAP_VOID(AnimateSprites, PORT_PROF_SPRITES, (void), ())
PROF_WRAP_VOID(BuildOamBuffer, PORT_PROF_SPRITES, (void), ())
PROF_WRAP_VOID(ProcessDma3Requests, PORT_PROF_DMA3, (void), ())
PROF_WRAP_VOID(LZ77UnCompWram, PORT_PROF_LZ, (const u32 *src, void *dest), (src, dest))
PROF_WRAP_VOID(LZ77UnCompVram, PORT_PROF_LZ, (const u32 *src, void *dest), (src, dest))
PROF_WRAP_VOID(RLUnCompWram, PORT_PROF_LZ, (const u32 *src, void *dest), (src, dest))
PROF_WRAP_VOID(RLUnCompVram, PORT_PROF_LZ, (const u32 *src, void *dest), (src, dest))
PROF_WRAP_VOID(CpuSet, PORT_PROF_COPY, (const void *src, void *dest, u32 control), (src, dest, control))
PROF_WRAP_VOID(CpuFastSet, PORT_PROF_COPY, (const void *src, void *dest, u32 control), (src, dest, control))
PROF_WRAP_VOID(DmaSet, PORT_PROF_COPY, (int n, const void *src, void *dest, u32 control), (n, src, dest, control))

u8 __real_UpdatePaletteFade(void);
u8 __wrap_UpdatePaletteFade(void)
{
    PORT_PROF_BEGIN(call);
    u8 result = __real_UpdatePaletteFade();
    PORT_PROF_END(call, PORT_PROF_FADE);
    return result;
}
