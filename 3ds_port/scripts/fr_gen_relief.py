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

# Lifted like rock, the lowest cell of each run the face it stands on: the
# Safari Zone's round bushes. The woods' trees stand up as cards instead
# (fr_gen_trees.py WOODS).
FOREST = {
    "gTileset_FuchsiaCity": [0x2F4],
}

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
    forest = FOREST.get(layout.secondary, ())
    tree = [[layout.collision(x, y) and layout.metatile(x, y) in forest
             and layout.metatile(x, y) not in PROPS.get(layout.secondary, ())
             for x in range(W)] for y in range(H)]
    for y in range(H):
        for x in range(W):
            if tree[y][x]:
                rock[y][x] = True
                foot = y + 1 >= H or not tree[y + 1][x]
                face[y][x] = [foot] * 16
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


# A cave: its blocked cells stand up from the floor south of them - a wall,
# a rock, a ledge's face stands as drawn - to ROOM_CAP; its sides drop
# steeply to the floor beside it; and what has no floor south of it (the
# rock south of the cave) stays down, where it would hide the cave from the
# camera. The map's elevations say which floor is up a level: a plateau
# (elevation 4 over the floor's 3) stands LEVEL higher, its stairs a ramp
# down to the floor, its rim's top flush with it.
ROOM_CAP = 48
FURNITURE_CAP = 16
LEVEL = 16          # a plateau one elevation up
SIDE_STEEP = 4      # a mass's sides: at 45 degrees a rock was a tent
VOID_SHARE = 0.85   # of a cell's pixels black: the filler round the room
FLOOR_ELEVATION = 3


