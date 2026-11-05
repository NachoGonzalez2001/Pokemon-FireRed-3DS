/*
 * The bottom screen, game side, for FireRed: what it shows and what a touch
 * does. Modelled on the Emerald port's 3ds_bottom_ui.c.
 *
 * In the field it is a panel over a dock. The dock along the bottom holds the
 * start menu's entries: POKéDEX, POKéMON, BAG, the player (trainer card), SAVE
 * and OPTION. A tap asks the game for that entry and presses START
 * (start_menu.c, CtrStartMenu_Request), so the game opens it exactly as if it
 * had been chosen from its menu. Above it are a header (location, the RUN
 * switch, play time), the region map with the player's place on it, and the
 * party (icons and HP); a tap on the party opens the party menu.
 *
 * The party, the bag, the summary, the trainer card and the Pokédex's lists and
 * entries have native pages of their own, over the game's state (Port_NativePage,
 * further down), and so do the PC's boxes. The game's other menu screens (a
 * habitat or area in the Pokédex, a mon's marks in the boxes, the player's PC, town map, shop, TM case, berry pouch, naming, Easy Chat, Teachy
 * TV) are shown here instead of on the top screen: each one's main callback calls
 * Port_MenuOnBottom, the top screen holds the last picture of the world
 * (3ds_game_full.c), and the GBA picture is put 1:1 in a frame. The console's
 * own buttons work them.
 *
 * Everything is drawn by the CPU into a 320x240 canvas laid out like the
 * bottom framebuffer (RGB565, column-major, each column bottom-to-top) with
 * the game's own fonts, icons and map art. The panel is redrawn only when
 * what it shows changes (a snapshot and a memcmp per frame); a menu's picture
 * is copied every frame it changes.
 */

#include <stdlib.h>
#include <string.h>

#include "global.h"
#include "main.h"
#include "gba/m4a_internal.h"
#include "battle.h"
#include "battle_anim.h"
#include "battle_controllers.h"
#include "battle_main.h"
#include "bg.h"
#include "data.h"
#include "decompress.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "fieldmap.h"
#include "item.h"
#include "list_menu.h"
#include "item_menu_icons.h"
#include "menu.h"
#include "overworld.h"
#include "party_menu.h"
#include "pokedex.h"
#include "pokemon_summary_screen.h"
#include "palette.h"
#include "pokemon.h"
#include "pokemon_icon.h"
#include "pokemon_storage_system_internal.h"
#include "region_map.h"
#include "script.h"
#include "sound.h"
#include "string_util.h"
#include "strings.h"
#include "text.h"
#include "window.h"
#include "constants/items.h"
#include "constants/moves.h"
#include "constants/songs.h"
#include "constants/region_map_sections.h"
#include "port_platform.h"

#include "3ds_bottom.h"
#include "3ds_extras.h"
#include "3ds_input.h"
#include "3ds_log.h"
#include "3ds_platform.h"
#include "fr_ui_icons.h"

/* text.c, start_menu.c and region_map.c, under PORT_BRIDGE */
void Port_DecompressGlyph(u8 fontId, u16 glyphId);
void CtrStartMenu_Request(u8 action);
bool8 CtrStartMenu_Pending(void);
bool8 CtrStartMenu_Busy(void);
void Port_GetRegionMapArt(u8 region, const void **mapGfx, const void **mapTilemap, const void **bgGfx,
                          const void **bgTilemap, const u16 **pal, const void **playerGfx, const u16 **playerPal);
u8 Port_GetRegionMapPlayer(s16 *x, s16 *y);
uint32_t CtrGame_Frames(void);
uint32_t CtrGame_Resets(void);
#ifdef CTR_INPUT_SCRIPT
bool CtrScript_Touch(u16 *x, u16 *y);
bool CtrScript_Stick(s16 *x, s16 *y);
#endif
/* settings.txt: the player walks freely (field_player_avatar.c) */
#define FREE_MOVE_KEY "free_move"
#define FOLLOWER_KEY "follower"
#define DAYNIGHT_KEY "daynight"      /* ctr_voxel.c: 0 off, 1 the clock, 2 fast */
#define SCREEN_FIT_KEY "screen_fit"  /* 3ds_soft_video.c: 0 the GBA's proportions, 1 the width */

/* start_menu.c's STARTMENU_* */
enum { MENU_POKEDEX, MENU_POKEMON, MENU_BAG, MENU_PLAYER, MENU_SAVE, MENU_OPTION, MENU_COUNT };

#define W CTR_BOTTOM_WIDTH
#define H CTR_BOTTOM_HEIGHT
#define HEADER_H 26
/* the region map art, and the part of it on the panel's map card */
#define MAP_W 240
#define MAP_H 160
#define MAP_CARD_X 6
#define MAP_CARD_Y 31
#define MAP_CARD_W 204
#define MAP_CARD_H 150
#define MAP_X 12
#define MAP_Y 34
#define MAP_VIEW_W 192
#define MAP_VIEW_H 122
#define MAP_SRC_X 24
#define MAP_SRC_Y 30
/* the party's cards, two by three */
#define PARTY_X 214
#define PARTY_Y 31
#define PARTY_CARD_W 49
#define PARTY_CARD_H 48
#define PARTY_STEP_X 52
#define PARTY_STEP_Y 51
/* the dock of the start menu's entries */
#define DOCK_Y 186
#define DOCK_KEY_X 4
#define DOCK_KEY_Y 191
#define DOCK_KEY_W 51
#define DOCK_KEY_H 45
#define DOCK_STEP 53
/* a page's dark footer, and its BACK key */
#define FOOTER_Y 206
#define FOOTER_H 34
#define BACK_X (W - 62)
#define BACK_Y 211
#define BACK_W 56
#define BACK_H 24
/* a menu's GBA picture, 1:1 in a frame */
#define GBA_W 240
#define GBA_H 160
#define GAME_X 40
#define GAME_Y 53

/* What the panel shows */
enum { SCR_MAP, SCR_OPTIONS };

/* The options screen: three tabs (CTR_EXTRAS_*) - SETTINGS, the game's own
 * settings and the port's, as the Emerald port's; ENHANCEMENTS and CHEATS,
 * the extras (3ds_extras.h). It replaces the game's option menu. */
enum {
    OPT_TEXT_SPEED, OPT_BATTLE_SCENE, OPT_BATTLE_STYLE, OPT_SOUND, OPT_BUTTON_MODE, OPT_FRAME,
    OPT_VOXEL, OPT_VOXEL_ANGLE, OPT_VOXEL_ZOOM, OPT_VOXEL_BLUR, OPT_VOXEL_BATTLE, OPT_DAYNIGHT,
    OPT_RUN, OPT_FREE_MOVE, OPT_FOLLOWER, OPT_SCREEN_FIT,
    OPT_COUNT
};
#define OPT_MAX_ROWS 16
#define OPT_PAGE_ROWS 6
#define TAB_X 6
#define TAB_Y 29
#define TAB_W 104
#define TAB_H 22
#define LIST_X 6
#define LIST_Y 46
#define LIST_W 308
#define LIST_H 158
#define ROW_Y 50
#define ROW_H 23
#define ROW_GAP 2
/* a long tab's pages: arrow keys in the footer */
#define PAGER_PREV_X 6
#define PAGER_NEXT_X 196
#define PAGER_KEY_W 56
/* the field header's RUN switch */
#define RUN_X 196
#define RUN_Y 3
#define RUN_W 68
#define RUN_H 19

/* Touch targets */
enum { HIT_NONE, HIT_BUTTON, HIT_PARTY = HIT_BUTTON + MENU_COUNT, HIT_RUN, HIT_BATTLE,
       HIT_TAB = HIT_BATTLE + 5, HIT_ROW = HIT_TAB + CTR_EXTRAS_PAGES, HIT_ROW_BACK = HIT_ROW + OPT_PAGE_ROWS,
       HIT_PAGE_PREV = HIT_ROW_BACK + OPT_PAGE_ROWS, HIT_PAGE_NEXT, HIT_BACK, HIT_SCENE, HIT_COUNT };

typedef struct {
    u16 species, iconSpecies, hp, maxHp;
    u8 egg, level;
} MonView;

/* One side's mon in battle */
typedef struct {
    u16 species, hp, maxHp;
    u8 level, present;
    u8 name[POKEMON_NAME_LENGTH + 1];
} FighterView;

typedef struct {
    u8 choose;       /* PORT_BATTLE_* the player is choosing, or 0 */
    u8 cursor;       /* the game's cursor in that menu */
    u8 balls[PARTY_SIZE]; /* 0 none, 1 able, 2 fainted or status */
    u16 moves[MAX_MON_MOVES];
    u8 pp[MAX_MON_MOVES], maxPp[MAX_MON_MOVES];
    FighterView player, opponent;
} BattleView;

typedef struct {
    u8 screen;       /* SCR_* */
    u8 optTab, optSub, optPage;  /* the options' tab, its screen and page */
    s16 optSig[OPT_PAGE_ROWS];   /* what each row of the page shows */
    u8 battle;       /* drawing the battle's page */
    BattleView b;
    MonView party[PARTY_SIZE];
    u8 partyCount;
    u8 enabled;      /* bit per MENU_* */
    u8 run;          /* bit 0 running is the default, bit 1 the player can run */
    u8 pressed;      /* HIT_* under the finger */
    u8 region;
    u8 onMap;        /* the player is placed on the map */
    s16 mapX, mapY;
    u16 mapsec;
    u16 hours;
    u8 minutes;
    u8 player[PLAYER_NAME_LENGTH + 1];
} ViewState;

static u16 sCanvas[W * H];
static u16 sLut[32768]; /* BGR555 -> RGB565 */
static ViewState sShown;
static bool8 sDrawn;
static u8 sTouchHit;
static u8 sInjectFrames;
static u16 sInjected;
static u32 sMenuFrame = 0xFFFFFFF0;
static bool8 sGameShown;
/* A game is under way: the field has been on since the last (soft) reset.
 * Before, on the title and the main menu, the panel shows no save's data. */
static bool8 sInGame;
static u32 sResetsSeen;
static u8 sScreen = SCR_MAP;
static u8 sOptTab, sOptSub, sOptPage;

/* The battle menus (battle_controller_player.c, Port_BattleMenu) */
static u32 sBattleMenuFrame = 0xFFFFFFF0;
static u8 sBattleMenuKind;
static struct ChooseMoveStruct sBattleMoves;
static s8 sBattleTap = -1;
static u8 sBattleTapKind;

/* The region map, rendered once per region: RGB565, row-major */
static u16 *sMapCache;
static u8 sMapCacheRegion = 0xFF;
static u8 sPlayerIcon[8 * 32];
static u16 sPlayerPal[16];
static bool8 sPlayerIconReady;

/* ------------------------------------------------------------------------ */
/* Canvas                                                                   */
/* ------------------------------------------------------------------------ */

static u16 Rgb(u8 r, u8 g, u8 b) /* 0..31 each */
{
    return (u16)((r << 11) | ((g << 1 | g >> 4) << 5) | b);
}

static inline void Put(int x, int y, u16 c)
{
    if ((unsigned)x < W && (unsigned)y < H)
        sCanvas[x * H + (H - 1 - y)] = c;
}

static void FillRect(int x, int y, int w, int h, u16 c)
{
    for (int i = x < 0 ? 0 : x; i < x + w && i < W; i++)
    {
        u16 *col = sCanvas + i * H;

        for (int j = y < 0 ? 0 : y; j < y + h && j < H; j++)
            col[H - 1 - j] = c;
    }
}

/* A 4bpp tile of 8x8; colour 0 is transparent. */
static void DrawTile4(const u8 *tile, int x, int y, const u16 *pal565, bool8 hflip, bool8 vflip)
{
    for (int py = 0; py < 8; py++)
        for (int px = 0; px < 8; px++)
        {
            int sx = hflip ? 7 - px : px, sy = vflip ? 7 - py : py;
            u8 v = tile[sy * 4 + sx / 2];

            v = (sx & 1) ? v >> 4 : v & 15;
            if (v)
                Put(x + px, y + py, pal565[v]);
        }
}

/* ------------------------------------------------------------------------ */
/* Text, in the game's fonts                                                */
/* ------------------------------------------------------------------------ */

static u16 NextChar(const u8 **s)
{
    u16 c = **s;

    if (c == EOS || c == CHAR_NEWLINE)
        return EOS;
    (*s)++;
    /* the game's other symbols: the one that shows here is its "Lv" */
    if (c == CHAR_EXTRA_SYMBOL)
        return *(*s)++ == CHAR_LV_2 ? CHAR_LV : 0x100;
    if (c == EXT_CTRL_CODE_BEGIN)
    {
        /* Control codes change colours or wait; none are drawn. */
        if (**s != EOS)
            *s += GetExtCtrlCodeLength(**s);
        return 0x100;
    }
    return c;
}

static int DrawGlyph(u8 font, u16 c, int x, int y, u16 fg, u16 shadow, bool8 draw)
{
    int w, h;

    Port_DecompressGlyph(font, c);
    w = gGlyphInfo.width;
    h = gGlyphInfo.height;
    if (draw)
        for (int py = 0; py < h && py < 16; py++)
            for (int px = 0; px < w && px < 16; px++)
            {
                const u8 *p = gGlyphInfo.pixels + ((py >= 8) * 2 + (px >= 8)) * 32 + (py & 7) * 4 + (px & 7) / 2;
                u8 v = (px & 1) ? *p >> 4 : *p & 15;

                if (v == 1)
                    Put(x + px, y + py, fg);
                else if (v == 2)
                    Put(x + px, y + py, shadow);
            }
    return w + GetFontAttribute(font, FONTATTR_LETTER_SPACING);
}

static int Text(u8 font, const u8 *str, int x, int y, u16 fg, u16 shadow, bool8 draw)
{
    int x0 = x;
    u16 c;

    while ((c = NextChar(&str)) != EOS)
        if (c != 0x100)
            x += DrawGlyph(font, c, x, y, fg, shadow, draw);
    return x - x0;
}

static int TextWidth(u8 font, const u8 *str)
{
    return Text(font, str, 0, 0, 0, 0, FALSE);
}

static void TextCentered(u8 font, const u8 *str, int cx, int y, u16 fg, u16 shadow)
{
    Text(font, str, cx - TextWidth(font, str) / 2, y, fg, shadow, TRUE);
}

static void TextRight(u8 font, const u8 *str, int right, int y, u16 fg, u16 shadow)
{
    Text(font, str, right - TextWidth(font, str), y, fg, shadow, TRUE);
}

/* An ASCII label in the game's charset. A few of them can be in use at once. */
static const u8 *Ascii(const char *s)
{
    static u8 bufs[4][24];
    static u8 next;
    u8 *buf = bufs[next++ & 3];
    int i;

    for (i = 0; s[i] && i < 23; i++)
    {
        char c = s[i];

        buf[i] = c >= 'A' && c <= 'Z' ? CHAR_A + (c - 'A')
               : c >= 'a' && c <= 'z' ? CHAR_a + (c - 'a')
               : c >= '0' && c <= '9' ? CHAR_0 + (c - '0')
               : c == '/' ? CHAR_SLASH : c == '&' ? CHAR_AMPERSAND : c == '.' ? CHAR_PERIOD
               : c == '-' ? CHAR_HYPHEN : c == '%' ? CHAR_PERCENT : c == ':' ? CHAR_COLON
               : c == '!' ? CHAR_EXCL_MARK : c == '?' ? CHAR_QUESTION_MARK : CHAR_SPACE;
    }
    buf[i] = EOS;
    return buf;
}

/* ------------------------------------------------------------------------ */
/* State                                                                    */
/* ------------------------------------------------------------------------ */

static bool8 InField(void)
{
    return gMain.callback1 == CB1_Overworld && gSaveBlock2Ptr != NULL && gSaveBlock1Ptr != NULL
        && gMapHeader.mapLayout != NULL && !Port_SceneShown();
}

/* The player stands in the field with nothing else going on. */
static bool8 FieldIdle(void)
{
    return InField() && !ArePlayerFieldControlsLocked() && !ScriptContext_IsEnabled()
        && gPlayerAvatar.tileTransitionState == T_NOT_MOVING && !gPaletteFade.active
        && !CtrStartMenu_Busy() && !CtrStartMenu_Pending();
}

static void SnapshotFighter(FighterView *f, u8 position)
{
    u8 battler = GetBattlerAtPosition(position);

    if (battler >= gBattlersCount || gBattleMons[battler].species == SPECIES_NONE)
        return;
    f->present = TRUE;
    f->species = gBattleMons[battler].species;
    f->hp = gBattleMons[battler].hp;
    f->maxHp = gBattleMons[battler].maxHP;
    f->level = gBattleMons[battler].level;
    StringCopyN(f->name, gBattleMons[battler].nickname, POKEMON_NAME_LENGTH);
    f->name[POKEMON_NAME_LENGTH] = EOS;
}

static void SnapshotBattle(ViewState *s)
{
    s->battle = TRUE;
    if (CtrGame_Frames() - sBattleMenuFrame <= 1)
    {
        s->b.choose = sBattleMenuKind;
        if (sBattleMenuKind == PORT_BATTLE_MOVE)
            for (int i = 0; i < MAX_MON_MOVES; i++)
            {
                s->b.moves[i] = sBattleMoves.moves[i];
                s->b.pp[i] = sBattleMoves.currentPp[i];
                s->b.maxPp[i] = sBattleMoves.maxPp[i];
            }
    }
    if (s->b.choose)
    {
        u8 battler = GetBattlerAtPosition(B_POSITION_PLAYER_LEFT);

        s->b.cursor = s->b.choose == PORT_BATTLE_MOVE ? gMoveSelectionCursor[battler] : gActionSelectionCursor[battler];
    }
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        u16 species = GetMonData(&gPlayerParty[i], MON_DATA_SPECIES_OR_EGG);

        if (species == SPECIES_NONE || species == SPECIES_EGG)
            continue;
        s->b.balls[i] = GetMonData(&gPlayerParty[i], MON_DATA_HP) == 0 || GetMonData(&gPlayerParty[i], MON_DATA_STATUS) ? 2 : 1;
    }
    SnapshotFighter(&s->b.player, B_POSITION_PLAYER_LEFT);
    SnapshotFighter(&s->b.opponent, B_POSITION_OPPONENT_LEFT);
}

static void SnapshotOptions(ViewState *s);

static void Snapshot(ViewState *s)
{
    memset(s, 0, sizeof(*s));
    s->pressed = sTouchHit;
    if (gSaveBlock2Ptr == NULL || gSaveBlock1Ptr == NULL)
        return;
    s->screen = sScreen;
    if (sScreen == SCR_OPTIONS)
        SnapshotOptions(s);
    if (gMain.inBattle)
    {
        SnapshotBattle(s);
        return;
    }
    s->enabled = (1 << MENU_BAG) | (1 << MENU_PLAYER) | (1 << MENU_SAVE) | (1 << MENU_OPTION);
    if (FlagGet(FLAG_SYS_POKEMON_GET))
        s->enabled |= 1 << MENU_POKEMON;
    if (FlagGet(FLAG_SYS_POKEDEX_GET))
        s->enabled |= 1 << MENU_POKEDEX;
    s->run = (CtrSettings_RunAlways() ? 1 : 0) | (FlagGet(FLAG_SYS_B_DASH) ? 2 : 0);
    s->hours = gSaveBlock2Ptr->playTimeHours;
    s->minutes = gSaveBlock2Ptr->playTimeMinutes;
    StringCopyN(s->player, gSaveBlock2Ptr->playerName, PLAYER_NAME_LENGTH);
    s->player[PLAYER_NAME_LENGTH] = EOS;
    if (InField())
    {
        s->mapsec = gMapHeader.regionMapSectionId;
        if (s->mapsec >= KANTO_MAPSEC_START && s->mapsec < MAPSEC_NONE)
        {
            s->region = Port_GetRegionMapPlayer(&s->mapX, &s->mapY);
            s->onMap = TRUE;
        }
    }
    else
    {
        /* Out of the field (a battle, a cutscene) the panel keeps its place. */
        s->mapsec = sShown.mapsec;
        s->region = sShown.region;
        s->onMap = sShown.onMap;
        s->mapX = sShown.mapX;
        s->mapY = sShown.mapY;
    }

    s->partyCount = gPlayerPartyCount > PARTY_SIZE ? PARTY_SIZE : gPlayerPartyCount;
    for (int i = 0; i < s->partyCount; i++)
    {
        struct Pokemon *mon = &gPlayerParty[i];
        MonView *m = &s->party[i];

        m->species = GetMonData(mon, MON_DATA_SPECIES);
        if (m->species == SPECIES_NONE)
            continue;
        m->egg = GetMonData(mon, MON_DATA_IS_EGG);
        m->iconSpecies = m->egg ? SPECIES_EGG : GetIconSpecies(m->species, GetMonData(mon, MON_DATA_PERSONALITY));
        m->hp = GetMonData(mon, MON_DATA_HP);
        m->maxHp = GetMonData(mon, MON_DATA_MAX_HP);
        m->level = GetMonData(mon, MON_DATA_LEVEL);
    }
}

/* ------------------------------------------------------------------------ */
/* Pokédex palette for the selected game edition                             */
/* ------------------------------------------------------------------------ */

/* 8-bit components to RGB565 */
#define C8(r, g, b) ((u16)((((r) >> 3) << 11) | (((g) >> 2) << 5) | ((b) >> 3)))

/* The builder selects the executable matching the ROM. Its game version
 * selects the shell and menu accents independently of the language. */
#ifdef LEAFGREEN
#define C_SHELL_HI  C8(81, 168, 92)
#define C_SHELL_LO  C8(25, 102, 51)
#define C_SHELL_DK  C8(13, 62, 34)
#define C_FLAT      C8(38, 132, 66)
#define C_BAND      C8(27, 102, 49)
#define C_BAND_DK   C8(16, 67, 34)
#define C_PRESSED   C8(228, 246, 231)
#else
#define C_SHELL_HI  C8(236, 82, 82)
#define C_SHELL_LO  C8(150, 24, 32)
#define C_SHELL_DK  C8(92, 14, 20)
#define C_FLAT      C8(214, 48, 54)
#define C_BAND      C8(176, 30, 40)
#define C_BAND_DK   C8(116, 18, 26)
#define C_PRESSED   C8(255, 236, 236)
#endif

#define C_BALL_TOP  C8(236, 82, 82)
#define C_INK       C8(24, 22, 28)
#define C_WHITE     C8(248, 248, 248)
#define C_SHADOW    C8(70, 74, 84)
#define C_MUTED     C8(120, 126, 138)
#define C_LENS      C8(60, 168, 240)
#define C_GOLD      C8(250, 206, 64)
#define C_GREEN     C8(82, 200, 104)
#define C_YELLOW    C8(250, 200, 60)
#define C_BRIGHTRED C8(240, 70, 70)
#define C_OFF       C8(190, 194, 202)
#define C_PAGE      C8(242, 243, 247)
#define C_CARD      C8(255, 255, 255)
#define C_LINE      C8(212, 216, 224)
#define C_TEXT      C8(44, 46, 56)
#define C_TEXT_SH   C8(208, 210, 218)
#define C_EMPTY     C8(234, 236, 241)
#define C_RIM       C8(200, 204, 212)
#define C_SLATE     C8(44, 48, 58)
#define C_SLATE_HI  C8(66, 72, 86)
#define C_SLATE_EDGE C8(90, 96, 110)

