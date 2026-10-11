/* See voxel_arena.h. */
#include <string.h>

#include "voxel_arena.h"

void VoxelArena_Init(VoxelArena *arena, void *base, uint32_t size, uint32_t align,
                     VoxelArenaPiece *pieces, unsigned capacity)
{
    arena->base = base;
    arena->align = align != 0 ? align : 1;
    arena->size = size & ~(arena->align - 1);
    arena->pieces = pieces;
    arena->count = 0;
    arena->capacity = capacity;
    arena->used = 0;
}

/* Start of gap i: the end of piece i-1, or the arena's start. */
static uint32_t GapStart(const VoxelArena *arena, unsigned i)
{
    return i == 0 ? 0 : arena->pieces[i - 1].offset + arena->pieces[i - 1].size;
}

static uint32_t GapEnd(const VoxelArena *arena, unsigned i)
{
    return i == arena->count ? arena->size : arena->pieces[i].offset;
}

void *VoxelArena_Alloc(VoxelArena *arena, uint32_t size, bool fromTop)
{
    unsigned at = arena->count + 1;
    uint32_t offset = 0;

    if (arena->base == NULL || size == 0 || arena->count >= arena->capacity)
        return NULL;
    size = (size + arena->align - 1) & ~(arena->align - 1);
    if (size > arena->size)
        return NULL;
    /* Gaps 0..count, the lowest first - or the highest, from the top. */
    for (unsigned n = 0; n <= arena->count; ++n)
    {
        unsigned i = fromTop ? arena->count - n : n;
        uint32_t start = GapStart(arena, i), end = GapEnd(arena, i);

        if (end - start >= size)
        {
            at = i;
            offset = fromTop ? end - size : start;
            break;
        }
    }
    if (at > arena->count)
        return NULL;
    memmove(&arena->pieces[at + 1], &arena->pieces[at],
            (arena->count - at) * sizeof(arena->pieces[0]));
    arena->pieces[at].offset = offset;
    arena->pieces[at].size = size;
    ++arena->count;
    arena->used += size;
    return arena->base + offset;
}

void VoxelArena_Free(VoxelArena *arena, void *block)
{
    uint32_t offset;
    unsigned lo = 0, hi;

    if (block == NULL || arena->base == NULL)
        return;
    offset = (uint32_t)((uint8_t *)block - arena->base);
    hi = arena->count;
    while (lo < hi)
    {
        unsigned mid = (lo + hi) / 2;

        if (arena->pieces[mid].offset < offset)
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo >= arena->count || arena->pieces[lo].offset != offset)
        return; /* not one of ours */
    arena->used -= arena->pieces[lo].size;
    memmove(&arena->pieces[lo], &arena->pieces[lo + 1],
            (arena->count - lo - 1) * sizeof(arena->pieces[0]));
    --arena->count;
}

uint32_t VoxelArena_LargestGap(const VoxelArena *arena)
{
    uint32_t largest = 0;

    if (arena->base == NULL)
        return 0;
    for (unsigned i = 0; i <= arena->count; ++i)
    {
        uint32_t gap = GapEnd(arena, i) - GapStart(arena, i);

        if (gap > largest)
            largest = gap;
    }
    return largest;
}
