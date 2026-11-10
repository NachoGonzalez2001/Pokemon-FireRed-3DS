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
 *
 * A roof's building, drawn south of the roof's edge (ROOM_HANG), hangs down
 * from that edge instead: a pixel P rows south of it, P rows below it.
 * A fence drawn on a diagonal (ROOM_SLANT) stands on that diagonal, its foot
 * running from row `ybot` at the cell's west edge to row `top` at its east.
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

/* A row on a cell a script changes stands only while the cell holds what the
 * layout does: or a barrier, opened, stays up. */
static bool RowStands(unsigned i, int x, int y)
{
    if (!(sRoomCells[i].flags & ROOM_LIVE))
        return true;
    for (unsigned k = 0; k < sizeof(sRoomLive) / sizeof(sRoomLive[0]); ++k)
        if (sRoomLive[k].row == i)
            return VoxelWorld_GetMetatileId(x, y) == sRoomLive[k].id;
    return true;
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
        if (sRoomCells[i].y == ly && sRoomCells[i].x == lx && !(sRoomCells[i].flags & ROOM_OVERLAY)
         && RowStands(i, x, y))
            return (int)i;
    }
    return -1;
}

/*
 * What scripts lay on a map: Silph Co.'s and the Hideout's gates, the Mansion's
 * barriers and statues, the beams of Vermilion's Gym. They come and go as it
 * plays, so they are found by the metatile the cell holds now and not in the
 * table of the layout's pieces. The entry in sRoomDoors of the one on the cell,
 * or -1. (Sorted by tileset: the map's own run of them, remembered.)
 */
static bool DoorRange(const VoxelMapInstance *inst, unsigned *first, unsigned *end)
{
    enum { DOORS = sizeof(sRoomDoors) / sizeof(sRoomDoors[0]) };
    static const void *lastSet;
    static unsigned lastFirst, lastEnd;

    if (inst->secondaryTileset != lastSet)
    {
        lastSet = inst->secondaryTileset;
        lastFirst = lastEnd = 0;
        for (unsigned d = 0; d < DOORS; ++d)
            if ((const void *)sRoomDoors[d].set == lastSet)
            {
                if (lastEnd == 0)
                    lastFirst = d;
                lastEnd = d + 1;
            }
    }
    *first = lastFirst;
    *end = lastEnd;
    return lastEnd != 0;
}

static int DoorAt(const VoxelMapInstance *inst, int x, int y)
{
    unsigned first, end;
    int id;

    if (!DoorRange(inst, &first, &end))
        return -1;
    id = VoxelWorld_GetMetatileId(x, y);
    for (unsigned d = first; d < end; ++d)
        if (sRoomDoors[d].id == id)
            return (int)d;
    return -1;
}