/* ------------------------------------------------------------------------ */
/* Shapes                                                                   */
/* ------------------------------------------------------------------------ */

static u16 Mix(u16 a, u16 b, int t, int n) /* a..b, t of n */
{
    int r = ((a >> 11) * (n - t) + (b >> 11) * t) / n;
    int g = (((a >> 5) & 63) * (n - t) + ((b >> 5) & 63) * t) / n;
    int bl = ((a & 31) * (n - t) + (b & 31) * t) / n;

    return (u16)(r << 11 | g << 5 | bl);
}

static u16 Lighter(u16 c, int k) /* k of 8 toward white */
{
    return Mix(c, 0xFFFF, k, 8);
}

static u16 Darker(u16 c, int k) /* k of 8 toward black */
{
    return Mix(c, 0, k, 8);
}

static u16 Grey(u16 c) /* a disabled thing: its brightness, greyed and flat */
{
    int l = ((c >> 11) * 2 + ((c >> 5) & 63) + (c & 31) * 2) / 6;

    l = (l + 16) / 2;
    return (u16)(l << 11 | (l * 2) << 5 | l);
}

static void Gradient(int x, int y, int w, int h, u16 top, u16 bottom)
{
    for (int j = 0; j < h; j++)
        FillRect(x, y + j, w, 1, Mix(top, bottom, j, h > 1 ? h - 1 : 1));
}

/* The inset of row j of a rounded corner of radius r. */
static int CornerInset(int j, int r)
{
    int dy, dx = 0;

    if (j >= r)
        return 0;
    dy = r - j;
    while ((dx + 1) * (dx + 1) + (dy - 1) * (dy - 1) <= r * r)
        dx++;
    return r - dx;
}

static void RoundRect(int x, int y, int w, int h, int r, u16 c)
{
    if (r * 2 > h)
        r = h / 2;
    if (r * 2 > w)
        r = w / 2;
    for (int j = 0; j < h; j++)
    {
        int in = CornerInset(j < h - j - 1 ? j : h - j - 1, r);

        FillRect(x + in, y + j, w - 2 * in, 1, c);
    }
}

/* A rounded box with a line round it. */
static void RoundBox(int x, int y, int w, int h, int r, u16 fill, u16 edge)
{
    RoundRect(x, y, w, h, r, edge);
    RoundRect(x + 1, y + 1, w - 2, h - 2, r > 1 ? r - 1 : 1, fill);
}

/* A rounded box whose upper rows shade from `top` down to its colour. */
static void RoundGradient(int x, int y, int w, int h, int r, u16 top, u16 c, int shadeRows)
{
    if (r * 2 > h)
        r = h / 2;
    for (int j = 0; j < h; j++)
    {
        int in = CornerInset(j < h - j - 1 ? j : h - j - 1, r);
        u16 row = j < shadeRows ? Mix(top, c, j, shadeRows) : c;

        FillRect(x + in, y + j, w - 2 * in, 1, row);
    }
}

static void Disc(int cx, int cy, int r, u16 c)
{
    for (int dy = -r; dy <= r; dy++)
        for (int dx = -r; dx <= r; dx++)
            if (dx * dx + dy * dy <= r * r + r / 2)
                Put(cx + dx, cy + dy, c);
}

static void Ring(int cx, int cy, int r, int thick, u16 c)
{
    int outer = r * r + r / 2, inner = (r - thick) * (r - thick) + (r - thick) / 2;

    for (int dy = -r; dy <= r; dy++)
        for (int dx = -r; dx <= r; dx++)
        {
            int d = dx * dx + dy * dy;

            if (d <= outer && d > inner)
                Put(cx + dx, cy + dy, c);
        }
}

/* ------------------------------------------------------------------------ */
/* Icons and the shell                                                      */
/* ------------------------------------------------------------------------ */

/* One of the port's icons (fr_ui_icons.h), blended over the canvas. */
static void DrawUiIcon(const UiIcon *icon, int x, int y, bool8 on)
{
    for (int j = 0; j < icon->size; j++)
        for (int i = 0; i < icon->size; i++)
        {
            int k = j * icon->size + i, a = icon->alpha[k];
            int px = x + i, py = y + j;
            u16 c = on ? icon->rgb[k] : Grey(icon->rgb[k]);

            if (a == 0 || (unsigned)px >= W || (unsigned)py >= H)
                continue;
            if (a < 250)
                c = Mix(sCanvas[px * H + (H - 1 - py)], c, a, 255);
            Put(px, py, c);
        }
}

static void Shell(int x, int y, int w, int h)
{
    Gradient(x, y, w, h, C_SHELL_HI, C_SHELL_LO);
}

/* The header across the top: the lens, a title, a darker slant on the right. */
static void Header(const u8 *title)
{
    FillRect(0, 0, W, HEADER_H - 3, C_FLAT);
    FillRect(0, HEADER_H - 3, W, 3, C_BAND);
    for (int j = 0; j < HEADER_H - 3; j++)
    {
        int x = 196 - 12 * j / (HEADER_H - 4);

        FillRect(x, j, W - x, 1, C_BAND);
    }
    DrawUiIcon(&sIconLens22, 4, 1, TRUE);
    if (title)
        Text(FONT_NORMAL, title, 30, 5, C_WHITE, C_BAND_DK, TRUE);
}

/* An arrow pointing left or right, its tip 3 px from the middle. */
static void Arrow(int cx, int cy, bool8 left, u16 c)
{
    for (int i = 0; i < 7; i++)
        FillRect(left ? cx - 3 + i : cx + 3 - i, cy - i, 1, 2 * i + 1, c);
}

static void Footer(void)
{
    FillRect(0, FOOTER_Y, W, FOOTER_H, C_SLATE);
    FillRect(0, FOOTER_Y, W, 1, C_INK);
}

static void BackKey(bool8 pressed)
{
    RoundBox(BACK_X, BACK_Y, BACK_W, BACK_H, 6, pressed ? C_SLATE : C_SLATE_HI, C_SLATE_EDGE);
    Arrow(BACK_X + 10, BACK_Y + 12, TRUE, C_WHITE);
    Text(FONT_SMALL, Ascii("BACK"), BACK_X + 18, BACK_Y + 4, C_WHITE, C_SLATE_HI, TRUE);
}

static void HpBar(int x, int y, int w, int hp, int maxHp)
{
    int fill = maxHp ? ((w - 2) * hp + maxHp - 1) / maxHp : 0;

    RoundRect(x, y, w, 6, 2, C_SLATE);
    FillRect(x + 1, y + 1, fill, 4, hp * 2 > maxHp ? C_GREEN : hp * 5 > maxHp ? C_YELLOW : C_BRIGHTRED);
}

/* ------------------------------------------------------------------------ */
/* The region map                                                           */
/* ------------------------------------------------------------------------ */

static void *Decompress(const void *src)
{
    u32 size = GetDecompressedDataSize(src);
    void *dst = size ? malloc(size) : NULL;

    if (dst)
        LZ77UnCompWram(src, dst);
    return dst;
}

/* One 30x20 tilemap of 4bpp tiles into the cache; colour 0 is see-through. */
static void RenderLayer(const u8 *tiles, const u16 *tilemap, const u16 *pal565, int palCount)
{
    for (int ty = 0; ty < MAP_H / 8; ty++)
        for (int tx = 0; tx < MAP_W / 8; tx++)
        {
            u16 e = tilemap[ty * 30 + tx];
            const u8 *tile = tiles + (e & 0x3FF) * 32;
            int pal = (e >> 12) < palCount ? (e >> 12) : 0;
            bool8 hf = (e >> 10) & 1, vf = (e >> 11) & 1;

            for (int py = 0; py < 8; py++)
                for (int px = 0; px < 8; px++)
                {
                    int sx = hf ? 7 - px : px, sy = vf ? 7 - py : py;
                    u8 v = tile[sy * 4 + sx / 2];

                    v = (sx & 1) ? v >> 4 : v & 15;
                    if (v)
                        sMapCache[(ty * 8 + py) * MAP_W + tx * 8 + px] = pal565[pal * 16 + v];
                }
        }
}

static bool8 BuildMapCache(u8 region)
{
    const void *mapGfx, *mapTilemap, *bgGfx, *bgTilemap, *playerGfx;
    const u16 *pal, *playerPal, *palData;
    u8 *mapTiles, *bgTiles, *icon;
    u16 *mapMap, *bgMap, pal565[16 * 16];
    u32 palBytes;
    int palCount;

    if (sMapCache && sMapCacheRegion == region)
        return TRUE;
    Port_GetRegionMapArt(region, &mapGfx, &mapTilemap, &bgGfx, &bgTilemap, &pal, &playerGfx, &playerPal);
    if (sMapCache == NULL)
        sMapCache = malloc(MAP_W * MAP_H * sizeof(u16));
    mapTiles = Decompress(mapGfx);
    mapMap = Decompress(mapTilemap);
    bgTiles = Decompress(bgGfx);
    bgMap = Decompress(bgTilemap);
    palData = Port_ResolveAssetPointer(pal);
    palBytes = Port_GetAssetSize(pal);
    palCount = palBytes / 32 > 16 ? 16 : palBytes / 32;
    if (sMapCache && mapTiles && mapMap && bgTiles && bgMap && palData && palCount > 0)
    {
        for (int i = 0; i < palCount * 16; i++)
            pal565[i] = sLut[palData[i] & 0x7FFF];
        for (int i = 0; i < MAP_W * MAP_H; i++)
            sMapCache[i] = pal565[0];
        RenderLayer(bgTiles, bgMap, pal565, palCount);
        RenderLayer(mapTiles, mapMap, pal565, palCount);
        sMapCacheRegion = region;
    }
    free(mapTiles);
    free(mapMap);
    free(bgTiles);
    free(bgMap);

    if (!sPlayerIconReady && (icon = Decompress(playerGfx)) != NULL)
    {
        const u16 *pp = Port_ResolveAssetPointer(playerPal);

        memcpy(sPlayerIcon, icon, sizeof(sPlayerIcon));
        free(icon);
        if (pp)
            for (int i = 0; i < 16; i++)
                sPlayerPal[i] = sLut[pp[i] & 0x7FFF];
        sPlayerIconReady = TRUE;
    }
    CtrLog_Write(CTR_LOG_VIDEO, "bottom: region map %u %s (%d palettes)", region,
                 sMapCacheRegion == region ? "ready" : "failed", palCount);
    return sMapCacheRegion == region;
}

static void PutClip(int x, int y, u16 c, int x0, int y0, int x1, int y1)
{
    if (x >= x0 && x < x1 && y >= y0 && y < y1)
        Put(x, y, c);
}

static void DrawMap(const ViewState *s)
{
    FillRect(MAP_X, MAP_Y, MAP_VIEW_W, MAP_VIEW_H, C_SLATE);
    if (!s->onMap || !BuildMapCache(s->region))
        return;
    for (int x = 0; x < MAP_VIEW_W; x++)
    {
        u16 *col = sCanvas + (MAP_X + x) * H + (H - 1 - MAP_Y);

        for (int y = 0; y < MAP_VIEW_H; y++)
            col[-y] = sMapCache[(MAP_SRC_Y + y) * MAP_W + MAP_SRC_X + x];
    }
    if (sPlayerIconReady)
    {
        /* a 16x16 sprite centred on the cell */
        int x = 8 * s->mapX + 36 - 8 - MAP_SRC_X + MAP_X, y = 8 * s->mapY + 36 - 8 - MAP_SRC_Y + MAP_Y;

        for (int t = 0; t < 4; t++)
            for (int py = 0; py < 8; py++)
                for (int px = 0; px < 8; px++)
                {
                    u8 v = sPlayerIcon[t * 32 + py * 4 + px / 2];

                    v = (px & 1) ? v >> 4 : v & 15;
                    if (v)
                        PutClip(x + (t & 1) * 8 + px, y + (t >> 1) * 8 + py, sPlayerPal[v],
                                MAP_X, MAP_Y, MAP_X + MAP_VIEW_W, MAP_Y + MAP_VIEW_H);
                }
    }
}

/* ------------------------------------------------------------------------ */
/* The options screen: SETTINGS, ENHANCEMENTS, CHEATS                        */
/* ------------------------------------------------------------------------ */

/* The 3D overworld's settings, live when the build has it. */
#define VOXEL_READY CTR_VOXEL_ENABLED

static bool8 OptionLive(int row)
{
    if (row < OPT_VOXEL)
        return TRUE;
    if (!VOXEL_READY)
        return FALSE;
    /* the 3D world's own settings, with the 3D world */
    return row == OPT_VOXEL || CtrSettings_Voxel();
}

static u8 OptionCount(int row)
{
    switch (row)
    {
    case OPT_TEXT_SPEED:
    case OPT_BUTTON_MODE: return 3;
    case OPT_FRAME:       return 10; /* option_menu.c's frame types */
    case OPT_VOXEL_ANGLE: return 6;
    case OPT_VOXEL_ZOOM:  return 5;
    case OPT_DAYNIGHT:    return 3;
    default:              return 2;
    }
}

static u8 OptionGet(int row)
{
    switch (row)
    {
    case OPT_TEXT_SPEED:   return gSaveBlock2Ptr->optionsTextSpeed;
    case OPT_BATTLE_SCENE: return gSaveBlock2Ptr->optionsBattleSceneOff;
    case OPT_BATTLE_STYLE: return gSaveBlock2Ptr->optionsBattleStyle;
    case OPT_SOUND:        return gSaveBlock2Ptr->optionsSound;
    case OPT_BUTTON_MODE:  return gSaveBlock2Ptr->optionsButtonMode;
    case OPT_FRAME:        return gSaveBlock2Ptr->optionsWindowFrameType;
    case OPT_RUN:          return CtrSettings_RunAlways();
    case OPT_FREE_MOVE:    return CtrSettings_GetInt(FREE_MOVE_KEY, 0) != 0;
    case OPT_VOXEL:        return CtrSettings_Voxel();
    case OPT_VOXEL_ANGLE:  return CtrSettings_VoxelPitch();
    case OPT_VOXEL_ZOOM:   return CtrSettings_VoxelZoom();
    case OPT_VOXEL_BLUR:   return CtrSettings_VoxelBlur();
    case OPT_FOLLOWER:     return CtrSettings_GetInt(FOLLOWER_KEY, 1) != 0;
    case OPT_SCREEN_FIT:   return CtrSettings_GetInt(SCREEN_FIT_KEY, 1) != 0;
    case OPT_DAYNIGHT:     return (u8)CtrSettings_GetInt(DAYNIGHT_KEY, 1) % 3;
    default:               return CtrSettings_VoxelBattle();
    }
}

static void OptionSet(int row, u8 value)
{
    switch (row)
    {
    case OPT_TEXT_SPEED:   gSaveBlock2Ptr->optionsTextSpeed = value; break;
    case OPT_BATTLE_SCENE: gSaveBlock2Ptr->optionsBattleSceneOff = value; break;
    case OPT_BATTLE_STYLE: gSaveBlock2Ptr->optionsBattleStyle = value; break;
    case OPT_SOUND:
        gSaveBlock2Ptr->optionsSound = value;
        SetPokemonCryStereo(value);
        break;
    case OPT_BUTTON_MODE:  gSaveBlock2Ptr->optionsButtonMode = value; break;
    case OPT_FRAME:        gSaveBlock2Ptr->optionsWindowFrameType = value; break;
    case OPT_RUN:          CtrSettings_SetRunAlways(value); break;
    case OPT_FREE_MOVE:    CtrSettings_SetInt(FREE_MOVE_KEY, value); break;
    case OPT_VOXEL:        CtrSettings_SetVoxel(value); break;
    case OPT_VOXEL_ANGLE:
    case OPT_VOXEL_ZOOM:   break; /* stepped, see OptionStep */
    case OPT_VOXEL_BLUR:   CtrSettings_SetVoxelBlur(value); break;
    case OPT_FOLLOWER:     CtrSettings_SetInt(FOLLOWER_KEY, value); break;
    case OPT_SCREEN_FIT:   CtrSettings_SetInt(SCREEN_FIT_KEY, value); break;
    case OPT_DAYNIGHT:     CtrSettings_SetInt(DAYNIGHT_KEY, value); break;
    default:               CtrSettings_SetVoxelBattle(value); break;
    }
}

static void OptionStep(int row, int dir)
{
    u8 count = OptionCount(row);

    if (!OptionLive(row))
        return;
    PlaySE(SE_SELECT);
    /* The camera's angle (degrees) and zoom (percent) step by the settings' own. */
    if (row == OPT_VOXEL_ANGLE)
        CtrSettings_StepVoxelPitch(dir);
    else if (row == OPT_VOXEL_ZOOM)
        CtrSettings_StepVoxelZoom(dir);
    else
        OptionSet(row, (u8)((OptionGet(row) + count + dir) % count));
}

static const u8 *OptionName(int row)
{
    switch (row)
    {
    case OPT_TEXT_SPEED:   return gText_TextSpeed;
    case OPT_BATTLE_SCENE: return gText_BattleScene;
    case OPT_BATTLE_STYLE: return gText_BattleStyle;
    case OPT_SOUND:        return gText_Sound;
    case OPT_BUTTON_MODE:  return gText_ButtonMode;
    case OPT_FRAME:        return gText_Frame;
    case OPT_RUN:          return Ascii("RUN ALWAYS");
    case OPT_FREE_MOVE:    return Ascii("FREE MOVE");
    case OPT_VOXEL:        return Ascii("3D WORLD");
    case OPT_VOXEL_ANGLE:  return Ascii("3D CAMERA ANGLE");
    case OPT_VOXEL_ZOOM:   return Ascii("3D ZOOM");
    case OPT_VOXEL_BLUR:   return Ascii("3D DEPTH BLUR");
    case OPT_FOLLOWER:     return Ascii("3D FOLLOWER");
    case OPT_SCREEN_FIT:   return Ascii("SCREEN FIT");
    case OPT_DAYNIGHT:     return Ascii("3D DAY/NIGHT");
    default:               return Ascii("3D BATTLE");
    }
}

static const u8 *OptionValue(int row, u8 value)
{
    static u8 buf[16];
    u8 *p;

    switch (row)
    {
    case OPT_TEXT_SPEED:   return value == 0 ? gText_TextSpeedSlow : value == 1 ? gText_TextSpeedMid : gText_TextSpeedFast;
    case OPT_BATTLE_STYLE: return value ? gText_BattleStyleSet : gText_BattleStyleShift;
    case OPT_SOUND:        return value ? gText_SoundStereo : gText_SoundMono;
    case OPT_BUTTON_MODE:  return value == 0 ? gText_ButtonTypeHelp : value == 1 ? gText_ButtonTypeLR : gText_ButtonTypeLEqualsA;
    case OPT_FRAME:
        p = StringCopy(buf, gText_FrameType);
        *p++ = CHAR_SPACE;
        ConvertIntToDecimalStringN(p, value + 1, STR_CONV_MODE_LEFT_ALIGN, 2);
        return buf;
    case OPT_VOXEL_ANGLE:
        ConvertIntToDecimalStringN(buf, value, STR_CONV_MODE_LEFT_ALIGN, 3);
        return buf;
    case OPT_DAYNIGHT:
        return Ascii(value == 0 ? "OFF" : value == 1 ? "CLOCK" : "FAST");
    case OPT_SCREEN_FIT:
        return Ascii(value ? "STRETCH" : "ORIGINAL");
    case OPT_VOXEL_ZOOM:
        p = ConvertIntToDecimalStringN(buf, value, STR_CONV_MODE_LEFT_ALIGN, 3);
        *p++ = CHAR_PERCENT;
        *p = EOS;
        return buf;
    default:
        return value ? gText_BattleSceneOn : gText_BattleSceneOff;
    }
}

/* A row of a page: one of the options, or an extra (3ds_extras.h). */
enum { ROW_TOGGLE, ROW_STEP, ROW_ACTION };
typedef struct {
    s8 opt;                  /* OPT_*, or -1 */
    const CtrExtra *extra;
} OptRow;

static int PageRows(u8 tab, u8 sub, OptRow *rows)
{
    int n = 0;

    if (tab == CTR_EXTRAS_OPTIONS)
    {
        for (int i = 0; i < OPT_COUNT; i++)
            rows[n++] = (OptRow){ (s8)i, NULL };
        return n;
    }
    for (unsigned i = 0; i < gCtrExtraCount && n < OPT_MAX_ROWS; i++)
        if (gCtrExtras[i].page == CTR_EXTRAS_SCREEN(tab, sub))
            rows[n++] = (OptRow){ -1, &gCtrExtras[i] };
    return n;
}

static u8 RowKind(const OptRow *r)
{
    if (r->opt >= 0)
        switch (r->opt)
        {
        case OPT_BATTLE_SCENE: case OPT_RUN: case OPT_FREE_MOVE: case OPT_VOXEL: case OPT_VOXEL_BLUR: case OPT_VOXEL_BATTLE:
        case OPT_FOLLOWER:
            return ROW_TOGGLE;
        default:
            return ROW_STEP;
        }
    if (r->extra->step)
        return ROW_STEP;
    if (r->extra->count == 0)
        return ROW_ACTION;
    return r->extra->values == gCtrExtrasOffOn ? ROW_TOGGLE : ROW_STEP;
}

static bool8 RowLive(const OptRow *r)
{
    return r->opt < 0 || OptionLive(r->opt);
}

static bool8 RowOn(const OptRow *r)
{
    if (r->opt == OPT_BATTLE_SCENE)
        return OptionGet(r->opt) == 0; /* the game keeps it as "off" */
    if (r->opt >= 0)
        return OptionGet(r->opt) != 0;
    return CtrExtras_Value(r->extra) != 0;
}

/* What the row shows, to know when to draw it again. */
static s16 RowSignature(const OptRow *r)
{
    s16 v;

    if (r->opt >= 0)
        return (s16)(OptionGet(r->opt) | (OptionLive(r->opt) << 8));
    v = r->extra->count ? (s16)CtrExtras_Value(r->extra) : 0;
    if (r->extra->text)
        for (const u8 *t = r->extra->text(); *t != EOS; t++)
            v = (s16)(v * 31 + *t);
    return v;
}

static void RowStep(const OptRow *r, int dir)
{
    if (r->opt >= 0)
    {
        OptionStep(r->opt, dir);
        return;
    }
    if (r->extra->count != 0 || r->extra->step)
        PlaySE(SE_SELECT);
    CtrExtras_Step(r->extra, dir);
}

static u8 PageCount(int rows)
{
    return rows <= OPT_PAGE_ROWS ? 1 : (rows + OPT_PAGE_ROWS - 1) / OPT_PAGE_ROWS;
}

void CtrExtras_ShowScreen(unsigned page, unsigned screen)
{
    sOptTab = page;
    sOptSub = screen;
    sOptPage = 0;
    sScreen = SCR_OPTIONS;
}

static void OptRowRect(int i, int *x, int *y, int *w, int *h)
{
    *x = LIST_X + 6;
    *y = ROW_Y + i * (ROW_H + ROW_GAP);
    *w = LIST_W - 12;
    *h = ROW_H;
}

static const char *const sTabNames[CTR_EXTRAS_PAGES] = { "SETTINGS", "ENHANCE", "CHEATS" };
/* SETTINGS' pages, by what each one's rows are about */
static const char *const sSettingsPages[] = { "GAME", "3D WORLD", "MORE" };

