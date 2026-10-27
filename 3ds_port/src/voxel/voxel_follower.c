/*
 * The Pokemon that follows the player (voxel_follower.h).
 *
 * The player's ground point is laid down as a path, a point every few
 * hundredths of a tile; the follower stands a tile or more back along it,
 * so it walks where the player walked, round corners and up stairs, at the
 * player's speed, and stops a tile behind. A warp or a jump of the world's
 * origin (a map's connection) starts the path over behind the player.
 *
 * Its picture is one of eight directions, as Mystery Dungeon draws them:
 * the direction it walks in, as the camera sees it - turning the camera
 * turns the follower's sprite. Walking, the walk animation, as fast as it
 * goes; standing, the idle one.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "global.h"
#include "main.h"
#include "pokemon.h"
#include "event_object_movement.h"
#include "field_player_avatar.h"
#include "quest_log.h"
#include "constants/event_objects.h"
#include "constants/species.h"
#include "3ds_data.h"
#include "3ds_log.h"
#include "3ds_video.h"
#include "voxel_entities.h"
#include "voxel_follower.h"
#include "voxel_grade.h"

bool8 CtrPlayer_Follower(void);   /* fr_bottom_ui.c: the option */

#define FOLLOWERS_PATH CTR_DATA_DIR "followers.bin"
#define FOLLOWERS_COUNT 387
#define FOLLOW_DISTANCE 1.0f      /* tiles behind, along the path, at least */
#define PATH_STEP 0.05f           /* tiles between the path's points */
#define PATH_POINTS 128
#define WARP_JUMP 3.0f            /* a move this long in a frame is a warp */
#define HEADING_AHEAD 0.4f        /* tiles: it faces where the path goes this far on */
#define HEADING_EASE 0.25f        /* of the way to the new heading, a frame */
#define TURN_MARGIN 10.0f         /* degrees past a sector's edge before it turns */
#define ANIM_HEAD 52
#define DIRECTIONS 8

static FILE *sFile;
static bool sFileTried, sFileBad;
static uint32_t sOffset[FOLLOWERS_COUNT], sSize[FOLLOWERS_COUNT];

static uint8_t *sEntry;           /* the species' sprites */
static int sSpecies = -1;         /* national number loaded, 0 none */
static int sFoot;
static float sDistance = FOLLOW_DISTANCE;   /* further back the wider it is */

static float sPathX[PATH_POINTS], sPathZ[PATH_POINTS];
static int sPathCount;            /* newest last */
static float sX, sZ, sDirX, sDirZ = 1.0f;
static bool sPlaced;
static float sAnimTime;
static int sScreenDir = -1;
static int sStill;
static u16 sMapKey = 0xFFFF;

static int sDrawnKey = -1, sDrawnW, sDrawnH;
static uint32_t sColumn[VOXEL_FOLLOWER_CELL_DIM];   /* Draw's atlas offsets */
static bool sColumnsBuilt;

static uint32_t Le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static bool OpenFile(void)
{
    uint8_t head[12];

    if (sFileTried)
        return sFile != NULL;
    sFileTried = true;
    sFile = fopen(FOLLOWERS_PATH, "rb");
    if (sFile == NULL)
    {
        CtrLog_Write(CTR_LOG_VIDEO, "follower: no %s (the builder downloads it)", FOLLOWERS_PATH);
        return false;
    }
    if (fread(head, 1, sizeof(head), sFile) != sizeof(head) || memcmp(head, "FRFW", 4) != 0
     || Le32(head + 4) != 1 || Le32(head + 8) != FOLLOWERS_COUNT
     || fread(sOffset, 4, FOLLOWERS_COUNT, sFile) != FOLLOWERS_COUNT
     || fread(sSize, 4, FOLLOWERS_COUNT, sFile) != FOLLOWERS_COUNT)
    {
        CtrLog_Write(CTR_LOG_ERROR, "follower: %s is not a follower file this game reads", FOLLOWERS_PATH);
        fclose(sFile);
        sFile = NULL;
        sFileBad = true;
        return false;
    }
    return true;
}

/* An animation's header in the loaded entry: 0 walking, 1 standing. */
static const uint8_t *Anim(int anim)
{
    const uint8_t *walk = sEntry;

    return anim == 0 ? walk : walk + ANIM_HEAD + 8 * DIRECTIONS * walk[0];
}

