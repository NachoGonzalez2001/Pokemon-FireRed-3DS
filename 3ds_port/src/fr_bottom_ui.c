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
#include "3ds_input.h"
#include "3ds_log.h"

/* text.c, start_menu.c and region_map.c, under PORT_BRIDGE */
void Port_DecompressGlyph(u8 fontId, u16 glyphId);
void CtrStartMenu_Request(u8 action);
bool8 CtrStartMenu_Pending(void);
bool8 CtrStartMenu_Busy(void);
void Port_GetRegionMapArt(u8 region, const void **mapGfx, const void **mapTilemap, const void **bgGfx,
                          const void **bgTilemap, const u16 **pal, const void **playerGfx, const u16 **playerPal);
u8 Port_GetRegionMapPlayer(s16 *x, s16 *y);
uint32_t CtrGame_Frames(void);
#ifdef CTR_INPUT_SCRIPT
bool CtrScript_Touch(u16 *x, u16 *y);
#endif

/* start_menu.c's STARTMENU_* */
enum { MENU_POKEDEX, MENU_POKEMON, MENU_BAG, MENU_PLAYER, MENU_SAVE, MENU_OPTION, MENU_COUNT };

#define W CTR_BOTTOM_WIDTH
#define H CTR_BOTTOM_HEIGHT
#define COLUMN_X 240
#define BUTTON_H (H / MENU_COUNT)
#define HEADER_H 24
#define MAP_Y HEADER_H
#define MAP_W 240
#define MAP_H 160
/* the map screen's top bar rows, which hold the location's name in game */
#define MAP_CROP 24
#define PARTY_Y (MAP_Y + MAP_H - MAP_CROP)
#define PARTY_SLOT_W 40
#define GBA_W 240
#define GBA_H 160
#define GAME_Y ((H - GBA_H) / 2)

/* Touch targets */
enum { HIT_NONE, HIT_BUTTON, HIT_PARTY = HIT_BUTTON + MENU_COUNT, HIT_BATTLE, HIT_COUNT = HIT_BATTLE + 5 };

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
static u8 sPadPressed = 0xFF;

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
            (*s)++;
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