/* A page key of the footer, with an arrow; grey at the first or last page. */
static void PagerKey(int x, bool8 left, bool8 live, bool8 pressed)
{
    RoundBox(x, BACK_Y, PAGER_KEY_W, BACK_H, 6, !live ? C_SLATE_HI : pressed ? C_BAND : C_FLAT, live ? C_BAND_DK : C_SLATE_HI);
    Arrow(x + PAGER_KEY_W / 2, BACK_Y + BACK_H / 2, left, live ? C_WHITE : C_MUTED);
}

static void DrawPager(const ViewState *s, int pages)
{
    char label[24];
    int n;

    if (s->optTab == CTR_EXTRAS_OPTIONS && s->optPage < ARRAY_COUNT(sSettingsPages))
        n = strlen(strcpy(label, sSettingsPages[s->optPage]));
    else
        n = strlen(strcpy(label, "PAGE"));
    label[n++] = ' ';
    label[n++] = '1' + s->optPage;
    label[n++] = '/';
    label[n++] = '0' + pages;
    label[n] = 0;
    PagerKey(PAGER_PREV_X, TRUE, s->optPage > 0, s->pressed == HIT_PAGE_PREV);
    PagerKey(PAGER_NEXT_X, FALSE, s->optPage + 1 < pages, s->pressed == HIT_PAGE_NEXT);
    TextCentered(FONT_SMALL, Ascii(label), (PAGER_PREV_X + PAGER_KEY_W + PAGER_NEXT_X) / 2, BACK_Y + 4, C_WHITE, C_SLATE);
}

static void Toggle(int x, int y, bool8 on, bool8 live)
{
    u16 track = !live ? C_LINE : on ? C_GREEN : C_OFF;
    int kx = on ? x + 20 : x + 2;

    RoundRect(x, y, 34, 14, 7, track);
    Disc(kx + 6, y + 7, 6, C_MUTED);
    Disc(kx + 6, y + 7, 5, C_WHITE);
}

static void DrawOptions(const ViewState *s)
{
    OptRow rows[OPT_MAX_ROWS];
    int count = PageRows(s->optTab, s->optSub, rows), pages = PageCount(count);

    Header(Ascii("OPTIONS"));
    FillRect(0, HEADER_H, W, H - HEADER_H, C_PAGE);
    RoundBox(LIST_X, LIST_Y, LIST_W, LIST_H, 5, C_CARD, C_LINE);
    /* the tabs, a Pokédex's index tabs; the chosen one opens into the list */
    for (int t = 0; t < CTR_EXTRAS_PAGES; t++)
    {
        int x = TAB_X + t * TAB_W;
        bool8 on = t == s->optTab, pressed = s->pressed == HIT_TAB + t;

        RoundBox(x, TAB_Y, TAB_W - 2, TAB_H, 5, on ? C_CARD : pressed ? C_BAND : C_FLAT, on ? C_LINE : C_BAND_DK);
        if (on)
            FillRect(x + 1, LIST_Y, TAB_W - 4, TAB_Y + TAB_H - LIST_Y, C_CARD);
        TextCentered(FONT_SMALL, Ascii(sTabNames[t]), x + TAB_W / 2 - 1, TAB_Y + 2,
                     on ? C_TEXT : C_WHITE, on ? C_TEXT_SH : C_BAND_DK);
    }
    for (int i = 0; i < OPT_PAGE_ROWS; i++)
    {
        int n = s->optPage * OPT_PAGE_ROWS + i, x, y, w, h;
        const OptRow *r = &rows[n];
        bool8 live, pressed, pressedBack;
        u8 kind;
        u16 ink, shade;

        if (n >= count)
            break;
        OptRowRect(i, &x, &y, &w, &h);
        live = RowLive(r);
        kind = RowKind(r);
        pressed = s->pressed == HIT_ROW + i;
        pressedBack = s->pressed == HIT_ROW_BACK + i;
        ink = live ? C_TEXT : C_OFF;
        shade = live ? C_TEXT_SH : C_CARD;
        if (i)
            FillRect(x + 2, y - 1, w - 4, 1, C_LINE);
        if (kind != ROW_STEP && (pressed || pressedBack))
            RoundRect(x, y, w, h, 4, C_PRESSED);
        Text(FONT_SMALL, r->opt >= 0 ? OptionName(r->opt) : Ascii(r->extra->name), x + 4, y + 3, ink, shade, TRUE);
        if (kind == ROW_TOGGLE)
        {
            Toggle(x + w - 38, y + 4, RowOn(r), live);
        }
        else if (kind == ROW_ACTION)
        {
            const u8 *label = Ascii(r->extra->values ? r->extra->values[0] : "GO");
            int bw = TextWidth(FONT_SMALL, label) + 14;

            RoundBox(x + w - bw - 2, y + 2, bw, h - 4, 5, pressed || pressedBack ? C_BAND : C_FLAT, C_BAND_DK);
            TextCentered(FONT_SMALL, label, x + w - 2 - bw / 2, y + 3, C_WHITE, C_BAND_DK);
        }
        else
        {
            const u8 *value;
            u16 arrow = live ? C_FLAT : C_OFF;

            if (r->opt >= 0)
                value = OptionValue(r->opt, OptionGet(r->opt));
            else if (r->extra->text)
                value = r->extra->text();
            else
                value = Ascii(r->extra->values[CtrExtras_Value(r->extra)]);
            RoundBox(x + w - 118, y + 2, 20, h - 4, 4, pressedBack ? C_PRESSED : C_PAGE, C_LINE);
            Arrow(x + w - 108, y + h / 2, TRUE, arrow);
            TextCentered(FONT_SMALL, value, x + w - 59, y + 3, live ? C_BAND : C_OFF, shade);
            RoundBox(x + w - 22, y + 2, 20, h - 4, 4, pressed ? C_PRESSED : C_PAGE, C_LINE);
            Arrow(x + w - 12, y + h / 2, FALSE, arrow);
        }
    }
    Footer();
    if (pages > 1)
        DrawPager(s, pages);
    BackKey(s->pressed == HIT_BACK);
}

static u8 OptionsHitTest(int x, int y)
{
    OptRow rows[OPT_MAX_ROWS];
    int count = PageRows(sOptTab, sOptSub, rows);

    if (y >= TAB_Y && y < LIST_Y + 3)
    {
        int t = (x - TAB_X) / TAB_W;

        return x >= TAB_X && t < CTR_EXTRAS_PAGES ? HIT_TAB + t : HIT_NONE;
    }
    if (y >= FOOTER_Y)
    {
        if (x >= BACK_X - 4)
            return HIT_BACK;
        if (PageCount(count) > 1)
            return x < (PAGER_PREV_X + PAGER_KEY_W + PAGER_NEXT_X) / 2 ? HIT_PAGE_PREV : HIT_PAGE_NEXT;
        return HIT_NONE;
    }
    for (int i = 0; i < OPT_PAGE_ROWS; i++)
    {
        int rx, ry, rw, rh;

        if (sOptPage * OPT_PAGE_ROWS + i >= count)
            break;
        OptRowRect(i, &rx, &ry, &rw, &rh);
        if (x >= rx && x < rx + rw && y >= ry && y < ry + rh + ROW_GAP)
            return (x < rx + rw - 60 ? HIT_ROW_BACK : HIT_ROW) + i;
    }
    return HIT_NONE;
}

static void OptionsActivate(u8 hit)
{
    OptRow rows[OPT_MAX_ROWS];
    int count = PageRows(sOptTab, sOptSub, rows);

    if (hit == HIT_BACK)
    {
        PlaySE(SE_SELECT);
        sScreen = SCR_MAP;
        return;
    }
    if (hit >= HIT_TAB && hit < HIT_TAB + CTR_EXTRAS_PAGES)
    {
        u8 tab = hit - HIT_TAB;

        if (tab != sOptTab)
        {
            PlaySE(SE_SELECT);
            sOptTab = tab;
            sOptSub = 0;
            sOptPage = 0;
        }
        return;
    }
    if (hit == HIT_PAGE_PREV || hit == HIT_PAGE_NEXT)
    {
        int page = sOptPage + (hit == HIT_PAGE_NEXT ? 1 : -1);

        if (page >= 0 && page < PageCount(count))
        {
            PlaySE(SE_SELECT);
            sOptPage = page;
        }
        return;
    }
    if ((hit >= HIT_ROW && hit < HIT_ROW + OPT_PAGE_ROWS) || (hit >= HIT_ROW_BACK && hit < HIT_ROW_BACK + OPT_PAGE_ROWS))
    {
        bool8 back = hit >= HIT_ROW_BACK;
        int n = sOptPage * OPT_PAGE_ROWS + (hit - (back ? HIT_ROW_BACK : HIT_ROW));
        const OptRow *r;

        if (n >= count)
            return;
        r = &rows[n];
        if (!RowLive(r))
            return;
        /* a switch or a button takes a tap anywhere on its row */
        RowStep(r, RowKind(r) == ROW_STEP && back ? -1 : 1);
    }
}


static void SnapshotOptions(ViewState *s)
{
    OptRow rows[OPT_MAX_ROWS];
    int count = PageRows(sOptTab, sOptSub, rows);

    if (sOptPage >= PageCount(count))
        sOptPage = 0;
    s->optTab = sOptTab;
    s->optSub = sOptSub;
    s->optPage = sOptPage;
    for (int i = 0; i < OPT_PAGE_ROWS; i++)
    {
        int n = sOptPage * OPT_PAGE_ROWS + i;

        s->optSig[i] = n < count ? RowSignature(&rows[n]) : 0;
    }
}

/* ------------------------------------------------------------------------ */
/* The panel                                                                */
/* ------------------------------------------------------------------------ */

static const u8 *MenuLabel(const ViewState *s, int i)
{
    switch (i)
    {
    case MENU_POKEDEX: return gText_MenuPokedex;
    case MENU_POKEMON: return gText_MenuPokemon;
    case MENU_BAG:     return gText_MenuBag;
    case MENU_PLAYER:  return s->player;
    case MENU_SAVE:    return gText_MenuSave;
    default:           return gText_MenuOption;
    }
}

static const UiIcon *const sMenuIcons[MENU_COUNT] = { &sIconDex26, &sIconBall26, &sIconBag26, &sIconCard26, &sIconSave26,
                                                      &sIconGear26 };

static void DrawDock(const ViewState *s)
{
    FillRect(0, DOCK_Y, W, H - DOCK_Y, C_BAND);
    FillRect(0, DOCK_Y, W, 2, C_BAND_DK);
    for (int i = 0; i < MENU_COUNT; i++)
    {
        bool8 on = i == MENU_OPTION || ((s->enabled >> i) & 1), pressed = s->pressed == HIT_BUTTON + i && on;
        int x = DOCK_KEY_X + i * DOCK_STEP, dy = pressed ? 1 : 0;

        RoundBox(x, DOCK_KEY_Y, DOCK_KEY_W, DOCK_KEY_H, 7, pressed ? C_PRESSED : on ? C_WHITE : C_EMPTY, C_BAND_DK);
        DrawUiIcon(sMenuIcons[i], x + (DOCK_KEY_W - 26) / 2, DOCK_KEY_Y + 1 + dy, on);
        TextCentered(FONT_SMALL, MenuLabel(s, i), x + DOCK_KEY_W / 2, DOCK_KEY_Y + 27 + dy,
                     on ? C_TEXT : C_MUTED, on ? C_TEXT_SH : C_EMPTY);
    }
}

static void DrawHeader(const ViewState *s)
{
    u8 name[32], time[16], *p;

    p = ConvertIntToDecimalStringN(time, s->hours, STR_CONV_MODE_LEFT_ALIGN, 3);
    *p++ = CHAR_COLON;
    ConvertIntToDecimalStringN(p, s->minutes, STR_CONV_MODE_LEADING_ZEROS, 2);
    if (s->onMap)
        GetMapName(name, s->mapsec, 0);
    Header(s->onMap ? name : NULL);
    TextRight(FONT_NORMAL, time, W - 8, 5, C_WHITE, C_BAND_DK);
    /* RUN: running by default, B then walks; grey until the running shoes */
    RoundRect(RUN_X, RUN_Y, RUN_W, RUN_H, 9, s->pressed == HIT_RUN ? C_SLATE_HI : C_SLATE);
    DrawUiIcon(&sIconShoe20, RUN_X + 6, RUN_Y, (s->run & 2) != 0);
    Toggle(RUN_X + RUN_W - 38, RUN_Y + 3, s->run & 1, (s->run & 2) != 0);
}

static void DrawMonIcon(const MonView *m, int x, int y)
{
    const u8 *tiles = Port_ResolveAssetPointer(GetMonIconTiles(m->iconSpecies, FALSE));
    const u16 *pal = Port_ResolveAssetPointer(gMonIconPaletteTable[gMonIconPaletteIndices[m->iconSpecies]].data);
    u16 pal565[16];

    if (tiles == NULL || pal == NULL)
        return;
    for (int i = 0; i < 16; i++)
        pal565[i] = sLut[pal[i] & 0x7FFF];
    for (int t = 0; t < 16; t++)
        DrawTile4(tiles + t * 32, x + (t % 4) * 8, y + (t / 4) * 8, pal565, FALSE, FALSE);
}

/* An empty place in the party: a ball's outline. */
static void EmptyBall(int cx, int cy, int r)
{
    Ring(cx, cy, r, 1, C_RIM);
    FillRect(cx - r, cy, 2 * r + 1, 1, C_RIM);
}

static void DrawParty(const ViewState *s)
{
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        const MonView *m = &s->party[i];
        int x = PARTY_X + (i % 2) * PARTY_STEP_X, y = PARTY_Y + (i / 2) * PARTY_STEP_Y;

        if (i >= s->partyCount || m->species == SPECIES_NONE)
        {
            RoundBox(x, y, PARTY_CARD_W, PARTY_CARD_H, 5, C_EMPTY, C_LINE);
            EmptyBall(x + PARTY_CARD_W / 2, y + PARTY_CARD_H / 2, 7);
            continue;
        }
        RoundBox(x, y, PARTY_CARD_W, PARTY_CARD_H, 5, s->pressed == HIT_PARTY ? C_PRESSED : C_CARD, C_LINE);
        DrawMonIcon(m, x + (PARTY_CARD_W - 32) / 2, y - 1);
        if (!m->egg)
        {
            u8 buf[8];

            HpBar(x + 4, y + 28, PARTY_CARD_W - 8, m->hp, m->maxHp);
            buf[0] = CHAR_LV;
            ConvertIntToDecimalStringN(buf + 1, m->level, STR_CONV_MODE_LEFT_ALIGN, 3);
            TextCentered(FONT_SMALL, buf, x + PARTY_CARD_W / 2, y + 33, C_TEXT, C_TEXT_SH);
        }
    }
}

static void RenderPanel(const ViewState *s)
{
    if (s->screen == SCR_OPTIONS)
        DrawOptions(s);
    else
    {
        u8 name[32];

        DrawHeader(s);
        FillRect(0, HEADER_H, W, DOCK_Y - HEADER_H, C_PAGE);
        RoundBox(MAP_CARD_X, MAP_CARD_Y, MAP_CARD_W, MAP_CARD_H, 6, C_CARD, C_LINE);
        DrawMap(s);
        if (s->onMap)
        {
            GetMapName(name, s->mapsec, 0);
            Text(FONT_SMALL, name, MAP_X + 3, MAP_Y + MAP_VIEW_H + 4, C_TEXT, C_TEXT_SH, TRUE);
            TextRight(FONT_SMALL, Ascii(s->region ? "SEVII ISLES" : "KANTO"),
                      MAP_X + MAP_VIEW_W - 3, MAP_Y + MAP_VIEW_H + 4, C_MUTED, C_CARD);
        }
        DrawParty(s);
        DrawDock(s);
    }
    CtrBottom_Blit(sCanvas, 0, W);
}

/* ------------------------------------------------------------------------ */
/* The battle's page                                                        */
/* ------------------------------------------------------------------------ */

static const u8 sTypeRgb[NUMBER_OF_MON_TYPES][3] = {
    [TYPE_NORMAL]   = {168, 168, 120}, [TYPE_FIGHTING] = {192,  48,  40}, [TYPE_FLYING]  = {168, 144, 240},
    [TYPE_POISON]   = {160,  64, 160}, [TYPE_GROUND]   = {224, 192, 104}, [TYPE_ROCK]    = {184, 160,  56},
    [TYPE_BUG]      = {168, 184,  32}, [TYPE_GHOST]    = {112,  88, 152}, [TYPE_STEEL]   = {184, 184, 208},
    [TYPE_MYSTERY]  = {104, 160, 144}, [TYPE_FIRE]     = {240, 128,  48}, [TYPE_WATER]   = {104, 144, 240},
    [TYPE_GRASS]    = {120, 200,  80}, [TYPE_ELECTRIC] = {248, 208,  48}, [TYPE_PSYCHIC] = {248,  88, 136},
    [TYPE_ICE]      = {152, 216, 216}, [TYPE_DRAGON]   = {112,  56, 248}, [TYPE_DARK]    = {112,  88,  72},
};

static u16 TypeColour(u8 type)
{
    const u8 *c = sTypeRgb[type < NUMBER_OF_MON_TYPES ? type : TYPE_NORMAL];

    return C8(c[0], c[1], c[2]);
}

/* The action menu: FIGHT across the top, BAG, POKéMON and RUN below it. The
 * move menu: four moves in a 2x2 grid, the footer's BACK as its CANCEL. */
static void ActionRect(int i, int *x, int *y, int *w, int *h)
{
    if (i == 0)
    {
        *x = 8, *y = 31, *w = W - 16, *h = 94;
        return;
    }
    *w = 98;
    *h = 70;
    *x = 8 + (i - 1) * (*w + 5);
    *y = 131;
}

static void MoveRect(int i, int *x, int *y, int *w, int *h)
{
    if (i == 4)
    {
        *x = BACK_X, *y = BACK_Y, *w = BACK_W, *h = BACK_H;
        return;
    }
    *w = 151;
    *h = 84;
    *x = 6 + (i & 1) * (*w + 6);
    *y = 31 + (i >> 1) * (*h + 3);
}

/* A big flat key with a darker lip; returns that shade, for the text's shadow. */
static u16 BigKey(int x, int y, int w, int h, u16 colour, bool8 on, bool8 focus, bool8 pressed)
{
    /* waiting for the game: the same key, faded toward the page */
    u16 c = on ? colour : Mix(colour, C_PAGE, 5, 8), lo = Darker(c, 3);
    int dy = pressed ? 2 : 0;

    if (focus && on)
        RoundRect(x - 2, y - 2, w + 4, h + 5, 11, C_GOLD);
    RoundRect(x, y + 3, w, h - 3, 9, lo);
    RoundGradient(x, y + dy, w, h - 3, 9, Lighter(c, 2), c, h / 3);
    return lo;
}

static void DrawPartyBalls(const ViewState *s, int cx, int y)
{
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        int x = cx - PARTY_SIZE * 7 + i * 14 + 7;

        Disc(x, y, 6, C_INK);
        Disc(x, y, 5, C_WHITE);
        if (s->b.balls[i])
        {
            u16 top = s->b.balls[i] == 1 ? C_BRIGHTRED : C_SHADOW;

            for (int dy = -5; dy < 0; dy++)
                for (int dx = -5; dx <= 5; dx++)
                    if (dx * dx + dy * dy <= 27)
                        Put(x + dx, y + dy, top);
        }
        FillRect(x - 5, y, 11, 1, C_INK);
    }
}

static void DrawActions(const ViewState *s)
{
    static const u8 sRgb[4][3] = { {214, 44, 48}, {232, 158, 36}, {58, 164, 88}, {58, 116, 214} };
    bool8 on = s->b.choose == PORT_BATTLE_ACTION;

    for (int i = 0; i < 4; i++)
    {
        int x, y, w, h;
        const u8 *label = i == 0 ? Ascii("FIGHT") : i == 1 ? gText_MenuBag : i == 2 ? gText_MenuPokemon : Ascii("RUN");
        bool8 pressed = s->pressed == HIT_BATTLE + i;
        u16 lo;

        ActionRect(i, &x, &y, &w, &h);
        lo = BigKey(x, y, w, h, C8(sRgb[i][0], sRgb[i][1], sRgb[i][2]), on, s->b.cursor == i, pressed);
        if (pressed)
            y += 2;
        if (i == 0)
        {
            /* a Poké Ball drawn in its colour, a shade lighter */
            u16 mark = Lighter(on ? C8(214, 44, 48) : Mix(C8(214, 44, 48), C_PAGE, 5, 8), 2);
            int cx = x + w / 2, cy = y + h / 2 - 1;

            Ring(cx, cy, 38, 3, mark);
            FillRect(cx - 38, cy - 1, 26, 3, mark);
            FillRect(cx + 13, cy - 1, 26, 3, mark);
            Ring(cx, cy, 11, 3, mark);
            TextCentered(FONT_NORMAL, label, cx, cy - 8, C_WHITE, lo);
            continue;
        }
        TextCentered(FONT_SMALL, label, x + w / 2, y + h - 22, C_WHITE, lo);
        if (i == 2)
            DrawPartyBalls(s, x + w / 2, y + 24);
        else
        {
            Disc(x + w / 2, y + 24, 18, C_WHITE);
            DrawUiIcon(i == 1 ? &sIconBag28 : &sIconShoe28, x + w / 2 - 14, y + 10, TRUE);
        }
    }
}

static void DrawMoves(const ViewState *s)
{
    for (int i = 0; i < MAX_MON_MOVES; i++)
    {
        u16 move = s->b.moves[i];
        u8 type, buf[16], *p;
        bool8 pressed = s->pressed == HIT_BATTLE + i, focus = s->b.cursor == i;
        int x, y, w, h;
        u16 colour;

        MoveRect(i, &x, &y, &w, &h);
        if (move == MOVE_NONE)
        {
            RoundBox(x, y, w, h, 8, C_EMPTY, C_LINE);
            continue;
        }
        type = gBattleMoves[move].type;
        colour = TypeColour(type);
        if (focus)
            RoundRect(x - 2, y - 2, w + 4, h + 4, 10, C_GOLD);
        RoundBox(x, y, w, h, 8, pressed ? C_PRESSED : C_CARD, C_LINE);
        RoundRect(x + 1, y + 1, w - 2, 26, 7, colour);
        FillRect(x + 1, y + 20, w - 2, 7, colour);
        Text(FONT_NORMAL, gMoveNames[move], x + 8, y + 4, C_WHITE, Darker(colour, 3), TRUE);
        Text(FONT_SMALL, gTypeNames[type], x + 8, y + 32, C_MUTED, C_CARD, TRUE);
        p = StringCopy(buf, Ascii("PP "));
        p = ConvertIntToDecimalStringN(p, s->b.pp[i], STR_CONV_MODE_LEFT_ALIGN, 2);
        *p++ = CHAR_SLASH;
        ConvertIntToDecimalStringN(p, s->b.maxPp[i], STR_CONV_MODE_LEFT_ALIGN, 2);
        TextRight(FONT_SMALL, buf, x + w - 8, y + 32, s->b.pp[i] ? C_TEXT : C_BRIGHTRED, C_CARD);
        RoundRect(x + 8, y + h - 18, w - 16, 7, 3, C_EMPTY);
        if (s->b.maxPp[i] && s->b.pp[i])
            RoundRect(x + 8, y + h - 18, (w - 16) * s->b.pp[i] / s->b.maxPp[i], 7, 3,
                      s->b.pp[i] * 4 > s->b.maxPp[i] ? colour : C_BRIGHTRED);
    }
}

