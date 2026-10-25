/*
 * Entry point: the real game, driven by its own AgbMain loop.
 *
 * Adapted from the Emerald 3DS port's 3ds_game_full.c (MIT, see NOTICE.md).
 * AgbMain runs forever and every iteration blocks in WaitForVBlank ->
 * VBlankIntrWait, which is where the 3DS backend presents the frame, pumps APT
 * and scans HID. Nothing about the game's control flow is re-implemented.
 *
 * FireRed's first renderer is the platform layer's scanline renderer
 * (src/platform/gba_fast_draw.c): after the game's VBlank handler, DrawFrame
 * plays the 160 lines of the frame - VCount and HBlank interrupts, HBlank
 * DMAs and all - into a 240x160 picture the native side scales onto the top
 * screen (3ds_soft_video.c). Every GBA effect the game uses comes out as on
 * the hardware, which is what a first port needs; the GPU compositor of the
 * Emerald port returns with the voxel world.
 */

/* Before the game's headers, whose global.h defines abs and friends. */
#include <setjmp.h>
#include <stdlib.h>

#include "global.h"
#include "main.h"
#include "overworld.h"
#include "battle.h"
#include "battle_main.h"
#include "field_effect.h"
#include "constants/field_effects.h"
#include "gba/flash_internal.h"
#include "gpu_regs.h"
#include "palette.h"
#include "cgb_audio.h"
#include "sound.h"
#include "sound_mixer.h"
#include "m4a.h"
#include "port_platform.h"
#include "port_log.h"
#include "port_prof.h"

#include "3ds_platform.h"
#include "3ds_video.h"
#include "3ds_softvideo.h"
#include "3ds_assets.h"
#include "3ds_audio.h"
#include "3ds_bottom.h"

#include <stdio.h>
#include <string.h>

void AgbMain(void);
extern IntrFunc gIntrTable[];
void CtrEmu_Reset(void);
u16 Platform_GetKeyInput(void);
void CtrEmu_BeginVBlank(void);
void CtrEmu_EndVBlank(void);
/* src/platform/gba_fast_draw.c, built with RENDERER_FAST_DRAW */
void DrawFrame(uint16_t *pixels);
/* overworld.c: the field is on the screen, not a menu over it */
bool8 Port_FieldShown(void);

/* gIntrTableTemplate order: VCount, Serial, Timer3, HBlank, VBlank, ... */
#define INTR_INDEX_VBLANK 4

static u32 sFrames;
static bool sStarted;
static uint16_t sFrame[CTR_SOFT_WIDTH * CTR_SOFT_HEIGHT];
static uint16_t sWorld[CTR_SOFT_WIDTH * CTR_SOFT_HEIGHT];
/*
 * The top screen held on the world while menus run on the bottom one: from
 * the first menu frame until the field or the battle is back. Between two
 * menus (the party's to the summary's, to the fly map) come frames of
 * neither, black or half built: they are not shown above, nor kept as the
 * world. Anything else that follows a menu (an evolution) shows once it has
 * gone on a while.
 */
#define TOP_HOLD_GRACE 60
static bool sTopHeld;
static u32 sTopHeldSince;
#if CTR_VOXEL_ENABLED
/* Hooks the Emerald port's voxel modules ask of the game (field_door.c and
 * sprite.c there); FireRed's 3D world starts without open doors or weather. */
bool8 PortDoor_Get(s16 *x, s16 *y, u8 *width, u8 *level)
{
    (void)x; (void)y; (void)width; (void)level;
    return FALSE;
}

bool8 CtrSprite_IsVoxelWeather(const struct Sprite *sprite)
{
    (void)sprite;
    return FALSE;
}

/* What goes over the 3D overworld: the message box layer, see-through
 * where nothing is drawn (gba_fast_draw.c). */
static uint16_t sUi[CTR_SOFT_WIDTH * CTR_SOFT_HEIGHT];
extern uint16_t *gPortUiPixels;
extern uint16_t gPortUiLayers;
extern bool8 gPortUiTrim;
extern bool8 gPortUiObjInWindows;
extern bool8 gPortUiScreenObj;
#endif
extern u8 gPortDrawLines;   /* gba_fast_draw.c */
#define PORT_DRAW_FRAME 1
#define PORT_DRAW_UI 2
#if CTR_VOXEL_ENABLED
/* The battle scene's state the 3D battle needs (patch 0007). */
bool8 CtrBattleIntro_Sliding(void);
bool8 CtrBattleBg_MoveBgShown(void);
#endif
#ifdef CTR_WATCHDOG
volatile uint32_t gPortCrumb;
void CtrLog_StartWatchdog(volatile const uint32_t *frames, volatile const uint32_t *crumb);
#define CRUMB(n) (gPortCrumb = (n))
#else
#define CRUMB(n)
#endif