def interior_relief(layout):
    W, H = layout.w, layout.h
    void_of = {}

    def void(m):
        if m not in void_of:
            px = layout.metatile_image(m).convert("RGB").load()
            black = sum(1 for y in range(16) for x in range(16) if px[x, y] == (0, 0, 0))
            void_of[m] = black >= VOID_SHARE * 256
        return void_of[m]

    # 0 floor, 1 blocked (stands), 2 void
    kind = [[2 if void(layout.metatile(x, y)) else 1 if layout.collision(x, y) else 0
             for x in range(W)] for y in range(H)]
    if not any(k == 1 for row in kind for k in row):
        return {}
    # walkable cells drawn as the rock round the cave (out of reach, past its
    # walls) are that rock: the drawing the map's blocked edge is made of
    import collections
    edge = collections.Counter(layout.metatile(x, y) for y in range(H) for x in range(W)
                               if (x in (0, W - 1) or y in (0, H - 1)) and kind[y][x] == 1)
    total = sum(edge.values())
    filler = {m for m, n in edge.items() if total and n >= 0.25 * total}
    for y in range(H):
        for x in range(W):
            if kind[y][x] == 0 and layout.metatile(x, y) in filler:
                kind[y][x] = 1

    # a blocked cell drawn over the floor - the floor showing between its
    # stones - is a rock, a cell tall, however it joins the walls; a wall's
    # face is drawn solid
    floors = collections.Counter(layout.metatile(x, y) for y in range(H) for x in range(W)
                                 if kind[y][x] == 0)
    floor_cols = set()
    for m, _ in floors.most_common(1):
        px = layout.metatile_image(m).convert("RGB").load()
        floor_cols |= {px[i, j] for j in range(16) for i in range(16)}
    rock_of = {}

    def rockish(x, y):
        m = layout.metatile(x, y)
        if m not in rock_of:
            px = layout.metatile_image(m).convert("RGB").load()
            n = sum(1 for j in range(16) for i in range(16) if px[i, j] in floor_cols)
            # (a wall's bevelled corner shows a wedge of floor, more than this)
            rock_of[m] = 0.12 * 256 <= n <= 0.35 * 256
        return rock_of[m]

    def near4(x, y):
        return [(nx, ny) for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                if 0 <= nx < W and 0 <= ny < H]

    # each floor cell's height from its elevation, at its north and south
    # edges; a cell between levels (elevation 0: stairs, a puddle) a ramp
    # from the floor north of it to the one south, or level with its floor
    floor_n = [[None] * W for _ in range(H)]
    floor_s = [[None] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            e = layout.elevation(x, y)
            if kind[y][x] == 0 and e >= FLOOR_ELEVATION:
                floor_n[y][x] = floor_s[y][x] = LEVEL * (e - FLOOR_ELEVATION)
    for y in range(H):
        for x in range(W):
            if kind[y][x] != 0 or floor_n[y][x] is not None:
                continue
            north = floor_s[y - 1][x] if y > 0 and kind[y - 1][x] == 0 else None
            south = floor_n[y + 1][x] if y + 1 < H and kind[y + 1][x] == 0 else None
            if north is not None and south is not None and north != south:
                floor_n[y][x], floor_s[y][x] = north, south
            else:
                near = [v for v in (north, south) if v is not None]
                near += [floor_n[y][n] for n in (x - 1, x + 1)
                         if 0 <= n < W and kind[y][n] == 0 and floor_n[y][n] is not None]
                floor_n[y][x] = floor_s[y][x] = min(near) if near else 0

    def floor_at(cx, p):
        cy = p // 16
        return floor_n[cy][cx] + (floor_s[cy][cx] - floor_n[cy][cx]) * (p % 16 + 1) / 16.0

    # along each lattice column from the south: the height climbed from the
    # last floor (None: blocked with no floor south of it yet)
    rows_px = H * 16
    up = {}
    for i in range(W * STEP + 1):
        cx = min(i * STEP, W * 16 - 1) // 16
        climb = None
        at = [0] * (rows_px + 1)
        for p in range(rows_px - 1, -1, -1):
            k = kind[p // 16][cx]
            if k == 0:
                climb = floor_at(cx, p)
                at[p] = climb
            elif k == 2:
                climb = None
                at[p] = 0
            else:
                if climb is not None:
                    climb += 1
                at[p] = climb
        for j in range(H * STEP + 1):
            up[(i, j)] = at[min(j * STEP, rows_px - 1)] if j * STEP < rows_px else 0

    def side(i, j):
        """Pixels across to the nearest floor cell level with the point."""
        ux, vy = i * STEP, j * STEP
        best = INF
        for cy in {min(vy // 16, H - 1), max(0, (vy - 1) // 16)}:
            for cx in range(W):
                if kind[cy][cx] == 0:
                    d = max(cx * 16 - ux, 0, ux - (cx * 16 + 16))
                    best = min(best, d)
        return best

    # Walls are what reaches the black round the cave (or the map's edge); a
    # mass standing free on the floor - a rock - is one cell tall at most
    # over its floor, its upper rows its top seen from above; the rim of a
    # plateau is as tall as the plateau.
    cap = [[ROOM_CAP] * W for _ in range(H)]
    base = [[0] * W for _ in range(H)]
    wallcell = [[False] * W for _ in range(H)]
    seen = set()
    for y in range(H):
        for x in range(W):
            if kind[y][x] != 1 or (x, y) in seen:
                continue
            group, todo, wall = [], [(x, y)], False
            seen.add((x, y))
            while todo:
                cx, cy = todo.pop()
                group.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not (0 <= nx < W and 0 <= ny < H) or kind[ny][nx] == 2:
                        wall = True
                    elif kind[ny][nx] == 1 and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        todo.append((nx, ny))
            for cx, cy in group:
                wallcell[cy][cx] = wall and not rockish(cx, cy)
                beside = [floor_n[ny][nx] for nx, ny in near4(cx, cy) if kind[ny][nx] == 0]
                base[cy][cx] = max(beside) if beside else 0
                cap[cy][cx] = max(ROOM_CAP, base[cy][cx] + FURNITURE_CAP) if wallcell[cy][cx] \
                    else base[cy][cx] + FURNITURE_CAP
                # a rim between a plateau and the floor below: flush with it
                if beside and min(beside) < max(beside):
                    cap[cy][cx] = min(cap[cy][cx], max(beside))
    # blocked with no floor south: a rock with floor beside it (the rocks
    # along the cave's south wall) stands a cell tall; the rock south of the
    # cave stays down; the rock beside it, whose column never meets a floor,
    # is the walls' mass
    open_col = [any(kind[y][x] == 0 for y in range(H)) for x in range(W)]
    for key, v in list(up.items()):
        if v is None:
            cx = min(key[0] * STEP, W * 16 - 1) // 16
            cy = min(key[1] * STEP, rows_px - 1) // 16
            if cy > 0 and kind[cy - 1][cx] == 0:
                up[key] = base[cy][cx] + FURNITURE_CAP
                cap[cy][cx] = min(cap[cy][cx], base[cy][cx] + FURNITURE_CAP)
            elif any(kind[ny][nx] == 0 for nx, ny in near4(cx, cy)) and not wallcell[cy][cx]:
                up[key] = base[cy][cx] + FURNITURE_CAP
                cap[cy][cx] = min(cap[cy][cx], base[cy][cx] + FURNITURE_CAP)
            elif any(kind[ny][nx] == 0 for nx, ny in near4(cx, cy)):
                up[key] = cap[cy][cx]       # a wall east or west of the floor
            else:
                up[key] = 0 if open_col[cx] else ROOM_CAP
    # the wall over a puddle at its foot rose from the puddle, short of the
    # wall beside it: a wall stands as tall as its neighbours a cell across
    dil = {}
    for (i, j), v in up.items():
        cx = min(i * STEP, W * 16 - 1) // 16
        cy = min(j * STEP, rows_px - 1) // 16
        if j * STEP < rows_px and kind[cy][cx] == 1 and wallcell[cy][cx]:
            best = v
            for d in range(-STEP, STEP + 1):
                n = (i + d, j)
                if n in up:
                    ncx = min(n[0] * STEP, W * 16 - 1) // 16
                    if kind[cy][ncx] == 1 and wallcell[cy][ncx]:
                        best = max(best, up[n])
            dil[(i, j)] = best
    up.update(dil)
    # every cell's say at each lattice point it touches; a point shared by
    # two cells takes the lower (a plateau's edge where no rim divides it
    # from the floor below steps down there, and leaves no crack)
    lattice = {}
    say = {}
    for y in range(H):
        for x in range(W):
            if kind[y][x] == 2:
                continue
            for c in range(SIDE):
                for a in range(SIDE):
                    key = (x * (SIDE - 1) + a, y * (SIDE - 1) + c)
                    if kind[y][x] == 0:
                        v = floor_n[y][x] + (floor_s[y][x] - floor_n[y][x]) * c / (SIDE - 1)
                    else:
                        if key not in lattice:
                            # a wall's cell stands whole, its face at its
                            # edge (the shared point takes the floor's
                            # height): a sheer step as drawn, not a ramp
                            sides = INF if wallcell[y][x] else base[y][x] + SIDE_STEEP * side(*key)
                            lattice[key] = min(cap[y][x], up[key], sides)
                        v = lattice[key]
                    say[key] = min(say.get(key, v), v)
    out = {}
    for y in range(H):
        for x in range(W):
            if kind[y][x] == 2:
                continue
            grid = [int(round(say[(x * (SIDE - 1) + a, y * (SIDE - 1) + c)]))
                    for c in range(SIDE) for a in range(SIDE)]
            if any(grid):
                out[(x, y)] = grid
    return out


OUTDOOR = {"MAP_TYPE_TOWN", "MAP_TYPE_CITY", "MAP_TYPE_ROUTE", "MAP_TYPE_OCEAN_ROUTE"}


def map_layouts(root, types):
    """The layouts maps of these types are drawn on, with those their own
    scripts swap in (setmaplayoutindex: Seven Island's house with its door
    open, Seafoam with its currents stopped)."""
    import re
    out = set()
    maps = os.path.join(root, "data", "maps")
    for name in os.listdir(maps):
        path = os.path.join(maps, name, "map.json")
        if not os.path.exists(path):
            continue
        m = json.load(open(path, encoding="utf-8"))
        if m.get("map_type") not in types:
            continue
        out.add(m.get("layout"))
        script = os.path.join(maps, name, "scripts.inc")
        if os.path.exists(script):
            out |= set(re.findall(r"setmaplayoutindex\s+(LAYOUT_\w+)",
                                  open(script, encoding="utf-8").read()))
    return out


def indoor_layouts(root, only=None):
    """The layouts indoor maps (houses, shops, centres, gyms) and caves are
    drawn on: a cave's rock walls stand up from its floor as a room's do."""
    layouts = json.load(open(os.path.join(root, "data", "layouts", "layouts.json"),
                             encoding="utf-8"))["layouts"]
    # (rooms stand up as pieces instead: fr_gen_rooms.py)
    indoor = map_layouts(root, ("MAP_TYPE_UNDERGROUND",))
    for index, entry in enumerate(layouts, start=1):
        lid = entry.get("id")
        if lid and lid in indoor and (not only or lid in only):
            yield index, lid


def outdoor_layouts(root, only=None):
    """The layouts outdoor maps are drawn on (not caves: they come later)."""
    layouts = json.load(open(os.path.join(root, "data", "layouts", "layouts.json"),
                             encoding="utf-8"))["layouts"]
    outdoor = map_layouts(root, OUTDOOR)
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
    jobs = [(i, l, relief_of) for i, l in outdoor_layouts(fr_art.ROOT, only)]
    jobs += [(i, l, interior_relief) for i, l in indoor_layouts(fr_art.ROOT, only)]
    for index, lid, solve in sorted(jobs):
        layout = fr_map_render.FrLayout(lid)
        cells = solve(layout)
        if not cells:
            continue
        tables.append((index, layout.w, layout.h, cells))
        if args.report:
            print("%-40s %4d cells, highest %d px" % (lid, len(cells), max(max(g) for g in cells.values())))
    size = write(args.output, tables)
    print("voxel relief: %d layouts, %d bytes -> %s" % (len(tables), size, args.output))


if __name__ == "__main__":
    main()
