#!/usr/bin/env python3
"""The pieces FireRed's rooms stand up as (src/voxel/voxel_room.c).

The GBA draws a room at 45 degrees: a thing H pixels tall standing on a row
of cells is drawn H pixels further north than it stands. So each object here
is a rectangle of its drawing and a height: the bottom H pixel rows of the
rectangle are its front, stood up at the rectangle's south edge, and the
rows above them its top, laid H pixels up. Seen from the GBA's angle it is
the drawing; from anywhere else, a box. A card is a box all front (a plant,
a chair); a wall is the room's top rows, all front, opaque.

Objects are listed by the tileset they are drawn from (ROOM_OBJECTS), each
the metatiles of its rectangle; wherever a room is drawn with them, they
stand. The cells under an object keep only the floor (the metatile's lower
layer) where the object is drawn on the upper one. Everything else in a room
lies flat - a guess from the collision stood rugs and tables up as tents.

Used by fr_gen_trees.py, which packs the art in the tree texture.
"""

import json
import os
import struct

import fr_art
import fr_map_render

# (cells, height in pixels). Cells row by row, north first; None matches
# anything (and is not part of the object).
ROOM_OBJECTS = {
    "gTileset_Building": [
        ([[0x04C, 0x04D], [0x054, 0x055]], 10),          # the table
        ([[0x04B]], 14), ([[0x04E]], 14),                 # its chairs
        ([[0x057], [0x05F]], 30), ([[0x047], [0x04F]], 30),   # pot plants
        ([[0x067], [0x05F]], 30), ([[0x09B], [0x093]], 30), ([[0x09C], [0x094]], 30),
    ],
    "gTileset_GenericBuilding1": [
        ([[0x283, 0x284, 0x285], [0x28B, 0x28C, 0x28D], [0x293, 0x294, 0x295]], 10),  # bed
        ([[0x035], [0x28E], [0x296]], 30),                # television on its table
    ],
    "gTileset_PokemonCenter": [
        # the counter, nurse's gap and all
        ([[0x2B1, 0x2B2, 0x2B3, 0x290, 0x363, 0x2B4, 0x2B5],
          [0x2B9, 0x2BC, 0x2BC, 0x298, 0x2BC, 0x2BC, 0x2BD]], 12),
        ([[0x29C, 0x29D], [0x2A4, 0x2A5]], 12),           # the table
        ([[0x2F5]], 8), ([[0x2FD]], 8),                   # its stools
    ],
    "gTileset_Mart": [
        ([[0x296, 0x297], [0x29E, 0x29F], [0x2A6, 0x2A7], [0x2AE, 0x2AF]], 40),  # shelves
        ([[0x296], [0x29E], [0x2A6], [0x2AE]], 40),
        ([[0x2A8, 0x2A9, 0x2AA], [0x2B0, 0x2B1, 0x2B2]], 12),   # the counter
        ([[0x2B7, 0x2BC], [0x2C1, 0x2C2]], 12),                  # the low counter
        ([[0x29D], [0x2A5], [0x2AD]], 30),                       # the display case
        ([[0x2B6]], 14),                                          # the plant's pot
    ],
}
WALL_ROWS = 2           # a room's back wall, from its top
VOID_SHARE = 0.85
INDOOR = ("MAP_TYPE_INDOOR",)


def layer(ts, entries, which):
    out = [[None] * 16 for _ in range(16)]
    for q in range(4):
        entry = entries[which * 4 + q]
        data = ts.subtile(entry & 0x3FF, (entry >> 12) & 0xF)
        fx, fy = bool(entry & 0x400), bool(entry & 0x800)
        for y in range(8):
            for x in range(8):
                out[(q >> 1) * 8 + y][(q & 1) * 8 + x] = data[(7 - y if fy else y) * 8 + (7 - x if fx else x)]
    return out


def indoor_layouts(root):
    layouts = json.load(open(os.path.join(root, "data", "layouts", "layouts.json"),
                             encoding="utf-8"))["layouts"]
    wanted = set()
    maps = os.path.join(root, "data", "maps")
    for name in os.listdir(maps):
        path = os.path.join(maps, name, "map.json")
        if os.path.exists(path):
            m = json.load(open(path, encoding="utf-8"))
            if m.get("map_type") in INDOOR:
                wanted.add(m.get("layout"))
    for index, entry in enumerate(layouts, start=1):
        if entry.get("id") in wanted:
            yield index, entry["id"]


class Room:
    def __init__(self, layout_id):
        self.L = fr_map_render.FrLayout(layout_id)
        self.w, self.h = self.L.w, self.L.h
        self._void = {}

    def m(self, x, y):
        return self.L.metatile(x, y)

    def tileset_of(self, m):
        return self.L.primary if m < 0x280 else self.L.secondary

    def entries(self, m):
        return self.L.entries(m)

    def void(self, x, y):
        m = self.m(x, y)
        if m not in self._void:
            px = self.L.metatile_image(m).convert("RGB").load()
            black = sum(1 for j in range(16) for i in range(16) if px[i, j] == (0, 0, 0))
            self._void[m] = black >= VOID_SHARE * 256
        return self._void[m]


