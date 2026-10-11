/*
 * A block of memory claimed once and handed out in pieces.
 *
 * The chunk meshes and the building pages used to come straight from the
 * console's VRAM allocator, a few thousand variable-sized pieces over an hour
 * of play, freed in whatever order the caches evicted them. VRAM ended up in
 * crumbs: 1.5 MiB free and no 512 KiB piece anywhere, so a city's building
 * page could not load at all. Each cache now claims its whole budget as one
 * block at start-up and cuts it here, where the fragmentation stays inside the
 * cache that caused it, and where the cache can cure it by evicting.
 *
 * First fit over an address-ordered list of live pieces; freeing merges by
 * construction, because a gap is simply the space between two neighbours.
 * Pieces may be taken from the low end or the high end: large and small ones
 * kept at opposite ends do not strand each other. Nothing here touches the
 * memory itself, so it is tested on the host.
 */
#ifndef CTR_VOXEL_ARENA_H
#define CTR_VOXEL_ARENA_H

#include <stdbool.h>
#include <stdint.h>

typedef struct
{
    uint32_t offset, size;
} VoxelArenaPiece;

typedef struct
{
    uint8_t *base;
    uint32_t size, align;
    VoxelArenaPiece *pieces; /* live, by address */
    unsigned count, capacity;
    uint32_t used;
} VoxelArena;

/* `pieces` holds `capacity` entries: at most that many pieces live at once.
 * `align` is a power of two; every piece starts and ends on it. */
void VoxelArena_Init(VoxelArena *arena, void *base, uint32_t size, uint32_t align,
                     VoxelArenaPiece *pieces, unsigned capacity);
/* NULL if no gap is large enough (or the piece table is full). */
void *VoxelArena_Alloc(VoxelArena *arena, uint32_t size, bool fromTop);
void VoxelArena_Free(VoxelArena *arena, void *block);
/* The largest piece that would fit right now. */
uint32_t VoxelArena_LargestGap(const VoxelArena *arena);

#endif
