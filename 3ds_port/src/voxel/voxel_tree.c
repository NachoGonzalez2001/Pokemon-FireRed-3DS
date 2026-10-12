#include <stddef.h>
#include "voxel_tree.h"
#include "voxel_relief.h"
#include "voxel_props_table.h"

extern const struct Tileset gTileset_LavenderTown;
#include "voxel_atlas.h"
#include "voxel_building.h"

/* Where gen_voxel_trees.py packs each tree, in texels. */
#define TEX_U(px) ((float)(px) / VOXEL_TREE_TEXTURE_DIM)
#define TEX_V(py) (1.0f - (float)(py) / VOXEL_TREE_TEXTURE_DIM)

/*
 * FireRed's General tree is two metatiles wide and three tall: the tip over
 * the grass (00E/00F), the crown (01E/01F; 01C/01D in a wood, a neighbour's
 * leaves at the edge) and the base (024-027; 014-017 in a wood, carrying the
 * next tree's tip), where the lowest leaves meet the shadow. A wood repeats
 * the crown and base rows every two metatiles.
 *
 * The crown row stands its whole tree up as one card, drawn off the tileset
 * by fr_gen_trees.py; the base keeps the shadow flat on the grass and the tip
 * gives its cell back to whatever the tree stood in front of.
 */
/*
 * The General tileset's props - signs, rocks, bushes, flowers, fences, the
 * south-facing ledges - stand up the same way the trees do: each one's upper
 * layer, packed in the tree texture by fr_gen_trees.py (voxel_props_table.h),
 * is a card standing where its drawing touches the ground. A card at the
 * cell's row r1 rising (r1 - r0) / 16 lands, at the GBA's 45 degrees, on
 * exactly the pixels the prop is drawn on; from anywhere else it stands up.
 * The ground under it is the same metatile without the prop.
 */
static int PropIndex(const void *secondaryTileset, int metatileId)
{
    static int16_t index[0x280];
    static bool built;

    if (!built)
    {
        for (unsigned i = 0; i < sizeof(index) / sizeof(index[0]); ++i)
            index[i] = -1;
        for (unsigned i = 0; i < sizeof(sProps) / sizeof(sProps[0]); ++i)
            if (sProps[i].set == 0)
                index[sProps[i].id] = (int16_t)i;
        built = true;
    }
    if (metatileId < 0)
        return -1;
    if (metatileId < (int)(sizeof(index) / sizeof(index[0])))
        return index[metatileId];
    /* a town's own: a few dozen entries, the tileset's first */
    for (unsigned i = 0; i < sizeof(sProps) / sizeof(sProps[0]); ++i)
        if (sProps[i].id == metatileId && sPropTilesets[sProps[i].set] == secondaryTileset)
            return (int)i;
    return -1;
}

/* `below` is the prop of the cell south of this one, or -1: a prop drawn
 * down to its cell's bottom over one drawn from its top - the mailbox's
 * head over its post - stands on that one's card, in its plane. */
/*
 * A fence running north-south is drawn as a post a cell, seen from above.
 * Stood up as a card it is a row of sticks; turned to run along the line,
 * the camera - looking north - sees it edge on, its posts squeezed thin. So
 * it is built of the fence drawn front on (sx, sy): every half cell one of
 * its posts, facing the camera as the east-west fences' posts do, and its
 * rail along the line between them.
 */
