#ifndef GUARD_PORT_PLATFORM_H
#define GUARD_PORT_PLATFORM_H

/*
 * ARM11 compatibility header for the portable bridge API.
 *
 * The shared game tree (`src/`, `include/`) carries small hooks behind
 * `#ifdef PORT_BRIDGE` for everything that lives outside the executable on
 * this target: asset stubs, script/text/event pointers, map payloads and save
 * storage. Game translation units are compiled with -DPORT_BRIDGE and this
 * header; the ARM11 backend implements the API (3ds_assets.c,
 * 3ds_map_loader.c, 3ds_script_loader.c, 3ds_compat.c).
 *
 * The native 3DS translation units (3ds_platform.c, 3ds_video.c, ...) are
 * compiled without PORT_BRIDGE and without this header.
 */

#include <stdbool.h>
#include "global.h"

/* ── Platform lifecycle hooks called from the shared main loop ───────────── */
void Port_InitVramBanks(void);
void Port_SyncVramToHardware(void);
void Port_AudioSyncPlayerState(void);
void Port_RecordMainLoopIteration(void);
void Port_SetGfxTilesetDebug(u8 secondary, u16 size, u8 nonzero);
void Port_SetGfxPaletteDebug(u8 secondary, u8 nonzero, u8 resolved);
void Port_SetGfxMetatileDebug(u16 id, u8 resolved, u16 first, u16 second);

/* ── External resources ─────────────────────────────────────────────────── */
/* Hardware profiling of a stretch of game code: logs the time since the last
 * mark when it is a millisecond or more (rate limited). */
void Port_ProfileMark(const char *label);
void Port_ProfBegin(void);
void Port_ProfAcc(const char *name);
void Port_AssetPreload(void);
void Port_TextPreload(void);
bool Port_IsAssetStub(const void *ptr);
const char *Port_GetAssetPath(const void *ptr);
u32 Port_GetAssetSize(const void *ptr);
u32 Port_GetAssetSizeExact(const void *base);
u32 Port_GetAssetSizeSized(const void *ptr, u32 size);
bool Port_LoadAssetToBuffer(const char *path, void *dest, u32 maxSize);
bool Port_LoadAssetPointerToBuffer(const void *ptr, void *dest, u32 maxSize);
bool Port_LoadAssetPointerToBufferSized(const void *ptr, void *dest, u32 size);
bool Port_LoadAssetRangeToBuffer(const void *base, u32 offset, void *dest, u32 size);
bool Port_LoadAssetPointerToHeap(const void *ptr, u8 **outBuf, u32 *outSize);
const void *Port_ResolveAssetPointer(const void *ptr);
const void *Port_ResolveAssetPointerSized(const void *ptr, u32 size);
const void *Port_ResolveAssetPointerInContainingAsset(const void *ptr, u32 size);
u32 Port_GetSpriteFrameSize(const void *base, u32 declaredSize);
const void *Port_ResolveSpriteFramePointer(const void *base, u32 size, u32 offset);
/* The same, only if the frame is already in memory: NULL rather than a read. */
const void *Port_PeekSpriteFramePointer(const void *base, u32 size, u32 offset);
const void *Port_ResolveFontPointer(const void *ptr);
void Port_PreloadLatinFonts(void);
u32 Port_GetDecompressedAssetSize(const void *ptr);
const void *Port_ResolveEventPointer(const void *ptr);
const u8 *Port_ResolveScriptPointer(const u8 *ptr);
const u8 *Port_ResolveTextPointer(const u8 *ptr);
bool Port_FontProbe_ReadNormalLatinGlyph(u16 glyphId, u8 *outBuf, u32 outSize);
const void *Port_FontProbe_GetNormalLatinStubBase(void);
u16 Port_FontProbe_CompareNormalLatinGlyph(u16 glyphId);

const struct MapLayout *Port_GetMapLayoutById(u16 mapLayoutId);
const struct MapHeader *Port_GetMapHeaderByGroupAndId(u16 mapGroup, u16 mapNum);
const void *Port_ResolveMapAssetPointer(const void *ptr);

/* ── Audio ───────────────────────────────────────────────────────────────
 * The sound bank is linked, so the mixer reads it in place; what is left here
 * is the debug channel below, which the mixer uses to mark its own frame.
 */
/* ── Save storage ────────────────────────────────────────────────────────── */
void Port_SaveInit(void);
bool Port_SaveIsAvailable(void);
u16 Port_WriteFlash(u32 offset, const void *data, u32 size);

/* ── Reclaimable resource cache ─────────────────────────────────────────── */
void Port_VisitGameHeap(void (*visit)(const void *, u32));