int VoxelRoom_Ground(const VoxelMapInstance *inst, int x, int y)
{
    int i = RoomCell(inst, x, y);

    if (i < 0)
    {
        /* under a gate: the room's floor */
        int d = DoorAt(inst, x, y);

        return d < 0 ? VOXEL_ROOM_NONE : sRoomDoors[d].floor;
    }
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
    if (i < 0 || (sRoomCells[i].flags & (ROOM_NO_GROUND | ROOM_FLAT | ROOM_NO_STAND)) || sRoomCells[i].h == 0
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
    *offZ -= sRoomCells[i].back / 16.0f;
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
    /* stood `back` pixels north of where its drawing puts it */
    const float oz = (float)inst->originY - sRoomCells[i].back / 16.0f;
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
    const float oz = (float)inst->originY - sRoomCells[i].back / 16.0f;
    const int split = ybot - h;                 /* the first row of the front */
    int ps = split - ly * 16, pe = ybot - ly * 16;
#define ROW_V(r) (v0 + (v1 - v0) * (float)(r) / 16.0f)
#define COL_U(c) (u0 + (u1 - u0) * (float)(c) / 16.0f)

    if (sRoomCells[i].flags & ROOM_MODEL)
    {
        EmitModel(b, inst, i, u0, v0, u1, v1);
        return;
    }
    if (sRoomCells[i].flags & ROOM_HANG)
    {
        /* a roof's building below its edge (row ybot): drawn as far south
         * of the edge as it goes down, so it hangs there */
        float z = oz + ybot / 16.0f;
        float ya = (ybot - ly * 16) / 16.0f, yb = ya - 1.0f;

        VoxelBuilder_Quad(b,
            &(VoxelVertex){x0, ya, z, u0, v0, 1.0f}, &(VoxelVertex){x1, ya, z, u1, v0, 1.0f},
            &(VoxelVertex){x1, yb, z, u1, v1, 1.0f}, &(VoxelVertex){x0, yb, z, u0, v1, 1.0f});
        return;
    }
    if (sRoomCells[i].flags & ROOM_SLANT)
    {
        /* a fence on a diagonal: its foot at row ybot on the cell's west
         * edge, `top` on its east, each pixel standing over it */
        const int te = sRoomCells[i].top;
        float zw = oz + ybot / 16.0f, ze = oz + te / 16.0f;
        float yw = (ybot - ly * 16) / 16.0f, ye = (te - ly * 16) / 16.0f;

        VoxelBuilder_Quad(b,
            &(VoxelVertex){x0, yw, zw, u0, v0, 1.0f}, &(VoxelVertex){x1, ye, ze, u1, v0, 1.0f},
            &(VoxelVertex){x1, ye - 1.0f, ze, u1, v1, 1.0f}, &(VoxelVertex){x0, yw - 1.0f, zw, u0, v1, 1.0f});
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

#define DOOR_LID_H 1.5f     /* a thin gate's height: the walls either side are 2 */
#define DOOR_DEPTH (13.0f / 16.0f)   /* a gate across a solid wall: as thick as the wall */
#define DOOR_BAND 5u        /* the rows of a gate's upper cell over its top */

/* The same drawing as a door of a kind found by its metatile, or -1 */
static int DoorOfId(unsigned first, unsigned end, unsigned id)
{
    for (unsigned d = first; d < end; ++d)
        if (sRoomDoors[d].id == id)
            return (int)d;
    return -1;
}

/* A gate running north to south, its long side: the panels the gate across a
 * corridor shows, a cell of them to a cell, its upper cell over its foot's. */
static void EmitGateSide(VoxelBuilder *b, const VoxelMapInstance *inst, float x, float za, float zb,
                         float h, bool east, float share)
{
    unsigned first, end;
    int upper, foot;

    if (!DoorRange(inst, &first, &end))
        return;
    upper = DoorOfId(first, end, 0x3B0);
    foot = DoorOfId(first, end, 0x3B8);
    if (upper < 0 || foot < 0)
        return;
    {
        const float ua = TEX_U(sRoomDoors[upper].sx), ub = TEX_U(sRoomDoors[upper].sx + 16.0f * share);
        const float uc = TEX_U(sRoomDoors[foot].sx), ud = TEX_U(sRoomDoors[foot].sx + 16.0f * share);

        SideQuad(b, x, 1.0f, h, za, zb, ua, TEX_V(sRoomDoors[upper].sy + DOOR_BAND),
                 ub, TEX_V(sRoomDoors[upper].sy + 16u), east);
        SideQuad(b, x, 0.0f, 1.0f, za, zb, uc, TEX_V(sRoomDoors[foot].sy),
                 ud, TEX_V(sRoomDoors[foot].sy + 16u), east);
    }
}

/* A gate's cell: a wide one a card, its top row over its foot's, standing on
 * the foot's south edge; a thin one running north, its top laid on it. */
static void EmitDoor(VoxelBuilder *b, const VoxelMapInstance *inst, int x, int y, int d)
{
    const float wx = (float)x;
    const unsigned sx = sRoomDoors[d].sx, sy = sRoomDoors[d].sy, rows = sRoomDoors[d].rows;
    float u0 = TEX_U(sx), u1 = TEX_U(sx + 16), v0 = TEX_V(sy), v1 = TEX_V(sy + rows);

    if (sRoomDoors[d].kind < 2)
    {
        bool upper = sRoomDoors[d].kind == 0;
        float z = (float)y + (upper ? 2.0f : 1.0f), ya = upper ? 2.0f : 1.0f;

        VoxelBuilder_Quad(b,
            &(VoxelVertex){wx, ya, z, u0, v0, 1.0f}, &(VoxelVertex){wx + 1.0f, ya, z, u1, v0, 1.0f},
            &(VoxelVertex){wx + 1.0f, ya - 1.0f, z, u1, v1, 1.0f}, &(VoxelVertex){wx, ya - 1.0f, z, u0, v1, 1.0f});
        if (sRoomDoors[d].set == &gTileset_SilphCo)
        {
            /* as thick as the walls it shuts: its back and, up there, its top */
            const float zb = z - DOOR_DEPTH;

            VoxelBuilder_Quad(b,
                &(VoxelVertex){wx + 1.0f, ya, zb, u1, v0, 0.7f}, &(VoxelVertex){wx, ya, zb, u0, v0, 0.7f},
                &(VoxelVertex){wx, ya - 1.0f, zb, u0, v1, 0.7f}, &(VoxelVertex){wx + 1.0f, ya - 1.0f, zb, u1, v1, 0.7f});
            if (upper)
            {
                const float ht = ROOM_SOLID_H / 16.0f, vt = TEX_V(sy + DOOR_BAND), vb = TEX_V(sy + DOOR_BAND + 1u);

                VoxelBuilder_Quad(b,
                    &(VoxelVertex){wx, ht, zb, u0, vt, 1.0f}, &(VoxelVertex){wx + 1.0f, ht, zb, u1, vt, 1.0f},
                    &(VoxelVertex){wx + 1.0f, ht, z, u1, vb, 1.0f}, &(VoxelVertex){wx, ht, z, u0, vb, 1.0f});
            }
        }
    }
    else
    {
        const unsigned c0 = sRoomDoors[d].c0, c1 = sRoomDoors[d].c1;
        /* between Silph's solid walls: as high as they are, and from its first
         * cell on to the front of the wall north of it */
        const bool solid = sRoomDoors[d].set == &gTileset_SilphCo;
        const float lh = solid ? ROOM_SOLID_H / 16.0f : DOOR_LID_H;
        float za = (float)y + lh, zb = za + rows / 16.0f;
        float xa = wx + c0 / 16.0f, xb = wx + (c1 + 1) / 16.0f;
        float su = TEX_U(sx + (c0 + c1) / 2 + 0.5f);

        if (solid && (sRoomDoors[d].id & ~1u) == 0x3C0)
            za = (float)y + 1.0f;
        VoxelBuilder_Quad(b,
            &(VoxelVertex){wx, lh, za, u0, v0, 1.0f}, &(VoxelVertex){wx + 1.0f, lh, za, u1, v0, 1.0f},
            &(VoxelVertex){wx + 1.0f, lh, zb, u1, v1, 1.0f}, &(VoxelVertex){wx, lh, zb, u0, v1, 1.0f});
        /* a side where its drawing stops short of the cell's edge: not where
         * it goes on into the gate's other half */
        if (c0 > 0)
        {
            if (solid)
                EmitGateSide(b, inst, xa, za, zb, lh, false, rows / 16.0f);
            else
                SideQuad(b, xa, 0.0f, lh, za, zb, su, v0, su, v1, false);
        }
        if (c1 < 15)
        {
            if (solid)
                EmitGateSide(b, inst, xb, za, zb, lh, true, rows / 16.0f);
            else
                SideQuad(b, xb, 0.0f, lh, za, zb, su, v0, su, v1, true);
        }
        if (sRoomDoors[d].kind == 3)
        {
            /* its south end: the gate's last row, down to the floor */
            VoxelBuilder_Quad(b,
                &(VoxelVertex){xa, lh, zb, su, v1, 0.85f}, &(VoxelVertex){xb, lh, zb, su, v1, 0.85f},
                &(VoxelVertex){xb, 0.0f, zb, su, v1, 0.85f}, &(VoxelVertex){xa, 0.0f, zb, su, v1, 0.85f});
        }
    }
}

/*
 * A solid wall's surfaces (fr_gen_rooms.py solid_walls). All of a wall stands in
 * the real world: its top the layout's height up, cut out to its drawing, its front where
 * the drawing's face ends, its sides and back from the face's rows.
 */
static void EmitSolid(VoxelBuilder *b, const VoxelMapInstance *inst, unsigned i, unsigned height)
{
    const float ox = (float)inst->originX, oz = (float)inst->originY;
    const float h = height / 16.0f;
    const unsigned sx = sRoomSolids[i].sx, sy = sRoomSolids[i].sy;
    const float wx = ox + sRoomSolids[i].x, a = sRoomSolids[i].a / 16.0f, e = sRoomSolids[i].b / 16.0f;
    const float z = oz + sRoomSolids[i].z / 16.0f;
    const float u0 = TEX_U(sx), u1 = TEX_U(sx + 16), v0 = TEX_V(sy), v1 = TEX_V(sy + 16);

    switch (sRoomSolids[i].kind)
    {
    case SOLID_LID:
    {
        float za = oz + sRoomSolids[i].y + h, zb = za + 1.0f;

        VoxelBuilder_Quad(b,
            &(VoxelVertex){wx, h, za, u0, v0, 1.0f}, &(VoxelVertex){wx + 1.0f, h, za, u1, v0, 1.0f},
            &(VoxelVertex){wx + 1.0f, h, zb, u1, v1, 1.0f}, &(VoxelVertex){wx, h, zb, u0, v1, 1.0f});
        break;
    }
    case SOLID_FRONT:
    case SOLID_BEHIND:  /* the same, behind a thing that stands against the wall */
    {
        const unsigned c0 = sRoomSolids[i].c0, c1 = sRoomSolids[i].c1 + 1u;
        const unsigned r0 = sRoomSolids[i].r0, r1 = sRoomSolids[i].r1;
        const int top = sRoomSolids[i].y * 16;
        float xa = wx + c0 / 16.0f, xb = wx + c1 / 16.0f;
        float zf = oz + a - (sRoomSolids[i].kind == SOLID_BEHIND ? 2.0f / 16.0f : 0.0f);
        float ya = (sRoomSolids[i].a - (top + (int)r0)) / 16.0f, yb = (sRoomSolids[i].a - (top + (int)r1)) / 16.0f;
        float ua = TEX_U(sx + c0), ub = TEX_U(sx + c1), va = TEX_V(sy + r0), vb = TEX_V(sy + r1);

        VoxelBuilder_Quad(b,
            &(VoxelVertex){xa, ya, zf, ua, va, 1.0f}, &(VoxelVertex){xb, ya, zf, ub, va, 1.0f},
            &(VoxelVertex){xb, yb, zf, ub, vb, 1.0f}, &(VoxelVertex){xa, yb, zf, ua, vb, 1.0f});
        break;
    }
    case SOLID_WEST:
    case SOLID_EAST:
        SideQuad(b, wx + sRoomSolids[i].c0 / 16.0f, 0.0f, h, oz + a, oz + e, u0, v0, u1, v1,
                 sRoomSolids[i].kind == SOLID_EAST);
        break;
    case SOLID_NORTH:
        VoxelBuilder_Quad(b,
            &(VoxelVertex){ox + e, h, z, u0, v0, 0.7f}, &(VoxelVertex){ox + a, h, z, u1, v0, 0.7f},
            &(VoxelVertex){ox + a, 0.0f, z, u1, v1, 0.7f}, &(VoxelVertex){ox + e, 0.0f, z, u0, v1, 0.7f});
        break;
    default:
        VoxelBuilder_Quad(b,
            &(VoxelVertex){ox + a, h, z, u0, v0, 0.9f}, &(VoxelVertex){ox + e, h, z, u1, v0, 0.9f},
            &(VoxelVertex){ox + e, 0.0f, z, u1, v1, 0.9f}, &(VoxelVertex){ox + a, 0.0f, z, u0, v1, 0.9f});
        break;
    }
}

void VoxelRoom_EmitInstance(VoxelBuilder *builder, const VoxelMapInstance *inst,
                            int x0, int y0, int x1, int y1)
{
    unsigned first, count;

    unsigned doorFirst, doorEnd;

    if (DoorRange(inst, &doorFirst, &doorEnd))
        for (int y = y0; y < y1; ++y)
            for (int x = x0; x < x1; ++x)
            {
                int d = DoorAt(inst, x, y);

                if (d >= 0)
                    EmitDoor(builder, inst, x, y, d);
            }
    if (inst != NULL && inst->indoor)
        for (unsigned l = 0; l < sizeof(sRoomSolidLayouts) / sizeof(sRoomSolidLayouts[0]); ++l)
            if (sRoomSolidLayouts[l].layout == (unsigned)inst->layoutId)
            {
                for (unsigned i = sRoomSolidLayouts[l].first;
                     i < (unsigned)sRoomSolidLayouts[l].first + sRoomSolidLayouts[l].count; ++i)
                {
                    int x = inst->originX + sRoomSolids[i].x, y = inst->originY + sRoomSolids[i].y;

                    if (x >= x0 && x < x1 && y >= y0 && y < y1
                     && (sRoomSolids[i].live == 0 || VoxelWorld_GetMetatileId(x, y) == sRoomSolids[i].live))
                        EmitSolid(builder, inst, i, sRoomSolidLayouts[l].h);
                }
                break;
            }
    if (!RoomRange(inst, &first, &count))
        return;
    for (unsigned i = first; i < first + count; ++i)
    {
        int x = inst->originX + sRoomCells[i].x, y = inst->originY + sRoomCells[i].y;

        if (sRoomCells[i].flags & (ROOM_ATLAS | ROOM_FLAT))
            continue;
        if (x >= x0 && x < x1 && y >= y0 && y < y1 && RowStands(i, x, y))
            EmitCell(builder, inst, i, TEX_U(sRoomCells[i].sx), TEX_V(sRoomCells[i].sy),
                     TEX_U(sRoomCells[i].sx + 16), TEX_V(sRoomCells[i].sy + 16));
    }
}