static void EmitPost(VoxelBuilder *builder, int x, int y, int prop, int north, int south)
{
    float cx = (float)x + sProps[prop].centre / 16.0f;
    float h = (16 - sProps[prop].sr) / 16.0f;
    float v0 = TEX_V(sProps[prop].sy + sProps[prop].sr), v1 = TEX_V(sProps[prop].sy + 16);
    /* a post of the front-on fence (columns 1..7) and a column of its rail
     * between two posts (column 8) */
    float pu0 = TEX_U(sProps[prop].sx + 1), pu1 = TEX_U(sProps[prop].sx + 8);
    float ru0 = TEX_U(sProps[prop].sx + 8), ru1 = TEX_U(sProps[prop].sx + 9);
    const float half = 3.5f / 16.0f;
    /* From the fence it meets to the next: another post runs on through the
     * cell, a fence drawn front on is met where it stands, and a free end
     * stops at the post in the middle of the cell. */
    float z0 = north < 0 ? (float)y + 0.25f : (float)y;
    float z1 = south < 0 ? (float)y + 0.75f
             : sProps[south].kind == 1 ? (float)y + 1.0f
             : (float)(y + 1) + sProps[south].r1 / 16.0f;

    /* posts every half cell from a cell's edge, as the fence drawn front on
     * keeps them: this cell's are at y + 0.5 and y + 1 (the one at y is the
     * cell north's, or the corner's own), and one more short of a corner
     * fence to the south, which brings its own post */
    float last = south >= 0 && sProps[south].kind == 1 ? (float)y + 1.0f : z1 - 0.01f;

    for (float pz = (float)y + 0.5f; pz <= last + 1e-4f; pz += 0.5f)
        VoxelBuilder_Quad(builder,
            &(VoxelVertex){cx - half, h,    pz, pu0, v0, 1.0f},
            &(VoxelVertex){cx + half, h,    pz, pu1, v0, 1.0f},
            &(VoxelVertex){cx + half, 0.0f, pz, pu1, v1, 1.0f},
            &(VoxelVertex){cx - half, 0.0f, pz, pu0, v1, 1.0f});
    VoxelBuilder_Quad(builder,
        &(VoxelVertex){cx, h,    z0, ru0, v0, 0.9f}, &(VoxelVertex){cx, h,    z1, ru1, v0, 0.9f},
        &(VoxelVertex){cx, 0.0f, z1, ru1, v1, 0.9f}, &(VoxelVertex){cx, 0.0f, z0, ru0, v1, 0.9f});
}

/*
 * A ledge: only its face stands, where the drawing meets the ground. Lifting
 * the ground above it too - a step - stretched that ground over the back of
 * the step; the face alone keeps the ground as it is drawn.
 */
static void EmitLedge(VoxelBuilder *builder, int x, int y, int prop)
{
    float wx = (float)x;
    float h = (sProps[prop].r1 - sProps[prop].r0) / 16.0f;
    float u0 = TEX_U(sProps[prop].x), u1 = TEX_U(sProps[prop].x + 16);
    float vm = TEX_V(sProps[prop].y + sProps[prop].r0);
    float vb = TEX_V(sProps[prop].y + sProps[prop].r1);
    float zf = (float)y + sProps[prop].r1 / 16.0f;

    VoxelBuilder_Quad(builder,
        &(VoxelVertex){wx,        h,    zf, u0, vm, 1.0f}, &(VoxelVertex){wx + 1.0f, h,    zf, u1, vm, 1.0f},
        &(VoxelVertex){wx + 1.0f, 0.0f, zf, u1, vb, 1.0f}, &(VoxelVertex){wx,        0.0f, zf, u0, vb, 1.0f});
}

/*
 * A wall drawn from above - a pen's hedge - raised as a low block over the
 * rows its drawing fills: the drawing on top, its sides the colour of its
 * edge rows.
 */
