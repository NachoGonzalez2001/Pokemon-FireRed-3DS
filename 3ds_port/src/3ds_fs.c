#include <3ds.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include "3ds_platform.h"
#include "3ds_data.h"

static bool sMounted;

static bool RelativePathValid(const char *path)
{
    if (!path || !*path || *path == '/' || strchr(path, ':') || strchr(path, '\\'))
        return false;
    /* Public API only accepts paths inside its chosen mount. */
    const char *p = path;
    while (*p)
    {
        const char *end = strchr(p, '/');
        size_t size = end ? (size_t)(end - p) : strlen(p);
        if (size == 0 || (size == 1 && p[0] == '.') || (size == 2 && p[0] == '.' && p[1] == '.'))
            return false;
        if (!end)
            break;
        p = end + 1;
    }
    return true;
}

static FILE *Open(const char *base, const char *path, const char *mode)
{
    char full[512];
    if (!RelativePathValid(path) || !mode)
    {
        errno = EINVAL;
        CtrLog_Write(CTR_LOG_ERROR, "invalid filesystem path/mode");
        return NULL;
    }
    if (snprintf(full, sizeof(full), "%s%s", base, path) >= (int)sizeof(full))
    {
        errno = ENAMETOOLONG;
        return NULL;
    }
    FILE *file = fopen(full, mode);
    if (!file)
        CtrLog_Write(CTR_LOG_ERROR, "open %s: errno=%d", full, errno);
    return file;
}

/*
 * Builds before the FireRed name kept their files in sdmc:/3ds/emerald3ds/,
 * the Emerald port's folder - which that port, beside this one on a card,
 * uses too. The save is copied (the old one stays, a backup) when the new
 * folder has none and the old one is FireRed's: section 0 of a FireRed save,
 * the trainer's, holds the game code 1 at 0xAC, where Emerald keeps a random
 * security key. The settings and the log switch come along with it.
 */
#define LEGACY_DIR "sdmc:/3ds/emerald3ds/"
#define SAVE_SECTOR 0x1000
#define SAVE_SECTORS 32
static const char *sMigrated;

static bool IsFireRedSave(const char *path)
{
    static u8 sector[SAVE_SECTOR];
    FILE *file = fopen(path, "rb");
    bool fireRed = false;

    if (file == NULL)
        return false;
    for (int i = 0; i < SAVE_SECTORS && !fireRed; i++)
    {
        u16 id;
        u32 signature, code;

        if (fread(sector, 1, SAVE_SECTOR, file) != SAVE_SECTOR)
            break;
        memcpy(&id, sector + 0xFF4, 2);
        memcpy(&signature, sector + 0xFF8, 4);
        memcpy(&code, sector + 0xAC, 4);
        fireRed = id == 0 && signature == 0x08012025 && code == 1;
    }
    fclose(file);
    return fireRed;
}

static bool Exists(const char *path)
{
    struct stat st;

    return stat(path, &st) == 0;
}

static bool CopyFile(const char *from, const char *to)
{
    static u8 buffer[16 * 1024];
    FILE *in = fopen(from, "rb"), *out;
    bool ok = in != NULL;
    size_t n;

    if (!ok)
        return false;
    out = fopen(to, "wb");
    ok = out != NULL;
    while (ok && (n = fread(buffer, 1, sizeof(buffer), in)) > 0)
        ok = fwrite(buffer, 1, n, out) == n;
    ok = ok && !ferror(in);
    fclose(in);
    if (out != NULL && fclose(out) != 0)
        ok = false;
    if (!ok)
        remove(to);
    return ok;
}

void CtrFs_MigrateLegacy(void)
{
    static const char *const sFiles[] = { "settings.txt", "debug.txt" };

    mkdir("sdmc:/3ds", 0777);
    mkdir("sdmc:/3ds/firered3ds", 0777);
    if (Exists(CTR_DATA_DIR "firered3ds.sav") || !IsFireRedSave(LEGACY_DIR "emerald3ds.sav"))
        return;
    if (!CopyFile(LEGACY_DIR "emerald3ds.sav", CTR_DATA_DIR "firered3ds.sav"))
    {
        sMigrated = "save copy FAILED";
        return;
    }
    for (unsigned i = 0; i < sizeof(sFiles) / sizeof(sFiles[0]); i++)
    {
        char from[64], to[64];

        snprintf(from, sizeof(from), LEGACY_DIR "%s", sFiles[i]);
        snprintf(to, sizeof(to), CTR_DATA_DIR "%s", sFiles[i]);
        if (Exists(from) && !Exists(to))
            CopyFile(from, to);
    }
    sMigrated = "save and settings copied";
}

bool CtrFs_Init(void)
{
    if (sMigrated != NULL)
        CtrLog_Write(CTR_LOG_FS, "from %s: %s", LEGACY_DIR, sMigrated);
    Result result = romfsInit();
    sMounted = R_SUCCEEDED(result);
    if (!sMounted)
    {
        CtrLog_Write(CTR_LOG_ERROR, "romfsInit: %08lx", (unsigned long)result);
        return false;
    }
    mkdir("sdmc:/3ds", 0777);
    mkdir("sdmc:/3ds/firered3ds", 0777);
    FILE *file = CtrFs_OpenAsset("boot.txt");
    char contents[64] = {0};
    bool valid = file && fgets(contents, sizeof(contents), file)
        && strcmp(contents, "FireRed3DS RomFS v1\n") == 0;
    if (file)
        fclose(file);
    CtrLog_Write(valid ? CTR_LOG_FS : CTR_LOG_ERROR, "RomFS boot marker %s", valid ? "PASS" : "FAIL");
    return valid;
}

void CtrFs_Shutdown(void)
{
    if (sMounted)
        romfsExit();
    sMounted = false;
}

FILE *CtrFs_OpenAsset(const char *relativePath)
{
    if (!sMounted)
    {
        errno = ENODEV;
        return NULL;
    }
    return Open("romfs:/", relativePath, "rb");
}

FILE *CtrFs_OpenData(const char *relativePath, const char *mode)
{
    return Open("sdmc:/3ds/firered3ds/", relativePath, mode);
}
