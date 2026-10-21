#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "global.h"
#include "3ds_platform.h"
#include "3ds_audio.h"
#include "3ds_emu_regs.h"
#include "3ds_bottom.h"
#include "gba/flash_internal.h"
/* FireRed has no real-time clock: the RTC entry points exist only for a game
 * that does (Emerald's siirtc.h). */
#if __has_include("siirtc.h")
#include "siirtc.h"
#define CTR_HAS_RTC 1
#else
#define CTR_HAS_RTC 0
#endif

#if CTR_HAS_RTC
static time_t sClockOffset;
static u8 sRtcStatus = SIIRTCINFO_24HOUR;
#endif

void CtrEmu_Reset(void)
{
    memset(REG_BASE, 0, 0x400);
    memset(PLTT, 0, PLTT_SIZE);
    memset(VRAM_, 0, VRAM_SIZE);
    memset(OAM, 0, OAM_SIZE);
    /* The BIOS's reset leaves the affine backgrounds at the identity
     * (PA = PD = 1.0), and games rely on it: FireRed's Oak speech shows its
     * 256-colour pictures on an affine BG2 without ever setting it. */
    REG_BG2PA = 0x100;
    REG_BG2PD = 0x100;
    REG_BG3PA = 0x100;
    REG_BG3PD = 0x100;
    REG_IME = 1;
    REG_KEYINPUT = KEYS_MASK;
    INTR_CHECK = 0;
    INTR_VECTOR = NULL;
}

void CtrEmu_BeginVBlank(void)
{
    REG_VCOUNT = 160;
    REG_DISPSTAT |= DISPSTAT_VBLANK;
    REG_IF |= INTR_FLAG_VBLANK;
}

void CtrEmu_EndVBlank(void)
{
    REG_DISPSTAT &= ~DISPSTAT_VBLANK;
    REG_IF &= ~INTR_FLAG_VBLANK;
    REG_VCOUNT = 0;
}

#ifdef CTR_INPUT_SCRIPT
/*
 * Test input, for driving the game without anyone at the keys:
 * sdmc:/3ds/emerald3ds/keys.txt, one press per line,
 *     <frame> <BUTTON>[+<BUTTON>...] [frames held, default 4]
 * with BUTTON one of A B SELECT START RIGHT LEFT UP DOWN R L, and '#'
 * starting a comment. The presses are held over the real keys.
 *     <frame> TOUCH <x> <y> [frames held]
 * touches the bottom screen at (x, y).
 *     <frame> STICK <x> <y> [frames held]
 * holds the circle pad at (x, y), -156..156 with +y up.
 */
#define MAX_SCRIPT_PRESSES 2048
static struct { u32 frame, length; u16 keys, touchX, touchY; bool touch, stick; s16 stickX, stickY; } sScript[MAX_SCRIPT_PRESSES];
static unsigned sScriptCount;
static bool sScriptLoaded;
uint32_t CtrGame_Frames(void);

static u16 ScriptButton(const char *name)
{
    static const struct { const char *name; u16 key; } names[] = {
        {"A", A_BUTTON}, {"B", B_BUTTON}, {"SELECT", SELECT_BUTTON}, {"START", START_BUTTON},
        {"RIGHT", DPAD_RIGHT}, {"LEFT", DPAD_LEFT}, {"UP", DPAD_UP}, {"DOWN", DPAD_DOWN},
        {"R", R_BUTTON}, {"L", L_BUTTON},
    };
    for (unsigned i = 0; i < ARRAY_COUNT(names); ++i)
        if (strcmp(name, names[i].name) == 0)
            return names[i].key;
    return 0;
}

