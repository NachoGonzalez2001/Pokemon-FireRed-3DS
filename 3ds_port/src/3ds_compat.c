/*
 * ARM11 implementation of the portable bridge hooks that are not resource
 * lookups: logging, debug channels, fonts, script/text pointers, save storage
 * and the audio debug channel. Every deferred behaviour is logged with the
 * plan's stub tag; none of them returns a fake success.
 */

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "port_platform.h"
#include "port_log.h"
#include "3ds_data.h"
#include "3ds_assets.h"
#include "3ds_platform.h"
#include "3ds_audio.h"
#include "gba/flash_internal.h"

/*
 * global.h redirects these four GBA registers to RAM under the bridge; this is
 * the storage the emulated registers live in, shared by every translation unit
 * that sees the bridge.
 */
volatile unsigned short gPortEmuIME;
volatile unsigned short gPortEmuIE;
volatile unsigned short gPortEmuIF;
volatile unsigned short gPortEmuDISPSTAT;

/* ── Logging bridge ─────────────────────────────────────────────────────── */

unsigned char g_PortLogActive = 1;

void Port_Log_Printf(const char *fmt, ...)
{
    char line[256];
    va_list args;
    size_t length;

    va_start(args, fmt);
    vsnprintf(line, sizeof(line), fmt, args);
    va_end(args);
    /* The game's messages end in '\n'; the 3DS logger adds its own. */
    length = strlen(line);
    while (length != 0 && (line[length - 1] == '\n' || line[length - 1] == '\r'))
        line[--length] = '\0';
    CtrLog_Write(CTR_LOG_GAME, "%s", line);
}

void Port_Log_Init(void) {}
void Port_Log_SetEnabled(unsigned char enabled) { g_PortLogActive = enabled; }
unsigned char Port_Log_IsEnabled(void) { return g_PortLogActive; }
void Port_Log_VBlankProtect(void) {}

void CtrAssets_Fatal(const char *detail)
{
    static char message[192];

    snprintf(message, sizeof(message), "[FS] %s", detail != NULL ? detail : "resource failure");
    CtrPlatform_Fatal(message);
}

/* ── Debug channels ─────────────────────────────────────────────────────── */

volatile u16 gPortDbgBirchTag, gPortDbgBirchA, gPortDbgBirchB, gPortDbgBirchC, gPortDbgBirchD;
volatile u16 gPortDbgDmaTag, gPortDbgDmaA, gPortDbgDmaB, gPortDbgDmaC, gPortDbgDmaD;
volatile u16 gPortDbgDma2Tag, gPortDbgDma2A, gPortDbgDma2B, gPortDbgDma2C, gPortDbgDma2D;
volatile u16 gPortDbgAudioTag, gPortDbgAudioA, gPortDbgAudioB, gPortDbgAudioC, gPortDbgAudioD;
volatile u16 gPortDbgAssetTag, gPortDbgAssetA, gPortDbgAssetB, gPortDbgAssetC;

void Port_SetBirchDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d)
{
    gPortDbgBirchTag = tag; gPortDbgBirchA = a; gPortDbgBirchB = b;
    gPortDbgBirchC = c; gPortDbgBirchD = d;
}

void Port_SetBirchDebug(u16 tag, u16 a, u16 b, u16 c) { Port_SetBirchDebugEx(tag, a, b, c, 0); }

void Port_SetDmaDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d)
{
    gPortDbgDmaTag = tag; gPortDbgDmaA = a; gPortDbgDmaB = b; gPortDbgDmaC = c; gPortDbgDmaD = d;
}

void Port_SetDmaDebug(u16 tag, u16 a, u16 b, u16 c) { Port_SetDmaDebugEx(tag, a, b, c, 0); }

void Port_SetDmaDebug2(u16 tag, u16 a, u16 b, u16 c, u16 d)
{
    gPortDbgDma2Tag = tag; gPortDbgDma2A = a; gPortDbgDma2B = b; gPortDbgDma2C = c; gPortDbgDma2D = d;
}

/*
 * The mixer already marks its own frame through this channel: 0x0D00 is the
 * first statement of RunMixerFrame and 0x0D09 the last, after the CGB channels
 * have been generated. Timing those two is the whole mixer cost, and it costs
 * nothing to measure at a point the code was going to call anyway.
 */
