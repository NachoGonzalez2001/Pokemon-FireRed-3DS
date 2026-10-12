#include <stddef.h>
#include "voxel_tree.h"
#include "voxel_relief.h"

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
    (void)secondaryTileset;
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
            if (part >= 0 || crown >= 0)
                EmitCell(builder, x, y, part, crown);
        }
}