static void EmitBlock(VoxelBuilder *builder, int x, int y, int prop)
{
    float x0 = (float)x, x1 = x0 + 1.0f;
    float z0 = (float)y + sProps[prop].r0 / 16.0f, z1 = (float)y + sProps[prop].r1 / 16.0f;
    const float h = 0.5f;
    float u0 = TEX_U(sProps[prop].x), u1 = TEX_U(sProps[prop].x + 16);
    float vt = TEX_V(sProps[prop].y + sProps[prop].r0), vb = TEX_V(sProps[prop].y + sProps[prop].r1);
    float ve = TEX_V(sProps[prop].y + sProps[prop].r1 - 1);

    VoxelBuilder_Quad(builder, /* top */
        &(VoxelVertex){x0, h, z0, u0, vt, 1.0f}, &(VoxelVertex){x1, h, z0, u1, vt, 1.0f},
        &(VoxelVertex){x1, h, z1, u1, vb, 1.0f}, &(VoxelVertex){x0, h, z1, u0, vb, 1.0f});
    VoxelBuilder_Quad(builder, /* south */
        &(VoxelVertex){x0, h, z1, u0, ve, 0.85f}, &(VoxelVertex){x1, h, z1, u1, ve, 0.85f},
        &(VoxelVertex){x1, 0.0f, z1, u1, vb, 0.85f}, &(VoxelVertex){x0, 0.0f, z1, u0, vb, 0.85f});
    VoxelBuilder_Quad(builder, /* north */
        &(VoxelVertex){x1, h, z0, u1, vt, 0.7f}, &(VoxelVertex){x0, h, z0, u0, vt, 0.7f},
        &(VoxelVertex){x0, 0.0f, z0, u0, ve, 0.7f}, &(VoxelVertex){x1, 0.0f, z0, u1, ve, 0.7f});
    VoxelBuilder_Quad(builder, /* west */
        &(VoxelVertex){x0, h, z0, u0, vt, 0.8f}, &(VoxelVertex){x0, h, z1, u0, vb, 0.8f},
        &(VoxelVertex){x0, 0.0f, z1, u0 + 1.0f / VOXEL_TREE_TEXTURE_DIM, vb, 0.8f},
        &(VoxelVertex){x0, 0.0f, z0, u0 + 1.0f / VOXEL_TREE_TEXTURE_DIM, vt, 0.8f});
    VoxelBuilder_Quad(builder, /* east */
        &(VoxelVertex){x1, h, z1, u1, vb, 0.8f}, &(VoxelVertex){x1, h, z0, u1, vt, 0.8f},
        &(VoxelVertex){x1, 0.0f, z0, u1 - 1.0f / VOXEL_TREE_TEXTURE_DIM, vt, 0.8f},
        &(VoxelVertex){x1, 0.0f, z1, u1 - 1.0f / VOXEL_TREE_TEXTURE_DIM, vb, 0.8f});
}

static void EmitProp(VoxelBuilder *builder, int x, int y, int prop, int below, int north,
                     bool westFence, bool eastFence)
{
    float wx = (float)x;
    float s0 = 0.0f, s1 = 1.0f;   /* the card's span across its cell */
    float zc = (float)y + sProps[prop].r1 / 16.0f;
    float base = 0.0f;
    float h = (sProps[prop].r1 - sProps[prop].r0) / 16.0f;
    float u0 = TEX_U(sProps[prop].x), u1 = TEX_U(sProps[prop].x + 16);
    float v0 = TEX_V(sProps[prop].y + sProps[prop].r0), v1 = TEX_V(sProps[prop].y + sProps[prop].r1);

    if (sProps[prop].kind == 2)
    {
        /* from the cell's south edge back to its middle, a third of a cell
         * up: a bed of flowers rather than a wall of them */
        VoxelBuilder_Quad(builder,
            &(VoxelVertex){wx,        0.35f, zc - 0.5f, u0, v0, 1.0f},
            &(VoxelVertex){wx + 1.0f, 0.35f, zc - 0.5f, u1, v0, 1.0f},
            &(VoxelVertex){wx + 1.0f, 0.0f,  zc,        u1, v1, 1.0f},
            &(VoxelVertex){wx,        0.0f,  zc,        u0, v1, 1.0f});
        return;
    }
    /* A fence drawn front on that turns a corner into a north-south one:
     * it ends at that fence's post, not at its cell's edge, or its end
     * stands across the turning fence. */
    {
        int post = below >= 0 && sProps[below].kind == 1 ? below
                 : north >= 0 && sProps[north].kind == 1 ? north : -1;

        /* kept on the side the fence comes from */
        if (post >= 0 && sProps[prop].kind == 0 && westFence != eastFence)
        {
            float c = sProps[post].centre / 16.0f;

            if (westFence)
                s1 = c + 2.0f / 16.0f;
            else
                s0 = c - 2.0f / 16.0f;
        }
    }
    if (below >= 0 && sProps[prop].r1 == 16 && sProps[prop].r0 > 0 && sProps[below].r0 == 0)
    {
        zc = (float)(y + 1) + sProps[below].r1 / 16.0f;
        base = sProps[below].r1 / 16.0f;
    }
    VoxelBuilder_Quad(builder,
        &(VoxelVertex){wx + s0, base + h, zc, u0 + (u1 - u0) * s0, v0, 1.0f},
        &(VoxelVertex){wx + s1, base + h, zc, u0 + (u1 - u0) * s1, v0, 1.0f},
        &(VoxelVertex){wx + s1, base,     zc, u0 + (u1 - u0) * s1, v1, 1.0f},
        &(VoxelVertex){wx + s0, base,     zc, u0 + (u1 - u0) * s0, v1, 1.0f});
}