void Port_SetAudioDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d)
{
    /* 0x0D02-03 the sequencer, 0x0D04-05 the PSG registers, 0x0D06-07 the
     * sampled voices, 0x0D08-09 the PSG channels' waves. */
    static uint64_t mixStart, partStart;
    static uint64_t parts[4];

    gPortDbgAudioTag = tag; gPortDbgAudioA = a; gPortDbgAudioB = b;
    gPortDbgAudioC = c; gPortDbgAudioD = d;

    if ((tag & 0xFFF0) != 0x0D00)
        return;
    if (tag == 0x0D00)
    {
        mixStart = CtrPlatform_Ticks();
    }
    else if (tag == 0x0D02 || tag == 0x0D04 || tag == 0x0D06 || tag == 0x0D08)
    {
        partStart = CtrPlatform_Ticks();
    }
    else if ((tag == 0x0D03 || tag == 0x0D05 || tag == 0x0D07) && partStart != 0)
    {
        parts[(tag - 0x0D03) / 2] += CtrPlatform_Ticks() - partStart;
        partStart = 0;
    }
    else if (tag == 0x0D09 && mixStart != 0)
    {
        static float sum, peak;
        static unsigned frames;
        uint64_t now = CtrPlatform_Ticks();
        float ms = CtrPlatform_TickMs(now - mixStart);

        if (partStart != 0)
            parts[3] += now - partStart;
        partStart = 0;
        CtrAudio_Stats()->mixMs = ms;
        mixStart = 0;
        /* Wherever it runs (a worker core or the game thread), its average
         * and worst in the log, every 600 mixed frames. */
        sum += ms;
        if (ms > peak) peak = ms;
        if (++frames == 600)
        {
            CtrLog_Write(CTR_LOG_AUDIO, "mixer %.3f ms a frame, peak %.3f (sequencer %.3f, psg regs %.3f, "
                         "voices %.3f, psg waves %.3f)", sum / frames, peak,
                         CtrPlatform_TickMs(parts[0]) / frames, CtrPlatform_TickMs(parts[1]) / frames,
                         CtrPlatform_TickMs(parts[2]) / frames, CtrPlatform_TickMs(parts[3]) / frames);
            sum = peak = 0.0f;
            frames = 0;
            memset(parts, 0, sizeof(parts));
        }
    }
}

void Port_SetAssetDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d)
{
    (void)d;
    gPortDbgAssetTag = tag; gPortDbgAssetA = a; gPortDbgAssetB = b; gPortDbgAssetC = c;
}

void Port_SetAssetDebug(u16 tag, u16 a, u16 b, u16 c) { Port_SetAssetDebugEx(tag, a, b, c, 0); }

void Port_SetGfxTilesetDebug(u8 secondary, u16 size, u8 nonzero)
{
    (void)secondary; (void)size; (void)nonzero;
}

void Port_SetGfxPaletteDebug(u8 secondary, u8 nonzero, u8 resolved)
{
    (void)secondary; (void)nonzero; (void)resolved;
}

void Port_SetGfxMetatileDebug(u16 id, u8 resolved, u16 first, u16 second)
{
    (void)id; (void)resolved; (void)first; (void)second;
}

/* Safe point between main-loop callbacks: the only place payloads may retire. */
void Port_RecordMainLoopIteration(void)
{
    CtrAssets_Collect();
}

/* ── Latin fonts ────────────────────────────────────────────────────────── */

/*
 * FireRed's glyph tables are static in text.c, which resolves each table's
 * base through the asset index before adding a glyph's offset (its GLYPHS
 * macro); there is no global font table to keep here, as the Emerald port
 * has. Fonts load on first use like every other asset.
 */
const void *Port_ResolveFontPointer(const void *ptr)
{
    return Port_ResolveAssetPointer(ptr);
}

void Port_PreloadLatinFonts(void) {}

void Port_TextPreload(void) {}

bool Port_FontProbe_ReadNormalLatinGlyph(u16 glyphId, u8 *outBuf, u32 outSize)
{
    (void)glyphId; (void)outBuf; (void)outSize;
    return false;
}

const void *Port_FontProbe_GetNormalLatinStubBase(void)
{
    return NULL;
}

u16 Port_FontProbe_CompareNormalLatinGlyph(u16 glyphId)
{
    (void)glyphId;
    return 0xFFFF;
}

/* ── Save storage ───────────────────────────────────────────────────────────
 *
 * The image is mirrored in FLASH_BASE so reads and verification stay cheap, and each write
 * puts *only its own range* into the file. Rewriting all 128 KiB per sector
 * would be fourteen times the traffic per save and would destroy the other
 * rotating slot on a half-finished write.
 *
 * The directory is created by CtrFs_Init, which runs before the game starts.
 */

/* Builds before the FireRed name kept it in sdmc:/3ds/emerald3ds/: see
 * CtrFs_MigrateLegacy (3ds_fs.c). */
#define CTR_SAVE_PATH CTR_DATA_DIR "firered3ds.sav"

static bool sSaveAvailable;