/* ── Debug channels: same signatures, routed to the 3DS logger/overlay ───── */
extern volatile u16 gPortDbgBirchTag;
extern volatile u16 gPortDbgBirchA;
extern volatile u16 gPortDbgBirchB;
extern volatile u16 gPortDbgBirchC;
extern volatile u16 gPortDbgBirchD;
extern volatile u16 gPortDbgDmaTag;
extern volatile u16 gPortDbgDmaA;
extern volatile u16 gPortDbgDmaB;
extern volatile u16 gPortDbgDmaC;
extern volatile u16 gPortDbgDmaD;
extern volatile u16 gPortDbgDma2Tag;
extern volatile u16 gPortDbgDma2A;
extern volatile u16 gPortDbgDma2B;
extern volatile u16 gPortDbgDma2C;
extern volatile u16 gPortDbgDma2D;
extern volatile u16 gPortDbgAudioTag;
extern volatile u16 gPortDbgAudioA;
extern volatile u16 gPortDbgAudioB;
extern volatile u16 gPortDbgAudioC;
extern volatile u16 gPortDbgAudioD;
extern volatile u16 gPortDbgAssetTag;
extern volatile u16 gPortDbgAssetA;
extern volatile u16 gPortDbgAssetB;
extern volatile u16 gPortDbgAssetC;

void Port_SetBirchDebug(u16 tag, u16 a, u16 b, u16 c);
void Port_SetBirchDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d);
void Port_SetDmaDebug(u16 tag, u16 a, u16 b, u16 c);
void Port_SetDmaDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d);
void Port_SetDmaDebug2(u16 tag, u16 a, u16 b, u16 c, u16 d);
void Port_SetAudioDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d);
void Port_SetAssetDebug(u16 tag, u16 a, u16 b, u16 c);
void Port_SetAssetDebugEx(u16 tag, u16 a, u16 b, u16 c, u16 d);

/*
 * An INCBIN here is a stub the port resolves: an offset or index applied to
 * the stub lands in unrelated memory. Resolve the base first, then index:
 * PORT_RES(gSomeGfx)[i], PORT_RES(table->tiles) + offset. Arrays decay to a
 * pointer to their first element.
 */
#define PORT_RES(p) ((__typeof__(&(p)[0]))Port_ResolveAssetPointer(p))

/* A menu screen's main callback calls this every frame it runs: its picture
 * goes to the bottom screen while the top screen holds the world. */
void Port_MenuOnBottom(void);
/* A menu with a native page of its own on the bottom screen (fr_bottom_ui.c):
 * the game runs it as ever, the page shows its state and turns taps into keys. */
enum { PORT_PAGE_NONE, PORT_PAGE_PARTY, PORT_PAGE_BAG, PORT_PAGE_SUMMARY, PORT_PAGE_CARD, PORT_PAGE_DEX, PORT_PAGE_STORAGE, PORT_PAGE_NAMING };
void Port_NativePage(u8 page);
/* The region map, its picture zoomed to the whole screen. A tap at a place in
 * the GBA picture moves its cursor; TRUE if the cursor was already there. */
