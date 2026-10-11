/*
 * ARM11 map payload resolver.
 *
 * `gen_map_data.py` replaces every `.incbin "data/layouts/<map>/map.bin"` with a
 * 12-byte descriptor {offset, size, slot} and writes all payloads to a single
 * `maps/layouts.bin`. The game still sees a pointer to the descriptor, so the
 * resolver maps it to the real tile data.
 *
 * The whole payload file is 0.7 MiB, so it stays resident: a resolved map
 * pointer remains valid for the entire session and map changes free nothing.
 */

#include <stdio.h>
#include <stdlib.h>

#include "port_platform.h"
#include "port_log.h"
#include "3ds_assets.h"
#include "3ds_data.h"

#define MAP_PAYLOAD_PATH "maps/layouts.bin"

struct MapAsset
{
    u32 offset;
    u32 size;
    u32 slot;
};

extern const struct MapAsset gPortMapAssetsStart[], gPortMapAssetsEnd[];

static u8 *sPayload;
static u32 sPayloadSize;
static bool sTried;

bool CtrMaps_Init(void)
{
    FILE *file;
    long size;

    if (sTried)
        return sPayload != NULL;
    sTried = true;

    file = CtrData_Open(MAP_PAYLOAD_PATH);
    if (file == NULL)
    {
        PORT_LOG("[ERROR] map payloads missing: %s\n", MAP_PAYLOAD_PATH);
        return false;
    }
    if (fseek(file, 0, SEEK_END) != 0 || (size = ftell(file)) <= 0
     || fseek(file, 0, SEEK_SET) != 0)
    {
        fclose(file);
        PORT_LOG("[ERROR] map payload file unreadable\n");
        return false;
    }
    sPayload = malloc((size_t)size);
    if (sPayload == NULL || fread(sPayload, 1, (size_t)size, file) != (size_t)size)
    {
        free(sPayload);
        sPayload = NULL;
        fclose(file);
        PORT_LOG("[ERROR] map payloads could not be loaded (%ld bytes)\n", size);
        return false;
    }
    fclose(file);
    sPayloadSize = (u32)size;
    PORT_LOG("[FS] maps: %lu KiB resident, %lu descriptors\n",
            (unsigned long)(sPayloadSize >> 10),
            (unsigned long)(gPortMapAssetsEnd - gPortMapAssetsStart));
    return true;
}

u32 CtrMaps_Bytes(void)
{
    return sPayloadSize;
}

const void *Port_ResolveMapAssetPointer(const void *ptr)
{
    const struct MapAsset *asset = ptr;
    u32 addr = (u32)ptr;

    if (addr < (u32)gPortMapAssetsStart || addr >= (u32)gPortMapAssetsEnd)
        return ptr;
    if ((addr - (u32)gPortMapAssetsStart) % sizeof(*asset) != 0)
        goto fail;
    if (!CtrMaps_Init())
        goto fail;
    if (asset->size == 0 || asset->offset > sPayloadSize
     || asset->size > sPayloadSize - asset->offset)
        goto fail;
    return sPayload + asset->offset;

fail:
    /* A descriptor is not tile data: never continue with it. */
    PORT_LOG("[ERROR] map descriptor %08lX unresolved\n", (unsigned long)addr);
    CtrAssets_Fatal("map payload could not be resolved");
}

extern const struct MapLayout *const gMapLayouts[];
extern const struct MapHeader *const *const gMapGroups[];

const struct MapLayout *Port_GetMapLayoutById(u16 mapLayoutId)
{
    if (mapLayoutId == 0)
        return NULL;
    return gMapLayouts[mapLayoutId - 1];
}

const struct MapHeader *Port_GetMapHeaderByGroupAndId(u16 mapGroup, u16 mapNum)
{
    return gMapGroups[mapGroup][mapNum];
}
