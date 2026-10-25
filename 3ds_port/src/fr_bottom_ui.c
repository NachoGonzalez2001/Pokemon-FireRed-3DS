/*
 * The bottom screen, game side, for FireRed: what it shows and what a touch
 * does. Modelled on the Emerald port's 3ds_bottom_ui.c.
 *
 * In the field it is a panel and a column. The column on the right holds the
 * start menu's entries: POKéDEX, POKéMON, BAG, the player (trainer card),
 * SAVE and OPTION. A tap asks the game for that entry and presses START
 * (start_menu.c, CtrStartMenu_Request), so the game opens it exactly as if it
 * had been chosen from its menu. The 240x240 panel on the left shows a header
 * (location, play time), the region map with the player's place on it, and
 * the party (icons and HP); a tap on the party opens the party menu.
 *
 * The game's menu screens (party, bag, Pokédex, trainer card, options,
 * summary, PC, town map, shop, TM case, berry pouch, naming) are shown here
 * instead of on the top screen: each one's main callback calls
 * Port_MenuOnBottom, the top screen holds the last picture of the world
 * (3ds_game_full.c), and the GBA picture is put 1:1 in the panel's place, its
 * edges carried out to the panel's. The column then has the GBA's buttons
 * (A, B, START, SELECT, L, R) to press by touch.
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
#include "battle.h"
#include "battle_controllers.h"
#include "battle_main.h"
#include "data.h"
#include "decompress.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "fieldmap.h"
#include "overworld.h"
#include "palette.h"
#include "pokemon.h"
#include "pokemon_icon.h"
#include "region_map.h"
#include "script.h"
#include "sound.h"
#include "string_util.h"
#include "strings.h"
#include "text.h"
#include "constants/moves.h"
#include "constants/songs.h"
#include "constants/region_map_sections.h"
#include "port_platform.h"

#include "3ds_bottom.h"
#include "3ds_extras.h"
#include "3ds_input.h"
#include "3ds_log.h"
#include "3ds_platform.h"

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

/* start_menu.c's STARTMENU_* */
enum { MENU_POKEDEX, MENU_POKEMON, MENU_BAG, MENU_PLAYER, MENU_SAVE, MENU_OPTION, MENU_COUNT };

#define W CTR_BOTTOM_WIDTH
#define H CTR_BOTTOM_HEIGHT
#define COLUMN_X 240
#define HEADER_H 26
/* the column's keys, below the header; the pad's (a menu shown) full height */
#define KEYS_Y (HEADER_H + 3)
#define KEY_STEP ((H - KEYS_Y - 2) / MENU_COUNT)
#define PAD_H (H / MENU_COUNT)
/* the region map art, and the part of it behind the glass */
#define MAP_W 240
#define MAP_H 160
#define MAP_X 8
#define MAP_Y 34
#define MAP_VIEW_W 224
#define MAP_VIEW_H 122
#define MAP_SRC_X 8
#define MAP_SRC_Y 30
/* the party's display strip */
#define PARTY_X 8
#define PARTY_Y 166
#define PARTY_VIEW_W 224
#define PARTY_VIEW_H 68
#define GBA_W 240
#define GBA_H 160
#define GAME_Y ((H - GBA_H) / 2)

/* What the panel left of the column shows */
enum { SCR_MAP, SCR_OPTIONS };

/* The options screen: three tabs (CTR_EXTRAS_*) - SETTINGS, the game's own
 * settings and the port's, as the Emerald port's; ENHANCEMENTS and CHEATS,
 * the extras (3ds_extras.h). It replaces the game's option menu. */
enum {
    OPT_TEXT_SPEED, OPT_BATTLE_SCENE, OPT_BATTLE_STYLE, OPT_SOUND, OPT_BUTTON_MODE, OPT_FRAME,
    OPT_RUN, OPT_FREE_MOVE, OPT_VOXEL, OPT_VOXEL_ANGLE, OPT_VOXEL_ZOOM, OPT_VOXEL_BLUR, OPT_VOXEL_BATTLE,
    OPT_FOLLOWER,
    OPT_COUNT
};
#define OPT_MAX_ROWS 16
#define OPT_PAGE_ROWS 6
#define TAB_Y 30
#define TAB_H 18
#define LIST_X 4
#define LIST_Y 50
#define LIST_W 232
#define LIST_H 186
#define ROW_H 26
#define ROW_GAP 3
#define DOTS_Y 230

/* Touch targets */
enum { HIT_NONE, HIT_BUTTON, HIT_PARTY = HIT_BUTTON + MENU_COUNT, HIT_BATTLE,
       HIT_TAB = HIT_BATTLE + 5, HIT_ROW = HIT_TAB + CTR_EXTRAS_PAGES, HIT_ROW_BACK = HIT_ROW + OPT_PAGE_ROWS,
       HIT_PAGE = HIT_ROW_BACK + OPT_PAGE_ROWS, HIT_COUNT };