void Port_RegionMapOnBottom(void);
bool8 Port_RegionMapIsFly(void);
bool8 Port_RegionMapTap(int x, int y);
enum { PORT_MENU_LIST, PORT_MENU_ACTIONS, PORT_MENU_QUANTITY, PORT_MENU_OTHER };
#define PORT_MENU_MAX_ACTIONS 8
#define PORT_NO_WINDOW 0xFF
struct PortPartyView {
    u8 mode;                /* PORT_MENU_* */
    u8 chooseMultiple;
    u8 multi;               /* a link's layout: the partner's slots are out of reach */
    s8 slot, slot2;         /* the cursor, and where it went while switching */
    u8 switching;
    u8 numActions;
    const u8 *actions[PORT_MENU_MAX_ACTIONS];
    const u8 *desc[6];      /* what a slot shows in place of its HP */
    u8 helpWindow;          /* the short prompt */
    u8 windows[3];          /* others that may be up, or PORT_NO_WINDOW */
};
bool8 Port_PartyGetView(struct PortPartyView *view);
void Port_PartyTapSlot(u8 slot);
struct PortBagView {
    u8 mode;                /* PORT_MENU_* */
    u8 pocket, nItems;
    u16 cursor;             /* the list's selected row; nItems is CANCEL */
    u8 numActions;
    const u8 *actions[4];
    u8 actionRow[4];        /* the row of the game's menu each one is */
    u8 windows[11];         /* those up, or PORT_NO_WINDOW */
};
bool8 Port_BagGetView(struct PortBagView *view);
void Port_BagMoveCursor(u16 index);
u8 Port_BagOpenWindow(u8 which);
struct Pokemon;
struct PortSummaryView {
    u8 ready;               /* it takes a page flip now */
    u8 selecting;           /* the moves page's cursor is up */
    u8 cursorReady;         /* that cursor takes a move now */
    u8 page, isEgg, swapping, moveCursor, ailment;
    u16 species;
    u16 moveIds[5];
    u32 personality, otId, sig;
    const struct Pokemon *mon;
    const u8 *nickname, *speciesName, *otName, *dexNum, *idNum, *itemName, *gender, *level, *hp;
    const u8 *expPoints, *expNext, *abilityName, *abilityDesc;
    const u8 *stats[5], *moveName[5], *moveCurPp[5], *moveMaxPp[5], *movePower[5], *moveAccuracy[5];
    u8 memoWindow;
};
bool8 Port_SummaryGetView(struct PortSummaryView *view);
void Port_SummarySetMoveCursor(u8 row);
struct PortCardView {
    u8 ready;               /* it takes a key now */
    u8 onBack, hasPokedex, hasHof, hasLink, hasTrades, stars;
    u8 hasBadge[8];
    u16 pic, trainerId, caught, hours, minutes, hofHours, hofMinutes, hofSeconds;
    u16 wins, losses, trades;
    u32 money, berryCrush, unionRoom;
    u16 monSpecies[6];
    const u8 *name, *badgeTiles;
    const u8 *profile[4];
};
bool8 Port_CardGetView(struct PortCardView *view);
enum { PORT_DEX_TOP, PORT_DEX_LIST, PORT_DEX_ENTRY };
struct ListMenuItem;
struct PortDexView {
    u8 mode;                /* PORT_DEX_* */
    u8 listTask, national;
    u16 count, cursor, species, seenKanto, ownedKanto, seenNational, ownedNational;
    u32 unlocked;
    const struct ListMenuItem *items;
};
struct PokedexEntry;
const struct PokedexEntry *Port_DexEntry(u16 natNum);
bool8 Port_DexHasPage(void);
/* The PC's boxes. The game's fixed windows: 1 its message, 2 an item's details. */
#define PORT_STORAGE_MESSAGE_WINDOW 1
#define PORT_STORAGE_ITEM_INFO_WINDOW 2
#define PORT_STORAGE_LAST_FIXED_WINDOW 2
struct PortStorageView {
    u8 ready;               /* its main task takes input now */
    u8 option, area, pos, currentBox, holding, itemMode;
    u8 multi;               /* several mons taken at once: the game's own cursor */
    u8 numMenu;             /* a menu of that many rows is up */
    u8 chooseBox, chooseCurrent; /* the box chooser is up, and on which box */
    u16 species, movingItem;
    u32 personality;
    const void *pal;
    const u8 *nickname, *genderLevel, *itemName;
    const u8 *menuText[7];
};
bool8 Port_StorageHasPage(void);
bool8 Port_StorageGetView(struct PortStorageView *view);
void Port_StorageSetCursor(s8 area, s8 pos);
u8 Port_StorageChooseBox(u8 *current);
bool8 Port_StorageCursor(struct PortStorageView *view);
bool8 Port_DexGetView(struct PortDexView *view);
/* The keyboard. Its cursor at x == columns is on the keys beside it: the next
 * page, delete and OK. */
enum { PORT_KB_LOWER, PORT_KB_UPPER, PORT_KB_SYMBOLS };
enum { PORT_NAMING_NO_ICON, PORT_NAMING_PLAYER, PORT_NAMING_BOX, PORT_NAMING_MON, PORT_NAMING_RIVAL };
#define PORT_NAMING_COLUMNS 8
#define PORT_NAMING_ROWS 4
#define PORT_NAMING_MESSAGE_WINDOW 0
struct PortNamingView {
    u8 ready;               /* it takes a key now */
    u8 message;             /* its message that the mon went to the PC */
    u8 next;                /* PORT_KB_*: the page after this one */
    u8 columns;
    s8 cursorX, cursorY;
    u8 maxChars, caret, icon;
    u16 species, gender;    /* for the player's name, species is their gender */
    u32 personality;
    const u8 *title;
    const u8 *keys;         /* PORT_NAMING_ROWS rows of PORT_NAMING_COLUMNS */
    u8 text[16];
};
bool8 Port_NamingGetView(struct PortNamingView *view);
void Port_NamingSetCursor(s16 x, s16 y);
/* list_menu.c: put a list's cursor on an item */
void Port_ListSetCursor(u8 listTaskId, u16 index);
/* menu.c: the menu now open in a window */
u8 Port_MenuWindow(void);
u8 Port_YesNoWindow(void);
void Port_MenuGeometry(u8 *top, u8 *rowHeight, u8 *rows);
void Port_MenuSetCursor(u8 row);

/* A full-screen scene's main callback (evolution, trade, Hall of Fame...)
 * calls this every frame it runs: FireRed leaves the field's callback1 set
 * under it, and the scene is shown as the GBA's picture, not the world. */
void Port_SceneOnTop(void);
bool Port_SceneShown(void);

/* The battle's action and move menus call this every frame they take input:
 * the bottom screen shows them as buttons, and the call returns the button
 * tapped (0-3, or 4 for the move menu's cancel), or -1. moveInfo is the
 * move menu's struct ChooseMoveStruct, NULL for the action menu. */
enum { PORT_BATTLE_ACTION = 1, PORT_BATTLE_MOVE = 2, PORT_BATTLE_SWITCH = 3 };
s8 Port_BattleMenu(u8 kind, const void *moveInfo);

#endif