static const uint8_t *Frame(int anim, int dir, int frame)
{
    const uint8_t *a = Anim(anim);

    return a + ANIM_HEAD + 8 * (dir * a[0] + frame);
}

static bool Load(int national)
{
    if (national == sSpecies)
        return sEntry != NULL;
    free(sEntry);
    sEntry = NULL;
    sSpecies = national;
    sDrawnKey = -1;
    if (national <= 0 || national >= FOLLOWERS_COUNT || sSize[national] == 0)
        return false;
    sEntry = malloc(sSize[national]);
    if (sEntry == NULL || fseek(sFile, (long)sOffset[national], SEEK_SET) != 0
     || fread(sEntry, 1, sSize[national], sFile) != sSize[national])
    {
        CtrLog_Write(CTR_LOG_ERROR, "follower: #%d could not be read", national);
        free(sEntry);
        sEntry = NULL;
        return false;
    }
    /* Where its feet are: the lowest a facing-down walking frame reaches,
     * so the walk's own bob stays in the picture. How far back it walks:
     * half its width behind the player's half a tile, so a Gyarados does
     * not walk over them. */
    sFoot = 0;
    sDistance = FOLLOW_DISTANCE;
    for (int f = 0; f < Anim(0)[0]; ++f)
    {
        float reach = 0.5f + Frame(0, 2, f)[2] / 16.0f * 0.5f;

        if (reach > sDistance)
            sDistance = reach;
    }
    for (int f = 0; f < Anim(0)[0]; ++f)
    {
        const uint8_t *r = Frame(0, 0, f);
        int bottom = (int8_t)r[1] + r[3];

        if (f == 0 || bottom > sFoot)
            sFoot = bottom;
    }
    return true;
}

/* The party's first Pokemon able to walk: not an egg, not fainted. */
static int LeadNational(void)
{
    for (int i = 0; i < PARTY_SIZE; ++i)
    {
        u16 species = GetMonData(&gPlayerParty[i], MON_DATA_SPECIES_OR_EGG, NULL);

        if (species == SPECIES_NONE || species == SPECIES_EGG)
            continue;
        if (GetMonData(&gPlayerParty[i], MON_DATA_HP, NULL) == 0)
            continue;
        return SpeciesToNationalPokedexNum(species);
    }
    return 0;
}

static void FacingVector(float *x, float *z)
{
    u8 facing = gObjectEvents[gPlayerAvatar.objectEventId].facingDirection;

    *x = facing == DIR_WEST ? -1.0f : facing == DIR_EAST ? 1.0f : 0.0f;
    *z = facing == DIR_NORTH ? -1.0f : facing == DIR_SOUTH ? 1.0f : 0.0f;
}

/* A new path: the player, and a tile behind them. */
static void StartPath(float px, float pz)
{
    float fx, fz;

    FacingVector(&fx, &fz);
    sPathX[0] = px - fx * sDistance;
    sPathZ[0] = pz - fz * sDistance;
    sPathX[1] = px;
    sPathZ[1] = pz;
    sPathCount = 2;
    sX = sPathX[0];
    sZ = sPathZ[0];
    sDirX = fx;
    sDirZ = fz;
    sScreenDir = -1;
    sPlaced = true;
    sStill = 1000;
}

void VoxelFollower_Reset(void)
{
    sPlaced = false;
    sPathCount = 0;
    sDrawnKey = -1;
}

/* The point `distance` back along the path from the player at (px, pz). */
static void PathPoint(float px, float pz, float distance, float *x, float *z)
{
    float tx = px, tz = pz, left = distance;

    for (int i = sPathCount - 1; i >= 0; --i)
    {
        float sx = sPathX[i] - tx, sz = sPathZ[i] - tz;
        float len = sqrtf(sx * sx + sz * sz);

        if (len >= left)
        {
            tx += sx * (left / len);
            tz += sz * (left / len);
            break;
        }
        left -= len;
        tx = sPathX[i];
        tz = sPathZ[i];
    }
    *x = tx;
    *z = tz;
}