void Port_SaveInit(void)
{
    FILE *file;
    long size;
    bool loaded;

    memset(FLASH_BASE, 0xFF, sizeof(FLASH_BASE));
    sSaveAvailable = false;

    file = fopen(CTR_SAVE_PATH, "rb");
    if (file == NULL)
    {
        /* Created by the first real save, not while starting a new game. */
        sSaveAvailable = errno == ENOENT;
        CtrLog_Write(sSaveAvailable ? CTR_LOG_FS : CTR_LOG_ERROR,
                     "save %s: %s (errno=%d)",
                     sSaveAvailable ? "will be created" : "unavailable",
                     CTR_SAVE_PATH, errno);
        return;
    }

    size = -1;
    if (fseek(file, 0, SEEK_END) == 0)
        size = ftell(file);
    loaded = size >= 0 && (u32)size <= sizeof(FLASH_BASE)
          && fseek(file, 0, SEEK_SET) == 0
          && fread(FLASH_BASE, 1, (size_t)size, file) == (size_t)size && !ferror(file);
    if (fclose(file) != 0)
        loaded = false;
    if (!loaded)
    {
        memset(FLASH_BASE, 0xFF, sizeof(FLASH_BASE));
        CtrLog_Write(CTR_LOG_ERROR, "save read failed: %s (size=%ld)", CTR_SAVE_PATH, size);
        return;
    }

    /* A short file still holds whole sectors; the game recovers the older slot. */
    sSaveAvailable = true;
    CtrLog_Write(CTR_LOG_FS, "save loaded: %s (%ld bytes)", CTR_SAVE_PATH, size);
}

bool Port_SaveIsAvailable(void)
{
    return sSaveAvailable;
}

u16 Port_WriteFlash(u32 offset, const void *data, u32 size)
{
    FILE *file;
    long fileSize;
    bool ok;

    if (!sSaveAvailable || data == NULL || offset > sizeof(FLASH_BASE)
     || size > sizeof(FLASH_BASE) - offset)
        return 1;

    file = fopen(CTR_SAVE_PATH, "r+b");
    if (file == NULL && errno == ENOENT)
        file = fopen(CTR_SAVE_PATH, "w+b");
    if (file == NULL)
        goto fail;

    /* Writing past the end of a short file would leave a hole, so the image is
     * grown from the mirror first and only then is the range written. */
    ok = fseek(file, 0, SEEK_END) == 0;
    fileSize = ok ? ftell(file) : -1;
    ok = fileSize >= 0 && (u32)fileSize <= sizeof(FLASH_BASE);
    if (ok && (u32)fileSize < sizeof(FLASH_BASE))
    {
        u32 remaining = sizeof(FLASH_BASE) - (u32)fileSize;

        ok = fwrite(FLASH_BASE + fileSize, 1, remaining, file) == remaining;
    }
    if (ok)
        ok = fseek(file, (long)offset, SEEK_SET) == 0 && fwrite(data, 1, size, file) == size;
    if (ok)
        ok = fflush(file) == 0;
    if (fclose(file) != 0)
        ok = false;
    if (!ok)
        goto fail;

    memmove(FLASH_BASE + offset, data, size);
    return 0;

fail:
    CtrLog_Write(CTR_LOG_ERROR, "save write failed: offset=%lu size=%lu errno=%d",
                 (unsigned long)offset, (unsigned long)size, errno);
    return 1;
}

/* ── Entry points the excluded GBA link/multiboot units would provide ───── */

/* FireRed builds its Mystery Gift and e-Reader screens as they are (no link
 * partner ever answers); only the berry-fix multiboot program is left out. */
u32 JoyBusRead(void) { return 0; }
void JoyBusWrite(void) {}
void CB2_InitBerryFixProgram(void) { CTR_STUB("BERRY_FIX", "GBA berry-fix program not applicable"); }

/* src/rom_header.s, which the executable does not assemble: the cartridge
 * identity the game compares against a link partner's. */
const char RomHeaderGameCode[4] = {'B', 'P', 'R', 'E'};
const char RomHeaderSoftwareVersion = 1;   /* rev 1 */

/* src/crt0.s's interrupt dispatcher: main.c copies it into IntrMain_Buffer
 * (0x800 bytes), which nothing runs here (CtrGame_VBlank calls the handlers
 * itself). Zeroes of the copy's size, so the copy reads only its own source. */
const u32 intr_main[0x200];

/*
 * Save-image verification. The GBA original relocated its comparison loop into
 * IWRAM because the cartridge bus needed it; here the save image is ordinary
 * RAM. VerifyFlashSector_Core is compiled out under PORTABLE (it returns 0
 * unconditionally), so this compares the bytes itself instead of reporting a
 * match that was never checked.
 */
static u32 CompareSaveBytes(const u8 *src, const u8 *target, u32 size)
{
    while (size-- != 0)
    {
        if (*target++ != *src++)
            return (u32)(target - 1);
    }
    return 0;
}

u32 VerifyFlashSectorNBytes(u16 sectorNum, u8 *src, u32 n)
{
    u32 base;

    if (gFlash == NULL || sectorNum >= gFlash->sector.count || n == 0
     || n > gFlash->sector.size)
        return 1;
    base = (u32)sectorNum << gFlash->sector.shift;
    if (base >= sizeof(FLASH_BASE) || n > sizeof(FLASH_BASE) - base)
        return 1;
    return CompareSaveBytes(src, FLASH_BASE + base, n);
}

u32 VerifyFlashSector(u16 sectorNum, u8 *src)
{
    return VerifyFlashSectorNBytes(sectorNum, src, gFlash != NULL ? gFlash->sector.size : 0);
}
