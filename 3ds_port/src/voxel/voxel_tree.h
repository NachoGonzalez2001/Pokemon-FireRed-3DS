/* General tileset trees: the shadow flat on the ground, the tree a north-leaning card. */
#ifndef CTR_VOXEL_TREE_H
#define CTR_VOXEL_TREE_H

#include "voxel_mesh_builder.h"

#define VOXEL_TREE_TEXTURE_DIM 512u   /* wide */
#define VOXEL_TREE_TEXTURE_H 1024u    /* tall: the rooms' art below the props' */
/* game data (taken off the General tileset): the data pack's, not the RomFS's */
#define VOXEL_TREE_TEXTURE_PATH "voxel/trees.rgba5551"

/* Emerald's one-cell small tree; FireRed's General has none in use. */
#define VOXEL_TREE_SMALL 4
#define VOXEL_TREE_BASE_LEFT 2
#define VOXEL_TREE_BASE_RIGHT 3
/* A wood's big tree, three cells wide: its base, VOXEL_TREE_WOOD + column;
 * VOXEL_TREE_WOOD_FLOOR a cell of a wood whose ground the tree pass draws */
#define VOXEL_TREE_WOOD 8
#define VOXEL_TREE_WOOD_FLOOR (VOXEL_TREE_WOOD + 3)

/* A tree's base, whose cell the tree pass draws (its shadow): the half
 * VOXEL_TREE_BASE_LEFT/RIGHT, a wood's VOXEL_TREE_WOOD + column, or -1.
 * secondaryTileset is the map's. */
int VoxelTree_Part(const void *secondaryTileset, int metatileId);
/* A tree's crown row, where its card stands: the column, or -1. Its ground
 * is VoxelTree_GroundMetatile's, drawn by the ground pass. */
int VoxelTree_Crown(const void *secondaryTileset, int metatileId);
/* Whether the cell is any part of a wood's big trees (VOXEL_TREE_WOOD). */
bool VoxelTree_InWood(const void *secondaryTileset, int metatileId);
/* Remove the old canopy from the cell above a tree, leaving its ground. */
int VoxelTree_GroundMetatile(const void *secondaryTileset, int metatileId);

/* Appended after the ordinary terrain; these vertices use the tree texture. */
void VoxelTree_EmitInstance(VoxelBuilder *builder, const VoxelMapInstance *inst,
                            int x0, int y0, int x1, int y1);
void VoxelTree_EmitBorder(VoxelBuilder *builder, int x0, int y0, int x1, int y1);

#endif