static void Follow(float px, float pz)
{
    float lastX = sPathX[sPathCount - 1], lastZ = sPathZ[sPathCount - 1];
    float dx = px - lastX, dz = pz - lastZ;
    float ox = sX, oz = sZ, ax, az;

    if (dx * dx + dz * dz >= PATH_STEP * PATH_STEP)
    {
        if (sPathCount == PATH_POINTS)
        {
            memmove(sPathX, sPathX + 1, sizeof(float) * (PATH_POINTS - 1));
            memmove(sPathZ, sPathZ + 1, sizeof(float) * (PATH_POINTS - 1));
            --sPathCount;
        }
        sPathX[sPathCount] = px;
        sPathZ[sPathCount] = pz;
        ++sPathCount;
    }
    /* back along the path from the player, a tile of it or more */
    PathPoint(px, pz, sDistance, &sX, &sZ);
    dx = sX - ox;
    dz = sZ - oz;
    if (dx * dx + dz * dz > 0.0004f * 0.0004f)
    {
        float step = sqrtf(dx * dx + dz * dz);
        float hx, hz, len;

        /* Facing where the path goes a little further on, eased: free
         * movement lays the path down a pixel across, a pixel along, and
         * the frame's own step turned the sprite between a diagonal and a
         * straight direction every few frames - it flickered. */
        PathPoint(px, pz, sDistance > HEADING_AHEAD ? sDistance - HEADING_AHEAD : 0.0f, &ax, &az);
        hx = ax - sX;
        hz = az - sZ;
        len = sqrtf(hx * hx + hz * hz);
        if (len < 0.01f)
        {
            hx = dx;
            hz = dz;
            len = step;
        }
        hx = sDirX + (hx / len - sDirX) * HEADING_EASE;
        hz = sDirZ + (hz / len - sDirZ) * HEADING_EASE;
        len = sqrtf(hx * hx + hz * hz);
        if (len > 0.001f)
        {
            sDirX = hx / len;
            sDirZ = hz / len;
        }
        /* a sixteenth of a tile a frame is walking pace: the walk's own speed */
        sAnimTime += step * 16.0f < 0.5f ? 0.5f : step * 16.0f > 3.0f ? 3.0f : step * 16.0f;
        if (sStill > 8)
            sAnimTime = 0.0f;
        sStill = 0;
    }
    else
    {
        if (++sStill == 8)
            sAnimTime = 0.0f;
        sAnimTime += 1.0f;
    }
}

/* The direction as the camera sees it: 0 down (towards the camera), 2
 * right, 4 up, 6 left, the diagonals between. */
static int ScreenDirection(float yawDegrees)
{
    const float pi = 3.14159265358979323846f;
    float yaw = yawDegrees * (pi / 180.0f);
    float sx = sDirX * cosf(yaw) - sDirZ * sinf(yaw);
    float sy = sDirX * sinf(yaw) + sDirZ * cosf(yaw);
    float angle = atan2f(sx, sy) * (180.0f / pi);
    int k = (int)lroundf(angle / 45.0f);

    k = ((k % DIRECTIONS) + DIRECTIONS) % DIRECTIONS;
    /* the one it shows until the heading is well into another's sector */
    if (sScreenDir >= 0 && k != sScreenDir)
    {
        float off = fabsf(fmodf(angle - sScreenDir * 45.0f + 540.0f, 360.0f) - 180.0f);

        if (off < 22.5f + TURN_MARGIN)
            k = sScreenDir;
    }
    sScreenDir = k;
    return k;
}

static int FrameAt(const uint8_t *anim, float time)
{
    int frames = anim[0], total = 0, t;

    for (int f = 0; f < frames; ++f)
        total += anim[36 + f] ? anim[36 + f] : 1;
    t = (int)time % (total > 0 ? total : 1);
    for (int f = 0; f < frames; ++f)
    {
        t -= anim[36 + f] ? anim[36 + f] : 1;
        if (t < 0)
            return f;
    }
    return 0;
}

