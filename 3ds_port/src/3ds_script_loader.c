/*
 * ARM11 bundle loader: game data, scripts and songs.
 *
 * Three regions of the executable are reserved empty and filled from the game
 * data before AgbMain runs. Script bytecode and MP2K song data are bundled
 * because their pointers sit at unaligned offsets and 3dsxtool refuses to build
 * a relocation table for them; the game's linked read-only data is bundled
 * because it is game content and ships in the data pack, not in the 3DSX. Each
 * region has exactly the payload's size, with every symbol already at its real
 * offset inside it (scripts/ctr_bundle.py, scripts/gen_gamedata_bundle.py).
 *
 * Because each region is where its symbols already point, `EventScript_X`,
 * `gScriptCmdTable` and `gSongTable[n].header` need no resolution hook.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "port_platform.h"
#include "port_log.h"
#include "3ds_assets.h"
#include "3ds_data.h"

#define BUNDLE_VERSION 1

#define SCRIPT_BUNDLE_PATH "scripts/scripts.bin"
#define SCRIPT_RELOC_PATH "romfs:/scripts/scripts.rel"
#define SCRIPT_BUNDLE_MAGIC 0x42533343u /* "C3SB", little endian */

#define SONG_BUNDLE_PATH "sound/songs.bin"
#define SONG_RELOC_PATH "romfs:/sound/songs.rel"
#define SONG_BUNDLE_MAGIC 0x42413343u /* "C3AB", little endian */

#define GAMEDATA_BUNDLE_PATH "gamedata/gamedata.bin"
#define GAMEDATA_RELOC_PATH "romfs:/gamedata/gamedata.rel"
#define GAMEDATA_BUNDLE_MAGIC 0x44473343u /* "C3GD", little endian */

extern u8 __ctr_script_blob[], __ctr_script_blob_end[];
extern u8 __ctr_song_blob[], __ctr_song_blob_end[];
/* The game's linked read-only data, reserved NOLOAD by emerald3ds.ld.in. */
extern u8 __ctr_gamedata[], __ctr_gamedata_end[];
void AgbMain(void);

struct BundleHeader
{
    u32 magic;
    u32 version;
    u32 payloadBytes;
    u32 referenceAddress;
    u32 internalCount;
    u32 externalCount;
};

static u32 sScriptBytes;
static u32 sSongBytes;
static u32 sGameDataBytes;

static void *ReadFile(const char *path, u32 *outSize)
{
    FILE *file = fopen(path, "rb");
    long size;
    void *buffer;

    if (file == NULL)
        return NULL;
    if (fseek(file, 0, SEEK_END) != 0 || (size = ftell(file)) <= 0
     || fseek(file, 0, SEEK_SET) != 0)
    {
        fclose(file);
        return NULL;
    }
    buffer = malloc((size_t)size);
    if (buffer == NULL || fread(buffer, 1, (size_t)size, file) != (size_t)size)
    {
        free(buffer);
        fclose(file);
        return NULL;
    }
    fclose(file);
    *outSize = (u32)size;
    return buffer;
}

/* Relocation sites are unaligned by construction: never store through a u32*. */
static u32 ReadSite(const u8 *at)
{
    u32 value;

    memcpy(&value, at, sizeof(value));
    return value;
}

static void WriteSite(u8 *at, u32 value)
{
    memcpy(at, &value, sizeof(value));
}

