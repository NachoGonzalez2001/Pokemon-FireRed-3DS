#!/usr/bin/env python3
"""FireRed's mountains, read off the drawing, as voxel/relief.bin.

The renderer's relief model (src/voxel/voxel_relief.h): a point (u, v) of
the map's art lifted to a height h stands at (u, h, v + h), which the GBA's
45-degree view sees as the drawing itself whatever h is. So the mountains are
not modelled: the art is lifted, and the only question is how high.

FireRed draws its rock in two shades. The light one is rock seen from above;
the dark one (DARK) is a south-facing face, drawn one cell tall at the foot
of each step. So, along each column of the art:

  * from the walkable ground south of a mass, every row of face climbed
    lifts the rock one pixel - a face stands exactly vertical (v + h stays
    the same down it) and each band is a step up to the next terrace;
  * a mass whose foot is off the map's south edge shows no face: it stands
    HIDDEN pixels high, up from the edge it is seen from the north by;
  * nothing is higher than its distance to the nearest ground that is not
    rock: the sides and the north rims of a mass slope down at 45 degrees,
    so the sheet stays whole (the faces, rising one pixel a pixel from
    their foot, are never cut).

Only blocked cells drawn mostly in rock are lifted; the walkable ground, the
trees and everything else stay level.

    python fr_gen_relief.py --output romfs/voxel/relief.bin [--layouts A,B] [--report]
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fr_art  # noqa: E402
import fr_map_render  # noqa: E402

PROPS_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "voxel",
                           "voxel_props_table.h")


def prop_metatiles():
    """{tileset name or None for General: metatiles} the console stands up
    as props (fences, signs, boulders...): never rock, however brown."""
    import re
    text = open(PROPS_TABLE, encoding="utf-8").read()
    sets = [None] + re.findall(r"^    &(\w+),", text, re.M)
    out = {}
    for s, m in re.findall(r"^    \{\s*(\d+),\s*0x([0-9A-F]+),", text, re.M):
        out.setdefault(sets[int(s)], set()).add(int(m, 16))
    return out


PROPS = prop_metatiles()


def cave_door():
    """MB_CAVE_DOOR: a cave's mouth is walkable, drawn in the rock's face."""
    import re
    path = os.path.join(fr_art.ROOT, "include", "constants", "metatile_behaviors.h")
    for line in open(path, encoding="utf-8"):
        m = re.match(r"#define MB_CAVE_DOOR\s+(0x[0-9A-Fa-f]+|\d+)", line)
        if m:
            return int(m.group(1), 0)
    return -1


CAVE_DOOR = cave_door()

SIDE = 5            # lattice points per cell side, every 4 pixels
STEP = 4
# General's rock (palettes 0 and 1): seen from above, and its faces
LIGHT = {(0xde, 0xc5, 0xa4), (0xbd, 0x94, 0x8b), (0xee, 0xd5, 0xc5), (0x94, 0x6a, 0x6a)}
DARK = {(0x7b, 0x4a, 0x4a), (0x5a, 0x39, 0x41)}
OUTLINE = {(0x7b, 0x7b, 0x83)}
ROCK = LIGHT | DARK | OUTLINE
ROCK_SHARE = 0.4    # of a blocked cell's pixels, for it to be rock
FACE_ROW = 11       # dark pixels of 16 for a row to be face
FACE_ROWS = 4       # such rows for a cell to be a face: a side edge has one or two
HIDDEN = 32         # a mass seen from the north only
TALL = 48           # a column of rock the whole height of the map
INF = 1 << 20


class Classes:
    """Per metatile (of a tileset pair): its rock share and its face rows."""

    def __init__(self, layout):
        self.layout = layout
        self.cache = {}

    def of(self, m):
        if m not in self.cache:
            img = self.layout.metatile_image(m).convert("RGB")
            px = img.load()
            rock = sum(1 for y in range(16) for x in range(16) if px[x, y] in ROCK)
            face = [sum(1 for x in range(16) if px[x, y] in DARK) >= FACE_ROW for y in range(16)]
            if sum(face) < FACE_ROWS:
                face = [False] * 16
            else:
                # the band, from its first face row to its last
                first, last = face.index(True), 15 - face[::-1].index(True)
                face = [first <= y <= last for y in range(16)]
            self.cache[m] = (rock / 256.0, face)
        return self.cache[m]


def relief_of(layout):
    """{(x, y): 25 heights in pixels} for the layout's lifted cells."""
    W, H = layout.w, layout.h
    classes = Classes(layout)
    rock = [[False] * W for _ in range(H)]
    face = [[None] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            share, rows = classes.of(layout.metatile(x, y))
            m = layout.metatile(x, y)
            prop = m in PROPS.get(None if m < 0x280 else layout.secondary, ())
            door = layout.behaviour(x, y) == CAVE_DOOR
            if (layout.collision(x, y) or door) and share >= ROCK_SHARE and not prop:
                rock[y][x] = True
                face[y][x] = rows
    # Rock drawn walkable but shut in by rock (the top of Diglett's Cave's
    # mound) is rock: no one stands there, and left level it was a pit.
    seen = set()
    for y in range(H):
        for x in range(W):
            if rock[y][x] or (x, y) in seen or classes.of(layout.metatile(x, y))[0] < 0.9:
                continue
            group, todo, shut = [], [(x, y)], True
            seen.add((x, y))
            while todo:
                cx, cy = todo.pop()
                group.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not (0 <= nx < W and 0 <= ny < H):
                        shut = False
                    elif rock[ny][nx] or (nx, ny) in seen:
                        continue
                    elif classes.of(layout.metatile(nx, ny))[0] >= 0.9:
                        seen.add((nx, ny))
                        todo.append((nx, ny))
                    else:
                        shut = False
            if shut:
                for cx, cy in group:
                    rock[cy][cx] = True
                    face[cy][cx] = classes.of(layout.metatile(cx, cy))[1]
    # A cave's mouth stands in the face it is cut in: the face's band, from
    # the rock beside it, or it stood flat and dented the rock round it.
    for y in range(H):
        for x in range(W):
            if rock[y][x] and layout.behaviour(x, y) == CAVE_DOOR:
                beside = [face[y][n] for n in (x - 1, x + 1)
                          if 0 <= n < W and rock[y][n] and any(face[y][n])]
                face[y][x] = beside[0] if beside else [y >= 2 for y in range(16)]
    if not any(any(r) for r in rock):
        return {}

    # Along each lattice column, from the south: the face climbed so far
    # over the ground (INF when the rock runs off the south edge), and from
    # the north whether the run met ground (HIDDEN) or the edge (INF).
    cols = W * STEP + 1
    rows_px = H * 16
    up = [[0] * (H * STEP + 1) for _ in range(cols)]
    down = [[0] * (H * STEP + 1) for _ in range(cols)]
    for i in range(cols):
        px = min(i * STEP, W * 16 - 1)
        cx = px // 16
        climb = INF     # off the south edge: rock goes on
        at = [0] * (rows_px + 1)
        at[rows_px] = climb
        for p in range(rows_px - 1, -1, -1):
            cy = p // 16
            if not rock[cy][cx]:
                climb = 0
            elif face[cy][cx][p % 16] and climb < INF:
                climb += 1
            at[p] = climb if rock[cy][cx] else 0
        for j in range(H * STEP + 1):
            up[i][j] = at[min(j * STEP, rows_px)]
        cap = INF
        top = [0] * (rows_px + 1)
        for p in range(rows_px):
            cy = p // 16
            if not rock[cy][cx]:
                cap = HIDDEN
            top[p] = cap
        for j in range(H * STEP + 1):
            down[i][j] = top[min(j * STEP, rows_px - 1)]

    def ground_distance(i, j):
        """Pixels from lattice point (i, j) to the nearest cell that is not
        rock (the map's outside counts as rock: the next map goes on)."""
        ux, vy = i * STEP, j * STEP
        best = INF
        r = TALL // 16 + 1
        cx0, cy0 = ux // 16, vy // 16
        for cy in range(cy0 - r, cy0 + r + 1):
            if cy < 0 or cy >= H:
                continue
            for cx in range(cx0 - r, cx0 + r + 1):
                if cx < 0 or cx >= W or rock[cy][cx]:
                    continue
                dx = max(cx * 16 - ux, 0, ux - (cx * 16 + 16))
                dy = max(cy * 16 - vy, 0, vy - (cy * 16 + 16))
                d = (dx * dx + dy * dy) ** 0.5
                if d < best:
                    best = d
        return best

    lattice = {}

    def height(i, j):
        if (i, j) not in lattice:
            a, b = up[i][j], down[i][j]
            h = TALL if a >= INF and b >= INF else min(a, b)
            lattice[(i, j)] = int(min(h, ground_distance(i, j)))
        return lattice[(i, j)]

    out = {}
    for y in range(H):
        for x in range(W):
            if not rock[y][x]:
                continue
            grid = [height(x * (SIDE - 1) + a, y * (SIDE - 1) + c)
                    for c in range(SIDE) for a in range(SIDE)]
            if any(grid):
                out[(x, y)] = grid
    return out


OUTDOOR = {"MAP_TYPE_TOWN", "MAP_TYPE_CITY", "MAP_TYPE_ROUTE", "MAP_TYPE_OCEAN_ROUTE"}


def outdoor_layouts(root, only=None):
    """The layouts outdoor maps are drawn on (not caves: they come later)."""
    layouts = json.load(open(os.path.join(root, "data", "layouts", "layouts.json"),
                             encoding="utf-8"))["layouts"]
    outdoor = set()
    maps = os.path.join(root, "data", "maps")
    for name in os.listdir(maps):
        path = os.path.join(maps, name, "map.json")
        if os.path.exists(path):
            m = json.load(open(path, encoding="utf-8"))
            if m.get("map_type") in OUTDOOR:
                outdoor.add(m.get("layout"))
    for index, entry in enumerate(layouts, start=1):
        lid = entry.get("id")
        if not lid or lid not in outdoor or entry.get("primary_tileset") != "gTileset_General":
            continue
        if only and lid not in only:
            continue
        yield index, lid


def write(path, tables):
    """VXL4 (see src/voxel/voxel_relief.c), with an empty cut table."""
    head = struct.pack("<4sHH", b"VXL4", len(tables), SIDE)
    rows, blobs = [], []
    offset = 8 + 14 * len(tables)
    for index, w, h, cells in tables:
        most = max((max(g) for g in cells.values()), default=0)
        unit = 2 if most > 127 else 1
        body = bytearray()
        for (x, y) in sorted(cells, key=lambda k: (k[1], k[0])):
            body += struct.pack("<BB", x, y)
            body += struct.pack("<25b", *[min(127, v // unit) for v in cells[(x, y)]])
        rows.append(struct.pack("<HHHHIh", index, len(cells), w, h | (0x4000 if unit == 2 else 0),
                                offset, 0))
        blobs.append(bytes(body))
        offset += len(body)
    data = head + b"".join(rows) + b"".join(blobs)
    cuts_at = len(data)
    data += struct.pack("<HH", 0, 0)
    data += struct.pack("<I4s", cuts_at, b"CUTS")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--layouts", help="comma-separated layout ids (default: every outdoor one)")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    only = set(args.layouts.split(",")) if args.layouts else None
    tables = []
    for index, lid in outdoor_layouts(fr_art.ROOT, only):
        layout = fr_map_render.FrLayout(lid)
        cells = relief_of(layout)
        if not cells:
            continue
        tables.append((index, layout.w, layout.h, cells))
        if args.report:
            print("%-40s %4d cells, highest %d px" % (lid, len(cells), max(max(g) for g in cells.values())))
    size = write(args.output, tables)
    print("voxel relief: %d layouts, %d bytes -> %s" % (len(tables), size, args.output))


if __name__ == "__main__":
    main()