/*
 * The CGB channels are generated in software beside the sample mixer, and they
 * need the output rate before the first note. m4a fixes that rate itself the
 * moment it starts, but it starts inside AgbMain, after the first mix could
 * already have happened. So the rate is set from the same constant the DSP was
 * opened with, and checked against what m4a actually chose on the first frame.
 */
static void StartCgbChannels(void)
{
    cgb_audio_init(CTR_AUDIO_SAMPLE_RATE);
}

/*
 * Soft reset: A+B+START+SELECT, and the game's own DoSoftReset. The GBA clears
 * its RAM and starts the game again. Here the game's variables (its .data and
 * .bss, gathered by firered3ds.ld.in) are put back as they were when AgbMain
 * first started, the emulated hardware is cleared, and AgbMain is entered
 * again. Not put back: the platform/ layer (emulated hardware, the flash with
 * the save), the port's state and the data the port loaded before AgbMain.
 */
extern char __ctr_game_data[], __ctr_game_data_end[];
extern char __ctr_game_bss[], __ctr_game_bss_end[];
static char *sGameAtStart;
static jmp_buf sAgbMainEntry;
static u32 sResets;

static size_t GameDataBytes(void) { return (size_t)(__ctr_game_data_end - __ctr_game_data); }
static size_t GameBssBytes(void) { return (size_t)(__ctr_game_bss_end - __ctr_game_bss); }

static void KeepGameAtStart(void)
{
    sGameAtStart = malloc(GameDataBytes() + GameBssBytes());
    if (sGameAtStart == NULL)
    {
        CtrLog_Write(CTR_LOG_ERROR, "soft reset unavailable: no memory for %lu KiB",
                     (unsigned long)((GameDataBytes() + GameBssBytes()) >> 10));
        return;
    }
    memcpy(sGameAtStart, __ctr_game_data, GameDataBytes());
    memcpy(sGameAtStart + GameDataBytes(), __ctr_game_bss, GameBssBytes());
    CtrLog_Write(CTR_LOG_GAME, "soft reset ready: game data %lu KiB, bss %lu KiB",
                 (unsigned long)(GameDataBytes() >> 10), (unsigned long)(GameBssBytes() >> 10));
}

/*
 * With A+B+START+SELECT still held, AgbMain would reset again at once, for
 * ever. The GBA reads the keys live and resets until they are let go; here the
 * reset waits, frame by frame, until they are.
 */
static void WaitForResetKeysUp(void)
{
    const u16 keys = A_BUTTON | B_BUTTON | START_BUTTON | SELECT_BUTTON;

    while ((Platform_GetKeyInput() & keys) == keys)
    {
        CtrPlatform_SleepUs(1000000 / 60);
        if (!CtrPlatform_BeginFrame())
        {
            CtrPlatform_Shutdown();
            exit(0);
        }
    }
}

void CtrGame_SoftReset(void)
{
    if (sGameAtStart == NULL)
    {
        CTR_STUB("RESET", "soft reset unavailable");
        return;
    }
    /* The sound worker mixes from the game's variables: not while they change. */
    CtrAudio_LockSound();
    memcpy(__ctr_game_data, sGameAtStart, GameDataBytes());
    memcpy(__ctr_game_bss, sGameAtStart + GameDataBytes(), GameBssBytes());
    CtrEmu_Reset();
    StartCgbChannels();
    CtrAudio_UnlockSound();
    ++sResets;
    WaitForResetKeysUp();
    longjmp(sAgbMainEntry, 1);
}

static void CheckAudioRate(void)
{
    static bool checked;
    const struct SoundInfo *info = SOUND_INFO_PTR;
    unsigned expected;

    if (checked || info == NULL || info->ident != ID_NUMBER)
        return;
    checked = true;
    expected = (unsigned)info->pcmFreq;
    if (expected != CTR_AUDIO_SAMPLE_RATE)
    {
        CtrLog_Write(CTR_LOG_ERROR, "mixer runs at %u Hz but the DSP was opened at %d Hz",
                     expected, CTR_AUDIO_SAMPLE_RATE);
        cgb_audio_init(expected);
    }
    else
    {
        CtrLog_Write(CTR_LOG_AUDIO, "mixer and DSP agree at %u Hz, %u samples per frame",
                     expected, (unsigned)info->pcmSamplesPerVBlank);
    }
}

/* What the overlay reports about the frame the mixer has just produced. */
static void SampleAudioStats(void)
{
    const struct SoundInfo *info = SOUND_INFO_PTR;
    /* One block of memory, two declarations of it: m4a calls it a SoundInfo,
     * the mixer a SoundMixerState. */
    const struct SoundMixerState *mixer = (const struct SoundMixerState *)info;
    CtrAudioStats *stats = CtrAudio_Stats();
    unsigned voices = 0;

    if (info == NULL || info->ident != ID_NUMBER)
        return;
    for (unsigned i = 0; i < mixer->numChans && i < MAX_SAMPLE_CHANNELS; ++i)
    {
        if ((mixer->chans[i].status & 0xC7) != 0)
            ++voices;
    }
    stats->voices = voices;
    stats->song = GetCurrentMapMusic();
}


