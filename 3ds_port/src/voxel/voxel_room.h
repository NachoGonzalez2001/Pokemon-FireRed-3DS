/*
 * A room's standing pieces: its back wall, its furniture, read off the
 * drawing by scripts/fr_gen_rooms.py (voxel_room_table.h), their art in the
 * tree texture. See voxel_room.c.
 */
#ifndef CTR_VOXEL_ROOM_H
#define CTR_VOXEL_ROOM_H

#include "voxel_mesh_builder.h"
#include "voxel_world.h"

#define VOXEL_ROOM_NONE (-2)    /* no piece: the cell is drawn as it is */
#define VOXEL_ROOM_NO_GROUND (-1)

/* What lies flat under a piece: a metatile id (a bare id for the floor under
 * an object drawn on the upper layer), VOXEL_ROOM_NO_GROUND, or
 * VOXEL_ROOM_NONE when no piece stands on the cell. */
int VoxelRoom_Ground(const VoxelMapInstance *inst, int x, int y);

/* Whether a thing on the cell (x, y) stands on its piece - a Poke Ball on a
 * table - and if so where: `rise` up, `offZ` back or forward from the cell's
 * centre, onto the middle of the piece's top. */
bool VoxelRoom_StandOn(const VoxelMapInstance *inst, int x, int y, float *rise, float *offZ);

/* The pieces of the cells in [x0,x1) x [y0,y1), in the tree texture. */
void VoxelRoom_EmitInstance(VoxelBuilder *builder, const VoxelMapInstance *inst,
                            int x0, int y0, int x1, int y1);

/* A piece drawn with the map's own atlas (the whole drawing of its cell):
 * the metatile, or -1; and the piece, with its UVs, in the ground pass. */
int VoxelRoom_AtlasArt(const VoxelMapInstance *inst, int x, int y);
void VoxelRoom_EmitAtlasCell(VoxelBuilder *builder, const VoxelMapInstance *inst, int x, int y,
                             float u0, float v0, float u1, float v1);

#endif
