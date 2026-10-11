/*
 * The bottom screen, game side, for FireRed: what it shows and what a touch
 * does. Modelled on the Emerald port's 3ds_bottom_ui.c, reduced to FireRed's
 * start menu for now.
 *
 * A column of buttons on the right holds the start menu's entries: POKéDEX,
 * POKéMON, BAG, the player (trainer card), SAVE and OPTION. A tap asks the
 * game for that entry and presses START (start_menu.c, CtrStartMenu_Request),
 * so the game opens it exactly as if it had been chosen from its menu, on the
 * top screen. The 240x240 area on the left shows the party (icons, names,
 * levels, HP) under a header with the location and the play time; a tap on
 * a party slot opens the party menu.
 *
 * Everything is drawn by the CPU into a 320x240 canvas laid out like the
 * bottom framebuffer (RGB565, column-major, each column bottom-to-top) with
 * the game's own fonts and icons, and only when what it shows changes: every
 * frame costs a snapshot of the shown values and a memcmp.
 */

#include <string.h>

#include "global.h"
#include "main.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "fieldmap.h"
#include "money.h"
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
#include "constants/songs.h"
#include "port_platform.h"

#include "3ds_bottom.h"
#include "3ds_input.h"
#include "3ds_log.h"

/* text.c and start_menu.c, under PORT_BRIDGE */
void Port_DecompressGlyph(u8 fontId, u16 glyphId);
void CtrStartMenu_Request(u8 action);
bool8 CtrStartMenu_Pending(void);
bool8 CtrStartMenu_Busy(void);
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
#define SLOT_W 116
#define SLOT_H 68

/* Touch targets */
enum { HIT_NONE, HIT_BUTTON, HIT_SLOT = HIT_BUTTON + MENU_COUNT, HIT_COUNT = HIT_SLOT + PARTY_SIZE };

typedef struct {
    u16 species, iconSpecies, hp, maxHp;
    u8 level, egg;
    u8 name[POKEMON_NAME_LENGTH + 1];
} MonView;

typedef struct {
    MonView party[PARTY_SIZE];
    u8 partyCount;
    u8 enabled;      /* bit per MENU_* */
    u8 idle;         /* the field takes the column's taps */
    u8 pressed;      /* HIT_* under the finger */
    u16 mapsec;
    u16 hours;
    u8 minutes;
    u8 player[PLAYER_NAME_LENGTH + 1];
} ViewState;

static u16 sCanvas[W * H];
static ViewState sShown;
static bool8 sDrawn;
static u8 sTouchHit;
static u8 sInjectFrames;
static u16 sInjected;

/* ------------------------------------------------------------------------ */
/* Canvas                                                                   */
/* ------------------------------------------------------------------------ */

static u16 Rgb(u8 r, u8 g, u8 b) /* 0..31 each */
{
    return (u16)((r << 11) | ((g << 1 | g >> 4) << 5) | b);
}