void CtrGame_VBlank(void)
{
#ifdef CTR_WATCH_HEAP
    {
        extern bool32 CheckHeap(void);
        static bool8 reported;

        if (!reported && !CheckHeap())
        {
            reported = TRUE;
            CtrLog_Write(CTR_LOG_ERROR, "heap corrupt at frame %lu cb2=%08lx", (unsigned long)sFrames,
                         (unsigned long)(uintptr_t)gMain.callback2);
        }
    }
#endif
    CRUMB(0x100);
    PORT_PROF_BEGIN(vblank);
    CtrEmu_BeginVBlank();
    /*
     * The GBA VBlank handler is the game's own VBlankIntr: it runs the vblank
     * callback, applies buffered GPU registers and services DMA3 requests. It
     * must observe the same enable bits the game sets.
     */
    if (REG_IME && (REG_IE & INTR_FLAG_VBLANK) && gIntrTable[INTR_INDEX_VBLANK])
        gIntrTable[INTR_INDEX_VBLANK]();
    CRUMB(0x101);
    CtrEmu_EndVBlank();
    PORT_PROF_END(vblank, PORT_PROF_VBLANK);
    /* The lines of the frame, with the HBlank work between them. */
    PORT_PROF_BEGIN(lines);
    CRUMB(0x102);
#if CTR_VOXEL_ENABLED
    {
        bool voxelUi = CtrSettings_Voxel() && gMain.callback1 == CB1_Overworld && !CtrBottom_TakesGameFrame()
                    && !sTopHeld;
        /* The 3D battle: the world as the scenery, the battle's own picture
         * without it (BG3) over it - and while the scenery slides in, without
         * the entry picture either (BG1, BG2). A move's background on BG3 is
         * the 2D battle's, whole. */
        bool battle = CtrSettings_Voxel() && CtrSettings_VoxelBattle() && gMain.inBattle
                   && gMain.callback2 == BattleMainCB2 && !(gBattleTypeFlags & BATTLE_TYPE_LINK);
        bool sliding = battle && CtrBattleIntro_Sliding();
        bool scenery = battle && !CtrBattleBg_MoveBgShown();

        if (scenery)
        {
            gPortUiLayers = sliding ? (DISPCNT_BG0_ON | DISPCNT_OBJ_ON)
                                    : (DISPCNT_BG0_ON | DISPCNT_BG1_ON | DISPCNT_BG2_ON | DISPCNT_OBJ_ON);
            gPortUiTrim = FALSE;
            gPortUiPixels = sUi;
            gPortUiObjInWindows = FALSE;
            gPortUiScreenObj = FALSE;
            CtrSoftVideo_SetBanner(false);
        }
        else
        {
            gPortUiLayers = DISPCNT_BG0_ON;
            gPortUiTrim = TRUE;
            gPortUiPixels = voxelUi ? sUi : NULL;
            /* a field move's banner: the Pokemon in it, over the world */
            gPortUiObjInWindows = FieldEffectActiveListContains(FLDEFF_FIELD_MOVE_SHOW_MON)
                               || FieldEffectActiveListContains(FLDEFF_FIELD_MOVE_SHOW_MON_INIT);
            CtrSoftVideo_SetBanner(gPortUiObjInWindows && gPortUiPixels != NULL);
            /* the field's sprites are 3D; a message's picture is not */
            gPortUiScreenObj = TRUE;
        }
        /* BG3's scroll shakes the scenery when a move hits; not while it slides in */
        CtrSoftVideo_SetBattle(scenery, sliding,
                               sliding ? 0.0f : (float)((int)((GetGpuReg(REG_OFFSET_BG3HOFS) + 128) & 255) - 128),
                               sliding ? 0.0f : (float)((int)((GetGpuReg(REG_OFFSET_BG3VOFS) + 128) & 255) - 128));
        CtrSoftVideo_SetUi(gPortUiPixels);
    }
#endif
    /*
     * Only what will be seen is drawn - on an N3DS the lines were most of a
     * frame's work. A frame fast-forward hides, none of it; under the 3D
     * world, its UI layer alone: the picture is drawn when the world was not
     * (it stands in until a new map's world is built).
     */
    if (!CtrPlatform_FrameShown())
        gPortDrawLines = 0;
#if CTR_VOXEL_ENABLED
    else if (gPortUiPixels != NULL && CtrSoftVideo_DrewVoxel() && !CtrBottom_TakesGameFrame())
        gPortDrawLines = PORT_DRAW_UI;
#endif
    else
        gPortDrawLines = PORT_DRAW_FRAME | PORT_DRAW_UI;
    DrawFrame(sFrame);
    CRUMB(0x103);
    PORT_PROF_END(lines, PORT_PROF_LINES);
    if (CtrBottom_TakesGameFrame())
    {
        /* A menu screen: its picture goes below, the world stays above. */
        CtrBottom_ShowGameFrame(sFrame);
        CtrSoftVideo_SetFrame(sWorld);
        CtrSoftVideo_SetFrameDrawn(true);
        sTopHeld = true;
        sTopHeldSince = sFrames;
        CtrSoftVideo_SetClean(false);
    }
    else if (sTopHeld && !Port_FieldShown()
             && !(gMain.inBattle && gMain.callback2 == BattleMainCB2)
             && sFrames - sTopHeldSince < TOP_HOLD_GRACE)
    {
        /* between menus, or on the way back */
        CtrSoftVideo_SetFrame(sWorld);
        CtrSoftVideo_SetFrameDrawn(true);
        CtrSoftVideo_SetClean(false);
    }
    else
    {
        /* The last picture neither fading nor faded is what a menu leaves on
         * the top: a finished fade to black is no longer active, but black. */
        bool clean = !gPaletteFade.active && gPaletteFade.y == 0;

        sTopHeld = false;
        CtrSoftVideo_SetFrame(sFrame);
        CtrSoftVideo_SetFrameDrawn(gPortDrawLines & PORT_DRAW_FRAME);
        CtrSoftVideo_SetClean(clean);
        if (clean && (gPortDrawLines & PORT_DRAW_FRAME))
            memcpy(sWorld, sFrame, sizeof(sWorld));
    }
    CtrSoftVideo_HoldTop(sTopHeld);
#ifdef CTR_FRAME_DUMP
    /* Diagnostic: the rendered frame and the registers the renderer read,
     * as they stand at frame CTR_FRAME_DUMP (tools: raw BGR555, 240x160). */
#ifndef CTR_FRAME_DUMP_COUNT
#define CTR_FRAME_DUMP_COUNT 8
#endif
#ifndef CTR_FRAME_DUMP_START
#define CTR_FRAME_DUMP_START 0
#endif
    if (sFrames >= CTR_FRAME_DUMP_START && (sFrames - CTR_FRAME_DUMP_START) % CTR_FRAME_DUMP == 0
     && (sFrames - CTR_FRAME_DUMP_START) / CTR_FRAME_DUMP <= CTR_FRAME_DUMP_COUNT)
    {
        char name[64];
        FILE *file;
        const u16 *regs = (const u16 *)REG_BASE;

        snprintf(name, sizeof(name), "sdmc:/3ds/firered3ds/frame_%04lu.raw", (unsigned long)sFrames);
        file = fopen(name, "wb");

        if (file)
        {
            fwrite(sFrame, sizeof(sFrame), 1, file);
            fwrite(REG_BASE, 0x60, 1, file);
            fwrite(PLTT, 0x40, 1, file);
            fclose(file);
        }
        {
            /* the bottom screen's canvas beside it (fr_bottom_ui.c) */
            extern void CtrBottom_Dump(const char *path);

            snprintf(name, sizeof(name), "sdmc:/3ds/firered3ds/bottom_%04lu.raw", (unsigned long)sFrames);
            CtrBottom_Dump(name);
#if CTR_VOXEL_ENABLED
            if (gPortUiPixels != NULL)
            {
                snprintf(name, sizeof(name), "sdmc:/3ds/firered3ds/ui_%04lu.raw", (unsigned long)sFrames);
                file = fopen(name, "wb");
                if (file)
                {
                    fwrite(sUi, sizeof(sUi), 1, file);
                    fclose(file);
                }
                CtrLog_Write(CTR_LOG_VIDEO, "ui dump %lu: DISPCNT=%04x BG0..3CNT=%04x %04x %04x %04x WININ=%04x WINOUT=%04x",
                             (unsigned long)sFrames, regs[0], regs[4], regs[5], regs[6], regs[7], regs[0x48 / 2], regs[0x4A / 2]);
            }
#endif
        }
        {
            extern u16 gPlttBufferUnfaded[], gPlttBufferFaded[];
            extern struct PaletteFadeControl gPaletteFade;

            CtrLog_Write(CTR_LOG_VIDEO, "frame dump %lu: cb2=%08lx state=%u DISPCNT=%04x BG0CNT=%04x "
                         "BLDCNT=%04x BLDY=%04x PLTT %04x %04x %04x unfaded %04x %04x %04x faded %04x %04x %04x",
                         (unsigned long)sFrames, (unsigned long)(uintptr_t)gMain.callback2, gMain.state,
                         regs[0], regs[4], regs[0x50 / 2], regs[0x54 / 2],
                         ((const u16 *)PLTT)[0], ((const u16 *)PLTT)[1], ((const u16 *)PLTT)[2],
                         gPlttBufferUnfaded[0], gPlttBufferUnfaded[1], gPlttBufferUnfaded[2],
                         gPlttBufferFaded[0], gPlttBufferFaded[1], gPlttBufferFaded[2]);
        }
    }
#endif
    CheckAudioRate();
    SampleAudioStats();
    ++sFrames;
}