/* The GBA buttons of the column while a menu is shown */
static const u16 sPadKeys[MENU_COUNT] = { A_BUTTON, B_BUTTON, START_BUTTON, SELECT_BUTTON, L_BUTTON, R_BUTTON };
static const char *const sPadLabels[MENU_COUNT] = { "A", "B", "START", "SELECT", "L", "R" };

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
    u8 idle;         /* the field takes the column's taps */
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
static u8 sPadPressed = 0xFF;
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

/* A box with rounded corners (a pixel cut at each) and a border. */
static void DrawBox(int x, int y, int w, int h, u16 fill, u16 border)
{
    FillRect(x + 1, y, w - 2, h, border);
    FillRect(x, y + 1, w, h - 2, border);
    FillRect(x + 1, y + 1, w - 2, h - 2, fill);
}

static u16 Dim(u16 c)
{
    return (c >> 1) & 0x7BEF;
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
               : c == '!' ? CHAR_EXCL_MARK : CHAR_SPACE;
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
        && gMapHeader.mapLayout != NULL;
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
    s->idle = FieldIdle();
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
/* Colours: a Pokédex - red shell, dark glass, charcoal keys                */
/* ------------------------------------------------------------------------ */

/* 8-bit components to RGB565 */
#define C8(r, g, b) ((u16)((((r) >> 3) << 11) | (((g) >> 2) << 5) | ((b) >> 3)))

#define C_RED       C8(206, 40, 46)
#define C_RED_HI    C8(236, 82, 82)
#define C_RED_LO    C8(150, 24, 32)
#define C_RED_DK    C8(92, 14, 20)
#define C_SEAM      C8(60, 8, 12)
#define C_INK       C8(24, 22, 28)
#define C_KEY       C8(44, 48, 56)
#define C_KEY_HI    C8(70, 76, 88)
#define C_KEY_LO    C8(28, 30, 36)
#define C_KEY_LIT   C8(64, 70, 82)
#define C_GLASS     C8(22, 26, 32)
#define C_GLASS_HI  C8(40, 46, 56)
#define C_GLASS_LO  C8(30, 34, 42)
#define C_BEZEL     C8(60, 64, 74)
#define C_WHITE     C8(248, 248, 248)
#define C_SHADOW    C8(70, 74, 84)
#define C_MUTED     C8(120, 124, 132)
#define C_LENS      C8(60, 168, 240)
#define C_LENS_HI   C8(170, 222, 255)
#define C_GOLD      C8(250, 206, 64)
#define C_GREEN     C8(88, 216, 108)
#define C_YELLOW    C8(255, 210, 72)
#define C_BRIGHTRED C8(255, 82, 82)
#define C_LCD       C8(140, 255, 170)
#define C_PAPER     C8(250, 250, 250)
#define C_ROW       C8(236, 238, 242)
#define C_ROW_EDGE  C8(210, 212, 218)
#define C_ROW_FOCUS C8(255, 236, 236)
#define C_ROW_TEXT  C8(40, 40, 48)
#define C_ROW_SH    C8(200, 200, 208)
#define C_OFF       C8(180, 184, 192)
#define C_LETTERBOX C8(24, 26, 32)

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
/* Pixel icons, 12x12                                                       */
/* ------------------------------------------------------------------------ */

static const char *const sIconDex[12] = {
    "............", ".kkkkkkkkkk.", ".krrrrrrrrk.", ".krkkkrrrrk.", ".kkbbbkrrrk.", ".kbwbbkrrrk.",
    ".kbbbbkrrrk.", ".krkkkrrrrk.", ".krrrrrrrrk.", ".krkkkkkkrk.", ".kkkkkkkkkk.", "............",
};
static const char *const sIconBall[12] = {
    "....kkkk....", "..kkrrrrkk..", ".krrrrrrrrk.", ".krwrrrrrrk.", "krrrrkkrrrrk", "kkkkkwwkkkkk",
    "kwwwwkkwwwwk", ".kwwwwwwwwk.", ".kwwwwwwwwk.", "..kkwwwwkk..", "....kkkk....", "............",
};
static const char *const sIconBag[12] = {
    "....kkkk....", "...k....k...", "..kkkkkkkk..", ".kooooooook.", ".kooddddook.", ".koodwwdook.",
    ".kooddddook.", ".kooooooook.", ".kooooooook.", ".kooooooook.", "..kkkkkkkk..", "............",
};
static const char *const sIconCard[12] = {
    "............", "kkkkkkkkkkkk", "kbbbbbbbbbbk", "kbwwwbbbbbbk", "kbwwwbbwwwbk", "kbwwwbbbbbbk",
    "kbkkkbbwwwbk", "kbbbbbbbbbbk", "kbbbbbbwwbbk", "kbbbbbbbbbbk", "kkkkkkkkkkkk", "............",
};
static const char *const sIconSave[12] = {
    "kkkkkkkkkkkk", "kuuwwwwwwuuk", "kuuwwwwkwuuk", "kuuwwwwkwuuk", "kuuwwwwwwuuk", "kuuuuuuuuuuk",
    "kuuuuuuuuuuk", "kuukkkkkkuuk", "kuukwwwwkuuk", "kuukkkkkkuuk", "kuukwwwwkuuk", "kkkkkkkkkkkk",
};
static const char *const sIconGear[12] = {
    "....gggg....", ".g.gggggg.g.", "..gggggggg..", ".ggggkkgggg.", ".gggk..kggg.", "gggk....kggg",
    "gggk....kggg", ".gggk..kggg.", ".ggggkkgggg.", "..gggggggg..", ".g.gggggg.g.", "....gggg....",
};
static const char *const sIconRun[12] = {
    "......k.....", ".....kwk....", "....kwwk....", "...kwwwkkkkk", "..kwwwwwwwwk", ".kwwwwwwwwwk",
    "..kwwwwwwwwk", "...kwwwkkkkk", "....kwwk....", ".....kwk....", "......k.....", "............",
};

static u16 IconColour(char c)
{
    switch (c)
    {
    case 'k': return C_INK;
    case 'w': return C_WHITE;
    case 'r': return C_BRIGHTRED;
    case 'b': return C8(120, 190, 250);
    case 'o': return C8(214, 150, 70);
    case 'd': return C8(120, 70, 30);
    case 'u': return C8(90, 120, 220);
    case 'g': return C8(200, 204, 212);
    default:  return C_INK;
    }
}

static void DrawIcon(const char *const *icon, int x, int y, int scale, bool8 on)
{
    for (int j = 0; j < 12; j++)
        for (int i = 0; i < 12; i++)
        {
            char c = icon[j][i];

            if (c != '.')
                FillRect(x + i * scale, y + j * scale, scale, scale, on ? IconColour(c) : Grey(IconColour(c)));
        }
}

/* ------------------------------------------------------------------------ */
/* The shell                                                                */
/* ------------------------------------------------------------------------ */

static void Shell(int x, int y, int w, int h)
{
    Gradient(x, y, w, h, C_RED_HI, C_RED_LO);
}

static void Lens(int cx, int cy, int r)
{
    Disc(cx, cy, r + 2, C_WHITE);
    Disc(cx, cy, r + 1, C_INK);
    Disc(cx, cy, r, C_LENS);
    Disc(cx - r / 3, cy - r / 3, r / 2, C_LENS_HI);
}

static void Leds(int x, int y)
{
    static const u16 colours[3] = { C_BRIGHTRED, C_YELLOW, C_GREEN };

    for (int i = 0; i < 3; i++)
    {
        Disc(x + i * 8 + 2, y + 2, 3, C_INK);
        Disc(x + i * 8 + 2, y + 2, 2, colours[i]);
    }
}

/* The header across the top: the lens, its lights, a title; on the right
 * an LCD readout when there is one. */
static void Header(const u8 *title, const u8 *readout)
{
    Shell(0, 0, W, HEADER_H);
    FillRect(0, 0, W, 1, C8(250, 130, 130));
    FillRect(0, HEADER_H, W, 1, C_RED_DK);
    Lens(13, 13, 7);
    Leds(26, 3);
    if (title)
        Text(FONT_NORMAL, title, 28, 9, C_WHITE, C_RED_DK, TRUE);
    if (readout)
    {
        int w = TextWidth(FONT_NORMAL, readout) + 12;

        RoundBox(W - w - 6, 5, w, 18, 6, C_GLASS, C_RED_DK);
        TextRight(FONT_NORMAL, readout, W - 12, 6, C_LCD, C_GLASS);
    }
}

/* The hinge between the panel and the column. */
static void Hinge(void)
{
    FillRect(COLUMN_X, HEADER_H + 1, 4, H - HEADER_H - 1, C_RED_DK);
    FillRect(COLUMN_X + 1, HEADER_H + 1, 1, H - HEADER_H - 1, C_SEAM);
    for (int k = 0; k < 2; k++)
    {
        int y = k ? 200 : 60;

        Disc(COLUMN_X + 2, y + 2, 2, C8(170, 170, 176));
        Disc(COLUMN_X + 2, y + 2, 1, C8(110, 110, 118));
    }
}

/* A glass screen let into the shell: a dark bezel round the picture. */
static void Bezel(int x, int y, int w, int h)
{
    RoundRect(x - 3, y - 3, w + 6, h + 6, 7, C_INK);
    RoundRect(x - 2, y - 2, w + 4, h + 4, 6, C_BEZEL);
}

/* A charcoal key: a shadow on the shell, a lit top edge, a red stripe, its
 * icon and label; gold round it when it is the one chosen. */
static void Key(int x, int y, int w, int h, const u8 *label, const char *const *icon, bool8 on, bool8 lit,
                bool8 pressed)
{
    u16 body = !on ? C_KEY_LO : pressed ? C_KEY_LO : lit ? C_KEY_LIT : C_KEY;
    int dy = pressed ? 1 : 0, tx = x + 9;

    RoundRect(x, y + 2, w, h, 6, C_SEAM);
    if (lit && on)
        RoundBox(x - 2, y - 2 + dy, w + 4, h + 4, 8, body, C_GOLD);
    RoundRect(x, y + dy, w, h, 6, body);
    Gradient(x + 3, y + 2 + dy, w - 6, 4, on && !pressed ? C_KEY_HI : C_KEY, body);
    FillRect(x + 4, y + h - 2 + dy, w - 9, 1, C8(20, 22, 26));
    FillRect(x + 3, y + 6 + dy, 3, h - 12, on ? C_RED : C_SHADOW);
    if (icon)
    {
        DrawIcon(icon, tx, y + dy + (h - 12) / 2, 1, on);
        tx += 15;
    }
    Text(FONT_SMALL, label, tx, y + dy + h / 2 - 8, on ? C_WHITE : C_MUTED, C_INK, TRUE);
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
    RoundRect(MAP_X, MAP_Y, MAP_VIEW_W, MAP_VIEW_H, 2, C_GLASS);
    if (!s->onMap || !BuildMapCache(s->region))
        return;
    for (int x = 0; x < MAP_VIEW_W; x++)
    {
        u16 *col = sCanvas + (MAP_X + x) * H + (H - 1 - MAP_Y);

        for (int y = 0; y < MAP_VIEW_H; y++)
        {
            u16 c = sMapCache[(MAP_SRC_Y + y) * MAP_W + MAP_SRC_X + x];

            /* faint scanlines on the glass */
            col[-y] = y % 3 == 0 ? Darker(c, 1) : c;
        }
    }
    FillRect(MAP_X + 4, MAP_Y + 1, MAP_VIEW_W - 40, 1, C_WHITE);
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
    *y = LIST_Y + 6 + i * (ROW_H + ROW_GAP);
    *w = LIST_W - 12;
    *h = ROW_H;
}

static const char *const sTabNames[CTR_EXTRAS_PAGES] = { "SETTINGS", "ENHANCE", "CHEATS" };

static void Toggle(int x, int y, bool8 on, bool8 live)
{
    u16 track = !live ? C_ROW_EDGE : on ? C_GREEN : C_OFF;
    int kx = on ? x + 20 : x + 2;

    RoundRect(x, y, 34, 14, 7, track);
    Disc(kx + 6, y + 7, 6, C_MUTED);
    Disc(kx + 6, y + 7, 5, C_WHITE);
}

static void DrawOptions(const ViewState *s)
{
    static const u8 left[] = { CHAR_LEFT_ARROW, EOS }, right[] = { CHAR_RIGHT_ARROW, EOS };
    OptRow rows[OPT_MAX_ROWS];
    int count = PageRows(s->optTab, s->optSub, rows), pages = PageCount(count);
    int tw = (COLUMN_X - 8) / CTR_EXTRAS_PAGES;

    Header(Ascii("OPTIONS"), NULL);
    Shell(0, HEADER_H + 1, COLUMN_X, H - HEADER_H - 1);
    /* the tabs, a Pokédex's index tabs */
    for (int t = 0; t < CTR_EXTRAS_PAGES; t++)
    {
        int x = 4 + t * tw;
        bool8 on = t == s->optTab, pressed = s->pressed == HIT_TAB + t;

        RoundRect(x, TAB_Y, tw - 2, TAB_H + (on ? 6 : 0), 6, on ? C_PAPER : pressed ? C_SEAM : C_RED_DK);
        TextCentered(FONT_SMALL, Ascii(sTabNames[t]), x + tw / 2 - 1, TAB_Y + 3,
                     on ? C_INK : C8(255, 190, 190), on ? C_ROW_SH : C_RED_DK);
    }
    RoundRect(LIST_X, LIST_Y, LIST_W, LIST_H, 6, C_PAPER);
    FillRect(LIST_X, LIST_Y, LIST_W, 6, C_PAPER);
    for (int i = 0; i < OPT_PAGE_ROWS; i++)
    {
        int n = s->optPage * OPT_PAGE_ROWS + i, x, y, w, h;
        const OptRow *r = &rows[n];
        bool8 live, pressed;
        u8 kind;
        u16 ink, shade;

        if (n >= count)
            break;
        OptRowRect(i, &x, &y, &w, &h);
        live = RowLive(r);
        kind = RowKind(r);
        pressed = s->pressed == HIT_ROW + i || s->pressed == HIT_ROW_BACK + i;
        ink = live ? C_ROW_TEXT : C_OFF;
        shade = live ? C_ROW_SH : C_ROW;
        RoundBox(x, y, w, h, 5, pressed ? C_ROW_FOCUS : C_ROW, pressed ? C_RED : C_ROW_EDGE);
        Text(FONT_SMALL, r->opt >= 0 ? OptionName(r->opt) : Ascii(r->extra->name), x + 8, y + 5, ink, shade, TRUE);
        if (kind == ROW_TOGGLE)
        {
            Toggle(x + w - 44, y + 6, RowOn(r), live);
        }
        else if (kind == ROW_ACTION)
        {
            const u8 *label = Ascii(r->extra->values ? r->extra->values[0] : "GO");
            int bw = TextWidth(FONT_SMALL, label) + 14;

            RoundBox(x + w - bw - 6, y + 4, bw, h - 8, 5, pressed ? C_RED_LO : C_RED, C_RED_DK);
            TextCentered(FONT_SMALL, label, x + w - 6 - bw / 2, y + 5, C_WHITE, C_RED_DK);
        }
        else
        {
            const u8 *value;
            u16 arrow = live ? C_RED : C_OFF;

            if (r->opt >= 0)
                value = OptionValue(r->opt, OptionGet(r->opt));
            else if (r->extra->text)
                value = r->extra->text();
            else
                value = Ascii(r->extra->values[CtrExtras_Value(r->extra)]);
            Text(FONT_SMALL, left, x + w - 104, y + 5, arrow, shade, TRUE);
            TextCentered(FONT_SMALL, value, x + w - 58, y + 5, live ? C_RED_DK : C_OFF, shade);
            TextRight(FONT_SMALL, right, x + w - 8, y + 5, arrow, shade);
        }
    }
    /* the pages of a long tab: dots, a tap on them the next */
    if (pages > 1)
        for (int p = 0; p < pages; p++)
            Disc(COLUMN_X / 2 - (pages - 1) * 5 + p * 10, DOTS_Y, 2, p == s->optPage ? C_RED : C_OFF);
}

static u8 OptionsHitTest(int x, int y)
{
    OptRow rows[OPT_MAX_ROWS];
    int count = PageRows(sOptTab, sOptSub, rows);

    if (y >= TAB_Y && y < TAB_Y + TAB_H + 4)
    {
        int t = (x - 4) / ((COLUMN_X - 8) / CTR_EXTRAS_PAGES);

        return t >= 0 && t < CTR_EXTRAS_PAGES ? HIT_TAB + t : HIT_NONE;
    }
    if (y >= DOTS_Y - 6 && PageCount(count) > 1)
        return HIT_PAGE;
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

    if (hit >= HIT_TAB && hit < HIT_TAB + CTR_EXTRAS_PAGES)
    {
        u8 tab = hit - HIT_TAB;

        PlaySE(SE_SELECT);
        if (tab == sOptTab)
            sOptPage = (sOptPage + 1) % PageCount(count);
        else
        {
            sOptTab = tab;
            sOptSub = 0;
            sOptPage = 0;
        }
        return;
    }
    if (hit == HIT_PAGE)
    {
        PlaySE(SE_SELECT);
        sOptPage = (sOptPage + 1) % PageCount(count);
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

static const char *const *const sMenuIcons[MENU_COUNT] = { sIconDex, sIconBall, sIconBag, sIconCard, sIconSave,
                                                           sIconGear };

static void KeyRect(int i, int *x, int *y, int *w, int *h)
{
    *x = COLUMN_X + 8;
    *y = KEYS_Y + i * KEY_STEP + 2;
    *w = W - COLUMN_X - 13;
    *h = KEY_STEP - 5;
}

static void DrawColumn(const ViewState *s)
{
    Shell(COLUMN_X, HEADER_H + 1, W - COLUMN_X, H - HEADER_H - 1);
    Hinge();
    for (int i = 0; i < MENU_COUNT; i++)
    {
        bool8 option = i == MENU_OPTION;
        int x, y, w, h;

        KeyRect(i, &x, &y, &w, &h);
        Key(x, y, w, h, MenuLabel(s, i), sMenuIcons[i], option || (((s->enabled >> i) & 1) && s->idle),
            option && s->screen == SCR_OPTIONS, s->pressed == HIT_BUTTON + i);
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
    Header(s->onMap ? name : NULL, time);
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

static void DrawParty(const ViewState *s)
{
    int sw = (PARTY_VIEW_W - 4) / PARTY_SIZE;

    RoundRect(PARTY_X, PARTY_Y, PARTY_VIEW_W, PARTY_VIEW_H, 2, s->pressed == HIT_PARTY ? C_GLASS_HI : C_GLASS);
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        const MonView *m = &s->party[i];
        int x = PARTY_X + 2 + i * sw, cx = x + sw / 2;
        bool8 filled = i < s->partyCount && m->species != SPECIES_NONE;

        RoundBox(x + 1, PARTY_Y + 3, sw - 2, PARTY_VIEW_H - 6, 5, filled ? C_GLASS_HI : C_GLASS_LO,
                 filled ? C8(70, 76, 90) : C8(44, 48, 58));
        if (!filled)
        {
            /* an empty place: a ball's outline */
            Ring(cx, PARTY_Y + 31, 6, 1, C8(60, 66, 80));
            FillRect(cx - 6, PARTY_Y + 31, 13, 1, C8(60, 66, 80));
            continue;
        }
        DrawMonIcon(m, cx - 16, PARTY_Y + 4);
        if (!m->egg)
        {
            int bw = sw - 10, fill = m->maxHp ? ((bw - 2) * m->hp + m->maxHp - 1) / m->maxHp : 0;
            u16 c = m->hp * 2 > m->maxHp ? C_GREEN : m->hp * 5 > m->maxHp ? C_YELLOW : C_BRIGHTRED;
            u8 buf[8];

            FillRect(x + 5, PARTY_Y + 40, bw, 5, C_INK);
            FillRect(x + 6, PARTY_Y + 41, fill, 3, c);
            buf[0] = CHAR_LV;
            ConvertIntToDecimalStringN(buf + 1, m->level, STR_CONV_MODE_LEFT_ALIGN, 3);
            TextCentered(FONT_SMALL, buf, cx, PARTY_Y + 47, C_WHITE, C_INK);
        }
    }
}

static void RenderPanel(const ViewState *s)
{
    if (s->screen == SCR_OPTIONS)
        DrawOptions(s);
    else
    {
        DrawHeader(s);
        Shell(0, HEADER_H + 1, COLUMN_X, H - HEADER_H - 1);
        Bezel(MAP_X, MAP_Y, MAP_VIEW_W, MAP_VIEW_H);
        DrawMap(s);
        Bezel(PARTY_X, PARTY_Y, PARTY_VIEW_W, PARTY_VIEW_H);
        DrawParty(s);
    }
    DrawColumn(s);
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
 * move menu: four moves in a 2x2 grid, CANCEL under them. */
static void ActionRect(int i, int *x, int *y, int *w, int *h)
{
    if (i == 0)
    {
        *x = 10, *y = 20, *w = W - 20, *h = 108;
        return;
    }
    *w = (W - 20 - 2 * 8) / 3;
    *h = 90;
    *x = 10 + (i - 1) * (*w + 8);
    *y = 140;
}

static void MoveRect(int i, int *x, int *y, int *w, int *h)
{
    if (i == 4)
    {
        *x = 10, *y = 202, *w = W - 20, *h = 30;
        return;
    }
    *w = (W - 20 - 8) / 2;
    *h = 82;
    *x = 10 + (i & 1) * (*w + 8);
    *y = 20 + (i >> 1) * (*h + 8);
}

/* A big glossy key; returns its darker shade, for the text's shadow. */
static u16 BigKey(int x, int y, int w, int h, u16 colour, bool8 on, bool8 focus, bool8 pressed)
{
    u16 c = on ? colour : Grey(colour), lo = Darker(c, 3);
    int dy = pressed ? 2 : 0;

    if (focus && on)
        RoundRect(x - 3, y - 3, w + 6, h + 6, 12, C_GOLD);
    RoundRect(x, y + 3, w, h, 10, C8(10, 10, 14));
    RoundGradient(x, y + dy, w, h, 10, Lighter(c, 2), c, h / 2);
    FillRect(x + 8, y + h - 3 + dy, w - 16, 1, lo);
    return lo;
}

static void DrawBattleBackground(void)
{
    Gradient(0, 0, W, H, C8(34, 38, 46), C8(20, 22, 28));
    for (int y = 0; y < H; y += 4)
        FillRect(0, y, W, 1, C8(30, 34, 41));
    Shell(0, 0, W, 12);
    FillRect(0, 12, W, 1, C_RED_DK);
    Lens(10, 6, 3);
    Leds(20, 2);
}

static void DrawPartyBalls(const ViewState *s, int cx, int y)
{
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        int x = cx - PARTY_SIZE * 6 + i * 12 + 5;

        Disc(x, y, 5, C_INK);
        Disc(x, y, 4, C_WHITE);
        if (s->b.balls[i])
        {
            u16 top = s->b.balls[i] == 1 ? C_BRIGHTRED : C_SHADOW;

            for (int dy = -4; dy < 0; dy++)
                for (int dx = -4; dx <= 4; dx++)
                    if (dx * dx + dy * dy <= 18)
                        Put(x + dx, y + dy, top);
        }
        FillRect(x - 4, y, 9, 1, C_INK);
    }
}

static void DrawActions(const ViewState *s)
{
    static const u8 sRgb[4][3] = { {214, 44, 48}, {236, 176, 40}, {60, 176, 92}, {60, 120, 220} };
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
            u16 mark = Lighter(on ? C8(214, 44, 48) : Grey(C8(214, 44, 48)), 2);
            int cx = x + w / 2, cy = y + h / 2;

            Ring(cx, cy, 40, 3, mark);
            FillRect(cx - 40, cy - 1, 28, 3, mark);
            FillRect(cx + 13, cy - 1, 28, 3, mark);
            Ring(cx, cy, 11, 3, mark);
            TextCentered(FONT_NORMAL, label, cx, cy - 8, on ? C_WHITE : C_MUTED, lo);
            continue;
        }
        TextCentered(FONT_NORMAL, label, x + w / 2, y + h - 28, on ? C_WHITE : C_MUTED, lo);
        if (i == 1)
            DrawIcon(sIconBag, x + w / 2 - 12, y + 14, 2, on);
        else if (i == 2)
            DrawPartyBalls(s, x + w / 2, y + 30);
        else
            DrawIcon(sIconRun, x + w / 2 - 12, y + 14, 2, on);
    }
}

static void DrawMoves(const ViewState *s)
{
    int x, y, w, h;

    for (int i = 0; i < MAX_MON_MOVES; i++)
    {
        u16 move = s->b.moves[i], lo;
        u8 type, buf[16], *p;
        bool8 pressed = s->pressed == HIT_BATTLE + i;
        int tw;

        MoveRect(i, &x, &y, &w, &h);
        if (move == MOVE_NONE)
        {
            RoundBox(x, y, w, h, 10, C8(30, 34, 41), C8(44, 48, 58));
            continue;
        }
        type = gBattleMoves[move].type;
        lo = BigKey(x, y, w, h, TypeColour(type), TRUE, s->b.cursor == i, pressed);
        if (pressed)
            y += 2;
        Text(FONT_NORMAL, gMoveNames[move], x + 10, y + 9, C_WHITE, lo, TRUE);
        tw = TextWidth(FONT_SMALL, gTypeNames[type]) + 12;
        RoundRect(x + 9, y + 32, tw, 16, 7, lo);
        Text(FONT_SMALL, gTypeNames[type], x + 15, y + 32, C_WHITE, lo, TRUE);
        p = StringCopy(buf, Ascii("PP "));
        p = ConvertIntToDecimalStringN(p, s->b.pp[i], STR_CONV_MODE_LEFT_ALIGN, 2);
        *p++ = CHAR_SLASH;
        ConvertIntToDecimalStringN(p, s->b.maxPp[i], STR_CONV_MODE_LEFT_ALIGN, 2);
        TextRight(FONT_SMALL, buf, x + w - 10, y + h - 30, s->b.pp[i] ? C_WHITE : C_BRIGHTRED, lo);
        FillRect(x + 10, y + h - 12, w - 20, 4, lo);
        if (s->b.maxPp[i])
            FillRect(x + 10, y + h - 12, (w - 20) * s->b.pp[i] / s->b.maxPp[i], 4, C_WHITE);
    }
    MoveRect(4, &x, &y, &w, &h);
    RoundRect(x, y, w, h, 8, s->pressed == HIT_BATTLE + 4 ? C_KEY_LO : C_KEY);
    Gradient(x + 4, y + 2, w - 8, 8, C_KEY_HI, C_KEY);
    TextCentered(FONT_NORMAL, Ascii("CANCEL"), x + w / 2, y + h / 2 - 8, C_WHITE, C_INK);
}

static void RenderBattle(const ViewState *s)
{
    DrawBattleBackground();
    if (s->b.choose == PORT_BATTLE_MOVE)
        DrawMoves(s);
    else
        DrawActions(s);
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

static void DrawPad(void)
{
    Shell(COLUMN_X, 0, W - COLUMN_X, H);
    FillRect(COLUMN_X, 0, 4, H, C_RED_DK);
    FillRect(COLUMN_X + 1, 0, 1, H, C_SEAM);
    for (int i = 0; i < MENU_COUNT; i++)
        Key(COLUMN_X + 8, i * PAD_H + 4, W - COLUMN_X - 13, PAD_H - 8, Ascii(sPadLabels[i]), NULL, TRUE, FALSE,
            sPadPressed == i);
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

    Header(NULL, NULL);
    Shell(0, HEADER_H + 1, W, H - HEADER_H - 1);
    /* the ball, a little shadow under it */
    Disc(cx + 3, cy + 4, r + 3, C_RED_DK);
    Disc(cx, cy, r + 3, C_INK);
    HalfDisc(cx, cy, r, TRUE, C_RED_HI);
    HalfDisc(cx, cy, r, FALSE, C_WHITE);
    Disc(cx - r / 3, cy - r / 2, r / 6, C8(255, 150, 150));
    FillRect(cx - r, cy - 4, 2 * r + 1, 9, C_INK);
    Disc(cx, cy, 17, C_INK);
    Disc(cx, cy, 13, C_WHITE);
    Ring(cx, cy, 9, 1, C8(190, 194, 202));
    TextCentered(FONT_NORMAL, Ascii("POKEMON FIRERED"), cx, cy + r + 14, C_WHITE, C_RED_DK);
    CtrBottom_Blit(sCanvas, 0, W);
}

/* The 240x160 picture at (0, GAME_Y), on a dark ground above and below. */
void CtrBottom_ShowGameFrame(const u16 *frame)
{
    if (!sGameShown)
    {
        sGameShown = TRUE;
        DrawPad();
        CtrBottom_Blit(sCanvas, COLUMN_X, W);
    }
    for (int x = 0; x < GBA_W; x++)
    {
        u16 *col = sCanvas + x * H + (H - 1);
        u16 top = C_LETTERBOX, bottom = C_LETTERBOX;
        int y = 0;

        for (; y < GAME_Y; y++)
            col[-y] = top;
        for (int sy = 0; sy < GBA_H; sy++, y++)
            col[-y] = sLut[frame[sy * GBA_W + x] & 0x7FFF];
        for (; y < H; y++)
            col[-y] = bottom;
    }
    CtrBottom_Blit(sCanvas, 0, GBA_W);
}

/* ------------------------------------------------------------------------ */
/* Touch                                                                    */
/* ------------------------------------------------------------------------ */

static u8 BattleHitTest(const ViewState *s, int x, int y)
{
    bool8 moves = s->b.choose == PORT_BATTLE_MOVE;

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
    if (x < COLUMN_X && sScreen == SCR_OPTIONS)
        return OptionsHitTest(x, y);
    if (x >= COLUMN_X)
    {
        int i = (y - KEYS_Y) / KEY_STEP;

        if (y < KEYS_Y)
            return HIT_NONE;
        return HIT_BUTTON + (i < MENU_COUNT ? i : MENU_COUNT - 1);
    }
    if (y >= PARTY_Y - 4)
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

static void Activate(const ViewState *s, u8 hit)
{
    if (s->battle)
    {
        if (s->b.choose && hit >= HIT_BATTLE && hit < HIT_BATTLE + 5
         && (s->b.choose == PORT_BATTLE_MOVE || hit < HIT_BATTLE + 4))
        {
            PlaySE(SE_SELECT);
            sBattleTap = hit - HIT_BATTLE;
            sBattleTapKind = s->b.choose;
        }
        return;
    }
    if (hit >= HIT_TAB && hit < HIT_COUNT)
    {
        OptionsActivate(hit);
        return;
    }
    /* OPTION shows the port's own options screen, or goes back to the map. */
    if (hit == HIT_BUTTON + MENU_OPTION)
    {
        PlaySE(SE_SELECT);
        sScreen = sScreen == SCR_OPTIONS ? SCR_MAP : SCR_OPTIONS;
        return;
    }
    if (!s->idle)
        return;
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

/* While a menu is shown the column's buttons are held as long as touched. */
static void ProcessPadTouch(bool active, u16 x, u16 y)
{
    u8 pad = active && x >= COLUMN_X ? (y / PAD_H < MENU_COUNT ? y / PAD_H : MENU_COUNT - 1) : 0xFF;

    if (pad != sPadPressed)
    {
        sPadPressed = pad;
        DrawPad();
        CtrBottom_Blit(sCanvas, COLUMN_X, W);
    }
    if (sInjectFrames == 0)
        sInjected = pad != 0xFF ? sPadKeys[pad] : 0;
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
    if (CtrBottom_TakesGameFrame())
    {
        /* the picture itself arrives from CtrGame_VBlank */
        ProcessPadTouch(active, x, y);
        return;
    }
    if (sGameShown)
    {
        /* back from a menu: the panel again, from scratch */
        sGameShown = FALSE;
        sPadPressed = 0xFF;
        if (sInjectFrames == 0)
            sInjected = 0;
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
