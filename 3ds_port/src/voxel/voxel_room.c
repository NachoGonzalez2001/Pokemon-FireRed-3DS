/*
 * A room's standing pieces.
 *
 * The GBA draws a room at 45 degrees: a thing H pixels tall is drawn H pixels
 * north of where it stands. A piece is a rectangle of the drawing ending at
 * pixel row `ybot` and H pixels tall: the drawing's rows within H of ybot are
 * its front, standing at ybot; the rows above lie H up, its top. A pixel at
 * row P of the drawing therefore stands at
 *
 *     front: z = ybot,          height = ybot - P
 *     top:   z = (P + H),       height = H          (pixels)
 *
 * and z - height is P either way: from the GBA's angle the drawing, from any
 * other a box with straight sides. A card is a piece all front; the back
 * wall is one too, opaque. `lift` raises a piece onto another one (the
 * flowers on the counter), up and back alike, so it stays on its drawing.
 *
 * A model (ROOM_MODEL) is a box of its own measure instead - h tall, depth
 * deep, standing at ybot: its front the whole drawing from its first row
 * (`top`) down, its top that first row's strip stretched back, its sides the
 * side art the generator made for it. It is for things drawn front on
 * (shelves, a cooler, a television), whose drawing is no top at all.
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

/* The cell's own piece: an overlay standing on it is not. */
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
        if (sRoomCells[i].y == ly && sRoomCells[i].x == lx && !(sRoomCells[i].flags & ROOM_OVERLAY))
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

bool VoxelRoom_StandOn(const VoxelMapInstance *inst, int x, int y, float *rise, float *offZ)
{
    int i = RoomCell(inst, x, y);
    int top, back;

    /* walls and nothing-there; and only a piece that stops low, furniture */
    if (i < 0 || (sRoomCells[i].flags & (ROOM_NO_GROUND | ROOM_FLAT)) || sRoomCells[i].h == 0
     || sRoomCells[i].h + sRoomCells[i].lift > 16)
        return false;
    top = sRoomCells[i].h + sRoomCells[i].lift;
    if (sRoomCells[i].flags & ROOM_MODEL)
    {
        /* a box: its front at its drawing's bottom, `depth` deep */
        back = sRoomCells[i].ybot + sRoomCells[i].lift - sRoomCells[i].depth;
        *offZ = (back + sRoomCells[i].depth * 0.5f) / 16.0f - (sRoomCells[i].y + 0.5f);
    }
    else
    {
        /* the drawn top: its rows above the front, set back by the height
         * (EmitCell) */
        int split = sRoomCells[i].ybot - sRoomCells[i].h, first = sRoomCells[i].y * 16;
        int rows = split - first;

        if (rows < 0)
            rows = 0;
        if (rows > 16)
            rows = 16;
        *offZ = (first + rows * 0.5f + top) / 16.0f - (sRoomCells[i].y + 0.5f);
    }
    *rise = top / 16.0f;
    return true;
}

static void SideQuad(VoxelBuilder *b, float x, float y0, float y1, float za, float zb,
                     float u0, float v0, float u1, float v1, bool east)
{
    if (east)
        VoxelBuilder_Quad(b,
            &(VoxelVertex){x, y1, zb, u1, v0, 0.8f}, &(VoxelVertex){x, y1, za, u0, v0, 0.8f},
            &(VoxelVertex){x, y0, za, u0, v1, 0.8f}, &(VoxelVertex){x, y0, zb, u1, v1, 0.8f});
    else
        VoxelBuilder_Quad(b,
            &(VoxelVertex){x, y1, za, u0, v0, 0.8f}, &(VoxelVertex){x, y1, zb, u1, v0, 0.8f},
            &(VoxelVertex){x, y0, zb, u1, v1, 0.8f}, &(VoxelVertex){x, y0, za, u0, v1, 0.8f});
}

/* A model: the cell's share of the box's front, and with the cell that holds
 * the box's first row, its top and its sides. */