uint32_t CtrGame_Frames(void) { return sFrames; }
uint32_t CtrGame_Resets(void) { return sResets; }
uint32_t CtrGame_APresses(void) { return 0; }
uint32_t CtrGame_Checks(void) { return 0; }

bool CtrGame_IsOverworld(void)
{
    if (gMapHeader.mapLayout == NULL || gSaveBlock1Ptr == NULL)
        return false;
    /* FireRed keeps CB2_Overworld static; the field's callback 1 is public. */
    return gMain.callback1 == CB1_Overworld || gMain.callback2 == CB2_OverworldBasic;
}

/* AgbMain never returns, so a reset request restarts the process state here. */
void CtrGame_Frame(void)
{
}

void CtrGame_Init(void)
{
    const struct CtrAssetStats *stats;

    if (sStarted)
    {
        /* Once: a soft reset re-enters AgbMain itself (CtrGame_SoftReset). */
        CTR_STUB("RESET", "CtrGame_Init called again");
        return;
    }
    sStarted = true;

    /* Before anything reads a game table: the game's linked read-only data
     * lives in the data pack, and its region is empty until this returns. */
    if (!CtrGameData_Init())
        CtrAssets_Fatal("the game data bundle is required before anything else");
    CtrEmu_Reset();
    memset(FLASH_BASE, 0xFF, sizeof(FLASH_BASE));

    /* Fail loudly here rather than letting the game read stub bytes as tiles,
     * or zeroes as script opcodes. */
    Port_AssetPreload();
    CtrAssets_StartWarmup();
    if (!CtrScripts_Init())
        CtrAssets_Fatal("the script bundle is required before AgbMain");
    if (!CtrMaps_Init())
        CtrAssets_Fatal("map payloads are required to reach the overworld");
    /* gSongTable already points into this region; without it every song header
     * is zeroes and MP2K would run a silent, malformed track. */
    if (!CtrSongs_Init())
        CtrAssets_Fatal("the song bundle is required before AgbMain");
    Port_PreloadLatinFonts();
    CtrBottom_Init();
#ifdef CTR_WATCHDOG
    CtrLog_StartWatchdog(&sFrames, &gPortCrumb);
#endif
    /* Before AgbMain, because the game asks Port_SaveIsAvailable early and a
     * save that loads later would never be seen. */
    Port_SaveInit();
    StartCgbChannels();

    stats = CtrAssets_GetStats();
    CtrLog_Write(CTR_LOG_FS, "resources ready: %lu assets, index %lu KiB, maps %lu KiB, scripts %lu KiB",
                 (unsigned long)stats->entries, (unsigned long)(stats->indexBytes >> 10),
                 (unsigned long)(CtrMaps_Bytes() >> 10), (unsigned long)(CtrScripts_Bytes() >> 10));
    CtrLog_Write(CTR_LOG_AUDIO, "songs: %lu KiB resident, game data %lu KiB",
                 (unsigned long)(CtrSongs_Bytes() >> 10), (unsigned long)(CtrGameData_Bytes() >> 10));

    CtrVideo_Bind((CtrVideoMemory){VRAM_, (const uint16_t *)PLTT,
                  (const uint16_t *)OAM, (const uint16_t *)REG_BASE});
    KeepGameAtStart();
    CtrPlatform_ReportMemory("before AgbMain");
    if (setjmp(sAgbMainEntry) == 0)
        CtrLog_Write(CTR_LOG_GAME, "entering AgbMain");
    else
        CtrLog_Write(CTR_LOG_GAME, "soft reset %lu: entering AgbMain again", (unsigned long)sResets);
    AgbMain();
    CtrPlatform_Fatal("AgbMain returned");
}