def match_objects(room):
    """[(cells {(x, y)}, x0, x1, ybot, h)] for each listed object found."""
    found, taken = [], set()
    specs = []
    for ts in (room.L.primary, room.L.secondary):
        for cells, h in ROOM_OBJECTS.get(ts, ()):
            specs.append((cells, h))
    specs.sort(key=lambda s: -sum(1 for row in s[0] for c in row if c is not None))
    for cells, h in specs:
        rows, cols = len(cells), len(cells[0])
        for y in range(room.h - rows + 1):
            for x in range(room.w - cols + 1):
                here = {(x + i, y + j) for j in range(rows) for i in range(cols)
                        if cells[j][i] is not None}
                if here & taken:
                    continue
                if all(room.m(x + i, y + j) == cells[j][i] for j in range(rows) for i in range(cols)
                       if cells[j][i] is not None):
                    found.append((here, x, x + cols, y + rows, h))
                    taken |= here
    return found, taken


def walls(room, taken):
    """The room's back wall: each column's first WALL_ROWS cells that are not
    the black round the room, stood up at the last one's south edge."""
    out = []
    for x in range(room.w):
        y0 = next((y for y in range(room.h) if not room.void(x, y)), None)
        if y0 is None:
            continue
        cells = [(x, y) for y in range(y0, min(room.h, y0 + WALL_ROWS)) if (x, y) not in taken]
        if len(cells) != WALL_ROWS:
            continue
        out.append((set(cells), x, x + 1, y0 + WALL_ROWS, WALL_ROWS * 16))
    return out


def floor_near(room, x, y, skip):
    for d in range(1, 6):
        for dx, dy in ((0, d), (0, -d), (-d, 0), (d, 0)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < room.w and 0 <= ny < room.h and (nx, ny) not in skip \
                    and not room.void(nx, ny) and not room.L.collision(nx, ny):
                return room.m(nx, ny)
    return room.m(x, y)


FLAG_WEST, FLAG_EAST, FLAG_NO_GROUND, FLAG_BARE = 1, 2, 4, 8


def build(root, place_art):
    """place_art(rgba16x16) -> (sx, sy). Returns [(layout index, [cell rows])]."""
    out = []
    for index, lid in indoor_layouts(root):
        try:
            room = Room(lid)
        except Exception:
            continue
        objects, taken = match_objects(room)
        pieces = [(o, False) for o in objects] + [(w, True) for w in walls(room, taken)]
        all_cells = set().union(*[p[0][0] for p in pieces]) if pieces else set()
        rows = []
        for (cells, x0, x1, ybot, h), wall in pieces:
            for (x, y) in sorted(cells, key=lambda c: (c[1], c[0])):
                m = room.m(x, y)
                ts = fr_art.Tilesets(room.L.primary, room.L.secondary) if not hasattr(room, "ts") else room.ts
                room.ts = ts
                e = room.entries(m)
                top = layer(ts, e, 1)
                upper = any(top[j][i][1] for j in range(16) for i in range(16)) and not wall
                if upper:
                    art = [[(top[j][i][0] + (255,)) if top[j][i][1] else None for i in range(16)]
                           for j in range(16)]
                else:
                    img = room.L.metatile_image(m).convert("RGB").load()
                    art = [[img[i, j] + (255,) for i in range(16)] for j in range(16)]
                sx, sy = place_art(art)
                flags = 0
                if (x - 1, y) not in cells:
                    flags |= FLAG_WEST
                if (x + 1, y) not in cells:
                    flags |= FLAG_EAST
                if wall:
                    flags |= FLAG_NO_GROUND
                    ground = 0
                elif upper:
                    flags |= FLAG_BARE
                    ground = m
                else:
                    ground = floor_near(room, x, y, all_cells)
                rows.append((y, x, h, ybot, flags, sx, sy, ground))
        if rows:
            rows.sort()
            out.append((index, lid, rows))
    return out


def write_table(rooms, path):
    lines = ["/* Generated by scripts/fr_gen_trees.py (fr_gen_rooms.py): each room's",
             " * standing pieces, cell by cell, row by row. A piece is a rectangle of",
             " * the drawing ending at row `ybot`, `h` pixels tall: its rows within h",
             " * of ybot stand at ybot's edge, those above lie h up (voxel_room.c). */",
             "#ifndef CTR_VOXEL_ROOM_TABLE_H", "#define CTR_VOXEL_ROOM_TABLE_H", "",
             "#define ROOM_WEST 1", "#define ROOM_EAST 2", "#define ROOM_NO_GROUND 4",
             "#define ROOM_BARE 8", "",
             "static const struct { unsigned short layout, first, count; } sRoomLayouts[] = {"]
    first = 0
    for index, lid, rows in rooms:
        lines.append("    { %d, %d, %d }, /* %s */" % (index, first, len(rows), lid))
        first += len(rows)
    lines += ["};", "",
              "static const struct",
              "{",
              "    unsigned char y, x, h, ybot, flags;",
              "    unsigned short sx, sy, ground;",
              "} sRoomCells[] = {"]
    for index, lid, rows in rooms:
        for r in rows:
            lines.append("    { %d, %d, %d, %d, %d, %d, %d, 0x%03X }," % r)
    lines += ["};", "", "#endif", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