/* A fighter in the footer: its name and level, its HP. */
static void DrawFighter(const FighterView *f, int x, int w)
{
    u8 buf[8] = { CHAR_LV };

    if (!f->present)
        return;
    Text(FONT_SMALL, f->name, x, FOOTER_Y + 2, C_WHITE, C_SLATE, TRUE);
    ConvertIntToDecimalStringN(buf + 1, f->level, STR_CONV_MODE_LEFT_ALIGN, 3);
    TextRight(FONT_SMALL, buf, x + w, FOOTER_Y + 2, C_OFF, C_SLATE);
    HpBar(x, FOOTER_Y + 20, w, f->hp, f->maxHp);
}

static void RenderBattle(const ViewState *s)
{
    FillRect(0, HEADER_H, W, FOOTER_Y - HEADER_H, C_PAGE);
    if (s->b.choose && s->b.player.present)
    {
        u8 title[32], *p = StringCopy(title, Ascii("What will "));

        p = StringCopy(p, s->b.player.name);
        StringCopy(p, Ascii(" do?"));
        Header(title);
    }
    else
        Header(NULL);
    Footer();
    if (s->b.choose == PORT_BATTLE_MOVE)
    {
        DrawMoves(s);
        DrawFighter(&s->b.player, 10, 150);
        BackKey(s->pressed == HIT_BATTLE + 4);
    }
    else
    {
        DrawActions(s);
        DrawFighter(&s->b.player, 10, 142);
        DrawFighter(&s->b.opponent, 168, 142);
    }
    CtrBottom_Blit(sCanvas, 0, W);
}

/* ------------------------------------------------------------------------ */
/* The battle menus and a menu's picture                                    */
/* ------------------------------------------------------------------------ */

s8 Port_BattleMenu(u8 kind, const void *moveInfo)
{
    s8 tap = -1;

    sBattleMenuFrame = CtrGame_Frames();
    sBattleMenuKind = kind;
    if (moveInfo)
        memcpy(&sBattleMoves, moveInfo, sizeof(sBattleMoves));
    if (sBattleTap >= 0 && sBattleTapKind == kind)
        tap = sBattleTap;
    sBattleTap = -1;
    return tap;
}

/* ------------------------------------------------------------------------ */
/* A menu's picture                                                         */
/* ------------------------------------------------------------------------ */

void Port_MenuOnBottom(void)
{
    sMenuFrame = CtrGame_Frames();
}

/* The game's picture this frame belongs on the bottom screen. */
bool CtrBottom_TakesGameFrame(void)
{
    return CtrGame_Frames() - sMenuFrame <= 1;
}

/* Before a game is under way: the Pokédex, shut - its lens and lights, a
 * Poké Ball on the shell, the game's name. Nothing to touch. */
static void HalfDisc(int cx, int cy, int r, bool8 upper, u16 c)
{
    for (int dy = upper ? -r : 1; dy <= (upper ? 0 : r); dy++)
        for (int dx = -r; dx <= r; dx++)
            if (dx * dx + dy * dy <= r * r + r / 2)
                Put(cx + dx, cy + dy, c);
}

static void RenderTitle(void)
{
    const int cx = W / 2, cy = 112, r = 50;

    Header(NULL);
    Shell(0, HEADER_H + 1, W, H - HEADER_H - 1);
    /* the ball, a little shadow under it */
    Disc(cx + 3, cy + 4, r + 3, C_SHELL_DK);
    Disc(cx, cy, r + 3, C_INK);
    HalfDisc(cx, cy, r, TRUE, C_BALL_TOP);
    HalfDisc(cx, cy, r, FALSE, C_WHITE);
    Disc(cx - r / 3, cy - r / 2, r / 6, C8(255, 150, 150));
    FillRect(cx - r, cy - 4, 2 * r + 1, 9, C_INK);
    Disc(cx, cy, 17, C_INK);
    Disc(cx, cy, 13, C_WHITE);
    Ring(cx, cy, 9, 1, C8(190, 194, 202));
#if defined(LEAFGREEN) && defined(SPANISH)
    const char *title = "POKEMON VERDE HOJA";
#elif defined(LEAFGREEN)
    const char *title = "POKEMON LEAFGREEN";
#elif defined(SPANISH)
    const char *title = "POKEMON ROJO FUEGO";
#else
    const char *title = "POKEMON FIRERED";
#endif
    TextCentered(FONT_NORMAL, Ascii(title), cx, cy + r + 14, C_WHITE, C_SHELL_DK);
    CtrBottom_Blit(sCanvas, 0, W);
}

static bool8 sPageDrawn;
static bool8 PageActive(void);
static void Inject(u16 key);

/* The region map fills the screen: the art's 192x144 of land and sea, side
 * stripes and key bar left out, at 5/3. A tap moves its cursor there. */
#define ZOOM_SRC_X 24
#define ZOOM_SRC_Y 16
#define ZOOM_BACK_Y 3
#define ZOOM_FLY_X (BACK_X - 48)
#define ZOOM_FLY_W 44
enum { ZOOM_HIT_NONE, ZOOM_HIT_BACK, ZOOM_HIT_FLY, ZOOM_HIT_MAP };
static u32 sZoomFrame = 0xFFFFFFF0;
static u8 sZoomPressed;
static bool8 sZoomShown;

void Port_RegionMapOnBottom(void)
{
    Port_MenuOnBottom();
    sZoomFrame = CtrGame_Frames();
}

static bool8 ZoomActive(void)
{
    return CtrGame_Frames() - sZoomFrame <= 1;
}

static void DrawZoomed(const u16 *frame)
{
    static u8 mapX[W], mapY[H];

    if (mapX[W - 1] == 0)
    {
        for (int x = 0; x < W; x++)
            mapX[x] = ZOOM_SRC_X + x * 3 / 5;
        for (int y = 0; y < H; y++)
            mapY[y] = ZOOM_SRC_Y + y * 3 / 5;
    }
    for (int x = 0; x < W; x++)
    {
        u16 *col = sCanvas + x * H + (H - 1);
        const u16 *src = frame + mapX[x];

        for (int y = 0; y < H; y++)
            col[-y] = sLut[src[mapY[y] * GBA_W] & 0x7FFF];
    }
    /* the keys, over the sea at the top right */
    RoundBox(BACK_X, ZOOM_BACK_Y, BACK_W, BACK_H, 6, sZoomPressed == ZOOM_HIT_BACK ? C_SLATE : C_SLATE_HI, C_SLATE_EDGE);
    Arrow(BACK_X + 10, ZOOM_BACK_Y + 12, TRUE, C_WHITE);
    Text(FONT_SMALL, Ascii("BACK"), BACK_X + 18, ZOOM_BACK_Y + 4, C_WHITE, C_SLATE_HI, TRUE);
    if (Port_RegionMapIsFly())
    {
        RoundBox(ZOOM_FLY_X, ZOOM_BACK_Y, ZOOM_FLY_W, BACK_H, 6, sZoomPressed == ZOOM_HIT_FLY ? C_BAND : C_FLAT, C_BAND_DK);
        TextCentered(FONT_SMALL, Ascii("FLY"), ZOOM_FLY_X + ZOOM_FLY_W / 2, ZOOM_BACK_Y + 4, C_WHITE, C_BAND_DK);
    }
    CtrBottom_Blit(sCanvas, 0, W);
}

static u8 ZoomHitTest(int x, int y)
{
    if (y < ZOOM_BACK_Y + BACK_H + 3 && x >= BACK_X - 2)
        return ZOOM_HIT_BACK;
    if (y < ZOOM_BACK_Y + BACK_H + 3 && x >= ZOOM_FLY_X - 2 && Port_RegionMapIsFly())
        return ZOOM_HIT_FLY;
    return ZOOM_HIT_MAP;
}

static void ZoomTouch(bool active, u16 x, u16 y)
{
    static bool wasActive;
    static u8 downHit;
    static u16 lastX, lastY;

    if (active)
    {
        if (!wasActive)
            downHit = ZoomHitTest(x, y);
        sZoomPressed = ZoomHitTest(x, y) == downHit ? downHit : ZOOM_HIT_NONE;
        lastX = x;
        lastY = y;
    }
    else
    {
        if (wasActive && sZoomPressed == ZOOM_HIT_BACK)
            Inject(B_BUTTON);
        else if (wasActive && sZoomPressed == ZOOM_HIT_FLY)
            Inject(A_BUTTON);
        else if (wasActive && sZoomPressed == ZOOM_HIT_MAP
              && Port_RegionMapTap(ZOOM_SRC_X + lastX * 3 / 5, ZOOM_SRC_Y + lastY * 3 / 5))
            Inject(A_BUTTON);
        sZoomPressed = ZOOM_HIT_NONE;
    }
    wasActive = active;
}

/* The 240x160 picture at (GAME_X, GAME_Y), in a frame. */
void CtrBottom_ShowGameFrame(const u16 *frame)
{
    if (PageActive())
        return;
    sPageDrawn = FALSE;
    if (ZoomActive())
    {
        DrawZoomed(frame);
        sGameShown = TRUE;
        sZoomShown = TRUE;
        return;
    }
    if (!sGameShown || sZoomShown)
    {
        sZoomShown = FALSE;
        sGameShown = TRUE;
        Header(NULL);
        FillRect(0, HEADER_H, W, H - HEADER_H, C_SLATE);
        RoundBox(GAME_X - 4, GAME_Y - 4, GBA_W + 8, GBA_H + 8, 8, C_SLATE_HI, C_SLATE_EDGE);
        CtrBottom_Blit(sCanvas, 0, W);
    }
    for (int x = 0; x < GBA_W; x++)
    {
        u16 *col = sCanvas + (GAME_X + x) * H + (H - 1 - GAME_Y);

        for (int sy = 0; sy < GBA_H; sy++)
            col[-sy] = sLut[frame[sy * GBA_W + x] & 0x7FFF];
    }
    CtrBottom_Blit(sCanvas, GAME_X, GAME_X + GBA_W);
}

/* ------------------------------------------------------------------------ */
/* The native pages: the party and the bag                                  */
/* ------------------------------------------------------------------------ */

/* The game runs these menus as ever: each page draws its state and turns a tap
 * into the cursor and key it stands for. What the game prints in a window of
 * its own (messages, yes or no, quantities, level-ups) shows as a card, in the
 * place it has in the GBA picture, typing and all. */
#define PAGE_MAX_CARDS 8
/* the windows the menus always have, never a yes or no */
#define PARTY_MESSAGE_WINDOW 6
#define BAG_LAST_FIXED_WINDOW 2
#define BAG_ROWS 5
#define PAGE_MAX_ROWS 7
#define BAG_ROW_Y 32
#define BAG_ROW_H 26
#define BAG_LIST_X 62
#define BAG_LIST_W 252
#define BAG_TAB_H 58
#define FOOT_KEY_W 62
#define FOOT_KEY_STEP 67

enum { PAGE_HIT_BACK = 1, PAGE_HIT_SLOT, PAGE_HIT_ACTION = PAGE_HIT_SLOT + PARTY_SIZE,
       PAGE_HIT_POCKET = PAGE_HIT_ACTION + PORT_MENU_MAX_ACTIONS, PAGE_HIT_ROW = PAGE_HIT_POCKET + 3,
       PAGE_HIT_UP = PAGE_HIT_ROW + PAGE_MAX_ROWS, PAGE_HIT_DOWN, PAGE_HIT_FOOT, PAGE_HIT_MENU = PAGE_HIT_FOOT + 4,
       PAGE_HIT_DIALOG = PAGE_HIT_MENU + 16, PAGE_HIT_MOVE, PAGE_HIT_RAIL = PAGE_HIT_MOVE + 5,
       PAGE_HIT_BOX_CELL, PAGE_HIT_BOX_PARTY = PAGE_HIT_BOX_CELL + 30, PAGE_HIT_BOX_TITLE = PAGE_HIT_BOX_PARTY + PARTY_SIZE,
       PAGE_HIT_BOX_LEFT, PAGE_HIT_BOX_RIGHT, PAGE_HIT_BOX_CHOOSE };

typedef struct {
    u16 species, iconSpecies, hp, maxHp, item;
    u8 egg, level, ailment, gender;
    u8 name[POKEMON_NAME_LENGTH + 1];
} PageMon;

typedef struct {
    u8 page;         /* PORT_PAGE_* */
    u8 pressed;      /* PAGE_HIT_* under the finger */
    u8 cards[PAGE_MAX_CARDS];
    u8 cardCount;
    struct PortPartyView party;
    PageMon mons[PARTY_SIZE];
    struct PortBagView bag;
    u16 top;         /* a list's first row shown */
    u16 rowItem[BAG_ROWS], rowQuantity[BAG_ROWS];
    u16 registered;
    struct PortSummaryView sum;
    struct PortCardView card;
    struct PortDexView dex;
    struct PortStorageView box;
    u32 boxSig;
} PageView;

static u8 sPage;
static u32 sPageFrame = 0xFFFFFFF0;
static PageView sPageShown;
static u32 sPageHash;
static u8 sBagTop[3];
static s8 sBagWantPocket = -1;
static u8 sBagPocketTries;
static s8 sWantPage = -1;      /* the summary's page chosen by touch */
static u8 sWantTries;
static s8 sWantMove = -1;      /* its move, once the moves page's cursor is up */
static u16 sDexTop[2];

void Port_NativePage(u8 page)
{
    Port_MenuOnBottom();
    sPage = page;
    sPageFrame = CtrGame_Frames();
}

static bool8 PageActive(void)
{
    return CtrGame_Frames() - sPageFrame <= 1;
}

static void Inject(u16 key)
{
    sInjected = key;
    sInjectFrames = 3;
}

/* A game window is on the screen while the tilemap holds its first tile. */
static bool8 WindowOnScreen(u8 id)
{
    const struct WindowTemplate *t;
    const u16 *map;

    if (id >= WINDOWS_MAX || gWindows[id].tileData == NULL || gWindows[id].window.bg >= 4)
        return FALSE;
    t = &gWindows[id].window;
    map = GetBgTilemapBuffer(t->bg);
    return map != NULL && (map[t->tilemapTop * 32 + t->tilemapLeft] & 0x3FF) == t->baseBlock;
}

/* What the game printed in a window. Recoloured, it is text on the page's own
 * ground: the window's fill left out, its ink and shadow replaced. */
static void DrawWindowPixels(u8 id, int x, int y, bool8 recolour, u16 ink, u16 shadow)
{
    const struct Window *w = &gWindows[id];
    const u16 *pal = gPlttBufferUnfaded + w->window.paletteNum * 16;

    for (int ty = 0; ty < w->window.height; ty++)
        for (int tx = 0; tx < w->window.width; tx++)
        {
            const u8 *tile = w->tileData + (ty * w->window.width + tx) * 32;

            for (int py = 0; py < 8; py++)
                for (int px = 0; px < 8; px++)
                {
                    u8 v = tile[py * 4 + px / 2];

                    v = (px & 1) ? v >> 4 : v & 15;
                    if (v == 0 || (recolour && v == TEXT_COLOR_WHITE))
                        continue;
                    if (recolour && v == TEXT_COLOR_DARK_GRAY)
                        Put(x + tx * 8 + px, y + ty * 8 + py, ink);
                    else if (recolour && v == TEXT_COLOR_LIGHT_GRAY)
                        Put(x + tx * 8 + px, y + ty * 8 + py, shadow);
                    else
                        Put(x + tx * 8 + px, y + ty * 8 + py, sLut[pal[v] & 0x7FFF]);
                }
        }
}

static u32 WindowHash(u8 id)
{
    const struct Window *w = &gWindows[id];
    int bytes = w->window.width * w->window.height * 32;
    u32 h = id;

    for (int i = 0; i < bytes; i++)
        h = h * 33 + w->tileData[i];
    return h;
}

static void WindowCardRect(u8 id, int *x, int *y, int *w, int *h)
{
    const struct WindowTemplate *t = &gWindows[id].window;

    *x = GAME_X + t->tilemapLeft * 8;
    *y = GAME_Y + t->tilemapTop * 8;
    *w = t->width * 8;
    *h = t->height * 8;
}

static void DrawCards(const PageView *v)
{
    for (int i = 0; i < v->cardCount; i++)
    {
        int x, y, w, h;

        WindowCardRect(v->cards[i], &x, &y, &w, &h);
        RoundBox(x - 6, y - 5, w + 12, h + 10, 7, C_CARD, C_FLAT);
        DrawWindowPixels(v->cards[i], x, y, FALSE, 0, 0);
    }
}

static void AddCard(PageView *v, u8 id)
{
    if (!WindowOnScreen(id) || v->cardCount >= PAGE_MAX_CARDS)
        return;
    for (int i = 0; i < v->cardCount; i++)
        if (v->cards[i] == id)
            return;
    v->cards[v->cardCount++] = id;
}

/* Half-dark under a card or a sheet; the footer's keys stay lit. */
static void DimCanvas(void)
{
    for (int x = 0; x < W; x++)
    {
        u16 *col = sCanvas + x * H;

        for (int j = H - FOOTER_Y; j < H; j++)
            col[j] = ((col[j] >> 1) & 0x7BEF) + ((C_SLATE >> 1) & 0x7BEF);
    }
}

static void TextKey(int x, int y, int w, int h, const u8 *label, bool8 focus, bool8 pressed)
{
    u16 fill = pressed ? C_BAND : focus ? C_FLAT : C_PAGE;

    RoundBox(x, y, w, h, 6, fill, focus || pressed ? C_BAND_DK : C_LINE);
    TextCentered(FONT_SMALL, label, x + w / 2, y + (h - 16) / 2 + 1, focus || pressed ? C_WHITE : C_TEXT,
                 focus || pressed ? C_BAND_DK : C_TEXT_SH);
}

/* A key of a footer holding n of them: four are narrower. */
static void FootKeyN(int i, int n, const u8 *label, bool8 focus, bool8 pressed)
{
    int w = n > 3 ? 48 : FOOT_KEY_W, x = 6 + i * (w + (n > 3 ? 3 : 5));

    RoundBox(x, BACK_Y, w, BACK_H, 6, pressed ? C_BAND : C_FLAT, focus ? C_WHITE : C_BAND_DK);
    TextCentered(FONT_SMALL, label, x + w / 2, BACK_Y + 4, C_WHITE, C_BAND_DK);
}

static void FootKey(int i, const u8 *label, bool8 focus, bool8 pressed)
{
    FootKeyN(i, 3, label, focus, pressed);
}

static u8 FootHit(int x, int n)
{
    int w = n > 3 ? 48 : FOOT_KEY_W, step = w + (n > 3 ? 3 : 5), i = (x - 6) / step;

    return x >= 6 && i < n ? PAGE_HIT_FOOT + i : HIT_NONE;
}

/* The party: two columns of three cards. */
#define SLOT_X(i) (6 + ((i) % 2) * 156)
#define SLOT_Y(i) (31 + ((i) / 2) * 58)
#define SLOT_W 152
#define SLOT_H 54
/* the sheet of what to do with one of them */
#define SHEET_X 6
#define SHEET_Y 124
#define SHEET_W 308
#define SHEET_H 78
#define SHEET_KEY_W 71
#define SHEET_KEY_STEP 75

static void SheetKeyRect(int count, int i, int *x, int *y, int *w, int *h)
{
    bool8 two = count > 4;

    *w = SHEET_KEY_W;
    *h = two ? 22 : 36;
    *x = SHEET_X + 6 + (i % 4) * SHEET_KEY_STEP;
    *y = (two ? SHEET_Y + 28 : SHEET_Y + 36) + (i / 4) * 24;
}

static void DrawPartyCard(const PageView *v, int i)
{
    static const char *const ailments[] = { "", "PSN", "PAR", "SLP", "FRZ", "BRN", "PKRS", "FNT" };
    const PageMon *m = &v->mons[i];
    int x = SLOT_X(i), y = SLOT_Y(i);
    bool8 cursor = v->party.switching ? i == v->party.slot2 : i == v->party.slot;
    bool8 source = v->party.switching && i == v->party.slot;
    u8 buf[16], *p;

    if (m->species == SPECIES_NONE)
    {
        RoundBox(x, y, SLOT_W, SLOT_H, 6, C_EMPTY, C_LINE);
        EmptyBall(x + SLOT_W / 2, y + SLOT_H / 2, 8);
        return;
    }
    if (source)
        RoundBox(x, y, SLOT_W, SLOT_H, 6, C8(255, 248, 220), C_GOLD);
    else
        RoundBox(x, y, SLOT_W, SLOT_H, 6, cursor || v->pressed == PAGE_HIT_SLOT + i ? C_PRESSED : C_CARD, cursor ? C_FLAT : C_LINE);
    if (cursor)
        RoundBox(x + 1, y + 1, SLOT_W - 2, SLOT_H - 2, 5, C_PRESSED, C_FLAT);
    DrawMonIcon((const MonView *)&(MonView){ m->species, m->iconSpecies, m->hp, m->maxHp, m->egg, m->level }, x + 3, y + 10);
    Text(FONT_SMALL, m->name, x + 38, y + 3, C_TEXT, C_TEXT_SH, TRUE);
    if (m->egg)
        return;
    if (m->gender != MON_GENDERLESS)
    {
        u8 g[2] = { m->gender == MON_MALE ? CHAR_MALE : CHAR_FEMALE, EOS };

        Text(FONT_SMALL, g, x + 38 + TextWidth(FONT_SMALL, m->name) + 2, y + 3,
             m->gender == MON_MALE ? C8(70, 130, 230) : C8(230, 80, 110), C_CARD, TRUE);
    }
    buf[0] = CHAR_LV;
    ConvertIntToDecimalStringN(buf + 1, m->level, STR_CONV_MODE_LEFT_ALIGN, 3);
    TextRight(FONT_SMALL, buf, x + SLOT_W - 6, y + 3, C_MUTED, C_CARD);
    if (m->item != ITEM_NONE)
    {
        Disc(x + 8, y + 42, 4, C_BAND_DK);
        Disc(x + 8, y + 42, 3, C_GOLD);
    }
    if (v->party.desc[i])
    {
        Text(FONT_SMALL, v->party.desc[i], x + 38, y + 24, C_BAND, C_CARD, TRUE);
        return;
    }
    Text(FONT_SMALL, Ascii("HP"), x + 38, y + 20, C_BAND, C_CARD, TRUE);
    HpBar(x + 52, y + 25, SLOT_W - 58, m->hp, m->maxHp);
    p = ConvertIntToDecimalStringN(buf, m->hp, STR_CONV_MODE_LEFT_ALIGN, 3);
    *p++ = CHAR_SLASH;
    ConvertIntToDecimalStringN(p, m->maxHp, STR_CONV_MODE_LEFT_ALIGN, 3);
    TextRight(FONT_SMALL, buf, x + SLOT_W - 6, y + 34, C_TEXT, C_TEXT_SH);
    if (m->ailment && m->ailment < ARRAY_COUNT(ailments))
    {
        RoundRect(x + 38, y + 37, 28, 13, 4, m->ailment == AILMENT_FNT ? C_SLATE_HI : C_BRIGHTRED);
        TextCentered(FONT_SMALL, Ascii(ailments[m->ailment]), x + 52, y + 35, C_WHITE, m->ailment == AILMENT_FNT ? C_SLATE_HI : C_BRIGHTRED);
    }
}