/*
 * Called by the portable VBlankIntrWait. One iteration per frame: present,
 * then acquire the next frame's input. A closed lid, a Home menu exit or the
 * exit chord ends the process from here, which is the only place where the
 * game is at a consistent point.
 */
#ifdef CTR_DEBUG_WARP
#include "field_fadetransition.h"
#include "quest_log.h"
#include "script.h"
/* Diagnostic: once the field takes input, warp to CTR_DEBUG_WARP
 * (group,num,x,y), to look at any map without walking there. */
static void DebugWarp(void)
{
    static const int target[4] = { CTR_DEBUG_WARP };
    static bool8 done;

    if (done || gMain.callback1 != CB1_Overworld || ArePlayerFieldControlsLocked() || gPaletteFade.active
     || ScriptContext_IsEnabled() || gQuestLogState != 0)
        return;
    done = TRUE;
    CtrLog_Write(CTR_LOG_GAME, "debug warp to %d:%d (%d,%d)", target[0], target[1], target[2], target[3]);
    SetWarpDestination(target[0], target[1], -1, target[2], target[3]);
    DoWarp();
}
#endif

#ifdef CTR_DEBUG_TOUR
#include "field_fadetransition.h"
#include "quest_log.h"
#include "script.h"
#include "debug_tour_stops.h"
/*
 * Diagnostic: a tour of every map (tools/dev/gen_tour_stops.py writes the
 * stops). At each stop, once the field has stood still a moment, the stop is
 * written to tour_ready.txt; the driver outside captures the window and
 * answers with the stop's number in tour_ack.txt, and the tour goes on. A
 * stop that never settles (a map's own script holding the player) is
 * announced anyway after a while. tour_start.txt, when present, is the stop
 * to begin from.
 */