int VoxelTree_Part(const void *secondaryTileset, int metatileId)
{
    (void)secondaryTileset;
    switch (metatileId)
    {
    case 0x014: case 0x016: case 0x024: case 0x026: return VOXEL_TREE_BASE_LEFT;
    case 0x015: case 0x017: case 0x025: case 0x027: return VOXEL_TREE_BASE_RIGHT;
    default: return -1;
    }
}

int VoxelTree_Crown(const void *secondaryTileset, int metatileId)
{
    (void)secondaryTileset;
    switch (metatileId)
    {
    case 0x01C: case 0x01E: return 0;
    case 0x01D: case 0x01F: return 1;
    default: return -1;
    }
}

int VoxelTree_GroundMetatile(const void *secondaryTileset, int metatileId)
{
    int prop = PropIndex(secondaryTileset, metatileId);

    /* a ledge keeps its drawing on the ground under its face: the face
     * standing alone left a seam between it and the ground behind */
    if (prop >= 0 && sProps[prop].kind == 3)
        return metatileId;
    if (prop >= 0)
        return sProps[prop].ground != metatileId ? sProps[prop].ground
                                                 : (int)VOXEL_BARE_FIRST + metatileId;
    /* The Pokemon Tower's roof drawn over the grass of Route 10, where the
     * player walks behind it: the roof is modelled on the tower, the cells
     * keep only their grass. */
    if (secondaryTileset == &gTileset_LavenderTown && metatileId >= 0x2A5 && metatileId <= 0x2AF)
        return (int)VOXEL_BARE_FIRST + metatileId;
    switch (metatileId)
    {
    /* The crown's own ground: the card stands over it. */
    case 0x01C: case 0x01E: return 0x010;
    case 0x01D: case 0x01F: return 0x011;
    /* A tip, over the grass, the tall grass or a ledge's dirt. */
    case 0x00E: return 0x010;
    case 0x00F: return 0x011;
    case 0x00A: case 0x00B: case 0x00C: return 0x00D;
    case 0x0B4: case 0x0B5: return 0x07C;
    case 0x10A: case 0x10B: return 0x12B;
    case 0x255: case 0x25D: return 0x273;
    default: return metatileId;
    }
}

/* The card is the tree's 32:48 drawing: width 2, length 3 tiles, leaning
 * north at 50 degrees, fixed in the world rather than billboarded. Its foot
 * is at the base row's lowest leaves, sunk a little so no cut shows. */
static void EmitCrown(VoxelBuilder *builder, int x, int y, int col)
{
    float wx = (float)x, wz = (float)y;
    float u0 = TEX_U(col * 16), u1 = TEX_U(col * 16 + 16);
    float v0 = TEX_V(0), v1 = TEX_V(48);
    const float rise = 2.298133f, run = 1.928363f;
    const float baseHeight = -0.10f;
    float baseZ = wz + 1.9f;

    builder->rounded = true;
    VoxelBuilder_Quad(builder,
        &(VoxelVertex){wx,        baseHeight + rise, baseZ - run, u0, v0, 1.0f},
        &(VoxelVertex){wx + 1.0f, baseHeight + rise, baseZ - run, u1, v0, 1.0f},
        &(VoxelVertex){wx + 1.0f, baseHeight,        baseZ,       u1, v1, 1.0f},
        &(VoxelVertex){wx,        baseHeight,        baseZ,       u0, v1, 1.0f});
    builder->rounded = false;
}

static void EmitCell(VoxelBuilder *builder, int x, int y, int part, int crown)
{
    if (part >= 0)
    {
        int col = part - VOXEL_TREE_BASE_LEFT;

        VoxelMesh_Top(builder, (float)x, (float)y, 0.0f, 0.0f,
                      TEX_U(32 + col * 16), TEX_V(0), TEX_U(48 + col * 16), TEX_V(16), 1.0f);
    }
    if (crown >= 0)
        EmitCrown(builder, x, y, crown);
}