static void DrawPartyBase(const PageView *v)
{
    Header(gText_MenuPokemon);
    FillRect(0, HEADER_H, W, FOOTER_Y - HEADER_H, C_PAGE);
    for (int i = 0; i < PARTY_SIZE; i++)
        DrawPartyCard(v, i);
    Footer();
    BackKey(v->pressed == PAGE_HIT_BACK);
    if (v->party.mode == PORT_MENU_LIST && v->party.chooseMultiple)
        FootKey(2, Ascii("CONFIRM"), v->party.slot == PARTY_SIZE, v->pressed == PAGE_HIT_FOOT);
    if (v->party.mode == PORT_MENU_ACTIONS || v->cardCount)
        DimCanvas();
    if (v->party.mode == PORT_MENU_ACTIONS)
    {
        const PageMon *m = &v->mons[v->party.slot < PARTY_SIZE ? v->party.slot : 0];

        RoundBox(SHEET_X, SHEET_Y, SHEET_W, SHEET_H, 8, C_CARD, C_FLAT);
        DrawMonIcon((const MonView *)&(MonView){ m->species, m->iconSpecies, m->hp, m->maxHp, m->egg, m->level }, SHEET_X + 6, SHEET_Y - 2);
        for (int i = 0; i < v->party.numActions; i++)
        {
            int x, y, w, h;

            SheetKeyRect(v->party.numActions, i, &x, &y, &w, &h);
            TextKey(x, y, w, h, v->party.actions[i], i == Menu_GetCursorPos(), v->pressed == PAGE_HIT_ACTION + i);
        }
    }
}

/* What keeps changing on the party's page: the prompt, the cards. */
static void DrawPartyLive(const PageView *v)
{
    u8 help = v->party.helpWindow;

    if (v->party.mode == PORT_MENU_ACTIONS)
    {
        FillRect(SHEET_X + 40, SHEET_Y + 4, SHEET_W - 46, 24, C_CARD);
        if (WindowOnScreen(help))
            DrawWindowPixels(help, SHEET_X + 40, SHEET_Y + 6, TRUE, C_TEXT, C_TEXT_SH);
    }
    else if (v->cardCount == 0)
    {
        FillRect(4, FOOTER_Y + 1, 196, FOOTER_H - 1, C_SLATE);
        if (WindowOnScreen(help))
            DrawWindowPixels(help, 8, FOOTER_Y + (FOOTER_H - gWindows[help].window.height * 8) / 2, TRUE, C_WHITE, C_SLATE_HI);
    }
    DrawCards(v);
}

/* The item icons, drawn from a few kept decoded. */
typedef struct {
    u16 item;
    bool8 ready;
    u8 tiles[9 * 32];
    u16 pal[16];
} ItemIconCache;

static ItemIconCache sItemIcons[BAG_ROWS + 3];
static u8 sItemIconNext;

static void DrawItemIcon(u16 item, int x, int y)
{
    ItemIconCache *c = NULL;

    for (unsigned i = 0; i < ARRAY_COUNT(sItemIcons); i++)
        if (sItemIcons[i].ready && sItemIcons[i].item == item)
            c = &sItemIcons[i];
    if (c == NULL)
    {
        void *tiles = Decompress(GetItemIconGfxPtr(item, ITEMICON_TILES));
        u16 *pal = Decompress(GetItemIconGfxPtr(item, ITEMICON_PAL));

        c = &sItemIcons[sItemIconNext++ % ARRAY_COUNT(sItemIcons)];
        c->ready = tiles != NULL && pal != NULL;
        c->item = item;
        if (c->ready)
        {
            memcpy(c->tiles, tiles, sizeof(c->tiles));
            for (int i = 0; i < 16; i++)
                c->pal[i] = sLut[pal[i] & 0x7FFF];
        }
        free(tiles);
        free(pal);
    }
    if (c->ready)
        for (int t = 0; t < 9; t++)
            DrawTile4(c->tiles + t * 32, x + (t % 3) * 8, y + (t / 3) * 8, c->pal, FALSE, FALSE);
}

/* Lines of text, as the game breaks them. */
static void TextLines(u8 font, const u8 *str, int x, int y, int step, u16 ink, u16 shadow)
{
    while (TRUE)
    {
        Text(font, str, x, y, ink, shadow, TRUE);
        while (*str != EOS && *str != CHAR_NEWLINE)
            str++;
        if (*str == EOS)
            return;
        str++;
        y += step;
    }
}

static void DrawBagBase(const PageView *v)
{
    static const char *const names[] = { "ITEMS", "KEY", "BALLS" };
    static const u16 icons[] = { ITEM_POTION, ITEM_TOWN_MAP, ITEM_POKE_BALL };
    const struct PortBagView *b = &v->bag;
    u16 current = b->cursor < b->nItems ? BagGetItemIdByPocketPosition(b->pocket + 1, b->cursor) : ITEM_NONE;

    Header(gText_MenuBag);
    FillRect(BAG_LIST_X, HEADER_H, W - BAG_LIST_X, FOOTER_Y - HEADER_H, C_PAGE);
    FillRect(0, HEADER_H, BAG_LIST_X, FOOTER_Y - HEADER_H, C_BAND);
    /* the pockets */
    for (int i = 0; i < 3; i++)
    {
        int y = 30 + i * BAG_TAB_H;
        bool8 on = i == b->pocket, pressed = v->pressed == PAGE_HIT_POCKET + i;

        RoundBox(4, y, on ? BAG_LIST_X : BAG_LIST_X - 8, BAG_TAB_H - 4, 6, on ? C_CARD : pressed ? C_BAND_DK : C_FLAT, on ? C_LINE : C_BAND_DK);
        DrawItemIcon(icons[i], 19, y + 5);
        TextCentered(FONT_SMALL, Ascii(names[i]), 31, y + 33, on ? C_TEXT : C_WHITE, on ? C_TEXT_SH : C_BAND_DK);
    }
    /* the list */
    RoundBox(BAG_LIST_X, 30, BAG_LIST_W, 132, 6, C_CARD, C_LINE);
    FillRect(BAG_LIST_X, 32 + b->pocket * BAG_TAB_H, 3, BAG_TAB_H - 8, C_CARD);
    for (int i = 0; i < BAG_ROWS; i++)
    {
        int index = v->top + i, y = BAG_ROW_Y + i * BAG_ROW_H;
        bool8 cursor = index == b->cursor;

        if (index > b->nItems)
            break;
        if (cursor || v->pressed == PAGE_HIT_ROW + i)
            RoundBox(66, y, 236, 25, 5, C_PRESSED, C_FLAT);
        else if (i)
            FillRect(70, y, 228, 1, C_LINE);
        if (index == b->nItems)
        {
            Arrow(80, y + 12, TRUE, C_BAND);
            Text(FONT_SMALL, gFameCheckerText_Cancel, 96, y + 5, C_TEXT, C_TEXT_SH, TRUE);
            continue;
        }
        DrawItemIcon(v->rowItem[i], 68, y + 1);
        Text(FONT_SMALL, ItemId_GetName(v->rowItem[i]), 96, y + 5, C_TEXT, C_TEXT_SH, TRUE);
        if (v->rowQuantity[i])
        {
            u8 buf[8] = { CHAR_x };

            ConvertIntToDecimalStringN(buf + 1, v->rowQuantity[i], STR_CONV_MODE_LEFT_ALIGN, 3);
            TextRight(FONT_SMALL, buf, 296, y + 5, C_MUTED, C_CARD);
        }
        else if (v->rowItem[i] == v->registered)
        {
            RoundRect(268, y + 6, 30, 13, 4, C_FLAT);
            TextCentered(FONT_SMALL, Ascii("SEL"), 283, y + 4, C_WHITE, C_FLAT);
        }
    }
    /* how far along the list it is, a tap above or below moves a screenful */
    {
        int count = b->nItems + 1, h = count > BAG_ROWS ? 118 * BAG_ROWS / count : 118, y = count > BAG_ROWS ? 36 + (118 - h) * v->top / (count - BAG_ROWS) : 36;

        RoundRect(305, 36, 5, 118, 2, C_LINE);
        RoundRect(305, y, 5, h, 2, C_FLAT);
    }
    /* what it is */
    RoundRect(BAG_LIST_X, 165, BAG_LIST_W, 39, 6, C_SLATE);
    TextLines(FONT_SMALL, current != ITEM_NONE ? ItemId_GetDescription(current) : gText_CloseBag, BAG_LIST_X + 8, 165, 12, C_WHITE, C_SLATE);
    /* the keys */
    Footer();
    BackKey(v->pressed == PAGE_HIT_BACK);
    if (b->mode == PORT_MENU_ACTIONS)
        for (int i = 0; i < b->numActions; i++)
            FootKey(i, b->actions[i], b->actionRow[i] == Menu_GetCursorPos(), v->pressed == PAGE_HIT_FOOT + i);
    else if (b->mode == PORT_MENU_QUANTITY)
    {
        FootKey(0, Ascii("LESS"), FALSE, v->pressed == PAGE_HIT_FOOT);
        FootKey(1, Ascii("MORE"), FALSE, v->pressed == PAGE_HIT_FOOT + 1);
        FootKey(2, Ascii("OK"), FALSE, v->pressed == PAGE_HIT_FOOT + 2);
    }
    else
        Text(FONT_SMALL, Ascii(b->mode == PORT_MENU_LIST ? "Choose an item." : ""), 10, BACK_Y + 4, C_WHITE, C_SLATE, TRUE);
    if (v->cardCount)
        DimCanvas();
}

/* A 64x64 picture, a mon's or a trainer's, with the last one kept decoded. */
static u8 sPicTiles[0x800];
static u16 sPicPal[16];
static u32 sPicKey = 0xFFFFFFFF;

static void DrawPicFrom(bool8 trainer, u16 id, u32 personality, const void *palSrc, u32 key, int x, int y)
{
    if (key != sPicKey)
    {
        void *pal = Decompress(palSrc);

        if (trainer)
        {
            void *tiles = Decompress(gTrainerFrontPicTable[id].data);

            if (tiles)
                memcpy(sPicTiles, tiles, sizeof(sPicTiles));
            free(tiles);
        }
        else
            LoadSpecialPokePic(&gMonFrontPicTable[id], sPicTiles, id, personality, TRUE);
        if (pal)
        {
            for (int i = 0; i < 16; i++)
                sPicPal[i] = sLut[((const u16 *)pal)[i] & 0x7FFF];
            free(pal);
        }
        sPicKey = key;
    }
    for (int t = 0; t < 64; t++)
        DrawTile4(sPicTiles + t * 32, x + (t % 8) * 8, y + (t / 8) * 8, sPicPal, FALSE, FALSE);
}

static void DrawPic(bool8 trainer, u16 id, u32 personality, u32 otId, int x, int y)
{
    DrawPicFrom(trainer, id, personality, trainer ? gTrainerFrontPicPaletteTable[id].data : GetMonSpritePalFromSpeciesAndPersonality(id, otId, personality),
                (u32)trainer << 31 ^ (u32)id << 16 ^ personality ^ otId * 31, x, y);
}

static void DrawPicWithPal(u16 species, u32 personality, const void *pal, int x, int y)
{
    DrawPicFrom(FALSE, species, personality, pal, (u32)species << 16 ^ personality ^ (u32)(uintptr_t)pal * 31, x, y);
}

static void TypeChip(int x, int y, int w, u8 type)
{
    RoundRect(x, y, w, 14, 4, TypeColour(type));
    TextCentered(FONT_SMALL, gTypeNames[type], x + w / 2, y - 1, C_WHITE, Darker(TypeColour(type), 3));
}

static void TabsOverCard(const char *const *names, int count, int on, int pressed)
{
    for (int t = 0; t < count; t++)
    {
        int x = TAB_X + t * TAB_W;

        RoundBox(x, TAB_Y, TAB_W - 2, TAB_H, 5, t == on ? C_CARD : pressed == t ? C_BAND : C_FLAT, t == on ? C_LINE : C_BAND_DK);
        if (t == on)
            FillRect(x + 1, LIST_Y, TAB_W - 4, TAB_Y + TAB_H - LIST_Y, C_CARD);
        TextCentered(FONT_SMALL, Ascii(names[t]), x + TAB_W / 2 - 1, TAB_Y + 2, t == on ? C_TEXT : C_WHITE, t == on ? C_TEXT_SH : C_BAND_DK);
    }
}

static void InfoRow(int x, int y, int w, const u8 *label, const u8 *value)
{
    Text(FONT_SMALL, label, x, y, C_MUTED, C_CARD, TRUE);
    TextRight(FONT_SMALL, value, x + w, y, C_TEXT, C_TEXT_SH);
}

/* The summary: a tab per page; the mon on the left, the page on the right, a
 * band below for what takes a line of its own. */
#define SUM_DIVIDER_X 118
#define SUM_CARD_Y 46
#define SUM_RIGHT_X 126
#define SUM_RIGHT_W 180
#define SUM_TOP (SUM_CARD_Y + 6)
#define SUM_MOVE_Y SUM_TOP
#define SUM_MOVE_H 22

/* Text broken again to a width: the game's line ends count as spaces. */
static void TextWrapped(u8 font, const u8 *str, int x, int y, int width, int step, u16 ink, u16 shadow)
{
    int cx = x, space = TextWidth(font, Ascii(" ")) ;

    while (*str != EOS)
    {
        u8 word[32];
        int n = 0, w;

        while (*str == CHAR_SPACE || *str == CHAR_NEWLINE)
            str++;
        while (*str != EOS && *str != CHAR_SPACE && *str != CHAR_NEWLINE && n < (int)sizeof(word) - 1)
            word[n++] = *str++;
        word[n] = EOS;
        w = TextWidth(font, word);
        if (cx > x && cx + w > x + width)
        {
            cx = x;
            y += step;
        }
        Text(font, word, cx, y, ink, shadow, TRUE);
        cx += w + space;
    }
}

static void DrawSummaryMon(const struct PortSummaryView *s, int cardH)
{
    u16 tint = Lighter(TypeColour(gSpeciesInfo[s->species].types[0]), 6);
    int bottom = SUM_CARD_Y + cardH - 1;
    u8 lv[8] = { CHAR_LV };

    FillRect(LIST_X + 1, SUM_TOP, SUM_DIVIDER_X - LIST_X - 1, bottom - SUM_TOP - 3, tint);
    RoundRect(LIST_X + 1, bottom - 8, SUM_DIVIDER_X - LIST_X - 1, 8, 4, tint);
    FillRect(SUM_DIVIDER_X - 5, bottom - 8, 5, 8, tint);
    FillRect(SUM_DIVIDER_X, SUM_TOP, 1, bottom - SUM_TOP, C_LINE);
    DrawPic(FALSE, s->isEgg ? SPECIES_EGG : s->species, s->personality, s->otId, 30, SUM_TOP - 2);
    Text(FONT_SMALL, s->nickname, 12, SUM_CARD_Y + 66, C_TEXT, tint, TRUE);
    if (s->isEgg)
        return;
    ConvertIntToDecimalStringN(lv + 1, GetMonData((struct Pokemon *)s->mon, MON_DATA_LEVEL), STR_CONV_MODE_LEFT_ALIGN, 3);
    TextRight(FONT_SMALL, lv, SUM_DIVIDER_X - 5, SUM_CARD_Y + 66, C_BAND, tint);
    Text(FONT_SMALL, s->gender, 12 + TextWidth(FONT_SMALL, s->nickname) + 2, SUM_CARD_Y + 66, C8(70, 110, 220), tint, TRUE);
    if (gSpeciesInfo[s->species].types[0] == gSpeciesInfo[s->species].types[1])
        TypeChip(36, SUM_CARD_Y + 83, 52, gSpeciesInfo[s->species].types[0]);
    else
    {
        TypeChip(11, SUM_CARD_Y + 83, 50, gSpeciesInfo[s->species].types[0]);
        TypeChip(63, SUM_CARD_Y + 83, 50, gSpeciesInfo[s->species].types[1]);
    }
}

static void DrawSummarySkills(const struct PortSummaryView *s)
{
    static const char *const names[5] = { "ATTACK", "DEFENSE", "SP. ATK", "SP. DEF", "SPEED" };
    static const u8 monStats[5] = { MON_DATA_ATK, MON_DATA_DEF, MON_DATA_SPATK, MON_DATA_SPDEF, MON_DATA_SPEED };
    struct Pokemon *mon = (struct Pokemon *)s->mon;
    int best = 1, level = GetMonData(mon, MON_DATA_LEVEL);
    const u32 *table = gExperienceTables[gSpeciesInfo[s->species].growthRate];
    u32 exp = GetMonData(mon, MON_DATA_EXP), base = table[level], span = level < MAX_LEVEL ? table[level + 1] - base : 0;

    for (int i = 0; i < 5; i++)
        if ((int)GetMonData(mon, monStats[i]) > best)
            best = GetMonData(mon, monStats[i]);
    InfoRow(SUM_RIGHT_X, SUM_TOP - 1, SUM_RIGHT_W, Ascii("HP"), s->hp);
    HpBar(SUM_RIGHT_X, SUM_TOP + 13, SUM_RIGHT_W, GetMonData(mon, MON_DATA_HP), GetMonData(mon, MON_DATA_MAX_HP));
    for (int i = 0; i < 5; i++)
    {
        int y = SUM_TOP + 17 + i * 12, value = GetMonData(mon, monStats[i]);

        Text(FONT_SMALL, Ascii(names[i]), SUM_RIGHT_X, y, C_TEXT, C_TEXT_SH, TRUE);
        TextRight(FONT_SMALL, s->stats[i], SUM_RIGHT_X + 84, y, C_TEXT, C_TEXT_SH);
        RoundRect(SUM_RIGHT_X + 90, y + 5, SUM_RIGHT_W - 90, 6, 2, C_EMPTY);
        RoundRect(SUM_RIGHT_X + 90, y + 5, (SUM_RIGHT_W - 90) * value / best, 6, 2, C_LENS);
    }
    FillRect(SUM_RIGHT_X, SUM_TOP + 78, SUM_RIGHT_W, 1, C_LINE);
    InfoRow(SUM_RIGHT_X, SUM_TOP + 78, SUM_RIGHT_W, Ascii("EXP. POINTS"), s->expPoints);
    InfoRow(SUM_RIGHT_X, SUM_TOP + 92, 124, Ascii("NEXT LV."), s->expNext);
    RoundRect(SUM_RIGHT_X + 130, SUM_TOP + 97, SUM_RIGHT_W - 130, 6, 2, C_EMPTY);
    if (span)
        RoundRect(SUM_RIGHT_X + 130, SUM_TOP + 97, (SUM_RIGHT_W - 130) * (u64)(exp - base) / span, 6, 2, C_LENS);
    /* the ability */
    RoundRect(6, 165, 308, 39, 6, C_SLATE);
    Text(FONT_SMALL, s->abilityName, 14, 167, C_YELLOW, C_SLATE, TRUE);
    Text(FONT_SMALL, s->abilityDesc, 14, 182, C_WHITE, C_SLATE, TRUE);
}

static void DrawSummaryMoves(const PageView *v)
{
    const struct PortSummaryView *s = &v->sum;
    int rows = s->selecting ? 5 : 4;

    for (int i = 0; i < rows; i++)
    {
        int y = SUM_MOVE_Y + i * SUM_MOVE_H;
        bool8 cursor = s->selecting && i == s->moveCursor;

        if (cursor || v->pressed == PAGE_HIT_MOVE + i)
            RoundBox(SUM_DIVIDER_X + 3, y, 192, SUM_MOVE_H - 1, 5, s->swapping && cursor ? C8(255, 248, 220) : C_PRESSED, s->swapping && cursor ? C_GOLD : C_FLAT);
        else if (i)
            FillRect(SUM_RIGHT_X, y - 1, SUM_RIGHT_W, 1, C_LINE);
        if (s->moveIds[i] == MOVE_NONE)
        {
            Text(FONT_SMALL, i == 4 ? gFameCheckerText_Cancel : Ascii("-"), SUM_RIGHT_X + 54, y + 3, C_MUTED, C_CARD, TRUE);
            continue;
        }
        TypeChip(SUM_RIGHT_X, y + 4, 50, gBattleMoves[s->moveIds[i]].type);
        Text(FONT_SMALL, s->moveName[i], SUM_RIGHT_X + 54, y + 3, C_TEXT, C_TEXT_SH, TRUE);
        {
            int r = SUM_RIGHT_X + SUM_RIGHT_W - 2;

            Text(FONT_SMALL, s->moveMaxPp[i], r - TextWidth(FONT_SMALL, s->moveMaxPp[i]), y + 3, C_TEXT, C_TEXT_SH, TRUE);
            r -= TextWidth(FONT_SMALL, s->moveMaxPp[i]);
            Text(FONT_SMALL, Ascii("/"), r - 5, y + 3, C_MUTED, C_CARD, TRUE);
            TextRight(FONT_SMALL, s->moveCurPp[i], r - 6, y + 3, C_TEXT, C_TEXT_SH);
        }
    }
    RoundRect(6, 165, 308, 39, 6, C_SLATE);
    if (s->selecting && s->moveCursor < 5 && s->moveIds[s->moveCursor] != MOVE_NONE)
    {
        u8 c = s->moveCursor;

        TextWrapped(FONT_SMALL, gMoveDescriptionPointers[s->moveIds[c] - 1], 14, 165, 196, 12, C_WHITE, C_SLATE);
        Text(FONT_SMALL, Ascii("POWER"), 214, 167, C_YELLOW, C_SLATE, TRUE);
        TextRight(FONT_SMALL, s->movePower[c], 306, 167, C_WHITE, C_SLATE);
        Text(FONT_SMALL, Ascii("ACCURACY"), 214, 182, C_YELLOW, C_SLATE, TRUE);
        TextRight(FONT_SMALL, s->moveAccuracy[c], 306, 182, C_WHITE, C_SLATE);
    }
    else
        Text(FONT_SMALL, Ascii("Tap a move for more."), 14, 175, C_WHITE, C_SLATE, TRUE);
}

static void DrawSummaryBase(const PageView *v)
{
    static const char *const tabs[3] = { "INFO", "SKILLS", "MOVES" };
    const struct PortSummaryView *s = &v->sum;
    int page = s->page > PSS_PAGE_MOVES ? PSS_PAGE_MOVES : s->page, cardH = page == PSS_PAGE_INFO ? 100 : 116;

    Header(Ascii("SUMMARY"));
    FillRect(0, HEADER_H, W, FOOTER_Y - HEADER_H, C_PAGE);
    RoundBox(LIST_X, SUM_CARD_Y, LIST_W, cardH, 5, C_CARD, C_LINE);
    TabsOverCard(tabs, s->isEgg ? 1 : 3, page, v->pressed >= PAGE_HIT_POCKET && v->pressed < PAGE_HIT_POCKET + 3 ? v->pressed - PAGE_HIT_POCKET : -1);
    DrawSummaryMon(s, cardH);
    if (page == PSS_PAGE_INFO)
    {
        if (!s->isEgg)
        {
            InfoRow(SUM_RIGHT_X, SUM_TOP + 0, SUM_RIGHT_W, Ascii("No."), s->dexNum);
            InfoRow(SUM_RIGHT_X, SUM_TOP + 16, SUM_RIGHT_W, Ascii("NAME"), s->speciesName);
            InfoRow(SUM_RIGHT_X, SUM_TOP + 32, SUM_RIGHT_W, Ascii("OT"), s->otName);
            InfoRow(SUM_RIGHT_X, SUM_TOP + 48, SUM_RIGHT_W, Ascii("IDNo."), s->idNum);
            InfoRow(SUM_RIGHT_X, SUM_TOP + 64, SUM_RIGHT_W, Ascii("ITEM"), s->itemName);
        }
        RoundBox(LIST_X, 150, LIST_W, 54, 6, C_CARD, C_LINE);
    }
    else if (page == PSS_PAGE_SKILLS)
        DrawSummarySkills(s);
    else
        DrawSummaryMoves(v);
    Footer();
    BackKey(v->pressed == PAGE_HIT_BACK);
    if (s->selecting)
        FootKeyN(0, 1, s->swapping ? Ascii("PLACE") : Ascii("SWITCH"), FALSE, v->pressed == PAGE_HIT_FOOT);
    else
    {
        FootKeyN(0, 2, Ascii("PREV"), FALSE, v->pressed == PAGE_HIT_FOOT);
        FootKeyN(1, 2, Ascii("NEXT"), FALSE, v->pressed == PAGE_HIT_FOOT + 1);
    }
}