#define TOUR_DIR "sdmc:/3ds/firered3ds/"
/* The overworld's 3D status (ctr_voxel.c): "on" once it draws the map; a
 * heavy map shows the 2D picture while it loads. */
extern const char *CtrVoxel_Status(void);
extern const char *CtrVoxel_DebugLine(void);
static int TourReadInt(const char *path, int fallback)
{
    FILE *file = fopen(path, "r");
    int value = fallback;

    if (file)
    {
        if (fscanf(file, "%d", &value) != 1)
            value = fallback;
        fclose(file);
    }
    return value;
}

/* Each stop is seen from the front and turned to either side
 * (CTR_DEBUG_TOUR_VIEWS), so a model is judged from where the follow camera
 * never looks; voxel_camera.c turns the eye by gCtrDebugYaw. */
#ifndef CTR_DEBUG_TOUR_VIEWS
#define CTR_DEBUG_TOUR_VIEWS 1
#endif
float gCtrDebugYaw;
static const float sTourYaws[3] = { 0.0f, -55.0f, 55.0f };

static void TourWarp(int stop)
{
    CtrLog_Write(CTR_LOG_GAME, "tour %d: %s", stop, sTourStops[stop].name);
    SetWarpDestination(sTourStops[stop].group, sTourStops[stop].num, -1,
                       sTourStops[stop].x, sTourStops[stop].y);
    DoWarp();
}

static void DebugTour(void)
{
    static int stop = -1, view;
    static bool8 announced;
    static u32 since, still, lastPoll;
    const int count = (int)(sizeof(sTourStops) / sizeof(sTourStops[0]));
    bool8 idle = gMain.callback1 == CB1_Overworld && !ArePlayerFieldControlsLocked()
              && !gPaletteFade.active && !ScriptContext_IsEnabled() && gQuestLogState == 0;

    if (stop < 0)
    {
        if (!idle)
            return;
        remove(TOUR_DIR "tour_ack.txt");
        remove(TOUR_DIR "tour_ready.txt");
        stop = TourReadInt(TOUR_DIR "tour_start.txt", 0);
        if (stop < 0 || stop >= count)
            stop = 0;
        TourWarp(stop);
        since = sFrames;
        still = 0;
        return;
    }
    if (stop >= count)
        return;
    if (!announced)
    {
        FILE *file;

        still = (idle && strcmp(CtrVoxel_Status(), "on") == 0) ? still + 1 : 0;
        if (still < 60 && sFrames - since < 1800)
            return;
        file = fopen(TOUR_DIR "tour_ready.txt", "w");
        if (file)
        {
            fprintf(file, "%d %s_v%d %s %s\n", stop * 10 + view, sTourStops[stop].name, view,
                    still >= 60 ? "ok" : "stuck", CtrVoxel_Status());
            fclose(file);
        }
        announced = TRUE;
        lastPoll = sFrames;
        CtrLog_Write(CTR_LOG_GAME, "tour %d state: %s", stop, CtrVoxel_DebugLine());
        return;
    }
    if (sFrames - lastPoll < 10)
        return;
    lastPoll = sFrames;
    if (TourReadInt(TOUR_DIR "tour_ack.txt", -1) != stop * 10 + view)
        return;
    announced = FALSE;
    if (++view < CTR_DEBUG_TOUR_VIEWS)
    {
        /* the same stop, the camera turned: it settles before the next shot */
        gCtrDebugYaw = sTourYaws[view % 3];
        since = sFrames;
        still = 0;
        return;
    }
    view = 0;
    gCtrDebugYaw = 0.0f;
    if (++stop >= count)
    {
        FILE *file = fopen(TOUR_DIR "tour_ready.txt", "w");

        if (file)
        {
            fprintf(file, "%d done\n", stop * 10);
            fclose(file);
        }
        CtrLog_Write(CTR_LOG_GAME, "tour done");
        return;
    }
    /* a stop held by its map's script is warped out of all the same: the
     * driver notices if the game does not come back from it */
    if (ScriptContext_IsEnabled() || gMain.callback1 != CB1_Overworld)
        CtrLog_Write(CTR_LOG_GAME, "tour: leaving %d in the middle of a script", stop - 1);
    TourWarp(stop);
    since = sFrames;
    still = 0;
}
#endif

