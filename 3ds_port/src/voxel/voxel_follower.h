/*
 * The Pokemon that follows the player in the 3D world: the first of the
 * party, walking a tile behind on the path the player took. Only drawn; it
 * is no object of the game, so no script, door or puzzle ever meets it.
 * Its sprites are followers.bin, which the builder downloads at install
 * time (builder/firered3ds_builder/followers.py); without it, no follower.
 */
#ifndef CTR_VOXEL_FOLLOWER_H
#define CTR_VOXEL_FOLLOWER_H

#include <stdbool.h>
#include <stdint.h>

typedef struct
{
    float x, z;          /* its ground point, world */
    int dx, dy;          /* its picture's top left from there, pixels (y down) */
    int w, h;            /* its picture in the atlas's follower cell */
    int foot;            /* the row (from the ground point) its feet stand on */
} VoxelFollowerCard;

/* Moves and animates the follower for this frame, writing its picture into
 * the atlas's follower cell when it changed. False when none is drawn. */
bool VoxelFollower_Update(uint16_t *atlas, float yawDegrees, VoxelFollowerCard *card);

/* Forgets the path: the follower stands behind the player again. */
void VoxelFollower_Reset(void);

/* The visible wild Pokemon (OPTIONS, VISIBLE WILD), drawn as the follower is:
 * each card's picture in its own cell of the atlas. */
#define VOXEL_WILD_MAX 6
#define VOXEL_WILD_CELL_DIM 64u

typedef struct
{
    float x, z;          /* its ground point, world */
    int dx, dy;          /* its picture's top left from there, source pixels */
    int w, h;            /* its picture in its cell, atlas pixels */
    int foot;            /* the row (source pixels) its feet stand on */
    int scale;           /* source pixels per atlas pixel: 1, or 2 for the big */
    unsigned cellX, cellY;
    int spriteId;        /* its party icon, which the 3D view leaves out */
} VoxelWildCard;

/* Moves and animates the wild ones for this frame; `origin` is the map's
 * place in the world. Returns how many cards were written. */
int VoxelWild_Update(uint16_t *atlas, float yawDegrees, float originX, float originZ,
                     VoxelWildCard cards[VOXEL_WILD_MAX]);

#endif