static void Draw(uint16_t *atlas, int anim, int dir, int frame)
{
    const uint8_t *a = Anim(anim), *r = Frame(anim, dir, frame);
    int w = r[2], h = r[3];
    const uint8_t *px = sEntry + Le32(r + 4);
    uint16_t graded[16];
    int clearW = sDrawnW > w ? sDrawnW : w, clearH = sDrawnH > h ? sDrawnH : h;

    if (w > (int)VOXEL_FOLLOWER_CELL_DIM)
        w = VOXEL_FOLLOWER_CELL_DIM;
    if (h > (int)VOXEL_FOLLOWER_CELL_DIM)
        h = VOXEL_FOLLOWER_CELL_DIM;
    graded[0] = 0;
    for (int c = 1; c < 16; ++c)
        graded[c] = VoxelGrade_RGBA5551((uint16_t)(a[4 + 2 * c] | (a[5 + 2 * c] << 8)));
    /* A texel's place in the tiled atlas is a column's part plus a row's: the
     * columns' once, the row's once a row - a call a texel was a good part of
     * an Old 3DS's frame whenever the frame changed. */
    if (!sColumnsBuilt)
    {
        for (unsigned x = 0; x < VOXEL_FOLLOWER_CELL_DIM; ++x)
            sColumn[x] = CtrVideo_Texel(VOXEL_FOLLOWER_CELL_X + x, 0, VOXEL_SPRITE_ATLAS_DIM);
        sColumnsBuilt = true;
    }
    if (clearW > (int)VOXEL_FOLLOWER_CELL_DIM)
        clearW = VOXEL_FOLLOWER_CELL_DIM;
    if (clearH > (int)VOXEL_FOLLOWER_CELL_DIM)
        clearH = VOXEL_FOLLOWER_CELL_DIM;
    for (int y = 0; y < clearH; ++y)
    {
        uint16_t *row = atlas + (CtrVideo_Texel(VOXEL_FOLLOWER_CELL_X, VOXEL_FOLLOWER_CELL_Y + (unsigned)y,
                                                VOXEL_SPRITE_ATLAS_DIM) - sColumn[0]);
        const uint8_t *line = px;
        int x = 0, k = y * r[2];

        if (y < h)
            for (; x < w; ++x, ++k)
                row[sColumn[x]] = graded[(line[k >> 1] >> ((k & 1) * 4)) & 15];
        for (; x < clearW; ++x)
            row[sColumn[x]] = 0;
    }
    sDrawnW = w;
    sDrawnH = h;
}

bool VoxelFollower_Update(uint16_t *atlas, float yawDegrees, VoxelFollowerCard *card)
{
    const struct ObjectEvent *player = &gObjectEvents[gPlayerAvatar.objectEventId];
    float px, pz;
    u16 mapKey;
    int national, anim, dir, frame, key;
    const uint8_t *r;

    if (!CtrPlayer_Follower() || sFileBad || !OpenFile())
        return false;
    /* not on the water, a bike or in a battle; not when the player is
     * hidden, nor in the quest log's recap of an earlier session */
    if (gMain.inBattle || player->invisible || gQuestLogState != 0
     || (gPlayerAvatar.flags & (PLAYER_AVATAR_FLAG_SURFING | PLAYER_AVATAR_FLAG_UNDERWATER
                                | PLAYER_AVATAR_FLAG_MACH_BIKE | PLAYER_AVATAR_FLAG_ACRO_BIKE)))
    {
        VoxelFollower_Reset();
        return false;
    }
    national = LeadNational();
    if (!Load(national))
        return false;

    VoxelEntities_GetPlayerTilePos(&px, &pz);
    mapKey = (u16)(gSaveBlock1Ptr->location.mapGroup << 8 | gSaveBlock1Ptr->location.mapNum);
    if (!sPlaced || mapKey != sMapKey
     || fabsf(px - sPathX[sPathCount - 1]) > WARP_JUMP || fabsf(pz - sPathZ[sPathCount - 1]) > WARP_JUMP)
        StartPath(px, pz);
    sMapKey = mapKey;
    Follow(px, pz);

    anim = sStill > 8 ? 1 : 0;
    dir = ScreenDirection(yawDegrees);
    frame = FrameAt(Anim(anim), sAnimTime);
    key = ((national * 2 + anim) * DIRECTIONS + dir) * 16 + frame;
    if (key != sDrawnKey)
    {
        Draw(atlas, anim, dir, frame);
        sDrawnKey = key;
    }
    r = Frame(anim, dir, frame);
    card->x = sX;
    card->z = sZ;
    card->dx = (int8_t)r[0];
    card->dy = (int8_t)r[1];
    card->w = sDrawnW;
    card->h = sDrawnH;
    card->foot = sFoot;
    return true;
}