#ifdef CTR_DEBUG_GRANT
#include "event_data.h"
#include "pokedex.h"
#include "quest_log.h"
#include "script.h"
#include "constants/flags.h"
#include "constants/moves.h"
#include "constants/species.h"
/* One-off gift for the player's own save, once the field takes input: a
 * Pidgeot that knows Fly, the eight badges and every Kanto town to fly to.
 * The eighth badge marks it done, so a save that has it is left alone. */
static void DebugGrant(void)
{
    static bool8 checked;
    struct Pokemon mon;
    u16 flag;

    if (checked || gMain.callback1 != CB1_Overworld || ArePlayerFieldControlsLocked()
     || gPaletteFade.active || ScriptContext_IsEnabled() || gQuestLogState != 0)
        return;
    checked = TRUE;
    if (FlagGet(FLAG_BADGE08_GET))
    {
        CtrLog_Write(CTR_LOG_GAME, "debug grant: already given");
        return;
    }
    CreateMon(&mon, SPECIES_PIDGEOT, 40, USE_RANDOM_IVS, FALSE, 0, OT_ID_PLAYER_ID, 0);
    SetMonMoveSlot(&mon, MOVE_FLY, 0);
    GetSetPokedexFlag(SpeciesToNationalPokedexNum(SPECIES_PIDGEOT), FLAG_SET_SEEN);
    GetSetPokedexFlag(SpeciesToNationalPokedexNum(SPECIES_PIDGEOT), FLAG_SET_CAUGHT);
    for (flag = FLAG_BADGE01_GET; flag <= FLAG_BADGE08_GET; flag++)
        FlagSet(flag);
    for (flag = FLAG_WORLD_MAP_PALLET_TOWN; flag <= FLAG_WORLD_MAP_SAFFRON_CITY; flag++)
        FlagSet(flag);
    FlagSet(FLAG_WORLD_MAP_ROUTE4_POKEMON_CENTER_1F);
    FlagSet(FLAG_WORLD_MAP_ROUTE10_POKEMON_CENTER_1F);
    CtrLog_Write(CTR_LOG_GAME, "debug grant: Pidgeot %s, badges and fly map set",
                 GiveMonToPlayer(&mon) == MON_GIVEN_TO_PARTY ? "to the party" : "to the PC");
}
#endif

#ifdef CTR_DEBUG_BATTLE
#include "battle_setup.h"
#include "quest_log.h"
#include "script.h"
#include "script_pokemon_util.h"
#include "constants/items.h"
#include "constants/species.h"
/* Diagnostic: once the field takes input (after CTR_DEBUG_WARP's warp, when
 * there is one), a wild Pidgey: a battle to look at without walking for one. */
static void DebugBattle(void)
{
    static bool8 done;
    static u32 idleSince;

    if (done || gMain.callback1 != CB1_Overworld || ArePlayerFieldControlsLocked() || gPaletteFade.active
     || ScriptContext_IsEnabled() || gQuestLogState != 0)
    {
        idleSince = 0;
        return;
    }
#ifdef CTR_DEBUG_WARP
    {
        static const int target[4] = { CTR_DEBUG_WARP };

        if (gSaveBlock1Ptr->location.mapGroup != target[0] || gSaveBlock1Ptr->location.mapNum != target[1])
            return;
    }
#endif
    /* a moment standing still first, for the world to be drawn */
    if (idleSince == 0)
        idleSince = sFrames;
    if (sFrames - idleSince < 120)
        return;
    done = TRUE;
    CtrLog_Write(CTR_LOG_GAME, "debug battle: a wild Pidgey");
    CreateScriptedWildMon(SPECIES_PIDGEY, 5, ITEM_NONE);
    StartWildBattle();
}
#endif

#ifdef CTR_DEBUG_MONPIC
#include "quest_log.h"
#include "script_menu.h"
#include "constants/species.h"
/* Diagnostic: once the field has stood still a moment, a Pokemon's picture
 * in its window, as a script's showmonpic puts it over the field. */
static void DebugMonPic(void)
{
    static bool8 done;
    static u32 idleSince;

    if (done || !Port_FieldShown() || ArePlayerFieldControlsLocked() || gPaletteFade.active
     || gQuestLogState != 0)
    {
        idleSince = 0;
        return;
    }
    if (idleSince == 0)
        idleSince = sFrames;
    if (sFrames - idleSince < 240)
        return;
    done = TRUE;
    CtrLog_Write(CTR_LOG_GAME, "debug monpic");
    ScriptMenu_ShowPokemonPic(SPECIES_BULBASAUR, 10, 3);
}
#endif