static void DrawSummaryLive(const PageView *v)
{
    u8 memo = v->sum.memoWindow;

    if (memo < WINDOWS_MAX && gWindows[memo].tileData != NULL)
    {
        FillRect(LIST_X + 2, 152, LIST_W - 4, 50, C_CARD);
        DrawWindowPixels(memo, 10, 153, TRUE, C_TEXT, C_TEXT_SH);
    }
}

/* The trainer card: the front's data and badges, the back's records. */
static void DrawCardBase(const PageView *v)
{
    const struct PortCardView *c = &v->card;
    u8 buf[16], *p;

    Header(Ascii("TRAINER CARD"));
    FillRect(0, HEADER_H, W, FOOTER_Y - HEADER_H, C8(226, 236, 250));
    RoundBox(10, 31, 300, 171, 10, C_CARD, C_FLAT);
    RoundRect(13, 34, 294, 24, 6, C_FLAT);
    Text(FONT_NORMAL, c->name, 20, 38, C_WHITE, C_BAND_DK, TRUE);
    for (int i = 0; i < c->stars && i < 4; i++)
    {
        Disc(130 + i * 12, 46, 4, C_BAND_DK);
        Disc(130 + i * 12, 46, 3, C_GOLD);
    }
    p = StringCopy(buf, Ascii("IDNo. "));
    ConvertIntToDecimalStringN(p, c->trainerId, STR_CONV_MODE_LEADING_ZEROS, 5);
    TextRight(FONT_SMALL, buf, 300, 38, C_WHITE, C_BAND_DK);
    if (!c->onBack)
    {
        buf[0] = CHAR_CURRENCY;
        ConvertIntToDecimalStringN(buf + 1, c->money, STR_CONV_MODE_LEFT_ALIGN, 7);
        InfoRow(22, 62, 166, Ascii("MONEY"), buf);
        FillRect(22, 79, 166, 1, C_LINE);
        if (c->hasPokedex)
        {
            ConvertIntToDecimalStringN(buf, c->caught, STR_CONV_MODE_LEFT_ALIGN, 3);
            InfoRow(22, 83, 166, gText_MenuPokedex, buf);
        }
        FillRect(22, 100, 166, 1, C_LINE);
        p = ConvertIntToDecimalStringN(buf, c->hours > 999 ? 999 : c->hours, STR_CONV_MODE_LEFT_ALIGN, 3);
        *p++ = CHAR_COLON;
        ConvertIntToDecimalStringN(p, c->minutes > 59 ? 59 : c->minutes, STR_CONV_MODE_LEADING_ZEROS, 2);
        InfoRow(22, 104, 166, Ascii("TIME"), buf);
        FillRect(22, 121, 166, 1, C_LINE);
        RoundBox(202, 62, 96, 66, 6, C8(232, 238, 250), C_LINE);
        DrawPic(TRUE, c->pic, 0, 0, 218, 63);
        Text(FONT_SMALL, Ascii("BADGES"), 22, 128, C_BAND, C_CARD, TRUE);
        for (int i = 0; i < 8; i++)
        {
            int x = 22 + i * 35 + 15, y = 165;

            Disc(x, y, 15, C_LINE);
            Disc(x, y, 14, C_PAGE);
            if (c->hasBadge[i] && c->badgeTiles)
            {
                u16 pal[16];
                const u16 *src = gPlttBufferUnfaded + 3 * 16;

                for (int k = 0; k < 16; k++)
                    pal[k] = sLut[src[k] & 0x7FFF];
                DrawTile4(c->badgeTiles + i * 2 * 32, x - 8, y - 8, pal, FALSE, FALSE);
                DrawTile4(c->badgeTiles + (i * 2 + 1) * 32, x, y - 8, pal, FALSE, FALSE);
                DrawTile4(c->badgeTiles + (16 + i * 2) * 32, x - 8, y, pal, FALSE, FALSE);
                DrawTile4(c->badgeTiles + (17 + i * 2) * 32, x, y, pal, FALSE, FALSE);
            }
        }
    }
    else
    {
        int y = 64;

        if (c->hasHof)
        {
            p = ConvertIntToDecimalStringN(buf, c->hofHours, STR_CONV_MODE_LEFT_ALIGN, 3);
            *p++ = CHAR_COLON;
            p = ConvertIntToDecimalStringN(p, c->hofMinutes, STR_CONV_MODE_LEADING_ZEROS, 2);
            *p++ = CHAR_COLON;
            ConvertIntToDecimalStringN(p, c->hofSeconds, STR_CONV_MODE_LEADING_ZEROS, 2);
            InfoRow(22, y, 276, Ascii("HALL OF FAME DEBUT"), buf);
            y += 20;
        }
        if (c->hasLink)
        {
            p = ConvertIntToDecimalStringN(buf, c->wins, STR_CONV_MODE_LEFT_ALIGN, 4);
            *p++ = CHAR_HYPHEN;
            ConvertIntToDecimalStringN(p, c->losses, STR_CONV_MODE_LEFT_ALIGN, 4);
            InfoRow(22, y, 276, Ascii("LINK BATTLES"), buf);
            y += 20;
        }
        if (c->hasTrades)
        {
            ConvertIntToDecimalStringN(buf, c->trades, STR_CONV_MODE_LEFT_ALIGN, 5);
            InfoRow(22, y, 276, Ascii("TRADES"), buf);
            y += 20;
        }
        if (c->unionRoom)
        {
            ConvertIntToDecimalStringN(buf, c->unionRoom, STR_CONV_MODE_LEFT_ALIGN, 5);
            InfoRow(22, y, 276, Ascii("UNION ROOM"), buf);
            y += 20;
        }
        if (c->berryCrush)
        {
            ConvertIntToDecimalStringN(buf, c->berryCrush, STR_CONV_MODE_LEFT_ALIGN, 5);
            InfoRow(22, y, 276, Ascii("BERRY CRUSH"), buf);
            y += 20;
        }
        if (y == 64)
            TextCentered(FONT_SMALL, Ascii("No records yet."), W / 2, 90, C_MUTED, C_CARD);
        for (int i = 0; i < PARTY_SIZE; i++)
            if (c->monSpecies[i] != SPECIES_NONE)
            {
                MonView m = { .iconSpecies = c->monSpecies[i] };

                DrawMonIcon(&m, 24 + i * 46, 164);
            }
    }
    Footer();
    BackKey(v->pressed == PAGE_HIT_BACK);
    FootKeyN(0, 1, Ascii("FLIP"), FALSE, v->pressed == PAGE_HIT_FOOT);
}

/* The Pokédex: its lists on the left, a mon's details on the right. */
#define DEX_ROWS 7
#define DEX_ROW_Y 33
#define DEX_ROW_H 24
#define DEX_LIST_W 176
#define DEX_RAIL_X 174
#define DEX_PANE_X 186
#define DEX_PANE_W 128

static void DexHeight(u8 *buf, int natNum, bool8 caught)
{
    u8 *p = buf;

    if (caught)
    {
        u32 inches = 10000 * Port_DexEntry(natNum)->height / 254, feet;

        if (inches % 10 >= 5)
            inches += 10;
        feet = inches / 120;
        inches = (inches - feet * 120) / 10;
        p = ConvertIntToDecimalStringN(p, feet, STR_CONV_MODE_LEFT_ALIGN, 2);
        *p++ = CHAR_SGL_QUOTE_RIGHT;
        p = ConvertIntToDecimalStringN(p, inches, STR_CONV_MODE_LEADING_ZEROS, 2);
    }
    else
    {
        *p++ = CHAR_QUESTION_MARK;
        *p++ = CHAR_QUESTION_MARK;
        *p++ = CHAR_SGL_QUOTE_RIGHT;
        *p++ = CHAR_QUESTION_MARK;
        *p++ = CHAR_QUESTION_MARK;
    }
    *p++ = CHAR_DBL_QUOTE_RIGHT;
    *p = EOS;
}

static void DexWeight(u8 *buf, int natNum, bool8 caught)
{
    u8 *p = buf;

    if (caught)
    {
        u32 lbs = Port_DexEntry(natNum)->weight * 100000 / 4536;

        if (lbs % 10 >= 5)
            lbs += 10;
        p = ConvertIntToDecimalStringN(p, lbs / 100, STR_CONV_MODE_LEFT_ALIGN, 4);
        *p++ = CHAR_PERIOD;
        *p++ = CHAR_0 + (lbs / 10) % 10;
    }
    else
    {
        p = StringCopy(p, Ascii("????"));
        *p++ = CHAR_PERIOD;
        *p++ = CHAR_QUESTION_MARK;
    }
    *p++ = CHAR_SPACE;
    StringCopy(p, gText_Lbs);
}

/* A mon's details in a column x..x+w from y: its name, kind, types, size. */
static void DrawDexDetails(u16 species, bool8 caught, int x, int y, int w, u16 ground)
{
    int natNum = SpeciesToNationalPokedexNum(species);
    u8 buf[32];

    TextCentered(FONT_SMALL, gSpeciesNames[species], x + w / 2, y, C_TEXT, C_TEXT_SH);
    if (caught)
    {
        u8 *p = StringCopy(buf, Port_DexEntry(natNum)->categoryName);

        *p++ = CHAR_SPACE;
        StringCopy(p, gText_MenuPokemon);
    }
    else
        StringCopy(buf, Ascii("?????"));
    TextCentered(FONT_SMALL, buf, x + w / 2, y + 14, C_MUTED, ground);
    if (caught)
    {
        u8 a = gSpeciesInfo[species].types[0], b = gSpeciesInfo[species].types[1];

        if (a == b)
            TypeChip(x + w / 2 - 26, y + 32, 52, a);
        else
        {
            TypeChip(x + w / 2 - 52, y + 32, 50, a);
            TypeChip(x + w / 2 + 2, y + 32, 50, b);
        }
    }
    DexHeight(buf, natNum, caught);
    Text(FONT_SMALL, gText_HT, x + 8, y + 50, C_MUTED, ground, TRUE);
    Text(FONT_SMALL, buf, x + 30, y + 50, C_TEXT, ground, TRUE);
    DexWeight(buf, natNum, caught);
    Text(FONT_SMALL, gText_WT, x + 8, y + 65, C_MUTED, ground, TRUE);
    Text(FONT_SMALL, buf, x + 30, y + 65, C_TEXT, ground, TRUE);
}

static void DrawDexRail(int count, int top)
{
    int h = count > DEX_ROWS ? 160 * DEX_ROWS / count : 160;
    int y = DEX_ROW_Y + 2 + (count > DEX_ROWS ? (160 - h) * top / (count - DEX_ROWS) : 0);

    if (h < 12)
        h = 12;
    RoundRect(DEX_RAIL_X, DEX_ROW_Y + 2, 5, 160, 2, C_LINE);
    RoundRect(DEX_RAIL_X, y, 5, h, 2, C_FLAT);
}

static void DrawDexList(const PageView *v)
{
    const struct PortDexView *d = &v->dex;

    RoundBox(LIST_X, 31, DEX_LIST_W, 173, 6, C_CARD, C_LINE);
    for (int i = 0; i < DEX_ROWS; i++)
    {
        int index = v->top + i, y = DEX_ROW_Y + i * DEX_ROW_H;
        u32 item;
        u16 species;
        bool8 seen, caught;

        if (index >= d->count)
            break;
        item = d->items[index].index;
        if (d->mode == PORT_DEX_TOP)
        {
            bool8 locked = item < 32 && item < 9 && !(d->unlocked & (1u << item));

            if (item == (u32)LIST_HEADER)
            {
                RoundRect(9, y + 2, DEX_LIST_W - 22, DEX_ROW_H - 4, 4, C_BAND);
                Text(FONT_SMALL, d->items[index].label, 14, y + 3, C_WHITE, C_BAND_DK, TRUE);
                continue;
            }
            if (index == d->cursor || v->pressed == PAGE_HIT_ROW + i)
                RoundBox(9, y, DEX_LIST_W - 16, DEX_ROW_H - 1, 5, C_PRESSED, C_FLAT);
            Text(FONT_SMALL, d->items[index].label, 16, y + 4, locked ? C_OFF : C_TEXT, locked ? C_CARD : C_TEXT_SH, TRUE);
            continue;
        }
        species = item & 0xFFFF;
        seen = (item >> 16) & 1;
        caught = (item >> 17) & 1;
        if (index == d->cursor || v->pressed == PAGE_HIT_ROW + i)
            RoundBox(9, y, DEX_LIST_W - 16, DEX_ROW_H - 1, 5, C_PRESSED, C_FLAT);
        else if (i)
            FillRect(13, y, DEX_LIST_W - 22, 1, C_LINE);
        {
            u8 no[8];

            ConvertIntToDecimalStringN(no, SpeciesToNationalPokedexNum(species), STR_CONV_MODE_LEADING_ZEROS, 3);
            Text(FONT_SMALL, no, 14, y + 4, C_MUTED, C_CARD, TRUE);
        }
        if (caught)
        {
            Disc(40, y + 11, 5, C_INK);
            Disc(40, y + 11, 4, C_WHITE);
            for (int dy = -4; dy < 0; dy++)
                for (int dx = -4; dx <= 4; dx++)
                    if (dx * dx + dy * dy <= 18)
                        Put(40 + dx, y + 11 + dy, C_BRIGHTRED);
            FillRect(36, y + 11, 9, 1, C_INK);
        }
        Text(FONT_SMALL, d->items[index].label, 50, y + 4, seen ? C_TEXT : C_OFF, seen ? C_TEXT_SH : C_CARD, TRUE);
    }
    DrawDexRail(d->count, v->top);
}

static void DrawDexBase(const PageView *v)
{
    const struct PortDexView *d = &v->dex;
    u8 buf[24], *p;

    Header(gText_MenuPokedex);
    FillRect(0, HEADER_H, W, FOOTER_Y - HEADER_H, C_PAGE);
    if (d->mode == PORT_DEX_ENTRY)
    {
        bool8 caught = GetSetPokedexFlag(SpeciesToNationalPokedexNum(d->species), FLAG_GET_CAUGHT);
        u16 tint = Lighter(TypeColour(gSpeciesInfo[d->species].types[0]), 6);

        RoundBox(LIST_X, 31, 104, 112, 6, tint, C_LINE);
        DrawPic(FALSE, d->species, 0, 0, 26, 40);
        ConvertIntToDecimalStringN(buf, SpeciesToNationalPokedexNum(d->species), STR_CONV_MODE_LEADING_ZEROS, 3);
        Text(FONT_SMALL, buf, 12, 33, C_MUTED, tint, TRUE);
        RoundBox(114, 31, 200, 112, 6, C_CARD, C_LINE);
        DrawDexDetails(d->species, caught, 114, 36, 200, C_CARD);
        RoundRect(LIST_X, 147, LIST_W, 57, 6, C_SLATE);
        TextLines(FONT_SMALL, caught ? Port_DexEntry(SpeciesToNationalPokedexNum(d->species))->description : Ascii("Catch it to learn more."),
                  14, 148, 13, C_WHITE, C_SLATE);
        Footer();
        BackKey(v->pressed == PAGE_HIT_BACK);
        FootKeyN(0, 4, Ascii("AREA"), FALSE, v->pressed == PAGE_HIT_FOOT);
        FootKeyN(1, 4, Ascii("CRY"), FALSE, v->pressed == PAGE_HIT_FOOT + 1);
        FootKeyN(2, 4, Ascii("PREV"), FALSE, v->pressed == PAGE_HIT_FOOT + 2);
        FootKeyN(3, 4, Ascii("NEXT"), FALSE, v->pressed == PAGE_HIT_FOOT + 3);
        return;
    }
    DrawDexList(v);
    RoundBox(DEX_PANE_X, 31, DEX_PANE_W, 173, 6, C_CARD, C_LINE);
    if (d->mode == PORT_DEX_TOP)
    {
        DrawUiIcon(&sIconDex26, DEX_PANE_X + (DEX_PANE_W - 26) / 2, 38, TRUE);
        Text(FONT_SMALL, Ascii("KANTO"), DEX_PANE_X + 10, 70, C_BAND, C_CARD, TRUE);
        ConvertIntToDecimalStringN(buf, d->seenKanto, STR_CONV_MODE_LEFT_ALIGN, 3);
        InfoRow(DEX_PANE_X + 10, 86, DEX_PANE_W - 20, Ascii("SEEN"), buf);
        ConvertIntToDecimalStringN(buf, d->ownedKanto, STR_CONV_MODE_LEFT_ALIGN, 3);
        InfoRow(DEX_PANE_X + 10, 102, DEX_PANE_W - 20, Ascii("OWN"), buf);
        if (d->national)
        {
            Text(FONT_SMALL, Ascii("NATIONAL"), DEX_PANE_X + 10, 126, C_BAND, C_CARD, TRUE);
            ConvertIntToDecimalStringN(buf, d->seenNational, STR_CONV_MODE_LEFT_ALIGN, 3);
            InfoRow(DEX_PANE_X + 10, 142, DEX_PANE_W - 20, Ascii("SEEN"), buf);
            ConvertIntToDecimalStringN(buf, d->ownedNational, STR_CONV_MODE_LEFT_ALIGN, 3);
            InfoRow(DEX_PANE_X + 10, 158, DEX_PANE_W - 20, Ascii("OWN"), buf);
        }
    }
    else if (d->cursor < d->count)
    {
        u32 item = d->items[d->cursor].index;
        u16 species = item & 0xFFFF;
        bool8 seen = (item >> 16) & 1, caught = (item >> 17) & 1;

        if (seen)
        {
            DrawPic(FALSE, species, 0, 0, DEX_PANE_X + (DEX_PANE_W - 64) / 2, 34);
            DrawDexDetails(species, caught, DEX_PANE_X, 102, DEX_PANE_W, C_CARD);
        }
        else
        {
            EmptyBall(DEX_PANE_X + DEX_PANE_W / 2, 90, 24);
            TextCentered(FONT_SMALL, Ascii("Not seen yet"), DEX_PANE_X + DEX_PANE_W / 2, 124, C_MUTED, C_CARD);
        }
    }
    Footer();
    BackKey(v->pressed == PAGE_HIT_BACK);
    p = StringCopy(buf, Ascii("SEEN "));
    p = ConvertIntToDecimalStringN(p, d->national ? d->seenNational : d->seenKanto, STR_CONV_MODE_LEFT_ALIGN, 3);
    p = StringCopy(p, Ascii("   OWN "));
    ConvertIntToDecimalStringN(p, d->national ? d->ownedNational : d->ownedKanto, STR_CONV_MODE_LEFT_ALIGN, 3);
    Text(FONT_SMALL, buf, 10, BACK_Y + 4, C_WHITE, C_SLATE, TRUE);
}

static u8 SummaryHitTest(const PageView *v, int x, int y)
{
    const struct PortSummaryView *s = &v->sum;
    int page = s->page > PSS_PAGE_MOVES ? PSS_PAGE_MOVES : s->page;

    if (y >= FOOTER_Y)
        return FootHit(x, s->selecting ? 1 : 2);
    if (y >= TAB_Y && y < SUM_CARD_Y)
    {
        int t = (x - TAB_X) / TAB_W;

        return x >= TAB_X && t < (s->isEgg ? 1 : 3) ? PAGE_HIT_POCKET + t : HIT_NONE;
    }
    if (page == PSS_PAGE_MOVES && x > SUM_DIVIDER_X && y >= SUM_MOVE_Y)
    {
        int row = (y - SUM_MOVE_Y) / SUM_MOVE_H;

        if (row < 4 ? s->moveIds[row] != MOVE_NONE : row == 4 && s->selecting)
            return PAGE_HIT_MOVE + row;
    }
    return HIT_NONE;
}

static u8 DexHitTest(const PageView *v, int x, int y)
{
    const struct PortDexView *d = &v->dex;

    if (d->mode == PORT_DEX_ENTRY)
        return y >= FOOTER_Y ? FootHit(x, 4) : HIT_NONE;
    if (y >= FOOTER_Y || x >= LIST_X + DEX_LIST_W)
        return HIT_NONE;
    if (x >= DEX_RAIL_X - 6 && d->count > DEX_ROWS)
        return PAGE_HIT_RAIL;
    if (y >= DEX_ROW_Y && y < DEX_ROW_Y + DEX_ROWS * DEX_ROW_H)
    {
        int i = (y - DEX_ROW_Y) / DEX_ROW_H;

        if (v->top + i < d->count && d->items[v->top + i].index != (u32)LIST_HEADER)
            return PAGE_HIT_ROW + i;
    }
    return HIT_NONE;
}

static void SummaryActivate(const PageView *v, u8 hit)
{
    const struct PortSummaryView *s = &v->sum;

    if (hit >= PAGE_HIT_POCKET && hit < PAGE_HIT_POCKET + 3)
    {
        sWantPage = hit - PAGE_HIT_POCKET;
        sWantTries = 0;
    }
    else if (hit >= PAGE_HIT_MOVE && hit < PAGE_HIT_MOVE + 5)
    {
        int row = hit - PAGE_HIT_MOVE;

        if (!s->selecting)
        {
            /* the game opens the cursor; PageFrame then puts it on this move */
            sWantMove = row;
            Inject(A_BUTTON);
        }
        else if (row == 4 && s->moveIds[4] == MOVE_NONE)
            Inject(B_BUTTON);
        else
            Port_SummarySetMoveCursor(row);
    }
    else if (hit == PAGE_HIT_FOOT)
        Inject(s->selecting ? A_BUTTON : DPAD_UP);
    else if (hit == PAGE_HIT_FOOT + 1)
        Inject(DPAD_DOWN);
}

static void DexActivate(const PageView *v, u8 hit)
{
    if (hit >= PAGE_HIT_ROW && hit < PAGE_HIT_ROW + DEX_ROWS)
    {
        Port_ListSetCursor(v->dex.listTask, v->top + hit - PAGE_HIT_ROW);
        Inject(A_BUTTON);
    }
    else if (hit >= PAGE_HIT_FOOT && hit < PAGE_HIT_FOOT + 4)
    {
        static const u16 keys[4] = { A_BUTTON, START_BUTTON, DPAD_UP, DPAD_DOWN };

        Inject(keys[hit - PAGE_HIT_FOOT]);
    }
}