/* An ASCII label in the game's charset (capitals, digits, spaces). */
static const u8 *Ascii(const char *s)
{
    static u8 buf[16];
    int i;

    for (i = 0; s[i] && i < (int)sizeof(buf) - 1; i++)
    {
        char c = s[i];

        buf[i] = c >= 'A' && c <= 'Z' ? CHAR_A + (c - 'A') : c >= '0' && c <= '9' ? CHAR_0 + (c - '0') : CHAR_SPACE;
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

static void Snapshot(ViewState *s)
{
    memset(s, 0, sizeof(*s));
    s->pressed = sTouchHit;
    if (gSaveBlock2Ptr == NULL || gSaveBlock1Ptr == NULL)
        return;
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
/* Colours                                                                  */
/* ------------------------------------------------------------------------ */

#define C_PANEL    Rgb(29, 29, 27)
#define C_HEADER   Rgb(24, 5, 4)
#define C_HEADER_L Rgb(29, 10, 8)
#define C_WHITE    Rgb(31, 31, 31)
#define C_INK      Rgb(6, 6, 7)
#define C_INK_SH   Rgb(22, 22, 21)
#define C_GREY     Rgb(18, 18, 18)
#define C_SLOT     Rgb(31, 31, 30)
#define C_SLOT_EDGE Rgb(20, 19, 17)
#define C_RAIL     Rgb(18, 3, 3)
#define C_RAIL_L   Rgb(24, 6, 5)
#define C_PLATE    Rgb(31, 30, 28)
#define C_PLATE_ON Rgb(31, 24, 20)
#define C_PLATE_OFF Rgb(23, 22, 21)

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

static void DrawMap(const ViewState *s)
{
    if (!s->onMap || !BuildMapCache(s->region))
    {
        FillRect(0, MAP_Y, MAP_W, MAP_H - MAP_CROP, C_PANEL);
        return;
    }
    for (int x = 0; x < MAP_W; x++)
    {
        u16 *col = sCanvas + x * H + (H - 1 - MAP_Y);

        for (int y = MAP_CROP; y < MAP_H; y++)
            col[-(y - MAP_CROP)] = sMapCache[y * MAP_W + x];
    }
    if (sPlayerIconReady)
    {
        /* a 16x16 sprite centred on the cell */
        int x = 8 * s->mapX + 36 - 8, y = MAP_Y - MAP_CROP + 8 * s->mapY + 36 - 8;

        for (int t = 0; t < 4; t++)
            DrawTile4(sPlayerIcon + t * 32, x + (t & 1) * 8, y + (t >> 1) * 8, sPlayerPal, FALSE, FALSE);
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

static void DrawPlate(int i, const u8 *label, bool8 on, bool8 pressed)
{
    int y = i * BUTTON_H;
    u16 fill = !on ? C_PLATE_OFF : pressed ? C_PLATE_ON : C_PLATE;

    DrawBox(COLUMN_X + 5, y + 3, W - COLUMN_X - 9, BUTTON_H - 6, fill, C_INK);
    FillRect(COLUMN_X + 6, y + 4, 3, BUTTON_H - 8, on ? C_HEADER_L : C_GREY);
    TextCentered(FONT_NORMAL, label, COLUMN_X + 4 + (W - COLUMN_X) / 2, y + BUTTON_H / 2 - 7,
                 on ? C_INK : C_GREY, on ? C_INK_SH : C_PLATE_OFF);
}

static void DrawRail(void)
{
    FillRect(COLUMN_X, 0, W - COLUMN_X, H, C_RAIL);
    FillRect(COLUMN_X, 0, 2, H, C_RAIL_L);
}

static void DrawColumn(const ViewState *s)
{
    DrawRail();
    for (int i = 0; i < MENU_COUNT; i++)
        DrawPlate(i, MenuLabel(s, i), ((s->enabled >> i) & 1) && s->idle, s->pressed == HIT_BUTTON + i);
}

static void DrawHeader(const ViewState *s)
{
    u8 buf[32], *p;

    FillRect(0, 0, COLUMN_X, HEADER_H, C_HEADER);
    FillRect(0, HEADER_H - 2, COLUMN_X, 2, C_HEADER_L);
    if (s->onMap)
    {
        GetMapName(buf, s->mapsec, 0);
        Text(FONT_NORMAL, buf, 6, 4, C_WHITE, C_HEADER_L, TRUE);
    }
    p = ConvertIntToDecimalStringN(buf, s->hours, STR_CONV_MODE_LEFT_ALIGN, 3);
    *p++ = CHAR_COLON;
    ConvertIntToDecimalStringN(p, s->minutes, STR_CONV_MODE_LEADING_ZEROS, 2);
    TextRight(FONT_NORMAL, buf, COLUMN_X - 6, 4, C_WHITE, C_HEADER_L);
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
    int x0 = (MAP_W - PARTY_SIZE * PARTY_SLOT_W) / 2;

    FillRect(0, PARTY_Y, MAP_W, H - PARTY_Y, s->pressed == HIT_PARTY ? C_PLATE_ON : C_PANEL);
    FillRect(0, PARTY_Y, MAP_W, 1, C_SLOT_EDGE);
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        const MonView *m = &s->party[i];
        int x = x0 + i * PARTY_SLOT_W;

        if (i >= s->partyCount || m->species == SPECIES_NONE)
        {
            DrawBox(x + 4, PARTY_Y + 8, 32, 32, C_PANEL, C_SLOT_EDGE);
            continue;
        }
        DrawMonIcon(m, x + 4, PARTY_Y + 4);
        if (!m->egg)
        {
            int w = 30, fill = m->maxHp ? (w * m->hp + m->maxHp - 1) / m->maxHp : 0;
            u16 c = m->hp * 2 > m->maxHp ? Rgb(7, 27, 9) : m->hp * 5 > m->maxHp ? Rgb(30, 24, 2) : Rgb(29, 5, 4);

            u8 buf[8];

            DrawBox(x + 4, PARTY_Y + 40, w + 2, 6, Rgb(10, 10, 10), C_INK);
            FillRect(x + 5, PARTY_Y + 41, fill, 4, c);
            buf[0] = CHAR_LV;
            ConvertIntToDecimalStringN(buf + 1, m->level, STR_CONV_MODE_LEFT_ALIGN, 3);
            TextCentered(FONT_SMALL, buf, x + PARTY_SLOT_W / 2, PARTY_Y + 50, C_INK, C_INK_SH);
        }
    }
}

static void RenderPanel(const ViewState *s)
{
    DrawHeader(s);
    DrawMap(s);
    DrawParty(s);
    DrawColumn(s);
    CtrBottom_Blit(sCanvas, 0, W);
}

/* ------------------------------------------------------------------------ */
/* The battle's page                                                        */
/* ------------------------------------------------------------------------ */

static const u8 sTypeRgb[NUMBER_OF_MON_TYPES][3] = {
    [TYPE_NORMAL]   = {21, 21, 15}, [TYPE_FIGHTING] = {24,  6,  5}, [TYPE_FLYING]  = {20, 17, 30},
    [TYPE_POISON]   = {20,  8, 20}, [TYPE_GROUND]   = {28, 24, 13}, [TYPE_ROCK]    = {23, 20,  7},
    [TYPE_BUG]      = {20, 23,  4}, [TYPE_GHOST]    = {14, 11, 19}, [TYPE_STEEL]   = {23, 23, 26},
    [TYPE_MYSTERY]  = {13, 20, 19}, [TYPE_FIRE]     = {30, 16,  6}, [TYPE_WATER]   = {13, 18, 30},
    [TYPE_GRASS]    = {15, 25, 10}, [TYPE_ELECTRIC] = {31, 26,  6}, [TYPE_PSYCHIC] = {31, 11, 17},
    [TYPE_ICE]      = {19, 28, 28}, [TYPE_DRAGON]   = {14,  7, 31}, [TYPE_DARK]    = {14, 11,  9},
};

static u16 TypeColour(u8 type, bool8 light)
{
    const u8 *c = sTypeRgb[type < NUMBER_OF_MON_TYPES ? type : TYPE_NORMAL];

    if (light)
        return Rgb((c[0] + 31) / 2, (c[1] + 31) / 2, (c[2] + 31) / 2);
    return Rgb(c[0], c[1], c[2]);
}

#define C_BATTLE_BG    Rgb(6, 16, 18)
#define C_BATTLE_LINE  Rgb(10, 24, 25)
#define C_FOCUS        Rgb(31, 27, 6)

/* The action menu: FIGHT across the top, BAG, POKéMON and RUN below it. The
 * move menu: four moves in a 2x2 grid, CANCEL under them. */
static void ActionRect(int i, int *x, int *y, int *w, int *h)
{
    if (i == 0)
    {
        *x = 10, *y = 16, *w = W - 20, *h = 112;
        return;
    }
    *w = (W - 20 - 2 * 8) / 3;
    *h = 92;
    *x = 10 + (i - 1) * (*w + 8);
    *y = 140;
}

static void MoveRect(int i, int *x, int *y, int *w, int *h)
{
    if (i == 4)
    {
        *x = 10, *y = 200, *w = W - 20, *h = 32;
        return;
    }
    *w = (W - 20 - 8) / 2;
    *h = 84;
    *x = 10 + (i & 1) * (*w + 8);
    *y = 16 + (i >> 1) * (*h + 8);
}

/* A plate: white ground, a slanted band of colour, a darker rim; the
 * focused one (the game's cursor) has a gold ring. */
static void DrawSlantPlate(int x, int y, int w, int h, u16 colour, bool8 on, bool8 focus, bool8 pressed)
{
    u16 band = !on ? C_PLATE_OFF : pressed ? Dim(colour) : colour;
    u16 ground = on ? C_WHITE : Rgb(26, 26, 25);

    if (focus && on)
        DrawBox(x - 3, y - 3, w + 6, h + 6, C_FOCUS, C_FOCUS);
    DrawBox(x, y, w, h, ground, C_INK);
    /* the band leans right: it starts a quarter in at the top */
    for (int row = 1; row < h - 1; row++)
    {
        int from = x + w / 4 - (row * (w / 4)) / h;

        FillRect(from, y + row, x + w - 1 - from, 1, band);
    }
    FillRect(x + 1, y + 1, w - 2, 2, on ? C_WHITE : ground);
}

static void DrawPartyBalls(const ViewState *s, int cx, int y)
{
    for (int i = 0; i < PARTY_SIZE; i++)
    {
        int x = cx - PARTY_SIZE * 6 + i * 12;
        u16 top = s->b.balls[i] == 1 ? Rgb(29, 5, 4) : s->b.balls[i] == 2 ? Rgb(16, 16, 16) : Rgb(24, 24, 23);

        DrawBox(x, y, 10, 10, C_WHITE, C_INK);
        FillRect(x + 1, y + 1, 8, 4, s->b.balls[i] ? top : C_WHITE);
        FillRect(x + 1, y + 5, 8, 1, C_INK);
    }
}

static void DrawActions(const ViewState *s)
{
    static const u8 sRgb[4][3] = { {28, 6, 6}, {29, 23, 5}, {6, 22, 9}, {6, 13, 28} };
    bool8 on = s->b.choose == PORT_BATTLE_ACTION;

    for (int i = 0; i < 4; i++)
    {
        int x, y, w, h;
        const u8 *label = i == 0 ? Ascii("FIGHT") : i == 1 ? gText_MenuBag : i == 2 ? gText_MenuPokemon : Ascii("RUN");

        ActionRect(i, &x, &y, &w, &h);
        DrawSlantPlate(x, y, w, h, Rgb(sRgb[i][0], sRgb[i][1], sRgb[i][2]), on, s->b.cursor == i,
                       s->pressed == HIT_BATTLE + i);
        if (i == 0)
            TextCentered(FONT_NORMAL, label, x + w / 2, y + h / 2 - 7, on ? C_WHITE : C_GREY, on ? C_INK : C_PLATE_OFF);
        else
            TextCentered(FONT_NORMAL, label, x + w / 2, y + h - 22, on ? C_WHITE : C_GREY, on ? C_INK : C_PLATE_OFF);
        if (i == 2)
            DrawPartyBalls(s, x + w / 2, y + 14);
    }
}

static void DrawMoves(const ViewState *s)
{
    int x, y, w, h;

    for (int i = 0; i < MAX_MON_MOVES; i++)
    {
        u16 move = s->b.moves[i];
        u8 type, buf[16], *p;

        MoveRect(i, &x, &y, &w, &h);
        if (move == MOVE_NONE)
        {
            DrawBox(x, y, w, h, C_BATTLE_LINE, C_INK);
            continue;
        }
        type = gBattleMoves[move].type;
        DrawSlantPlate(x, y, w, h, TypeColour(type, FALSE), TRUE, s->b.cursor == i, s->pressed == HIT_BATTLE + i);
        Text(FONT_NORMAL, gMoveNames[move], x + 10, y + 10, C_WHITE, C_INK, TRUE);
        Text(FONT_SMALL, gTypeNames[type], x + 10, y + h - 22, C_WHITE, C_INK, TRUE);
        p = StringCopy(buf, Ascii("PP "));
        p = ConvertIntToDecimalStringN(p, s->b.pp[i], STR_CONV_MODE_LEFT_ALIGN, 2);
        *p++ = CHAR_SLASH;
        ConvertIntToDecimalStringN(p, s->b.maxPp[i], STR_CONV_MODE_LEFT_ALIGN, 2);
        TextRight(FONT_SMALL, buf, x + w - 10, y + h - 22, s->b.pp[i] ? C_WHITE : Rgb(31, 12, 10), C_INK);
    }
    MoveRect(4, &x, &y, &w, &h);
    DrawBox(x, y, w, h, s->pressed == HIT_BATTLE + 4 ? C_PLATE_ON : C_PLATE, C_INK);
    TextCentered(FONT_NORMAL, Ascii("CANCEL"), x + w / 2, y + h / 2 - 7, C_INK, C_INK_SH);
}

static void RenderBattle(const ViewState *s)
{
    FillRect(0, 0, W, H, C_BATTLE_BG);
    for (int y = 4; y < H; y += 8)
        FillRect(0, y, W, 1, C_BATTLE_LINE);
    FillRect(0, 0, W, 6, C_BATTLE_LINE);
    FillRect(0, H - 4, W, 4, C_BATTLE_LINE);
    if (s->b.choose == PORT_BATTLE_MOVE)
        DrawMoves(s);
    else
        DrawActions(s);
    CtrBottom_Blit(sCanvas, 0, W);
}

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
    DrawRail();
    for (int i = 0; i < MENU_COUNT; i++)
        DrawPlate(i, Ascii(sPadLabels[i]), TRUE, sPadPressed == i);
}

/* The 240x160 picture at (0, GAME_Y); the rows above and below carry its
 * first and last rows on, dimmed. */
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
        u16 top = Dim(sLut[frame[x] & 0x7FFF]), bottom = Dim(sLut[frame[(GBA_H - 1) * GBA_W + x] & 0x7FFF]);
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
    if (x >= COLUMN_X)
        return HIT_BUTTON + (y / BUTTON_H < MENU_COUNT ? y / BUTTON_H : MENU_COUNT - 1);
    if (y >= PARTY_Y)
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
        if (s->b.choose && hit >= HIT_BATTLE && hit < HIT_COUNT
         && (s->b.choose == PORT_BATTLE_MOVE || hit < HIT_BATTLE + 4))
        {
            PlaySE(SE_SELECT);
            sBattleTap = hit - HIT_BATTLE;
            sBattleTapKind = s->b.choose;
        }
        return;
    }
    if (!s->idle)
        return;
    if (hit >= HIT_BUTTON && hit < HIT_BUTTON + MENU_COUNT)
    {
        u8 i = hit - HIT_BUTTON;

        if ((s->enabled >> i) & 1)
            Open(i);
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
    u8 pad = active && x >= COLUMN_X ? (y / BUTTON_H < MENU_COUNT ? y / BUTTON_H : MENU_COUNT - 1) : 0xFF;

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
