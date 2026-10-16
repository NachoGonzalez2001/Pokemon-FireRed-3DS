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
X = {"xrep": 1}          # its middle column repeats: as long as it is drawn
Y0 = {"yrep": 0}         # its first row repeats

ROOM_OBJECTS = {
    "gTileset_Building": [
        # the GenericBuilding1 houses' tables and pots
        ([[0x0C8, 0x0C9], [0x0D0, 0x0D1]], 10), ([[0x0C6]], 14), ([[0x0C7]], 14),
        ([[0x0F6], [0x0FE]], 30), ([[0x0F5], [0x0FD]], 30),
        ([[0x155], [0x15D]], 30),
        ([[0x0DA, 0x0DB], [0x0E2, 0x0E3]], 12),
        ([[0x035], [0x281], [0x282]], 30),
        # tables and their chairs
        ([[0x04C, 0x04D], [0x054, 0x055]], 10),
        ([[0x04B]], 14), ([[0x04E]], 14),
        ([[0x165, 0x166], [0x16D, 0x16E]], 10),
        ([[0x16F]], 14), ([[0x167]], 14),
        ([[0x128, 0x129], [0x130, 0x131]], 10), ([[0x126]], 14),
        # pot plants, top and pot
        ([[0x057], [0x05F]], 30), ([[0x047], [0x04F]], 30), ([[0x067], [0x05F]], 30),
        ([[0x09B], [0x093]], 30), ([[0x09C], [0x094]], 30),
        ([[0x156], [0x15E]], 30), ([[0x102], [0x103]], 30), ([[0x102], [0x136]], 30),
        ([[0x12E], [0x136]], 30),
    ],
    "gTileset_GenericBuilding1": [
        ([[0x28B, 0x28C, 0x28D], [0x293, 0x294, 0x295]], 10),  # bed (the row above is floor)
        ([[0x035], [0x28E]], 22, {"depth": 6}),           # television; the console lies flat
    ],
    "gTileset_GenericBuilding2": [
        # gatehouse plants
        ([[0x2E9], [0x2F1]], 30), ([[0x2EA], [0x2F1]], 30), ([[0x2E8], [0x2F0]], 30),
        ([[0x2EF], [0x2F7]], 30),
        # the guards' counters, as long as they run, their top the row above
        ([[0x2EB, 0x2EC, 0x2ED], [0x2A4, 0x2A5, 0x2A6]], 16, X),
        ([[0x2FB, 0x2FC, 0x2FD], [0x303, 0x304, 0x305], [0x30B, 0x30C, 0x30D]], 14, X),
        ([[0x2EB, 0x29D, 0x28E], [0x2A4, 0x2A5, 0x296], [None, None, 0x28D], [None, None, 0x295]], 16, X),
        ([[0x2A4, 0x2A5, 0x2A6]], 8, X),
        # north-south dividers, and one turning into a counter
        ([[0x28D, None, None], [0x29C, 0x29F, 0x28E], [0x2A4, 0x2A5, 0x2A6]], 16, Y0),
        ([[0x28D], [0x295]], 16, Y0),
        # the underground path's L-shaped walls
        ([[0x294, 0x2A6], [0x28D, None], [0x29C, None], [0x2A4, 0x2A6]], 16),
        ([[0x2A4, 0x296], [None, 0x28D], [None, 0x29E], [0x2A4, 0x2A6]], 16),
        # tables, chairs, binoculars, statues
        ([[0x2D6, 0x2D7], [0x2DE, 0x2DF]], 12), ([[0x2E6]], 14), ([[0x2E7]], 14),
        ([[0x2C1], [0x2C9]], 30), ([[0x2C0], [0x2C8]], 30),
        ([[0x331], [0x32F]], 30), ([[0x32E], [0x32F]], 30),
    ],
    "gTileset_PokemonCenter": [
        # upstairs: the trade and battle counters with their machines
        ([[0x302, 0x363, 0x365], [0x303, 0x2E9, 0x366]], 12),
        ([[0x302, 0x363, 0x365], [0x303, 0x2E9, 0x367]], 12),
        ([[0x2F6], [0x2F8]], 12), ([[0x326], [0x062]], 12), ([[0x376], [0x37E]], 12),
        ([[0x2E7], [0x2EF]], 30), ([[0x300], [0x301]], 30),
        ([[0x288], [0x2E9]], 30), ([[0x340], [0x301]], 30),
        # the Indigo Plateau's counter running down the west wall
        ([[0x338], [0x331], [0x2B5], [0x2BD]], 12),
        ([[0x362]], 30), ([[0x32F]], 30),
        # the counter, nurse's gap and all
        ([[0x2B1, 0x2B2, 0x2B3, 0x290, 0x363, 0x2B4, 0x2B5],
          [0x2B9, 0x2BC, 0x2BC, 0x298, 0x2BC, 0x2BC, 0x2BD]], 12),
        ([[0x29C, 0x29D], [0x2A4, 0x2A5]], 12),           # the table
        ([[0x2F5]], 8), ([[0x2FD]], 8),                   # its stools
    ],
    "gTileset_Mart": [
        # the shelves, drawn front on: their cap the top, run back so a
        # shelf is a cabinet and not a sheet
        ([[0x296, 0x297], [0x29E, 0x29F], [0x2A6, 0x2A7], [0x2AE, 0x2AF]], 52, {"depth": 14}),
        ([[0x296], [0x29E], [0x2A6], [0x2AE]], 52, {"depth": 14}),
        ([[0x2B0, 0x2B1, 0x2B2]], 8),                            # the counter (above: floor)
        ([[0x2C1, 0x2C2]], 8),                                   # the low counter
        ([[0x29D], [0x2A5], [0x2AD]], 36, {"depth": 8}),         # the display case
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
        # the doormat's half in the bottom edge row, and whatever is beside
        # the black under the room: floor, never furniture
        self.flat = {(x, y) for y in range(self.h) for x in range(self.w)
                     if y + 1 >= self.h or self.void(x, y + 1)}

    def m(self, x, y):
        return self.L.metatile(x, y)

    def tileset_of(self, m):
        return self.L.primary if m < 0x280 else self.L.secondary

    def entries(self, m):
        return self.L.entries(m)

    def part_black(self, x, y):
        """A bevelled corner: a good part of it the black round the room."""
        m = self.m(x, y)
        px = self.L.metatile_image(m).convert("RGB").load()
        black = sum(1 for j in range(16) for i in range(16) if px[i, j] == (0, 0, 0))
        return 40 <= black < VOID_SHARE * 256

    def void(self, x, y):
        m = self.m(x, y)
        if m not in self._void:
            px = self.L.metatile_image(m).convert("RGB").load()
            black = sum(1 for j in range(16) for i in range(16) if px[i, j] == (0, 0, 0))
            self._void[m] = black >= VOID_SHARE * 256
        return self._void[m]


def expand(cells, xrep, yrep, n):
    """The pattern with its column xrep (or row yrep) repeated n times."""
    if xrep is not None:
        return [row[:xrep] + [row[xrep]] * n + row[xrep + 1:] for row in cells]
    if yrep is not None:
        return cells[:yrep] + [cells[yrep]] * n + cells[yrep + 1:]
    return cells


def match_objects(room):
    """[(cells {(x, y)}, x0, x1, ybot, h)] for each listed object found.

    An entry is (cells, h) or (cells, h, {"xrep": i} / {"yrep": j}): the
    column (row) named repeats as often as the room draws it - a counter
    or a divider as long as it runs."""
    found, taken = [], set()
    specs = []
    for ts in (room.L.primary, room.L.secondary):
        for spec in ROOM_OBJECTS.get(ts, ()):
            cells, h = spec[0], spec[1]
            opt = spec[2] if len(spec) > 2 else {}
            specs.append((cells, h, opt.get("xrep"), opt.get("yrep"), opt.get("depth", 0),
                          opt.get("rows")))
    specs.sort(key=lambda s: -sum(1 for row in s[0] for c in row if c is not None))
    for base, h, xrep, yrep, depth, only in specs:
        reps = range(max(room.w, room.h), 0, -1) if (xrep is not None or yrep is not None) else (1,)
        for y in range(room.h):
            for x in range(room.w):
                for n in reps:
                    cells = expand(base, xrep, yrep, n)
                    rows, cols = len(cells), len(cells[0])
                    if x + cols > room.w or y + rows > room.h:
                        continue
                    part = only or rows       # the rows that are the object
                    here = {(x + i, y + j) for j in range(part) for i in range(cols)
                            if cells[j][i] is not None}
                    if here & taken:
                        continue
                    if all(room.m(x + i, y + j) == cells[j][i] for j in range(rows) for i in range(cols)
                           if cells[j][i] is not None):
                        found.append((here, x, x + cols, y + part, h, here, depth))
                        taken |= here
                        break
    return found, taken


def walls(room, taken):
    """The room's back wall: each column's first WALL_ROWS cells that are not
    the black round the room, stood up at the last one's south edge; above an
    object standing in it (a plant against the wall), what is left of it."""
    out = []
    for x in range(room.w):
        y0 = next((y for y in range(room.h) if not room.void(x, y)), None)
        if y0 is None:
            continue
        cells = []
        for y in range(y0, min(room.h, y0 + WALL_ROWS)):
            if (x, y) in taken or not room.L.collision(x, y) or room.part_black(x, y):
                break
            cells.append((x, y))
        if cells:
            out.append((set(cells), x, x + 1, y0 + len(cells), len(cells) * 16))
    return out


AUTO_BOX = 12          # an unlisted piece of furniture's front
AUTO_CARD = 14         # an unlisted single thing standing


def has_upper(room, m):
    return any(v & 0x3FF for v in room.entries(m)[4:])


def auto_objects(room, taken):
    """Furniture no list names: each group of blocked cells left (not wall,
    not the black round the room) stands as a box AUTO_BOX tall, a column at
    a time so an L stands as drawn, its sides where the group ends. A group
    with leaves or a top drawn over the cells north of it (a pot plant, a
    lamp) is a card instead, the whole drawing standing."""
    out, seen = [], set(taken)
    for y in range(room.h):
        for x in range(room.w):
            if (x, y) in seen or room.void(x, y) or not room.L.collision(x, y) \
                    or (x, y) in room.flat:
                continue
            group, todo = set(), [(x, y)]
            seen.add((x, y))
            while todo:
                cx, cy = todo.pop()
                group.add((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < room.w and 0 <= ny < room.h and (nx, ny) not in seen \
                            and not room.void(nx, ny) and room.L.collision(nx, ny) \
                            and (nx, ny) not in room.flat:
                        seen.add((nx, ny))
                        todo.append((nx, ny))
            # against the room's side or round its edge: the room's own
            # strip of wall or stairs, which lie as drawn
            if any(cx in (0, room.w - 1) or (cx > 0 and room.void(cx - 1, cy))
                   or (cx < room.w - 1 and room.void(cx + 1, cy)) for cx, cy in group):
                continue
            # what is drawn over the cells just north of it is part of it
            crown = set()
            for (cx, cy) in group:
                n = (cx, cy - 1)
                if n not in group and n not in seen and cy > 0 and not room.void(*n) \
                        and not room.L.collision(*n) and has_upper(room, room.m(*n)):
                    crown.add(n)
            # a card is a small thing (a plant, a lamp, a chair); a long run
            # of wall with things drawn on its top is a box, never a slab
            small = len(group) <= 2 and len({cx for cx, _ in group}) == 1
            card = small and (bool(crown) or len(group) == 1)
            if not card:
                crown = set()
            cells = group | crown
            seen |= crown
            for cx in sorted({c[0] for c in cells}):
                col = sorted(cy for (px, cy) in cells if px == cx)
                runs, start = [], col[0]
                for a, b in zip(col, col[1:] + [None]):
                    if b != a + 1:
                        runs.append((start, a))
                        start = b
                for y0, y1 in runs:
                    run = {(cx, yy) for yy in range(y0, y1 + 1)}
                    rows = y1 - y0 + 1
                    h = min(rows * 16 - 2, 30) if card else AUTO_BOX
                    if card and rows == 1:
                        h = AUTO_CARD
                    out.append((run, cx, cx + 1, y1 + 1, h, cells))
    return out


def floor_near(room, x, y, skip):
    for d in range(1, 6):
        for dx, dy in ((0, d), (0, -d), (-d, 0), (d, 0)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < room.w and 0 <= ny < room.h and (nx, ny) not in skip \
                    and not room.void(nx, ny) and not room.L.collision(nx, ny):
                return room.m(nx, ny)
    return room.m(x, y)


FLAG_WEST, FLAG_EAST, FLAG_NO_GROUND, FLAG_BARE, FLAG_ATLAS = 1, 2, 4, 8, 16


def build(root, place_art):
    """place_art(rgba16x16) -> (sx, sy). Returns [(layout index, [cell rows])]."""
    out = []
    for index, lid in indoor_layouts(root):
        try:
            room = Room(lid)
        except Exception:
            continue
        objects, taken = match_objects(room)
        wall = walls(room, taken)
        for w in wall:
            taken |= w[0]
        pieces = [(o, "object") for o in objects] + [(w, "wall") for w in wall] \
            + [(a, "auto") for a in auto_objects(room, taken)]
        all_cells = set().union(*[p[0][0] for p in pieces]) if pieces else set()
        rows = []
        for piece, kind in pieces:
            wall = kind == "wall"
            cells, x0, x1, ybot, h = piece[:5]
            group = piece[5] if len(piece) > 5 else cells
            depth = piece[6] if len(piece) > 6 else 0
            first = min(cy for _, cy in cells)
            for (x, y) in sorted(cells, key=lambda c: (c[1], c[0])):
                m = room.m(x, y)
                ts = fr_art.Tilesets(room.L.primary, room.L.secondary) if not hasattr(room, "ts") else room.ts
                room.ts = ts
                e = room.entries(m)
                top = layer(ts, e, 1)
                upper = any(top[j][i][1] for j in range(16) for i in range(16)) and not wall
                # a card (all front) is the object alone, cut out of its
                # upper layer; a box's faces are solid, its whole drawing
                card = h >= (ybot - min(cy for _, cy in cells)) * 16 - 4
                flags = 0
                cap = 0
                if upper and card:
                    art = [[(top[j][i][0] + (255,)) if top[j][i][1] else None for i in range(16)]
                           for j in range(16)]
                    sx, sy = place_art(art)
                elif kind == "object":
                    # a listed piece of furniture: its whole drawing but the
                    # floor showing round it (a bed is not a block of floor)
                    floor = room.L.metatile_image(floor_near(room, x, y, all_cells)).convert("RGB").load()
                    img = room.L.metatile_image(m).convert("RGB").load()
                    art = [[None if (not top[j][i][1] and img[i, j] == floor[i, j]) else img[i, j] + (255,)
                            for i in range(16)] for j in range(16)]
                    sx, sy = place_art(art)
                    cap = next((j for j in range(16) if any(art[j][i] for i in range(16))), 0)
                else:
                    # the whole drawing: the map's own atlas has it
                    flags |= FLAG_ATLAS
                    sx, sy = m, 0
                if (x - 1, y) not in group:
                    flags |= FLAG_WEST
                if (x + 1, y) not in group:
                    flags |= FLAG_EAST
                if wall:
                    flags |= FLAG_NO_GROUND
                    ground = 0
                elif kind == "object":
                    # under it the floor beside it: its own lower layer is
                    # more of it, a second bed lying flat under the bed
                    ground = floor_near(room, x, y, all_cells)
                elif upper:
                    flags |= FLAG_BARE
                    ground = m
                else:
                    ground = floor_near(room, x, y, all_cells)
                rows.append((y, x, h, ybot, flags, sx, sy, ground, depth if y == first else 0, cap))
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
             "#define ROOM_BARE 8",
             "#define ROOM_ATLAS 16  /* its art is metatile `sx` in the map's atlas */", "",
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
              "    unsigned char depth;  /* the first row's top runs on this far back */",
              "    unsigned char cap;    /* the first row of the drawing that is the piece */",
              "} sRoomCells[] = {"]
    for index, lid, rows in rooms:
        for r in rows:
            lines.append("    { %d, %d, %d, %d, %d, %d, %d, 0x%03X, %d, %d }," % r)
    lines += ["};", "", "#endif", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