static bool LoadBundle(const char *what, const char *payloadPath, const char *relocPath,
                       u32 magic, u8 *blob, const u8 *blobEnd, u32 *outBytes)
{
    u32 region = (u32)(blobEnd - blob);
    struct BundleHeader header;
    u8 *relocs = NULL;
    FILE *payload = NULL;
    u32 payloadBytes = 0, relocBytes = 0, i;
    const u32 *sites;
    u32 delta;

    relocs = ReadFile(relocPath, &relocBytes);
    if (relocs == NULL || !CtrData_Size(payloadPath, &payloadBytes))
    {
        PORT_LOG("[ERROR] %s bundle missing (%s, %s)\n", what, payloadPath, relocPath);
        goto fail;
    }
    if (relocBytes < sizeof(header))
    {
        PORT_LOG("[ERROR] %s relocation table truncated\n", what);
        goto fail;
    }
    memcpy(&header, relocs, sizeof(header));
    if (header.magic != magic || header.version != BUNDLE_VERSION
     || header.payloadBytes != payloadBytes || payloadBytes != region
     || relocBytes != sizeof(header) + 4u * (header.internalCount + header.externalCount))
    {
        PORT_LOG("[ERROR] %s bundle does not match this executable "
                "(payload %lu, region %lu)\n",
                what, (unsigned long)payloadBytes, (unsigned long)region);
        goto fail;
    }

    /* Straight into the reserved region: no second copy of the payload. */
    payload = CtrData_Open(payloadPath);
    if (payload == NULL || fread(blob, 1, payloadBytes, payload) != payloadBytes)
    {
        PORT_LOG("[ERROR] %s payload could not be read\n", what);
        goto fail;
    }
    fclose(payload);
    payload = NULL;

    /* Everything the bundle knows about the executable was recorded at link
     * time; one symbol is enough to learn where the image actually landed. */
    delta = (u32)(uintptr_t)AgbMain - header.referenceAddress;

    sites = (const u32 *)(relocs + sizeof(header));
    for (i = 0; i < header.internalCount; i++)
    {
        u32 site = sites[i];

        if (site + 4 > region)
            goto badSite;
        WriteSite(blob + site, (u32)(uintptr_t)blob + ReadSite(blob + site));
    }
    sites += header.internalCount;
    for (i = 0; i < header.externalCount; i++)
    {
        u32 site = sites[i];

        if (site + 4 > region)
            goto badSite;
        WriteSite(blob + site, ReadSite(blob + site) + delta);
    }

    free(relocs);
    *outBytes = payloadBytes;
    PORT_LOG("[FS] %s: %lu KiB in place, %lu internal + %lu external relocs, rebase %ld\n",
            what, (unsigned long)(payloadBytes >> 10), (unsigned long)header.internalCount,
            (unsigned long)header.externalCount, (long)delta);
    return true;

badSite:
    PORT_LOG("[ERROR] %s relocation site outside the reserved region\n", what);
fail:
    if (payload != NULL)
        fclose(payload);
    free(relocs);
    return false;
}

bool CtrGameData_Init(void)
{
    static bool ready, tried;

    if (tried)
        return ready;
    tried = true;
    ready = LoadBundle("game data", GAMEDATA_BUNDLE_PATH, GAMEDATA_RELOC_PATH, GAMEDATA_BUNDLE_MAGIC,
                       __ctr_gamedata, __ctr_gamedata_end, &sGameDataBytes);
    return ready;
}

u32 CtrGameData_Bytes(void)
{
    return sGameDataBytes;
}

bool CtrScripts_Init(void)
{
    static bool ready, tried;

    if (tried)
        return ready;
    tried = true;
    ready = LoadBundle("scripts", SCRIPT_BUNDLE_PATH, SCRIPT_RELOC_PATH, SCRIPT_BUNDLE_MAGIC,
                       __ctr_script_blob, __ctr_script_blob_end, &sScriptBytes);
    return ready;
}

u32 CtrScripts_Bytes(void)
{
    return sScriptBytes;
}

bool CtrSongs_Init(void)
{
    static bool ready, tried;

    if (tried)
        return ready;
    tried = true;
    ready = LoadBundle("songs", SONG_BUNDLE_PATH, SONG_RELOC_PATH, SONG_BUNDLE_MAGIC,
                       __ctr_song_blob, __ctr_song_blob_end, &sSongBytes);
    return ready;
}

u32 CtrSongs_Bytes(void)
{
    return sSongBytes;
}

/*
 * The script data occupies the addresses its symbols already had, so these are
 * the identity. They exist because the shared game tree calls them; keeping the
 * call sites untouched is what lets the same sources build for both ports.
 */
const u8 *Port_ResolveScriptPointer(const u8 *ptr) { return ptr; }
const u8 *Port_ResolveTextPointer(const u8 *ptr) { return ptr; }
const void *Port_ResolveEventPointer(const void *ptr) { return ptr; }
