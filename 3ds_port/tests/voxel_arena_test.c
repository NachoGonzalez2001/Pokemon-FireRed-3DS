/* The VRAM arena against a byte map of which bytes are taken: pieces never
 * overlap, stay aligned and inside, frees give back exactly what was taken,
 * and a gap is found whenever the map says one exists. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/voxel/voxel_arena.c"

#define SIZE (64u * 1024u)
#define ALIGN 128u
#define SLOTS 64u

static uint8_t sMemory[SIZE];
static uint8_t sTaken[SIZE];

static uint32_t LargestFree(void)
{
    uint32_t best = 0, run = 0;

    for (uint32_t i = 0; i < SIZE; i += ALIGN)
    {
        run = sTaken[i] ? 0 : run + ALIGN;
        if (run > best)
            best = run;
    }
    return best;
}

int main(void)
{
    VoxelArena arena;
    VoxelArenaPiece pieces[SLOTS];
    struct { uint8_t *block; uint32_t size; } live[SLOTS];
    unsigned liveCount = 0;
    unsigned seed = 12345;

    VoxelArena_Init(&arena, sMemory, SIZE, ALIGN, pieces, SLOTS);
    assert(VoxelArena_LargestGap(&arena) == SIZE);

    /* Both ends: a low piece at 0, a high one flush with the end. */
    {
        uint8_t *low = VoxelArena_Alloc(&arena, 1000, false);
        uint8_t *high = VoxelArena_Alloc(&arena, 1000, true);

        assert(low == sMemory);
        assert(high == sMemory + SIZE - 1024);
        VoxelArena_Free(&arena, low);
        VoxelArena_Free(&arena, high);
        assert(arena.used == 0 && arena.count == 0);
    }

    for (unsigned step = 0; step < 200000; ++step)
    {
        seed = seed * 1103515245u + 12345u;
        if (liveCount > 0 && ((seed >> 16) % 3 == 0 || liveCount == SLOTS))
        {
            unsigned pick = (seed >> 8) % liveCount;
            uint32_t offset = (uint32_t)(live[pick].block - sMemory);

            VoxelArena_Free(&arena, live[pick].block);
            memset(sTaken + offset, 0, live[pick].size);
            live[pick] = live[--liveCount];
        }
        else
        {
            uint32_t size = 1 + (seed >> 12) % 12000;
            uint32_t rounded = (size + ALIGN - 1) & ~(ALIGN - 1);
            bool fromTop = (seed >> 20) & 1;
            uint8_t *block = VoxelArena_Alloc(&arena, size, fromTop);

            if (block == NULL)
            {
                /* Refused only when nothing that large is free. */
                assert(LargestFree() < rounded);
                continue;
            }
            uint32_t offset = (uint32_t)(block - sMemory);
            assert(offset % ALIGN == 0 && offset + rounded <= SIZE);
            for (uint32_t i = 0; i < rounded; ++i)
                assert(!sTaken[offset + i]);
            memset(sTaken + offset, 1, rounded);
            live[liveCount].block = block;
            live[liveCount].size = rounded;
            ++liveCount;
        }
        assert(VoxelArena_LargestGap(&arena) == LargestFree());
    }
    while (liveCount > 0)
        VoxelArena_Free(&arena, live[--liveCount].block);
    assert(arena.used == 0 && arena.count == 0 && VoxelArena_LargestGap(&arena) == SIZE);
    /* A pointer that is not a piece is ignored. */
    VoxelArena_Free(&arena, sMemory + 256);
    assert(arena.count == 0);
    printf("PASS: voxel arena\n");
    return 0;
}