static void LoadInputScript(void)
{
    FILE *file = fopen("sdmc:/3ds/emerald3ds/keys.txt", "r");
    char line[128];

    sScriptLoaded = true;
    if (file == NULL)
        return;
    while (sScriptCount < MAX_SCRIPT_PRESSES && fgets(line, sizeof(line), file))
    {
        char buttons[64], *name, *save;
        unsigned long frame, length = 4;
        u16 keys = 0;
        int fields;

        unsigned touchX, touchY;
        int stickX, stickY;

        if (line[0] == '#')
            continue;
        if (sscanf(line, "%lu STICK %d %d %lu", &frame, &stickX, &stickY, &length) >= 3)
        {
            memset(&sScript[sScriptCount], 0, sizeof(sScript[0]));
            sScript[sScriptCount].frame = frame;
            sScript[sScriptCount].length = length;
            sScript[sScriptCount].stick = true;
            sScript[sScriptCount].stickX = stickX;
            sScript[sScriptCount].stickY = stickY;
            ++sScriptCount;
            continue;
        }
        if (sscanf(line, "%lu TOUCH %u %u %lu", &frame, &touchX, &touchY, &length) >= 3)
        {
            sScript[sScriptCount].frame = frame;
            sScript[sScriptCount].length = length;
            sScript[sScriptCount].keys = 0;
            sScript[sScriptCount].touch = true;
            sScript[sScriptCount].stick = false;
            sScript[sScriptCount].touchX = touchX;
            sScript[sScriptCount].touchY = touchY;
            ++sScriptCount;
            continue;
        }
        fields = sscanf(line, "%lu %63s %lu", &frame, buttons, &length);
        if (fields < 2)
            continue;
        for (name = strtok_r(buttons, "+", &save); name; name = strtok_r(NULL, "+", &save))
            keys |= ScriptButton(name);
        if (keys == 0)
            continue;
        sScript[sScriptCount].frame = frame;
        sScript[sScriptCount].length = length;
        sScript[sScriptCount].keys = keys;
        sScript[sScriptCount].touch = false;
        sScript[sScriptCount].stick = false;
        ++sScriptCount;
    }
    fclose(file);
    CtrLog_Write(CTR_LOG_INPUT, "input script: %u presses", sScriptCount);
}

static u16 ScriptedKeys(void)
{
    u32 now = CtrGame_Frames();
    u16 keys = 0;

    if (!sScriptLoaded)
        LoadInputScript();
    for (unsigned i = 0; i < sScriptCount; ++i)
        if (now >= sScript[i].frame && now < sScript[i].frame + sScript[i].length)
            keys |= sScript[i].keys;
    return keys;
}

/* The scripted circle pad this frame (fr_bottom_ui.c), +y up. */
bool CtrScript_Stick(s16 *x, s16 *y)
{
    u32 now = CtrGame_Frames();

    if (!sScriptLoaded)
        LoadInputScript();
    for (unsigned i = 0; i < sScriptCount; ++i)
        if (sScript[i].stick && now >= sScript[i].frame && now < sScript[i].frame + sScript[i].length)
        {
            *x = sScript[i].stickX;
            *y = sScript[i].stickY;
            return true;
        }
    return false;
}

/* A scripted touch on the bottom screen this frame (fr_bottom_ui.c). */
bool CtrScript_Touch(u16 *x, u16 *y)
{
    u32 now = CtrGame_Frames();

    if (!sScriptLoaded)
        LoadInputScript();
    for (unsigned i = 0; i < sScriptCount; ++i)
        if (sScript[i].touch && now >= sScript[i].frame && now < sScript[i].frame + sScript[i].length)
        {
            *x = sScript[i].touchX;
            *y = sScript[i].touchY;
            return true;
        }
    return false;
}
#endif

u16 Platform_GetKeyInput(void)
{
    const CtrInput *input = CtrInput_Get();
    u16 held = input->held;
#ifdef CTR_INPUT_SCRIPT
    held |= ScriptedKeys();
    {
        s16 x, y;

        /* the scripted stick's way, as the real one's (3ds_input_decode.c) */
        if (!(held & (DPAD_UP | DPAD_DOWN | DPAD_LEFT | DPAD_RIGHT)) && CtrScript_Stick(&x, &y))
            held |= (x < 0 ? -x : x) > (y < 0 ? -y : y) ? (x < 0 ? DPAD_LEFT : DPAD_RIGHT)
                                                        : (y < 0 ? DPAD_DOWN : DPAD_UP);
    }
#endif

    /* Y is the 3DS's own SELECT: the registered item, as the bottom screen's
     * Y button says. */
    if (input->physicalHeld & CTR_KEY_Y)
        held |= SELECT_BUTTON;
    /* The bottom screen's column takes the buttons while X has its focus;
     * its touch controls press buttons through here. */
    held = CtrBottom_FilterKeys(held) | CtrBottom_InjectedKeys();
    REG_KEYINPUT = held ^ KEYS_MASK;
    return held;
}