/* The PC's boxes: the mon under the cursor and the party on the left, the box's
 * thirty places on the right. A tap on a place walks the game's cursor there
 * (the party opened or closed on the way, as the game asks) and presses A. */
#define BOX_CELL_W 33
#define BOX_CELL_H 30
#define BOX_GRID_X 116
#define BOX_GRID_Y 53
#define BOX_BAR_Y 29
#define BOX_BAR_H 22
#define BOX_ARROW_W 30
#define BOX_LEFT_X 6
#define BOX_LEFT_W 106
#define BOX_PARTY_Y 122
#define BOX_PARTY_W 35
#define BOX_PARTY_H 41

typedef struct { u16 iconSpecies, item; } BoxCell;

/* What the box and the party hold, read again when their bytes change. */
static BoxCell sBoxCells[IN_BOX_COUNT], sBoxParty[PARTY_SIZE];
static u32 sBoxCellsSig;
static bool8 sBoxCellsValid;
/* Where a tap wants the cursor, and the key to press there. */
static s8 sBoxWantArea = -1, sBoxWantPos;
static u16 sBoxWantKey;
static u16 sBoxWantAge;

static void ReadBoxCells(void)
{
    u8 box = StorageGetCurrentBox();

    for (int i = 0; i < IN_BOX_COUNT; i++)
    {
        struct BoxPokemon *mon = GetBoxedMonPtr(box, i);
        u16 species = GetBoxMonData(mon, MON_DATA_SPECIES_OR_EGG);

        sBoxCells[i].iconSpecies = species == SPECIES_NONE ? SPECIES_NONE : GetIconSpecies(species, GetBoxMonData(mon, MON_DATA_PERSONALITY));
        sBoxCells[i].item = species == SPECIES_NONE ? ITEM_NONE : GetBoxMonData(mon, MON_DATA_HELD_ITEM);
    }
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        u16 species = GetMonData(&gPlayerParty[i], MON_DATA_SPECIES_OR_EGG);

        sBoxParty[i].iconSpecies = species == SPECIES_NONE ? SPECIES_NONE : GetIconSpecies(species, GetMonData(&gPlayerParty[i], MON_DATA_PERSONALITY));
        sBoxParty[i].item = species == SPECIES_NONE ? ITEM_NONE : GetMonData(&gPlayerParty[i], MON_DATA_HELD_ITEM);
    }
}

static u32 BoxBytesSig(void)
{
    const u8 *box = (const u8 *)GetBoxedMonPtr(StorageGetCurrentBox(), 0);
    const u8 *party = (const u8 *)gPlayerParty;
    u32 h = StorageGetCurrentBox();

    for (unsigned i = 0; i < IN_BOX_COUNT * sizeof(struct BoxPokemon); i++)
        h = h * 33 + box[i];
    for (unsigned i = 0; i < sizeof(struct Pokemon) * PARTY_SIZE; i++)
        h = h * 33 + party[i];
    return h;
}

static void BoxCellRect(int i, int *x, int *y)
{
    *x = BOX_GRID_X + (i % IN_BOX_COLUMNS) * BOX_CELL_W;
    *y = BOX_GRID_Y + (i / IN_BOX_COLUMNS) * BOX_CELL_H;
}

static void BoxPartyRect(int i, int *x, int *y)
{
    *x = BOX_LEFT_X + (i % 3) * (BOX_PARTY_W + 1);
    *y = BOX_PARTY_Y + (i / 3) * BOX_PARTY_H;
}

static void DrawBoxIcon(const BoxCell *c, int x, int y)
{
    MonView m = { .iconSpecies = c->iconSpecies };

    DrawMonIcon(&m, x, y);
    if (c->item != ITEM_NONE)
    {
        Disc(x + 27, y + 25, 4, C_BAND_DK);
        Disc(x + 27, y + 25, 3, C_GOLD);
    }
}

static int BoxMonCount(u8 box)
{
    int n = 0;

    for (int i = 0; i < IN_BOX_COUNT; i++)
        n += GetBoxMonDataAt(box, i, MON_DATA_SPECIES) != SPECIES_NONE;
    return n;
}

static void DrawStorageBase(const PageView *v)
{
    const struct PortStorageView *b = &v->box;
    u8 count[8], *p;

    Header(Ascii("PC BOXES"));
    FillRect(0, HEADER_H, W, FOOTER_Y - HEADER_H, C_PAGE);
    /* the mon under the cursor, or carried */
    RoundBox(BOX_LEFT_X, BOX_BAR_Y, BOX_LEFT_W, 91, 6, C_CARD, C_LINE);
    if (b->species != SPECIES_NONE)
    {
        DrawPicWithPal(b->species, b->personality, b->pal, BOX_LEFT_X + (BOX_LEFT_W - 64) / 2, BOX_BAR_Y - 1);
        Text(FONT_SMALL, b->nickname, BOX_LEFT_X + 5, BOX_BAR_Y + 63, C_TEXT, C_TEXT_SH, TRUE);
        Text(FONT_SMALL, b->itemMode ? b->itemName : b->genderLevel, BOX_LEFT_X + 5, BOX_BAR_Y + 75, b->itemMode ? C_BAND : C_MUTED, C_CARD, TRUE);
    }
    else
        EmptyBall(BOX_LEFT_X + BOX_LEFT_W / 2, BOX_BAR_Y + 40, 20);
    /* the party */
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        int x, y;
        bool8 cursor = b->area == CURSOR_AREA_IN_PARTY && b->pos == i;

        BoxPartyRect(i, &x, &y);
        RoundBox(x, y, BOX_PARTY_W, BOX_PARTY_H - 1, 5, cursor || v->pressed == PAGE_HIT_BOX_PARTY + i ? C_PRESSED : sBoxParty[i].iconSpecies ? C_CARD : C_EMPTY, cursor ? C_FLAT : C_LINE);
        if (sBoxParty[i].iconSpecies)
            DrawBoxIcon(&sBoxParty[i], x + 1, y + 3);
        else
            EmptyBall(x + BOX_PARTY_W / 2, y + BOX_PARTY_H / 2, 6);
    }
    /* the box's name, its count, the arrows to the others */
    RoundRect(BOX_GRID_X, BOX_BAR_Y, IN_BOX_COLUMNS * BOX_CELL_W, BOX_BAR_H, 6, b->area == CURSOR_AREA_BOX_TITLE || v->pressed == PAGE_HIT_BOX_TITLE ? C_BAND : C_FLAT);
    RoundRect(BOX_GRID_X, BOX_BAR_Y, BOX_ARROW_W, BOX_BAR_H, 6, v->pressed == PAGE_HIT_BOX_LEFT ? C_BAND_DK : C_BAND);
    RoundRect(BOX_GRID_X + IN_BOX_COLUMNS * BOX_CELL_W - BOX_ARROW_W, BOX_BAR_Y, BOX_ARROW_W, BOX_BAR_H, 6, v->pressed == PAGE_HIT_BOX_RIGHT ? C_BAND_DK : C_BAND);
    Arrow(BOX_GRID_X + BOX_ARROW_W / 2, BOX_BAR_Y + BOX_BAR_H / 2, TRUE, C_WHITE);
    Arrow(BOX_GRID_X + IN_BOX_COLUMNS * BOX_CELL_W - BOX_ARROW_W / 2, BOX_BAR_Y + BOX_BAR_H / 2, FALSE, C_WHITE);
    Text(FONT_SMALL, GetBoxNamePtr(b->currentBox), BOX_GRID_X + BOX_ARROW_W + 6, BOX_BAR_Y + 3, C_WHITE, C_BAND_DK, TRUE);
    p = ConvertIntToDecimalStringN(count, BoxMonCount(b->currentBox), STR_CONV_MODE_LEFT_ALIGN, 2);
    *p++ = CHAR_SLASH;
    ConvertIntToDecimalStringN(p, IN_BOX_COUNT, STR_CONV_MODE_LEFT_ALIGN, 2);
    TextRight(FONT_SMALL, count, BOX_GRID_X + IN_BOX_COLUMNS * BOX_CELL_W - BOX_ARROW_W - 6, BOX_BAR_Y + 3, C_WHITE, C_BAND_DK);
    /* the thirty places */
    RoundBox(BOX_GRID_X - 1, BOX_GRID_Y - 1, IN_BOX_COLUMNS * BOX_CELL_W + 2, IN_BOX_ROWS * BOX_CELL_H + 2, 4, C_CARD, C_LINE);
    for (int i = 1; i < IN_BOX_COLUMNS; i++)
        FillRect(BOX_GRID_X + i * BOX_CELL_W, BOX_GRID_Y, 1, IN_BOX_ROWS * BOX_CELL_H, C_EMPTY);
    for (int i = 1; i < IN_BOX_ROWS; i++)
        FillRect(BOX_GRID_X, BOX_GRID_Y + i * BOX_CELL_H, IN_BOX_COLUMNS * BOX_CELL_W, 1, C_EMPTY);
    for (int i = 0; i < IN_BOX_COUNT; i++)
    {
        int x, y;
        bool8 cursor = b->area == CURSOR_AREA_IN_BOX && b->pos == i;

        BoxCellRect(i, &x, &y);
        if (cursor || v->pressed == PAGE_HIT_BOX_CELL + i)
            RoundBox(x, y, BOX_CELL_W, BOX_CELL_H, 5, C_PRESSED, C_FLAT);
        if (sBoxCells[i].iconSpecies)
            DrawBoxIcon(&sBoxCells[i], x, y - 3);
    }
    /* what the hand carries, over the place it is at */
    if (b->holding && b->species != SPECIES_NONE)
    {
        BoxCell held = { GetIconSpecies(b->species, b->personality), ITEM_NONE };
        int x = BOX_GRID_X, y = BOX_GRID_Y;

        if (b->area == CURSOR_AREA_IN_BOX)
            BoxCellRect(b->pos, &x, &y);
        else if (b->area == CURSOR_AREA_IN_PARTY && b->pos < PARTY_SIZE)
            BoxPartyRect(b->pos, &x, &y);
        DrawBoxIcon(&held, x - 3, y - 12);
    }
    if (b->movingItem != ITEM_NONE)
    {
        int x = BOX_GRID_X, y = BOX_GRID_Y;

        if (b->area == CURSOR_AREA_IN_BOX)
            BoxCellRect(b->pos, &x, &y);
        else if (b->area == CURSOR_AREA_IN_PARTY && b->pos < PARTY_SIZE)
            BoxPartyRect(b->pos, &x, &y);
        DrawItemIcon(b->movingItem, x + 4, y - 12);
    }
    Footer();
    BackKey(v->pressed == PAGE_HIT_BACK);
    if (v->cardCount || b->numMenu || b->chooseBox)
        DimCanvas();
    if (b->numMenu)
    {
        RoundBox(SHEET_X, SHEET_Y, SHEET_W, SHEET_H, 8, C_CARD, C_FLAT);
        for (int i = 0; i < b->numMenu; i++)
        {
            int x, y, w, h;

            SheetKeyRect(b->numMenu, i, &x, &y, &w, &h);
            TextKey(x, y, w, h, b->menuText[i], i == Menu_GetCursorPos(), v->pressed == PAGE_HIT_ACTION + i);
        }
    }
    if (b->chooseBox)
    {
        u8 *q;

        RoundBox(SHEET_X, SHEET_Y + 20, SHEET_W, SHEET_H - 20, 8, C_CARD, C_FLAT);
        TextKey(SHEET_X + 8, SHEET_Y + 30, 60, 38, Ascii(""), FALSE, v->pressed == PAGE_HIT_BOX_CHOOSE);
        Arrow(SHEET_X + 38, SHEET_Y + 49, TRUE, C_FLAT);
        TextKey(SHEET_X + 72, SHEET_Y + 30, SHEET_W - 144, 38, Ascii(""), TRUE, v->pressed == PAGE_HIT_BOX_CHOOSE + 1);
        TextCentered(FONT_SMALL, GetBoxNamePtr(b->chooseCurrent), W / 2, SHEET_Y + 32, C_WHITE, C_BAND_DK);
        q = ConvertIntToDecimalStringN(count, BoxMonCount(b->chooseCurrent), STR_CONV_MODE_LEFT_ALIGN, 2);
        *q++ = CHAR_SLASH;
        ConvertIntToDecimalStringN(q, IN_BOX_COUNT, STR_CONV_MODE_LEFT_ALIGN, 2);
        TextCentered(FONT_SMALL, count, W / 2, SHEET_Y + 48, C_WHITE, C_BAND_DK);
        TextKey(SHEET_X + SHEET_W - 68, SHEET_Y + 30, 60, 38, Ascii(""), FALSE, v->pressed == PAGE_HIT_BOX_CHOOSE + 2);
        Arrow(SHEET_X + SHEET_W - 38, SHEET_Y + 49, FALSE, C_FLAT);
    }
}

/* What keeps changing: the game's message in the footer, its cards. */
static void DrawStorageLive(const PageView *v)
{
    const struct PortStorageView *b = &v->box;

    FillRect(4, FOOTER_Y + 1, BACK_X - 8, FOOTER_H - 1, C_SLATE);
    if (b->numMenu)
    {
        /* a menu's question heads its sheet, by the mon when it is about one */
        bool8 aboutMon = b->area != CURSOR_AREA_BOX_TITLE && b->species != SPECIES_NONE;
        int x = SHEET_X + (aboutMon ? 40 : 10);

        FillRect(SHEET_X + 2, SHEET_Y + 4, SHEET_W - 4, 24, C_CARD);
        if (aboutMon)
        {
            BoxCell c = { GetIconSpecies(b->species, b->personality), ITEM_NONE };

            DrawBoxIcon(&c, SHEET_X + 6, SHEET_Y - 4);
        }
        if (WindowOnScreen(PORT_STORAGE_MESSAGE_WINDOW))
            DrawWindowPixels(PORT_STORAGE_MESSAGE_WINDOW, x, SHEET_Y + 8, TRUE, C_TEXT, C_TEXT_SH);
    }
    else if (WindowOnScreen(PORT_STORAGE_MESSAGE_WINDOW))
        DrawWindowPixels(PORT_STORAGE_MESSAGE_WINDOW, 8, FOOTER_Y + 9, TRUE, C_WHITE, C_SLATE_HI);
    DrawCards(v);
}

static u8 CardHitTest(const PageView *v, int x, int y);

static u8 StorageHitTest(const PageView *v, int x, int y)
{
    const struct PortStorageView *b = &v->box;

    if (v->cardCount)
    {
        u8 hit = CardHitTest(v, x, y);
        bool8 menuUp = FALSE;

        for (int i = 0; i < v->cardCount; i++)
            menuUp |= v->cards[i] == Port_YesNoWindow();
        return hit != HIT_NONE || menuUp ? hit : PAGE_HIT_DIALOG;
    }
    if (b->chooseBox)
    {
        if (y < SHEET_Y + 30 || y >= SHEET_Y + 68)
            return HIT_NONE;
        return PAGE_HIT_BOX_CHOOSE + (x < SHEET_X + 72 ? 0 : x < SHEET_X + SHEET_W - 72 ? 1 : 2);
    }
    if (b->numMenu)
    {
        for (int i = 0; i < b->numMenu; i++)
        {
            int bx, by, bw, bh;

            SheetKeyRect(b->numMenu, i, &bx, &by, &bw, &bh);
            if (x >= bx && x < bx + bw && y >= by && y < by + bh)
                return PAGE_HIT_ACTION + i;
        }
        return HIT_NONE;
    }
    /* the game waiting on a message of its own */
    if (!b->ready)
        return PAGE_HIT_DIALOG;
    if (y >= FOOTER_Y)
        return HIT_NONE;
    if (x >= BOX_GRID_X)
    {
        if (y < BOX_GRID_Y)
            return x < BOX_GRID_X + BOX_ARROW_W ? PAGE_HIT_BOX_LEFT : x >= BOX_GRID_X + IN_BOX_COLUMNS * BOX_CELL_W - BOX_ARROW_W ? PAGE_HIT_BOX_RIGHT : PAGE_HIT_BOX_TITLE;
        {
            int col = (x - BOX_GRID_X) / BOX_CELL_W, row = (y - BOX_GRID_Y) / BOX_CELL_H;

            return col < IN_BOX_COLUMNS && row < IN_BOX_ROWS ? PAGE_HIT_BOX_CELL + row * IN_BOX_COLUMNS + col : HIT_NONE;
        }
    }
    if (y >= BOX_PARTY_Y && x >= BOX_LEFT_X)
    {
        int col = (x - BOX_LEFT_X) / (BOX_PARTY_W + 1), row = (y - BOX_PARTY_Y) / BOX_PARTY_H;

        return col < 3 && row < 2 ? PAGE_HIT_BOX_PARTY + row * 3 + col : HIT_NONE;
    }
    return HIT_NONE;
}

static void StorageWant(s8 area, s8 pos, u16 key)
{
    sBoxWantArea = area;
    sBoxWantPos = pos;
    sBoxWantKey = key;
    sBoxWantAge = 0;
}

static void StorageActivate(const PageView *v, u8 hit)
{
    if (hit >= PAGE_HIT_MENU && hit < PAGE_HIT_DIALOG)
    {
        Port_MenuSetCursor(hit - PAGE_HIT_MENU);
        Inject(A_BUTTON);
    }
    else if (hit == PAGE_HIT_DIALOG)
        Inject(A_BUTTON);
    else if (hit >= PAGE_HIT_ACTION && hit < PAGE_HIT_ACTION + PORT_MENU_MAX_ACTIONS)
    {
        Port_MenuSetCursor(hit - PAGE_HIT_ACTION);
        Inject(A_BUTTON);
    }
    else if (hit >= PAGE_HIT_BOX_CHOOSE && hit < PAGE_HIT_BOX_CHOOSE + 3)
        Inject(hit == PAGE_HIT_BOX_CHOOSE ? DPAD_LEFT : hit == PAGE_HIT_BOX_CHOOSE + 1 ? A_BUTTON : DPAD_RIGHT);
    else if (hit >= PAGE_HIT_BOX_CELL && hit < PAGE_HIT_BOX_CELL + IN_BOX_COUNT)
        StorageWant(CURSOR_AREA_IN_BOX, hit - PAGE_HIT_BOX_CELL, A_BUTTON);
    else if (hit >= PAGE_HIT_BOX_PARTY && hit < PAGE_HIT_BOX_PARTY + PARTY_SIZE)
    {
        if (sBoxParty[hit - PAGE_HIT_BOX_PARTY].iconSpecies || v->box.holding)
            StorageWant(CURSOR_AREA_IN_PARTY, hit - PAGE_HIT_BOX_PARTY, A_BUTTON);
    }
    else if (hit == PAGE_HIT_BOX_TITLE)
        StorageWant(CURSOR_AREA_BOX_TITLE, 0, A_BUTTON);
    else if (hit == PAGE_HIT_BOX_LEFT)
        StorageWant(CURSOR_AREA_BOX_TITLE, 0, DPAD_LEFT);
    else if (hit == PAGE_HIT_BOX_RIGHT)
        StorageWant(CURSOR_AREA_BOX_TITLE, 0, DPAD_RIGHT);
}

/* One step of the way to where a tap wants the cursor, while the game takes one. */
static void StorageWalk(const struct PortStorageView *b)
{
    if (sBoxWantArea < 0)
        return;
    if (++sBoxWantAge > 300)
    {
        sBoxWantArea = -1;
        return;
    }
    if (!b->ready || sInjectFrames != 0)
        return;
    if (b->area == sBoxWantArea && b->pos == sBoxWantPos)
    {
        Inject(sBoxWantKey);
        sBoxWantArea = -1;
    }
    else if (sBoxWantArea == CURSOR_AREA_IN_PARTY)
    {
        if (b->area == CURSOR_AREA_IN_PARTY)
            Port_StorageSetCursor(sBoxWantArea, sBoxWantPos);
        else if (b->option != OPTION_MOVE_MONS && b->option != OPTION_MOVE_ITEMS)
            sBoxWantArea = -1;
        else if (b->area == CURSOR_AREA_BUTTONS && b->pos == 0)
            Inject(A_BUTTON); /* PARTY POKéMON */
        else
            Port_StorageSetCursor(CURSOR_AREA_BUTTONS, 0);
    }
    else if (b->area == CURSOR_AREA_IN_PARTY)
    {
        if (b->option != OPTION_MOVE_MONS && b->option != OPTION_MOVE_ITEMS)
            sBoxWantArea = -1;
        else
            Inject(B_BUTTON); /* the party closes */
    }
    else
        Port_StorageSetCursor(sBoxWantArea, sBoxWantPos);
}

static bool8 SnapshotPage(PageView *v)
{
    memset(v, 0, sizeof(*v));
    v->page = sPage;
    if (sPage == PORT_PAGE_SUMMARY)
        return Port_SummaryGetView(&v->sum);
    if (sPage == PORT_PAGE_STORAGE)
    {
        if (!Port_StorageGetView(&v->box))
            return FALSE;
        v->boxSig = BoxBytesSig();
        if (!sBoxCellsValid || v->boxSig != sBoxCellsSig)
        {
            ReadBoxCells();
            sBoxCellsSig = v->boxSig;
            sBoxCellsValid = TRUE;
        }
        /* a menu up has its sheet; yes or no's old window may be that menu's now */
        if (!v->box.numMenu && !v->box.chooseBox && Port_YesNoWindow() > PORT_STORAGE_LAST_FIXED_WINDOW)
            AddCard(v, Port_YesNoWindow());
        if (!v->box.numMenu && !v->box.chooseBox)
            AddCard(v, PORT_STORAGE_ITEM_INFO_WINDOW);
        return TRUE;
    }
    if (sPage == PORT_PAGE_CARD)
        return Port_CardGetView(&v->card);
    if (sPage == PORT_PAGE_DEX)
    {
        struct PortDexView *d = &v->dex;

        if (!Port_DexGetView(d))
            return FALSE;
        if (d->mode != PORT_DEX_ENTRY)
        {
            int top = sDexTop[d->mode], count = d->count;

            if (d->cursor < top)
                top = d->cursor ? d->cursor : 0;
            if (d->cursor >= top + DEX_ROWS)
                top = d->cursor - DEX_ROWS + 1;
            if (top > count - DEX_ROWS)
                top = count - DEX_ROWS;
            if (top < 0)
                top = 0;
            sDexTop[d->mode] = v->top = top;
        }
        return TRUE;
    }
    if (sPage == PORT_PAGE_PARTY)
    {
        if (!Port_PartyGetView(&v->party))
            return FALSE;
        for (int i = 0; i < PARTY_SIZE; i++)
        {
            struct Pokemon *mon = &gPlayerParty[i];
            PageMon *m = &v->mons[i];

            m->species = GetMonData(mon, MON_DATA_SPECIES);
            if (m->species == SPECIES_NONE)
                continue;
            m->egg = GetMonData(mon, MON_DATA_IS_EGG);
            m->iconSpecies = m->egg ? SPECIES_EGG : GetIconSpecies(m->species, GetMonData(mon, MON_DATA_PERSONALITY));
            m->hp = GetMonData(mon, MON_DATA_HP);
            m->maxHp = GetMonData(mon, MON_DATA_MAX_HP);
            m->level = GetMonData(mon, MON_DATA_LEVEL);
            m->item = GetMonData(mon, MON_DATA_HELD_ITEM);
            m->ailment = GetMonAilment(mon);
            m->gender = GetMonGender(mon);
            GetMonData(mon, MON_DATA_NICKNAME, m->name);
            StringGet_Nickname(m->name);
        }
        if (v->party.mode != PORT_MENU_ACTIONS || v->party.windows[2] != PORT_NO_WINDOW)
            for (int i = 0; i < 3; i++)
                AddCard(v, v->party.windows[i]);
        if (v->party.mode == PORT_MENU_OTHER && Port_YesNoWindow() > PARTY_MESSAGE_WINDOW)
            AddCard(v, Port_YesNoWindow());
        return TRUE;
    }
    if (!Port_BagGetView(&v->bag))
        return FALSE;
    {
        struct PortBagView *b = &v->bag;
        int count = b->nItems + 1, top = sBagTop[b->pocket];

        if (b->cursor < top)
            top = b->cursor;
        if (b->cursor >= top + BAG_ROWS)
            top = b->cursor - BAG_ROWS + 1;
        if (top > count - BAG_ROWS)
            top = count - BAG_ROWS;
        if (top < 0)
            top = 0;
        sBagTop[b->pocket] = v->top = top;
        for (int i = 0; i < BAG_ROWS && top + i < b->nItems; i++)
        {
            v->rowItem[i] = BagGetItemIdByPocketPosition(b->pocket + 1, top + i);
            if (b->pocket != POCKET_KEY_ITEMS - 1 && ItemId_GetImportance(v->rowItem[i]) == 0)
                v->rowQuantity[i] = BagGetQuantityByPocketPosition(b->pocket + 1, top + i);
        }
        v->registered = gSaveBlock1Ptr->registeredItem;
        for (unsigned i = 0; i < ARRAY_COUNT(b->windows); i++)
            AddCard(v, b->windows[i]);
        if (b->mode == PORT_MENU_OTHER && Port_YesNoWindow() > BAG_LAST_FIXED_WINDOW)
            AddCard(v, Port_YesNoWindow());
    }
    return TRUE;
}