void CtrGame_WaitFrame(void)
{
#ifdef CTR_DEBUG_WARP
    DebugWarp();
#endif
#ifdef CTR_DEBUG_MONPIC
    DebugMonPic();
#endif
#ifdef CTR_DEBUG_BATTLE
    DebugBattle();
#endif
    /* The battle scene on screen (not its bag or party): the compositor lays
     * it out as a battle - the box on the top screen's foot, the 3D world as
     * its scenery when that option is on. */
    {
        static bool8 wasBattle;
        bool8 battle = gMain.inBattle && gMain.callback2 == BattleMainCB2;

        if (battle != wasBattle)
            CtrLog_Write(CTR_LOG_VIDEO, "GBA battle %s at frame %lu", battle ? "on" : "off",
                         (unsigned long)sFrames);
        wasBattle = battle;
        CtrVideo_SetBattle(battle);
    }
#ifdef CTR_DEBUG_TOUR
    DebugTour();
#endif
#ifdef CTR_DEBUG_GRANT
    DebugGrant();
#endif
    static MainCallback lastCallback;
    static u32 nextReport;

    if (sFrames < 4)
        CtrLog_Write(CTR_LOG_GAME, "frame %lu: game reached VBlank wait", (unsigned long)sFrames);
    Port_ProfScene((const void *)gMain.callback2);
    CRUMB(0x200);
    CtrPlatform_EndFrame();
    CRUMB(0x201);
    if (!CtrPlatform_BeginFrame())
    {
        CtrPlatform_Shutdown();
        exit(0);
    }
    CRUMB(0x202);
    CtrPlatform_Diagnostic(sFrames, 0, 0);
    CtrBottom_Frame();
    CRUMB(0x203);

    /* Which screen the game is on: a callback change is the only unambiguous
     * marker of progress in the log. */
    if (gMain.callback2 != lastCallback || sFrames >= nextReport)
    {
        const struct CtrAssetStats *stats = CtrAssets_GetStats();
        const struct SaveBlock1 *save = gSaveBlock1Ptr;

        lastCallback = gMain.callback2;
        nextReport = sFrames + 600;
        CtrLog_Write(CTR_LOG_VIDEO, "DISPCNT=%04x BG0=%04x BG1=%04x BG2=%04x BG3=%04x",
                     GetGpuReg(REG_OFFSET_DISPCNT), GetGpuReg(REG_OFFSET_BG0CNT),
                     GetGpuReg(REG_OFFSET_BG1CNT), GetGpuReg(REG_OFFSET_BG2CNT),
                     GetGpuReg(REG_OFFSET_BG3CNT));
        /* The save blocks exist only once the game has allocated them; page
         * zero is unmapped on hardware. */
        CtrLog_Write(CTR_LOG_GAME,
                     "frame=%lu cb2=%08lx state=%u map=%d/%d assets=%lu/%lu %luKiB hit=%lu miss=%lu err=%lu",
                     (unsigned long)sFrames, (unsigned long)(uintptr_t)gMain.callback2,
                     gMain.state, save ? save->location.mapGroup : -1,
                     save ? save->location.mapNum : -1,
                     (unsigned long)stats->loads, (unsigned long)stats->entries,
                     (unsigned long)(stats->bytes >> 10), (unsigned long)stats->hits,
                     (unsigned long)stats->misses, (unsigned long)stats->errors);
    }
#ifdef CTR_DEBUG_STEPS
    /* Every step the player takes, to check movement by (local.mk). */
    if (gPlayerAvatar.objectEventId < OBJECT_EVENTS_COUNT)
    {
        static s16 lastX = -999, lastY = -999;
        const struct ObjectEvent *player = &gObjectEvents[gPlayerAvatar.objectEventId];

        if (player->active && (player->currentCoords.x != lastX || player->currentCoords.y != lastY))
        {
            lastX = player->currentCoords.x;
            lastY = player->currentCoords.y;
            CtrLog_Write(CTR_LOG_GAME, "step frame=%lu x=%d y=%d facing=%u moving=%u",
                         (unsigned long)sFrames, lastX, lastY, player->facingDirection,
                         player->movementDirection);
        }
        /* and every few frames, free movement's offset off the tile's middle */
        if (player->active && sFrames % 8 == 0)
        {
            static s16 lastOx = -999, lastOy = -999;
            bool8 ObjectEventGetSpriteOffset(struct ObjectEvent *, s16 *, s16 *);
            s16 ox = 0, oy = 0;

            if (!ObjectEventGetSpriteOffset((struct ObjectEvent *)player, &ox, &oy))
                ox = oy = 99;
            if (ox != lastOx || oy != lastOy)
            {
                lastOx = ox;
                lastOy = oy;
                CtrLog_Write(CTR_LOG_GAME, "free frame=%lu x=%d y=%d off=%d,%d cam=%d,%d action=%u tts=%u",
                             (unsigned long)sFrames, player->currentCoords.x, player->currentCoords.y, ox, oy,
                             gSaveBlock1Ptr->pos.x, gSaveBlock1Ptr->pos.y, player->movementActionId,
                             gPlayerAvatar.tileTransitionState);
            }
        }
    }
#endif
}