/* AgbMain owns the loop: this is the game's frame boundary. */
void CtrGame_WaitFrame(void);
void VBlankIntrWait(void) { CtrGame_WaitFrame(); }
/* At once, as on the GBA: DoSoftReset expects SoftReset not to return. */
void SoftReset(u32 flags)
{
    (void)flags;
    CtrGame_SoftReset();
}

#if CTR_HAS_RTC
static u8 Bcd(unsigned value) { return ((value / 10) << 4) | (value % 10); }
static unsigned FromBcd(u8 value) { return (value >> 4) * 10 + (value & 15); }

void Platform_GetStatus(struct SiiRtcInfo *rtc) { rtc->status = sRtcStatus; }
void Platform_SetStatus(struct SiiRtcInfo *rtc) { sRtcStatus = rtc->status; }

void Platform_GetDateTime(struct SiiRtcInfo *rtc)
{
    time_t now = time(NULL) + sClockOffset;
    struct tm value;
    if (!localtime_r(&now, &value))
        CtrPlatform_Fatal("RTC conversion failed");
    memset(rtc, 0, sizeof(*rtc));
    rtc->status = sRtcStatus;
    rtc->year = Bcd((value.tm_year + 1900) % 100);
    rtc->month = Bcd(value.tm_mon + 1);
    rtc->day = Bcd(value.tm_mday);
    rtc->dayOfWeek = Bcd(value.tm_wday);
    rtc->hour = Bcd(value.tm_hour);
    rtc->minute = Bcd(value.tm_min);
    rtc->second = Bcd(value.tm_sec);
}

void Platform_SetDateTime(struct SiiRtcInfo *rtc)
{
    struct tm value = {0};
    value.tm_year = 100 + FromBcd(rtc->year);
    value.tm_mon = FromBcd(rtc->month) - 1;
    value.tm_mday = FromBcd(rtc->day);
    value.tm_hour = FromBcd(rtc->hour);
    value.tm_min = FromBcd(rtc->minute);
    value.tm_sec = FromBcd(rtc->second);
    value.tm_isdst = -1;
    time_t requested = mktime(&value);
    if (requested == (time_t)-1)
        CtrPlatform_Fatal("invalid logical RTC date");
    sClockOffset = requested - time(NULL);
    CtrLog_Write(CTR_LOG_GAME, "logical RTC updated (session only)");
}

void Platform_GetTime(struct SiiRtcInfo *rtc)
{
    struct SiiRtcInfo full;
    Platform_GetDateTime(&full);
    rtc->hour = full.hour;
    rtc->minute = full.minute;
    rtc->second = full.second;
}

void Platform_SetTime(struct SiiRtcInfo *rtc)
{
    struct SiiRtcInfo full;
    Platform_GetDateTime(&full);
    full.hour = rtc->hour;
    full.minute = rtc->minute;
    full.second = rtc->second;
    Platform_SetDateTime(&full);
}

void Platform_SetAlarm(u8 *alarmData)
{
    (void)alarmData;
    CTR_UNIMPLEMENTED("RTC_ALARM: hardware alarm not supported");
}
#endif /* CTR_HAS_RTC */

/*
 * Nothing to flush: Port_WriteFlash commits each sector to the file as the game
 * writes it, so the save on SD is already current by the time a save finishes.
 * save.c only calls this outside the port bridge anyway.
 */
void Platform_StoreSaveFile(void)
{
}

void Platform_ReadFlash(u16 sector, u32 offset, u8 *dest, u32 size)
{
    u32 address = ((u32)sector << 12) + offset;

    if (address >= sizeof(FLASH_BASE) || size > sizeof(FLASH_BASE) - address)
    {
        CtrLog_Write(CTR_LOG_ERROR, "flash read out of range: %lu+%lu",
                     (unsigned long)address, (unsigned long)size);
        return;
    }
    memcpy(dest, FLASH_BASE + address, size);
}

void Platform_QueueAudio(s32 *samples, s32 count)
{
    /*
     * m4aSoundVSync hands over one mixer frame per VBlank, measured in bytes
     * because SDL's queue is. Four bytes per sample, two samples per frame.
     */
    CtrAudio_Queue(samples, count / (s32)(2 * sizeof(s32)));
}