static void EmitModel(VoxelBuilder *b, const VoxelMapInstance *inst, unsigned i,
                      float u0, float v0, float u1, float v1)
{
    const float x0 = (float)(inst->originX + sRoomCells[i].x), x1 = x0 + 1.0f;
    const float oz = (float)inst->originY;
    const int ly = sRoomCells[i].y, top = sRoomCells[i].top, ybot = sRoomCells[i].ybot;
    const float lift = sRoomCells[i].lift / 16.0f;
    const float h = sRoomCells[i].h / 16.0f, depth = sRoomCells[i].depth / 16.0f;
    const float zf = oz + (ybot + sRoomCells[i].lift) / 16.0f;
    const int span = ybot - top;
    int p0 = ly * 16 > top ? ly * 16 : top, p1 = ly * 16 + 16 < ybot ? ly * 16 + 16 : ybot;
#define ROW_V(r) (v0 + (v1 - v0) * (float)(r) / 16.0f)

    if (span <= 0)
        return;
    if (p1 > p0)
    {
        float ya = lift + h * (float)(ybot - p0) / span, yb = lift + h * (float)(ybot - p1) / span;
        float va = ROW_V(p0 - ly * 16), vb = ROW_V(p1 - ly * 16);

        VoxelBuilder_Quad(b,
            &(VoxelVertex){x0, ya, zf, u0, va, 1.0f}, &(VoxelVertex){x1, ya, zf, u1, va, 1.0f},
            &(VoxelVertex){x1, yb, zf, u1, vb, 1.0f}, &(VoxelVertex){x0, yb, zf, u0, vb, 1.0f});
    }
    if (ly == top / 16)
    {
        int r = top - ly * 16, r1 = r + 3 < 16 ? r + 3 : 16;
        float yt = lift + h, za = zf - depth;

        float yw = lift + h * (float)(ybot - sRoomCells[i].tw) / span;
        float ye = lift + h * (float)(ybot - sRoomCells[i].te) / span;
        unsigned flags = sRoomCells[i].flags;

        if (sRoomCells[i].tsx != 0 || sRoomCells[i].tsy != 0)
        {
            /* its top art: each column's first rows, opaque, run back */
            float tu0 = TEX_U(sRoomCells[i].tsx), tu1 = TEX_U(sRoomCells[i].tsx + 16);
            float tv0 = TEX_V(sRoomCells[i].tsy), tv1 = TEX_V(sRoomCells[i].tsy + 16);

            VoxelBuilder_Quad(b,
                &(VoxelVertex){x0, yt, za, tu0, tv0, 1.0f}, &(VoxelVertex){x1, yt, za, tu1, tv0, 1.0f},
                &(VoxelVertex){x1, yt, zf, tu1, tv1, 1.0f}, &(VoxelVertex){x0, yt, zf, tu0, tv1, 1.0f});
        }
        else
            VoxelBuilder_Quad(b, /* top: its first rows, stretched back */
                &(VoxelVertex){x0, yt, za, u0, ROW_V(r), 1.0f}, &(VoxelVertex){x1, yt, za, u1, ROW_V(r), 1.0f},
                &(VoxelVertex){x1, yt, zf, u1, ROW_V(r1), 1.0f}, &(VoxelVertex){x0, yt, zf, u0, ROW_V(r1), 1.0f});
        /* each side as high as the drawing reaches at that edge */
        if (sRoomCells[i].ssx != 0 || sRoomCells[i].ssy != 0)
        {
            float su0 = TEX_U(sRoomCells[i].ssx), su1 = TEX_U(sRoomCells[i].ssx + 16);
            float sv0 = TEX_V(sRoomCells[i].ssy), sv1 = TEX_V(sRoomCells[i].ssy + 16);

            if (flags & ROOM_WEST)
                SideQuad(b, x0 + sRoomCells[i].inw / 16.0f, lift, yw > yt ? yt : yw, za, zf,
                         su0, sv0, su1, sv1, false);
            if (flags & ROOM_EAST)
                SideQuad(b, x1 - sRoomCells[i].ine / 16.0f, lift, ye > yt ? yt : ye, za, zf,
                         su0, sv0, su1, sv1, true);
        }
    }
#undef ROW_V
}

