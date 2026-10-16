/*
 * A room's standing pieces.
 *
 * The GBA draws a room at 45 degrees: a thing H pixels tall is drawn H pixels
 * north of where it stands. A piece is a rectangle of the drawing ending at
 * row `ybot` and H pixels tall: the drawing's rows within H of ybot are its
 * front, standing at ybot's edge; the rows above lie H up, its top. A pixel
 * at row P of the drawing therefore stands at
 *
 *     front: z = ybot,          height = ybot * 16 - P
 *     top:   z = (P + H) / 16,  height = H
 *
 * and z - height is P / 16 either way: from the GBA's angle the drawing,
 * from any other a box with straight sides - never the ramps and wedges a
 * heightfield laid over the room made of every table. A card is a piece all
 * front; the back wall is one too, opaque.
 */
#include <stddef.h>

#include "voxel_room.h"
#include "voxel_tree.h"
#include "voxel_atlas.h"
#include "voxel_room_table.h"

#define TEX_U(px) ((float)(px) / VOXEL_TREE_TEXTURE_DIM)
#define TEX_V(py) (1.0f - (float)(py) / VOXEL_TREE_TEXTURE_H)
#define ROOM_LAYOUTS (sizeof(sRoomLayouts) / sizeof(sRoomLayouts[0]))

/* The layout's run of cells, cached for the map last asked about. */
static int RoomRange(const VoxelMapInstance *inst, unsigned *first, unsigned *count)
{
    static int lastLayout = -1, lastIndex = -1;

    if (inst == NULL || !inst->indoor)
        return 0;
    if (inst->layoutId != lastLayout)
    {
        lastLayout = inst->layoutId;
        lastIndex = -1;
        for (unsigned i = 0; i < ROOM_LAYOUTS; ++i)
            if (sRoomLayouts[i].layout == (unsigned)inst->layoutId)
            {
                lastIndex = (int)i;
                break;
            }
    }
    if (lastIndex < 0)
        return 0;
    *first = sRoomLayouts[lastIndex].first;
    *count = sRoomLayouts[lastIndex].count;
    return 1;
}

static int RoomCell(const VoxelMapInstance *inst, int x, int y)
{
    unsigned first, count;
    int lx = x - inst->originX, ly = y - inst->originY;

    if (!RoomRange(inst, &first, &count) || lx < 0 || ly < 0)
        return -1;
    for (unsigned i = first; i < first + count; ++i)
    {
        if (sRoomCells[i].y > ly)
            break;
        if (sRoomCells[i].y == ly && sRoomCells[i].x == lx)
            return (int)i;
    }
    return -1;
}

int VoxelRoom_Ground(const VoxelMapInstance *inst, int x, int y)
{
    int i = RoomCell(inst, x, y);

    if (i < 0)
        return VOXEL_ROOM_NONE;
    if (sRoomCells[i].flags & ROOM_NO_GROUND)
        return VOXEL_ROOM_NO_GROUND;
    if (sRoomCells[i].flags & ROOM_BARE)
        return (int)(VOXEL_BARE_FIRST + sRoomCells[i].ground);
    return sRoomCells[i].ground;
}