/* A tap on a card: on the row of a menu, else one card as a whole. */
static u8 CardHitTest(const PageView *v, int x, int y)
{
    u8 menu = Port_MenuWindow();

    for (int i = v->cardCount - 1; i >= 0; i--)
    {
        int cx, cy, cw, ch;

        WindowCardRect(v->cards[i], &cx, &cy, &cw, &ch);
        if (x < cx - 6 || x >= cx + cw + 6 || y < cy - 5 || y >= cy + ch + 5)
            continue;
        if (v->cards[i] == menu)
        {
            u8 top, rowH, rows;
            int row;

            Port_MenuGeometry(&top, &rowH, &rows);
            row = rowH ? (y - cy - top) / rowH : 0;
            if (row < 0 || y < cy + top)
                row = 0;
            if (row >= rows)
                row = rows - 1;
            return PAGE_HIT_MENU + row;
        }
        return PAGE_HIT_DIALOG;
    }
    return HIT_NONE;
}

static u8 PageHitTest(const PageView *v, int x, int y)
{
    if (y >= FOOTER_Y && x >= BACK_X - 4)
        return PAGE_HIT_BACK;
    if (v->page == PORT_PAGE_SUMMARY)
        return SummaryHitTest(v, x, y);
    if (v->page == PORT_PAGE_CARD)
        return y >= FOOTER_Y ? FootHit(x, 1) : HIT_NONE;
    if (v->page == PORT_PAGE_DEX)
        return DexHitTest(v, x, y);
    if (v->page == PORT_PAGE_STORAGE)
        return StorageHitTest(v, x, y);
    if (v->cardCount)
    {
        u8 hit = CardHitTest(v, x, y);
        bool8 menuUp = FALSE;

        for (int i = 0; i < v->cardCount; i++)
            menuUp |= v->cards[i] == Port_MenuWindow();
        /* a message goes on with a tap anywhere; a menu wants one of its rows */
        if (hit != HIT_NONE || menuUp || (v->page == PORT_PAGE_BAG && v->bag.mode == PORT_MENU_QUANTITY))
            ;
        else
            return PAGE_HIT_DIALOG;
        if (!(v->page == PORT_PAGE_BAG && v->bag.mode == PORT_MENU_QUANTITY))
            return hit;
    }
    if (v->page == PORT_PAGE_PARTY)
    {
        if (v->party.mode == PORT_MENU_ACTIONS)
        {
            for (int i = 0; i < v->party.numActions; i++)
            {
                int bx, by, bw, bh;

                SheetKeyRect(v->party.numActions, i, &bx, &by, &bw, &bh);
                if (x >= bx && x < bx + bw && y >= by && y < by + bh)
                    return PAGE_HIT_ACTION + i;
            }
            return HIT_NONE;
        }
        if (v->party.mode != PORT_MENU_LIST)
            return HIT_NONE;
        if (y >= FOOTER_Y)
            return v->party.chooseMultiple && x >= 6 + 2 * FOOT_KEY_STEP && x < 6 + 2 * FOOT_KEY_STEP + FOOT_KEY_W ? PAGE_HIT_FOOT : HIT_NONE;
        for (int i = 0; i < PARTY_SIZE; i++)
            if (v->mons[i].species != SPECIES_NONE && x >= SLOT_X(i) && x < SLOT_X(i) + SLOT_W && y >= SLOT_Y(i) && y < SLOT_Y(i) + SLOT_H)
                return PAGE_HIT_SLOT + i;
        return HIT_NONE;
    }
    if (y >= FOOTER_Y)
    {
        int i = (x - 6) / FOOT_KEY_STEP;
        int keys = v->bag.mode == PORT_MENU_ACTIONS ? v->bag.numActions : v->bag.mode == PORT_MENU_QUANTITY ? 3 : 0;

        return x >= 6 && i < keys ? PAGE_HIT_FOOT + i : HIT_NONE;
    }
    if (v->bag.mode != PORT_MENU_LIST)
        return HIT_NONE;
    if (x < BAG_LIST_X)
    {
        int i = (y - 30) / BAG_TAB_H;

        return y >= 30 && i < 3 ? PAGE_HIT_POCKET + i : HIT_NONE;
    }
    if (x >= 303 && y < 162 && v->bag.nItems + 1 > BAG_ROWS)
        return y < 96 ? PAGE_HIT_UP : PAGE_HIT_DOWN;
    if (y >= BAG_ROW_Y && y < BAG_ROW_Y + BAG_ROWS * BAG_ROW_H)
    {
        int i = (y - BAG_ROW_Y) / BAG_ROW_H;

        return v->top + i <= v->bag.nItems ? PAGE_HIT_ROW + i : HIT_NONE;
    }
    return HIT_NONE;
}

static void PageActivate(const PageView *v, u8 hit)
{
    /* the card's back closes with A, and B turns it over */
    if (hit == PAGE_HIT_BACK)
        Inject(v->page == PORT_PAGE_CARD && v->card.onBack ? A_BUTTON : B_BUTTON);
    else if (v->page == PORT_PAGE_SUMMARY)
        SummaryActivate(v, hit);
    else if (v->page == PORT_PAGE_CARD)
    {
        if (v->card.ready)
            Inject(v->card.onBack ? B_BUTTON : A_BUTTON);
    }
    else if (v->page == PORT_PAGE_DEX)
        DexActivate(v, hit);
    else if (v->page == PORT_PAGE_STORAGE)
        StorageActivate(v, hit);
    else if (hit >= PAGE_HIT_MENU && hit < PAGE_HIT_DIALOG)
    {
        Port_MenuSetCursor(hit - PAGE_HIT_MENU);
        Inject(A_BUTTON);
    }
    else if (hit == PAGE_HIT_DIALOG)
        Inject(A_BUTTON);
    else if (v->page == PORT_PAGE_PARTY)
    {
        if (hit >= PAGE_HIT_SLOT && hit < PAGE_HIT_SLOT + PARTY_SIZE)
        {
            Port_PartyTapSlot(hit - PAGE_HIT_SLOT);
            Inject(A_BUTTON);
        }
        else if (hit >= PAGE_HIT_ACTION && hit < PAGE_HIT_ACTION + PORT_MENU_MAX_ACTIONS)
        {
            Port_MenuSetCursor(hit - PAGE_HIT_ACTION);
            Inject(A_BUTTON);
        }
        else if (hit == PAGE_HIT_FOOT)
            Inject(v->party.slot == PARTY_SIZE ? A_BUTTON : START_BUTTON);
    }
    else if (hit >= PAGE_HIT_POCKET && hit < PAGE_HIT_POCKET + 3)
    {
        sBagWantPocket = hit - PAGE_HIT_POCKET;
        sBagPocketTries = 0;
    }
    else if (hit >= PAGE_HIT_ROW && hit < PAGE_HIT_ROW + BAG_ROWS)
    {
        Port_BagMoveCursor(v->top + hit - PAGE_HIT_ROW);
        Inject(A_BUTTON);
    }
    else if (hit == PAGE_HIT_UP)
        Port_BagMoveCursor(v->bag.cursor > BAG_ROWS ? v->bag.cursor - BAG_ROWS : 0);
    else if (hit == PAGE_HIT_DOWN)
        Port_BagMoveCursor(v->bag.cursor + BAG_ROWS > v->bag.nItems ? v->bag.nItems : v->bag.cursor + BAG_ROWS);
    else if (hit >= PAGE_HIT_FOOT && hit < PAGE_HIT_FOOT + 4)
    {
        int i = hit - PAGE_HIT_FOOT;

        if (v->bag.mode == PORT_MENU_ACTIONS)
        {
            Port_MenuSetCursor(v->bag.actionRow[i]);
            Inject(A_BUTTON);
        }
        else if (v->bag.mode == PORT_MENU_QUANTITY)
            Inject(i == 0 ? DPAD_DOWN : i == 1 ? DPAD_UP : A_BUTTON);
    }
}

static void PageFrame(bool active, u16 x, u16 y)
{
    static bool wasActive;
    static u8 downHit;
    PageView now;
    u32 hash = 0;

    sGameShown = FALSE;
    if (!SnapshotPage(&now))
    {
        /* between the menu's own states the page keeps what it shows */
        if (!sPageDrawn)
        {
            Header(NULL);
            FillRect(0, HEADER_H, W, H - HEADER_H, C_PAGE);
            CtrBottom_Blit(sCanvas, 0, W);
        }
        return;
    }
    if (now.page == PORT_PAGE_STORAGE)
        StorageWalk(&now.box);
    /* a summary page chosen by touch: the game's own flips, one at a time */
    if (now.page == PORT_PAGE_SUMMARY)
    {
        const struct PortSummaryView *sv = &now.sum;

        if (sWantMove >= 0 && sv->cursorReady)
        {
            Port_SummarySetMoveCursor(sWantMove);
            sWantMove = -1;
        }
        if (sWantPage >= 0 && sInjectFrames == 0 && (sv->ready || sv->cursorReady))
        {
            if (sv->page == sWantPage || sWantTries > 8)
                sWantPage = -1;
            else
            {
                sWantTries++;
                Inject(sv->page > PSS_PAGE_MOVES ? B_BUTTON : sv->page < sWantPage ? DPAD_RIGHT : DPAD_LEFT);
            }
        }
    }
    /* a pocket chosen by touch: the game's own steps, one at a time */
    if (now.page == PORT_PAGE_BAG && sBagWantPocket >= 0)
    {
        if (now.bag.pocket == sBagWantPocket || sBagPocketTries > 8)
            sBagWantPocket = -1;
        else if (now.bag.mode == PORT_MENU_LIST && sInjectFrames == 0)
        {
            sBagPocketTries++;
            Inject(sBagWantPocket < now.bag.pocket ? DPAD_LEFT : DPAD_RIGHT);
        }
    }
    if (active && !wasActive)
        downHit = PageHitTest(&now, x, y);
    if (active)
        sTouchHit = PageHitTest(&now, x, y) == downHit ? downHit : HIT_NONE;
    else
    {
        if (wasActive && sTouchHit != HIT_NONE)
            PageActivate(&now, sTouchHit);
        sTouchHit = HIT_NONE;
    }
    /* the Pokédex's rail: the list follows the finger */
    if (active && sTouchHit == PAGE_HIT_RAIL && now.dex.count > 1)
    {
        int index = (y - DEX_ROW_Y) * (now.dex.count - 1) / (DEX_ROWS * DEX_ROW_H);

        Port_ListSetCursor(now.dex.listTask, index < 0 ? 0 : index >= now.dex.count ? now.dex.count - 1 : index);
    }
    wasActive = active;
    now.pressed = sTouchHit;
    for (int i = 0; i < now.cardCount; i++)
        hash = hash * 31 + WindowHash(now.cards[i]);
    if (now.page == PORT_PAGE_PARTY && WindowOnScreen(now.party.helpWindow))
        hash = hash * 31 + WindowHash(now.party.helpWindow);
    if (now.page == PORT_PAGE_STORAGE && WindowOnScreen(PORT_STORAGE_MESSAGE_WINDOW))
        hash = hash * 31 + WindowHash(PORT_STORAGE_MESSAGE_WINDOW);
    if (now.page == PORT_PAGE_SUMMARY && now.sum.memoWindow < WINDOWS_MAX && gWindows[now.sum.memoWindow].tileData != NULL)
        hash = hash * 31 + WindowHash(now.sum.memoWindow);
    if (!sPageDrawn || memcmp(&now, &sPageShown, sizeof(now)) != 0)
    {
        switch (now.page)
        {
        case PORT_PAGE_PARTY:   DrawPartyBase(&now); break;
        case PORT_PAGE_BAG:     DrawBagBase(&now); break;
        case PORT_PAGE_SUMMARY: DrawSummaryBase(&now); break;
        case PORT_PAGE_CARD:    DrawCardBase(&now); break;
        case PORT_PAGE_STORAGE: DrawStorageBase(&now); break;
        default:                DrawDexBase(&now); break;
        }
    }
    else if (hash == sPageHash)
        return;
    if (now.page == PORT_PAGE_PARTY)
        DrawPartyLive(&now);
    else if (now.page == PORT_PAGE_SUMMARY)
        DrawSummaryLive(&now);
    else if (now.page == PORT_PAGE_STORAGE)
        DrawStorageLive(&now);
    else
        DrawCards(&now);
    CtrBottom_Blit(sCanvas, 0, W);
    sPageShown = now;
    sPageHash = hash;
    sPageDrawn = TRUE;
}

/* ------------------------------------------------------------------------ */
/* Touch                                                                    */
/* ------------------------------------------------------------------------ */

static u8 BattleHitTest(const ViewState *s, int x, int y)
{
    bool8 moves = s->b.choose == PORT_BATTLE_MOVE;

    /* no menu up: a message goes on with a tap */
    if (!s->b.choose)
        return HIT_SCENE;
    for (int i = 0; i < (moves ? 5 : 4); i++)
    {
        int bx, by, bw, bh;

        if (moves)
            MoveRect(i, &bx, &by, &bw, &bh);
        else
            ActionRect(i, &bx, &by, &bw, &bh);
        if (x >= bx && x < bx + bw && y >= by && y < by + bh)
            return HIT_BATTLE + i;
    }
    return HIT_NONE;
}

static u8 HitTest(int x, int y)
{
    /* a scene on the top screen (an item used, an evolution) goes on with a tap */
    if (Port_SceneShown())
        return HIT_SCENE;
    if (sScreen == SCR_OPTIONS)
        return OptionsHitTest(x, y);
    if (y < HEADER_H)
        return x >= RUN_X - 4 && x < RUN_X + RUN_W + 4 ? HIT_RUN : HIT_NONE;
    if (y >= DOCK_Y)
    {
        int i = (x - DOCK_KEY_X) / DOCK_STEP;

        return HIT_BUTTON + (x < DOCK_KEY_X ? 0 : i < MENU_COUNT ? i : MENU_COUNT - 1);
    }
    if (x >= PARTY_X - 2)
        return HIT_PARTY;
    return HIT_NONE;
}

static void Open(u8 action)
{
    PlaySE(SE_SELECT);
    CtrStartMenu_Request(action);
    sInjected = START_BUTTON;
    sInjectFrames = 3;
    CtrLog_Write(CTR_LOG_INPUT, "bottom: open start menu entry %u at frame %lu", action,
                 (unsigned long)CtrGame_Frames());
}

#define DOCK_WAIT_FRAMES 45
static u8 sDockWait;
static u8 sDockWaitFrames;

static void Activate(const ViewState *s, u8 hit)
{
    if (s->battle)
    {
        if (hit == HIT_SCENE)
            Inject(A_BUTTON);
        else if (s->b.choose && hit >= HIT_BATTLE && hit < HIT_BATTLE + 5
         && (s->b.choose == PORT_BATTLE_MOVE || hit < HIT_BATTLE + 4))
        {
            PlaySE(SE_SELECT);
            sBattleTap = hit - HIT_BATTLE;
            sBattleTapKind = s->b.choose;
        }
        return;
    }
    if (hit == HIT_SCENE)
    {
        Inject(A_BUTTON);
        return;
    }
    if (hit >= HIT_TAB && hit < HIT_COUNT)
    {
        OptionsActivate(hit);
        return;
    }
    if (hit == HIT_RUN)
    {
        if (s->run & 2)
        {
            PlaySE(SE_SELECT);
            CtrSettings_SetRunAlways(!CtrSettings_RunAlways());
        }
        return;
    }
    /* OPTION shows the port's own options screen; its BACK key leaves it. */
    if (hit == HIT_BUTTON + MENU_OPTION)
    {
        PlaySE(SE_SELECT);
        sScreen = SCR_OPTIONS;
        return;
    }
    /* mid-step the field takes no menu: the tap waits for the step's end */
    if (!FieldIdle())
    {
        sDockWait = hit;
        sDockWaitFrames = DOCK_WAIT_FRAMES;
        return;
    }
    if (hit >= HIT_BUTTON && hit < HIT_BUTTON + MENU_COUNT)
    {
        u8 i = hit - HIT_BUTTON;

        if ((s->enabled >> i) & 1)
        {
            sScreen = SCR_MAP;
            Open(i);
        }
    }
    else if (hit == HIT_PARTY && (s->enabled & (1 << MENU_POKEMON)) && s->partyCount)
    {
        Open(MENU_POKEMON);
    }
}

static bool ReadTouch(u16 *x, u16 *y)
{
    const CtrInput *in = CtrInput_Get();

    *x = in->touchX;
    *y = in->touchY;
#ifdef CTR_INPUT_SCRIPT
    if (CtrScript_Touch(x, y))
        return true;
#endif
    return in->touchActive;
}

static void ProcessPanelTouch(const ViewState *s, bool active, u16 x, u16 y)
{
    static bool wasActive;
    static u8 downHit;

    if (active && !wasActive)
        downHit = s->battle ? BattleHitTest(s, x, y) : HitTest(x, y);
    if (active)
        sTouchHit = (s->battle ? BattleHitTest(s, x, y) : HitTest(x, y)) == downHit ? downHit : HIT_NONE;
    else
    {
        if (wasActive && sTouchHit != HIT_NONE)
            Activate(s, sTouchHit);
        sTouchHit = HIT_NONE;
    }
    wasActive = active;
}

/* ------------------------------------------------------------------------ */
/* Entry points                                                             */
/* ------------------------------------------------------------------------ */

void CtrBottom_Init(void)
{
    for (unsigned c = 0; c < 32768; ++c)
        sLut[c] = Rgb(c & 31, (c >> 5) & 31, (c >> 10) & 31);
    memset(sCanvas, 0, sizeof(sCanvas));
    sDrawn = FALSE;
}

void CtrBottom_Frame(void)
{
    ViewState now;
    u16 x, y;
    bool active = ReadTouch(&x, &y);

    if (sInjectFrames && --sInjectFrames == 0)
        sInjected = 0;
    if (PageActive())
    {
        PageFrame(active, x, y);
        return;
    }
    if (ZoomActive())
        ZoomTouch(active, x, y);
    /* a menu's picture arrives from CtrGame_VBlank */
    if (CtrBottom_TakesGameFrame())
        return;
    if (sPageDrawn)
    {
        sPageDrawn = FALSE;
        sDrawn = FALSE;
    }
    if (sGameShown)
    {
        /* back from a menu: the panel again, from scratch */
        sGameShown = FALSE;
        sDrawn = FALSE;
    }
    if (CtrGame_Resets() != sResetsSeen)
    {
        /* back to the title: no game until the field is on again */
        sResetsSeen = CtrGame_Resets();
        sInGame = FALSE;
        sScreen = SCR_MAP;
        sDrawn = FALSE;
    }
    if (!sInGame && InField())
    {
        sInGame = TRUE;
        sDrawn = FALSE;
    }
    if (!sInGame)
    {
        if (!sDrawn)
            RenderTitle();
        sDrawn = TRUE;
        return;
    }
    Snapshot(&now);
    if (sDockWait != HIT_NONE)
    {
        u8 hit = sDockWait;

        sDockWait = HIT_NONE;
        if (FieldIdle())
            Activate(&now, hit);
        else if (--sDockWaitFrames)
            sDockWait = hit;
    }
    ProcessPanelTouch(&now, active, x, y);
    now.pressed = sTouchHit;
    if (sDrawn && memcmp(&now, &sShown, sizeof(now)) == 0)
        return;
    if (now.battle)
        RenderBattle(&now);
    else
        RenderPanel(&now);
    sShown = now;
    sDrawn = TRUE;
}

/* field_player_avatar.c: free movement (the options screen's FREE MOVE). */
/* The first Pokemon of the party walks behind the player in the 3D world
 * (voxel_follower.c), on unless turned off. */
bool8 CtrPlayer_Follower(void)
{
    return CtrSettings_GetInt(FOLLOWER_KEY, 1) != 0;
}

bool8 CtrPlayer_FreeMove(void)
{
    return CtrSettings_GetInt(FREE_MOVE_KEY, 0) != 0;
}

/* The circle pad, when it is what steers (not the D-pad) and out of its
 * middle: +y up. */
bool8 CtrPlayer_FreeStick(s16 *x, s16 *y)
{
    const CtrInput *input = CtrInput_Get();
    int sx = input->circleX, sy = input->circleY;

#ifdef CTR_INPUT_SCRIPT
    {
        s16 tx, ty;

        if (CtrScript_Stick(&tx, &ty))
        {
            sx = tx;
            sy = ty;
        }
    }
#endif
    if ((input->physicalHeld & CTR_KEY_DPAD) || sx * sx + sy * sy < CTR_CIRCLE_LEAVE * CTR_CIRCLE_LEAVE)
        return FALSE;
    *x = sx;
    *y = sy;
    return TRUE;
}

/* field_player_avatar.c: running without B (the options screen's RUN). */
bool8 CtrPlayer_RunAlways(void)
{
    return CtrSettings_RunAlways();
}

uint16_t CtrBottom_InjectedKeys(void)
{
    return sInjected;
}

uint16_t CtrBottom_FilterKeys(uint16_t held)
{
    return held;
}

#ifdef CTR_FRAME_DUMP
#include <stdio.h>
/* Diagnostic: the canvas as shown (column-major RGB565, 320x240). */
void CtrBottom_Dump(const char *path)
{
    FILE *file = fopen(path, "wb");

    if (file)
    {
        fwrite(sCanvas, sizeof(sCanvas), 1, file);
        fclose(file);
    }
}
#endif

/* No section ball in this design; kept for the shared header. */
const uint8_t *CtrBottom_BallMask(void)
{
    return NULL;
}
