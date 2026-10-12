#include <stddef.h>
#include "voxel_tree.h"
#include "voxel_relief.h"
#include "voxel_props_table.h"
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
static int PropIndex(int metatileId)
{
    static int16_t index[0x280];
    static bool built;

    if (!built)
    {
        for (unsigned i = 0; i < sizeof(index) / sizeof(index[0]); ++i)
            index[i] = -1;
        for (unsigned i = 0; i < sizeof(sProps) / sizeof(sProps[0]); ++i)
            index[sProps[i].id] = (int16_t)i;
        built = true;
    }
    if (metatileId < 0 || metatileId >= (int)(sizeof(index) / sizeof(index[0])))
        return -1;
    return index[metatileId];
}

static void EmitProp(VoxelBuilder *builder, int x, int y, int prop)
{
    float wx = (float)x;
    float zc = (float)y + sProps[prop].r1 / 16.0f;
    float h = (sProps[prop].r1 - sProps[prop].r0) / 16.0f;
    float u0 = TEX_U(sProps[prop].x), u1 = TEX_U(sProps[prop].x + 16);
    float v0 = TEX_V(sProps[prop].y + sProps[prop].r0), v1 = TEX_V(sProps[prop].y + sProps[prop].r1);

    VoxelBuilder_Quad(builder,
        &(VoxelVertex){wx,        h,    zc, u0, v0, 1.0f},
        &(VoxelVertex){wx + 1.0f, h,    zc, u1, v0, 1.0f},
        &(VoxelVertex){wx + 1.0f, 0.0f, zc, u1, v1, 1.0f},
        &(VoxelVertex){wx,        0.0f, zc, u0, v1, 1.0f});
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
    int prop = PropIndex(metatileId);

    (void)secondaryTileset;
    if (prop >= 0)
        return sProps[prop].ground;
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
            int prop = PropIndex(metatileId);
            /* a building's own cells are its model's */
            if (prop >= 0 && !VoxelBuildings_CellAt(inst, x, y, NULL, NULL))
            {
                builder->lift = VoxelRelief_CellLift(inst, x, y);
                builder->shift = VoxelRelief_CellShift(inst, x, y);
                EmitProp(builder, x, y, prop);
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
            int metatileId, part, crown;
            if (VoxelWorld_GetInstanceAt(x, y) != NULL)
                continue;
            metatileId = VoxelWorld_BorderMetatile(x, y);
            part = VoxelTree_Part(current->secondaryTileset, metatileId);
            crown = VoxelTree_Crown(current->secondaryTileset, metatileId);
            if (PropIndex(metatileId) >= 0)
                EmitProp(builder, x, y, PropIndex(metatileId));
            if (part >= 0 || crown >= 0)
                EmitCell(builder, x, y, part, crown);
        }
}