static u16 FromBgr555(u16 c)
{
    return Rgb(c & 31, (c >> 5) & 31, (c >> 10) & 31);
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

/* A 4bpp tile of 8x8; colour 0 is transparent. */
static void DrawTile4(const u8 *tile, int x, int y, const u16 *pal565)
{
    for (int py = 0; py < 8; py++)
        for (int px = 0; px < 8; px++)
        {
            u8 v = tile[py * 4 + px / 2];

            v = (px & 1) ? v >> 4 : v & 15;
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

/* ------------------------------------------------------------------------ */
/* State                                                                    */
/* ------------------------------------------------------------------------ */

/* The player stands in the field with nothing else going on. */
static bool8 FieldIdle(void)
{
    return gMain.callback1 == CB1_Overworld && !ArePlayerFieldControlsLocked() && !ScriptContext_IsEnabled()
        && gPlayerAvatar.tileTransitionState == T_NOT_MOVING && !gPaletteFade.active
        && !CtrStartMenu_Busy() && !CtrStartMenu_Pending();
}

static void Snapshot(ViewState *s)
{
    memset(s, 0, sizeof(*s));
    s->pressed = sTouchHit;
    if (gSaveBlock2Ptr == NULL || gSaveBlock1Ptr == NULL)
        return;
    s->idle = FieldIdle();
    s->enabled = (1 << MENU_BAG) | (1 << MENU_PLAYER) | (1 << MENU_SAVE) | (1 << MENU_OPTION);
    if (FlagGet(FLAG_SYS_POKEMON_GET))
        s->enabled |= 1 << MENU_POKEMON;
    if (FlagGet(FLAG_SYS_POKEDEX_GET))
        s->enabled |= 1 << MENU_POKEDEX;
    s->mapsec = gMapHeader.regionMapSectionId;
    s->hours = gSaveBlock2Ptr->playTimeHours;
    s->minutes = gSaveBlock2Ptr->playTimeMinutes;
    StringCopyN(s->player, gSaveBlock2Ptr->playerName, PLAYER_NAME_LENGTH);
    s->player[PLAYER_NAME_LENGTH] = EOS;

    s->partyCount = gPlayerPartyCount > PARTY_SIZE ? PARTY_SIZE : gPlayerPartyCount;
    for (int i = 0; i < s->partyCount; i++)
    {
        struct Pokemon *mon = &gPlayerParty[i];
        MonView *m = &s->party[i];

        m->species = GetMonData(mon, MON_DATA_SPECIES);
        if (m->species == SPECIES_NONE)
            continue;
        m->egg = GetMonData(mon, MON_DATA_IS_EGG);
        m->iconSpecies = GetIconSpecies(m->species, GetMonData(mon, MON_DATA_PERSONALITY));
        m->hp = GetMonData(mon, MON_DATA_HP);
        m->maxHp = GetMonData(mon, MON_DATA_MAX_HP);
        m->level = GetMonData(mon, MON_DATA_LEVEL);
        GetMonData(mon, MON_DATA_NICKNAME, m->name);
        m->name[POKEMON_NAME_LENGTH] = EOS;
    }
}

/* ------------------------------------------------------------------------ */
/* Drawing                                                                  */
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

static void DrawColumn(const ViewState *s)
{
    FillRect(COLUMN_X, 0, W - COLUMN_X, H, C_RAIL);
    FillRect(COLUMN_X, 0, 2, H, C_RAIL_L);
    for (int i = 0; i < MENU_COUNT; i++)
    {
        int y = i * BUTTON_H;
        bool8 on = (s->enabled >> i) & 1;
        bool8 pressed = s->pressed == HIT_BUTTON + i;
        u16 fill = !on || !s->idle ? C_PLATE_OFF : pressed ? C_PLATE_ON : C_PLATE;

        DrawBox(COLUMN_X + 5, y + 3, W - COLUMN_X - 9, BUTTON_H - 6, fill, C_INK);
        FillRect(COLUMN_X + 6, y + 4, 3, BUTTON_H - 8, on ? C_HEADER_L : C_GREY);
        TextCentered(FONT_NORMAL, MenuLabel(s, i), COLUMN_X + 4 + (W - COLUMN_X) / 2, y + BUTTON_H / 2 - 7,
                     on ? C_INK : C_GREY, on ? C_INK_SH : C_PLATE_OFF);
    }
}

static void DrawHeader(const ViewState *s)
{
    u8 buf[32], *p;

    FillRect(0, 0, COLUMN_X, HEADER_H, C_HEADER);
    FillRect(0, HEADER_H - 2, COLUMN_X, 2, C_HEADER_L);
    if (gSaveBlock2Ptr == NULL)
        return;
    GetMapName(buf, s->mapsec, 0);
    Text(FONT_NORMAL, buf, 6, 4, C_WHITE, C_HEADER_L, TRUE);
    p = ConvertIntToDecimalStringN(buf, s->hours, STR_CONV_MODE_LEFT_ALIGN, 3);
    *p++ = CHAR_COLON;
    ConvertIntToDecimalStringN(p, s->minutes, STR_CONV_MODE_LEADING_ZEROS, 2);
    TextRight(FONT_NORMAL, buf, COLUMN_X - 6, 4, C_WHITE, C_HEADER_L);
}

static void DrawMonIcon(const MonView *m, int x, int y)
{
    const u8 *tiles = Port_ResolveAssetPointer(GetMonIconTiles(m->egg ? SPECIES_EGG : m->iconSpecies, FALSE));
    u8 palIndex = gMonIconPaletteIndices[m->egg ? SPECIES_EGG : m->iconSpecies];
    const u16 *pal = Port_ResolveAssetPointer(gMonIconPaletteTable[palIndex].data);
    u16 pal565[16];

    if (tiles == NULL || pal == NULL)
        return;
    for (int i = 0; i < 16; i++)
        pal565[i] = FromBgr555(pal[i]);
    for (int t = 0; t < 16; t++)
        DrawTile4(tiles + t * 32, x + (t % 4) * 8, y + (t / 4) * 8, pal565);
}

static void DrawHpBar(int x, int y, int w, u16 hp, u16 maxHp)
{
    int fill = maxHp ? (w * hp + maxHp - 1) / maxHp : 0;
    u16 c = hp * 2 > maxHp ? Rgb(7, 27, 9) : hp * 5 > maxHp ? Rgb(30, 24, 2) : Rgb(29, 5, 4);

    DrawBox(x - 1, y - 1, w + 2, 6, Rgb(10, 10, 10), C_INK);
    FillRect(x, y, fill, 4, c);
}

static void DrawSlot(const ViewState *s, int i)
{
    int x = 4 + (i % 2) * (SLOT_W + 4), y = HEADER_H + 4 + (i / 2) * (SLOT_H + 2);
    const MonView *m = &s->party[i];
    u8 buf[16], *p;

    if (i >= s->partyCount || m->species == SPECIES_NONE)
    {
        DrawBox(x, y, SLOT_W, SLOT_H, C_PANEL, C_SLOT_EDGE);
        return;
    }
    DrawBox(x, y, SLOT_W, SLOT_H, s->pressed == HIT_SLOT + i ? C_PLATE_ON : m->hp == 0 && !m->egg ? C_PLATE_OFF : C_SLOT,
            C_SLOT_EDGE);
    DrawMonIcon(m, x + 2, y + 2);
    Text(FONT_NORMAL, m->name, x + 36, y + 5, C_INK, C_INK_SH, TRUE);
    if (m->egg)
        return;
    buf[0] = CHAR_LV;
    ConvertIntToDecimalStringN(buf + 1, m->level, STR_CONV_MODE_LEFT_ALIGN, 3);
    Text(FONT_SMALL, buf, x + 36, y + 21, C_INK, C_INK_SH, TRUE);
    DrawHpBar(x + 8, y + 40, SLOT_W - 16, m->hp, m->maxHp);
    p = ConvertIntToDecimalStringN(buf, m->hp, STR_CONV_MODE_LEFT_ALIGN, 3);
    *p++ = CHAR_SLASH;
    ConvertIntToDecimalStringN(p, m->maxHp, STR_CONV_MODE_LEFT_ALIGN, 3);
    TextRight(FONT_SMALL, buf, x + SLOT_W - 8, y + 48, C_INK, C_INK_SH);
}

static void Render(const ViewState *s)
{
    FillRect(0, 0, COLUMN_X, H, C_PANEL);
    DrawHeader(s);
    for (int i = 0; i < PARTY_SIZE; i++)
        DrawSlot(s, i);
    DrawColumn(s);
    CtrBottom_Blit(sCanvas, 0, W);
}

/* ------------------------------------------------------------------------ */
/* Touch                                                                    */
/* ------------------------------------------------------------------------ */

static u8 HitTest(int x, int y)
{
    if (x >= COLUMN_X)
        return HIT_BUTTON + (y / BUTTON_H < MENU_COUNT ? y / BUTTON_H : MENU_COUNT - 1);
    if (y >= HEADER_H + 4)
    {
        int col = (x - 4) / (SLOT_W + 4), row = (y - HEADER_H - 4) / (SLOT_H + 2);

        if (col >= 0 && col < 2 && row >= 0 && row < 3)
            return HIT_SLOT + row * 2 + col;
    }
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
    if (!s->idle)
        return;
    if (hit >= HIT_BUTTON && hit < HIT_BUTTON + MENU_COUNT)
    {
        u8 i = hit - HIT_BUTTON;

        if ((s->enabled >> i) & 1)
            Open(i);
    }
    else if (hit >= HIT_SLOT && hit < HIT_COUNT && (s->enabled & (1 << MENU_POKEMON))
             && hit - HIT_SLOT < s->partyCount)
    {
        Open(MENU_POKEMON);
    }
}

static void ProcessTouch(const ViewState *s)
{
    const CtrInput *in = CtrInput_Get();
    bool active = in->touchActive;
    u16 x = in->touchX, y = in->touchY;
    static bool wasActive;
    static u8 downHit;

#ifdef CTR_INPUT_SCRIPT
    if (CtrScript_Touch(&x, &y))
        active = true;
#endif
    if (active && !wasActive)
        downHit = HitTest(x, y);
    if (active)
        sTouchHit = HitTest(x, y) == downHit ? downHit : HIT_NONE;
    else
    {
        if (wasActive)
            CtrLog_Write(CTR_LOG_INPUT, "bottom: tap hit %u idle %u frame %lu", sTouchHit, s->idle,
                         (unsigned long)CtrGame_Frames());
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
    memset(sCanvas, 0, sizeof(sCanvas));
    sDrawn = FALSE;
}

void CtrBottom_Frame(void)
{
    ViewState now;

    if (sInjectFrames && --sInjectFrames == 0)
        sInjected = 0;
    Snapshot(&now);
    ProcessTouch(&now);
    now.pressed = sTouchHit;
    if (sDrawn && memcmp(&now, &sShown, sizeof(now)) == 0)
        return;
    Render(&now);
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