/* The cell's piece, its art the rectangle (u0, v0)-(u1, v1): v0 its top row. */
static void EmitCell(VoxelBuilder *b, const VoxelMapInstance *inst, unsigned i,
                     float u0, float v0, float u1, float v1)
{
    const float x0 = (float)(inst->originX + sRoomCells[i].x), x1 = x0 + 1.0f;
    const int ly = sRoomCells[i].y, h = sRoomCells[i].h, ybot = sRoomCells[i].ybot;
    const float oz = (float)inst->originY;
    const int split = ybot * 16 - h;            /* the first row of the front */
    int ps = split - ly * 16;
#define ROW_V(r) (v0 + (v1 - v0) * (float)(r) / 16.0f)
#define COL_U(c) (u0 + (u1 - u0) * (float)(c) / 16.0f)

    if (ps < 0) ps = 0;
    if (ps > 16) ps = 16;
    if (ps > 0)
    {
        float ht = h / 16.0f;
        float za = oz + (ly * 16 + h) / 16.0f;
        const float zb = oz + (ly * 16 + ps + h) / 16.0f;
        float va = ROW_V(0), vb = ROW_V(ps);

        VoxelBuilder_Quad(b, /* top */
            &(VoxelVertex){x0, ht, za, u0, va, 1.0f}, &(VoxelVertex){x1, ht, za, u1, va, 1.0f},
            &(VoxelVertex){x1, ht, zb, u1, vb, 1.0f}, &(VoxelVertex){x0, ht, zb, u0, vb, 1.0f});
        /* a thing drawn all but front on (a television) has no top to
         * speak of: its first row runs on back, so it is not a sheet */
        if (sRoomCells[i].depth != 0)
        {
            float zd = za - sRoomCells[i].depth / 16.0f, v1r = ROW_V(1);

            za = zd;
            VoxelBuilder_Quad(b,
                &(VoxelVertex){x0, ht, zd, u0, va, 1.0f}, &(VoxelVertex){x1, ht, zd, u1, va, 1.0f},
                &(VoxelVertex){x1, ht, zd + sRoomCells[i].depth / 16.0f, u1, v1r, 1.0f},
                &(VoxelVertex){x0, ht, zd + sRoomCells[i].depth / 16.0f, u0, v1r, 1.0f});
            VoxelBuilder_Quad(b, /* its back */
                &(VoxelVertex){x1, ht, zd, u1, va, 0.7f}, &(VoxelVertex){x0, ht, zd, u0, va, 0.7f},
                &(VoxelVertex){x0, 0.0f, zd, u0, v1r, 0.7f}, &(VoxelVertex){x1, 0.0f, zd, u1, v1r, 0.7f});
        }
        /* its sides, where the piece ends: plain, the colour of its frame
         * (a texel of its front's edge) - the drawing's edge column
         * stretched over them was the dark outline, or stripes of the top */
        {
            float su = COL_U(3.5f), sv = ROW_V(8.5f);

            if (sRoomCells[i].flags & ROOM_WEST)
                VoxelBuilder_Quad(b,
                    &(VoxelVertex){x0, ht,   za, su, sv, 0.75f}, &(VoxelVertex){x0, ht,   zb, su, sv, 0.75f},
                    &(VoxelVertex){x0, 0.0f, zb, su, sv, 0.75f}, &(VoxelVertex){x0, 0.0f, za, su, sv, 0.75f});
            su = COL_U(12.5f);
            if (sRoomCells[i].flags & ROOM_EAST)
                VoxelBuilder_Quad(b,
                    &(VoxelVertex){x1, ht,   zb, su, sv, 0.75f}, &(VoxelVertex){x1, ht,   za, su, sv, 0.75f},
                    &(VoxelVertex){x1, 0.0f, za, su, sv, 0.75f}, &(VoxelVertex){x1, 0.0f, zb, su, sv, 0.75f});
        }
    }
    if (ps < 16)
    {
        float z = oz + (float)ybot;
        float ya = (ybot * 16 - (ly * 16 + ps)) / 16.0f, yb = (ybot * 16 - (ly * 16 + 16)) / 16.0f;
        float va = ROW_V(ps), vb = ROW_V(16);

        VoxelBuilder_Quad(b, /* front */
            &(VoxelVertex){x0, ya, z, u0, va, 1.0f}, &(VoxelVertex){x1, ya, z, u1, va, 1.0f},
            &(VoxelVertex){x1, yb, z, u1, vb, 1.0f}, &(VoxelVertex){x0, yb, z, u0, vb, 1.0f});
    }
#undef ROW_V
#undef COL_U
}

int VoxelRoom_AtlasArt(const VoxelMapInstance *inst, int x, int y)
{
    int i = RoomCell(inst, x, y);

    return i >= 0 && (sRoomCells[i].flags & ROOM_ATLAS) ? (int)sRoomCells[i].sx : -1;
}

void VoxelRoom_EmitAtlasCell(VoxelBuilder *builder, const VoxelMapInstance *inst, int x, int y,
                             float u0, float v0, float u1, float v1)
{
    int i = RoomCell(inst, x, y);

    if (i >= 0 && (sRoomCells[i].flags & ROOM_ATLAS))
        EmitCell(builder, inst, (unsigned)i, u0, v0, u1, v1);
}

void VoxelRoom_EmitInstance(VoxelBuilder *builder, const VoxelMapInstance *inst,
                            int x0, int y0, int x1, int y1)
{
    unsigned first, count;

    if (!RoomRange(inst, &first, &count))
        return;
    for (unsigned i = first; i < first + count; ++i)
    {
        int x = inst->originX + sRoomCells[i].x, y = inst->originY + sRoomCells[i].y;

        if (x >= x0 && x < x1 && y >= y0 && y < y1 && !(sRoomCells[i].flags & ROOM_ATLAS))
            EmitCell(builder, inst, i, TEX_U(sRoomCells[i].sx), TEX_V(sRoomCells[i].sy),
                     TEX_U(sRoomCells[i].sx + 16), TEX_V(sRoomCells[i].sy + 16));
    }
}