void VoxelTree_EmitInstance(VoxelBuilder *builder, const VoxelMapInstance *inst,
                            int x0, int y0, int x1, int y1)
{
    if (!VoxelWorld_UsesTreeSprites(inst))
        return;
    if (x0 < inst->originX) x0 = inst->originX;
    if (y0 < inst->originY) y0 = inst->originY;
    if (x1 > inst->originX + inst->width) x1 = inst->originX + inst->width;
    if (y1 > inst->originY + inst->height) y1 = inst->originY + inst->height;
    for (int y = y0; y < y1; ++y)
        for (int x = x0; x < x1; ++x)
        {
            int metatileId = VoxelWorld_GetMetatileId(x, y);
            int part = VoxelTree_Part(inst->secondaryTileset, metatileId);
            int crown = VoxelTree_Crown(inst->secondaryTileset, metatileId);
            int prop = PropIndex(inst->secondaryTileset, metatileId);
            /* a building's own cells are its model's */
            if (prop >= 0 && !VoxelBuildings_CellAt(inst, x, y, NULL, NULL))
            {
                int below = VoxelWorld_GetInstanceAt(x, y + 1) == inst
                          ? PropIndex(inst->secondaryTileset, VoxelWorld_GetMetatileId(x, y + 1)) : -1;
                builder->lift = VoxelRelief_CellLift(inst, x, y);
                builder->shift = VoxelRelief_CellShift(inst, x, y);
                int north = VoxelWorld_GetInstanceAt(x, y - 1) == inst
                          ? PropIndex(inst->secondaryTileset, VoxelWorld_GetMetatileId(x, y - 1)) : -1;
                if (sProps[prop].kind == 1)
                    EmitPost(builder, x, y, prop, north, below);
                else if (sProps[prop].kind == 3)
                    EmitLedge(builder, x, y, prop);
                else if (sProps[prop].kind == 4)
                    EmitBlock(builder, x, y, prop);
                else
                {
                    bool west = VoxelWorld_GetInstanceAt(x - 1, y) == inst
                             && PropIndex(inst->secondaryTileset, VoxelWorld_GetMetatileId(x - 1, y)) >= 0;
                    bool east = VoxelWorld_GetInstanceAt(x + 1, y) == inst
                             && PropIndex(inst->secondaryTileset, VoxelWorld_GetMetatileId(x + 1, y)) >= 0;
                    EmitProp(builder, x, y, prop, below, north, west, east);
                }
                builder->lift = 0.0f;
                builder->shift = 0.0f;
            }
            if (part >= 0 || crown >= 0)
            {
                builder->lift = VoxelRelief_CellLift(inst, x, y);
                builder->shift = VoxelRelief_CellShift(inst, x, y);
                EmitCell(builder, x, y, part, crown);
                builder->lift = 0.0f;
                builder->shift = 0.0f;
            }
        }
}

void VoxelTree_EmitBorder(VoxelBuilder *builder, int x0, int y0, int x1, int y1)
{
    const VoxelMapInstance *current = VoxelWorld_Instance(0);

    if (!VoxelWorld_UsesTreeSprites(current))
        return;
    for (int y = y0; y < y1; ++y)
        for (int x = x0; x < x1; ++x)
        {
            int metatileId, part, crown, prop;
            if (VoxelWorld_GetInstanceAt(x, y) != NULL)
                continue;
            metatileId = VoxelWorld_BorderMetatile(x, y);
            part = VoxelTree_Part(current->secondaryTileset, metatileId);
            crown = VoxelTree_Crown(current->secondaryTileset, metatileId);
            prop = PropIndex(current->secondaryTileset, metatileId);
            if (prop >= 0 && sProps[prop].kind == 1)
                EmitPost(builder, x, y, prop, prop, prop);
            else if (prop >= 0 && sProps[prop].kind == 3)
                EmitLedge(builder, x, y, prop);
            else if (prop >= 0 && sProps[prop].kind == 4)
                EmitBlock(builder, x, y, prop);
            else if (prop >= 0)
                EmitProp(builder, x, y, prop, -1, -1, false, false);
            if (part >= 0 || crown >= 0)
                EmitCell(builder, x, y, part, crown);
        }
}
