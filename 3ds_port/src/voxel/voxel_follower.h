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

#endif