/* The cell's piece, its art the rectangle (u0, v0)-(u1, v1): v0 its top row. */
static void EmitCell(VoxelBuilder *b, const VoxelMapInstance *inst, unsigned i,
                     float u0, float v0, float u1, float v1)
{
    const float x0 = (float)(inst->originX + sRoomCells[i].x), x1 = x0 + 1.0f;
    const int ly = sRoomCells[i].y, h = sRoomCells[i].h, ybot = sRoomCells[i].ybot;
    const int lift = sRoomCells[i].lift;
    const float oz = (float)inst->originY;
    const int split = ybot - h;                 /* the first row of the front */
    int ps = split - ly * 16, pe = ybot - ly * 16;
#define ROW_V(r) (v0 + (v1 - v0) * (float)(r) / 16.0f)
#define COL_U(c) (u0 + (u1 - u0) * (float)(c) / 16.0f)

    if (sRoomCells[i].flags & ROOM_MODEL)
    {
        EmitModel(b, inst, i, u0, v0, u1, v1);
        return;
    }
    if (ps < 0) ps = 0;
    if (ps > 16) ps = 16;
    if (pe > 16) pe = 16;
    if (ps > 0)
    {
        float ht = (h + lift) / 16.0f;
        float za = oz + (ly * 16 + h + lift) / 16.0f;
        const float zb = oz + (ly * 16 + ps + h + lift) / 16.0f;
        float va = ROW_V(0), vb = ROW_V(ps);

        VoxelBuilder_Quad(b, /* top */
            &(VoxelVertex){x0, ht, za, u0, va, 1.0f}, &(VoxelVertex){x1, ht, za, u1, va, 1.0f},
            &(VoxelVertex){x1, ht, zb, u1, vb, 1.0f}, &(VoxelVertex){x0, ht, zb, u0, vb, 1.0f});
        /* a thing drawn all but front on has no top to speak of: its first
         * row runs on back, so it is not a sheet */
        if (sRoomCells[i].depth != 0)
        {
            float zd = za + (sRoomCells[i].cap - sRoomCells[i].depth) / 16.0f;
            float vcap = ROW_V(sRoomCells[i].cap), v1r = ROW_V(sRoomCells[i].cap + 1);

            za = zd;
            VoxelBuilder_Quad(b,
                &(VoxelVertex){x0, ht, zd, u0, vcap, 1.0f}, &(VoxelVertex){x1, ht, zd, u1, vcap, 1.0f},
                &(VoxelVertex){x1, ht, zd + sRoomCells[i].depth / 16.0f, u1, v1r, 1.0f},
                &(VoxelVertex){x0, ht, zd + sRoomCells[i].depth / 16.0f, u0, v1r, 1.0f});
            VoxelBuilder_Quad(b, /* its back */
                &(VoxelVertex){x1, ht, zd, u1, vcap, 0.7f}, &(VoxelVertex){x0, ht, zd, u0, vcap, 0.7f},
                &(VoxelVertex){x0, lift / 16.0f, zd, u0, v1r, 0.7f},
                &(VoxelVertex){x1, lift / 16.0f, zd, u1, v1r, 0.7f});
        }
        if (sRoomCells[i].flags & ROOM_ATLAS)
        {
            /* a wall's sides: its front's edge column, top to bottom, run back */
            if (zb - za >= 4.0f / 16.0f)
            {
                float vf0 = ROW_V(ps < 16 ? ps : 15), vf1 = ROW_V(16);

                if (sRoomCells[i].flags & ROOM_WEST)
                    SideQuad(b, x0, 0.0f, ht, za, zb, COL_U(1.5f), vf0, COL_U(1.5f), vf1, false);
                if (sRoomCells[i].flags & ROOM_EAST)
                    SideQuad(b, x1, 0.0f, ht, za, zb, COL_U(14.5f), vf0, COL_U(14.5f), vf1, true);
            }
        }
        else if (sRoomCells[i].ssx != 0 || sRoomCells[i].ssy != 0)
        {
            /* each side from where the drawing starts at that edge: before
             * it, nothing is drawn there to have a side */
            float su0 = TEX_U(sRoomCells[i].ssx), su1 = TEX_U(sRoomCells[i].ssx + 16);
            float sv0 = TEX_V(sRoomCells[i].ssy), sv1 = TEX_V(sRoomCells[i].ssy + 16);
            float zw = oz + (sRoomCells[i].tw + h + lift) / 16.0f;
            float ze = oz + (sRoomCells[i].te + h + lift) / 16.0f;

            if (zw < za) zw = za;
            if (ze < za) ze = za;
            if ((sRoomCells[i].flags & ROOM_WEST) && zw < zb)
                SideQuad(b, x0 + sRoomCells[i].inw / 16.0f, lift / 16.0f, ht, zw, zb,
                         su0, sv0, su1, sv1, false);
            if ((sRoomCells[i].flags & ROOM_EAST) && ze < zb)
                SideQuad(b, x1 - sRoomCells[i].ine / 16.0f, lift / 16.0f, ht, ze, zb,
                         su0, sv0, su1, sv1, true);
        }
    }
    if (ps < pe)
    {
        float z = oz + (ybot + lift) / 16.0f;
        float ya = (ybot - (ly * 16 + ps) + lift) / 16.0f, yb = (ybot - (ly * 16 + pe) + lift) / 16.0f;
        float va = ROW_V(ps), vb = ROW_V(pe);

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

        if (sRoomCells[i].flags & (ROOM_ATLAS | ROOM_FLAT))
            continue;
        if (x >= x0 && x < x1 && y >= y0 && y < y1)
            EmitCell(builder, inst, i, TEX_U(sRoomCells[i].sx), TEX_V(sRoomCells[i].sy),
                     TEX_U(sRoomCells[i].sx + 16), TEX_V(sRoomCells[i].sy + 16));
    }
}
