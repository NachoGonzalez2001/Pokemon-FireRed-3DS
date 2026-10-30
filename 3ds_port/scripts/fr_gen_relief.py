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
TOP_JOIN = 9        # a top this near its neighbour's is the same plateau, drawn ragged
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
    climbs, tops = [], []
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
            elif climb < INF:
                # a top: rock seen from above, level at what was climbed
                # ([column, its south row, its north row, height])
                if tops and tops[-1][0] == i and tops[-1][2] == p + 1 and tops[-1][3] == climb:
                    tops[-1][2] = p
                else:
                    tops.append([i, p, p, climb])
            at[p] = climb if rock[cy][cx] else 0
        climbs.append(at)
    # A top drawn as one is level: the faces under it, drawn ragged (a
    # stepped foot, a band a few rows longer in one tile than the next), had
    # each column of it stand a few pixels off its neighbour's - ribs down the
    # whole plateau. A top rises to its neighbours' within TOP_JOIN of its own
    # height, and the faces under it are stretched to it; rock drawn with no
    # face under it stays where it is.
    by_col = {}
    for t in tops:
        by_col.setdefault(t[0], []).append(t)
    level = {id(t): t[3] for t in tops}
    changed = True
    while changed:
        changed = False
        for t in tops:
            for n in by_col.get(t[0] - 1, []) + by_col.get(t[0] + 1, []):
                if t[3] and n[1] >= t[2] and n[2] <= t[1] \
                        and level[id(t)] < level[id(n)] <= t[3] + TOP_JOIN:
                    level[id(t)] = level[id(n)]
                    changed = True
    for i in range(cols):
        at = climbs[i]
        mine = by_col.get(i, [])
        top_at = {q: t for t in mine for q in range(t[2], t[1] + 1)}
        # a face with no top over it goes on from the top under it, moved
        # with it
        moved = 0
        for p in range(rows_px - 1, -1, -1):
            if p in top_at:
                moved = level[id(top_at[p])] - top_at[p][3]
            elif not 0 < at[p] < INF:
                moved = 0
            else:
                at[p] += moved
        for t in mine:
            # the face under it, down to the ground or the top it rose from
            p = t[1] + 1
            while p < rows_px and 0 < at[p] < INF and p not in top_at:
                p += 1
            low = level[id(top_at[p])] if p in top_at else 0
            for k, q in enumerate(range(p - 1, t[1], -1), start=1):
                at[q] = low + (level[id(t)] - low) * k / float(p - 1 - t[1])
            for q in range(t[2], t[1] + 1):
                at[q] = level[id(t)]
    for i in range(cols):
        at = climbs[i]
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


# A cave: its blocked cells stand up from the floor south of them as the
# GBA draws them - a mass's face, the band of face rows at its foot, stands
# 1:1 and the rest of the mass is its level top, the whole mass as tall as
# its faces. Its sides drop steeply to the floor beside it; what has no floor
# south of it (the rock south of the cave) stays down, where it would hide the
# cave from the camera. The map's elevations say which floor is up a level: a
# plateau (elevation 4 over the floor's 3) stands LEVEL higher, its stairs a
# ramp down to the floor, its rim's top flush with it.
ROOM_CAP = 48
FURNITURE_CAP = 16
LEVEL = 16          # a plateau one elevation up
SIDE_STEEP = 4      # a mass's sides: at 45 degrees a rock was a tent
VOID_SHARE = 0.85   # of a cell's pixels black: the filler round the room
FLOOR_ELEVATION = 3
FACE_SHARE = 10     # of a row's 16 pixels nearer the faces' colour than the tops'
FOOT_GAP = 4        # rows at a mass's foot under its face (a bevel, a shadow)
STONE_NEAR = 50     # a colour this near the masses' top or face is theirs...
STONE_SHARE = 0.2   # ...and a cell this much of it drawn as rock


def interior_relief(layout):
    W, H = layout.w, layout.h
    pix = {}

    def image(m):
        if m not in pix:
            pix[m] = layout.metatile_image(m).convert("RGB").load()
        return pix[m]

    void_of = {}

    def void(m):
        if m not in void_of:
            px = image(m)
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
    # stones - is a rock, however it joins the walls; a wall's face is drawn
    # solid
    floors = collections.Counter(layout.metatile(x, y) for y in range(H) for x in range(W)
                                 if kind[y][x] == 0)
    floor_cols = set()
    for m, _ in floors.most_common(1):
        px = image(m)
        floor_cols |= {px[i, j] for j in range(16) for i in range(16)}
    rock_of = {}

    def rockish(x, y):
        m = layout.metatile(x, y)
        if m not in rock_of:
            px = image(m)
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

    def flood(same):
        """Ids of the blocked cells joined by `same` neighbours."""
        ids, count = [[-1] * W for _ in range(H)], 0
        for y in range(H):
            for x in range(W):
                if kind[y][x] != 1 or ids[y][x] >= 0:
                    continue
                ids[y][x], todo = count, [(x, y)]
                while todo:
                    cx, cy = todo.pop()
                    for nx, ny in near4(cx, cy):
                        if kind[ny][nx] == 1 and ids[ny][nx] < 0 and same(cx, cy, nx, ny):
                            ids[ny][nx] = count
                            todo.append((nx, ny))
                count += 1
        return ids, count

    # Walls are what reaches the black round the cave (or the map's edge); a
    # rock drawn over the floor is not, and is a mass of its own beside
    # whatever it touches
    joined, n = flood(lambda *_: True)
    walled = [False] * n
    for y in range(H):
        for x in range(W):
            if kind[y][x] == 1 and (x in (0, W - 1) or y in (0, H - 1)
                                    or any(kind[ny][nx] == 2 for nx, ny in near4(x, y))):
                walled[joined[y][x]] = True
    wallcell = [[kind[y][x] == 1 and walled[joined[y][x]] and not rockish(x, y)
                 for x in range(W)] for y in range(H)]

    def small(x, y):
        return rockish(x, y) and not wallcell[y][x]
    mass, _ = flood(lambda x, y, nx, ny: small(x, y) == small(nx, ny))
    base = [[0] * W for _ in range(H)]
    rim = [[False] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if kind[y][x] == 1:
                beside = [floor_n[ny][nx] for nx, ny in near4(x, y) if kind[ny][nx] == 0]
                base[y][x] = max(beside) if beside else 0
                # a rim between a plateau and the floor below
                rim[y][x] = bool(beside) and min(beside) < max(beside)

    # The masses' colours: their tops, seen from above (a cell blocked all
    # round), and their faces (the foot of a cell with the floor south of
    # it). A row of a tile is face when most of it is nearer the faces'.
    top, face = [0, 0, 0, 0], [0, 0, 0, 0]
    for y in range(H):
        for x in range(W):
            if kind[y][x] != 1:
                continue
            px = image(layout.metatile(x, y))
            if len(near4(x, y)) == 4 and all(kind[ny][nx] == 1 for nx, ny in near4(x, y)):
                for c in (px[i, j] for j in range(16) for i in range(16)):
                    if c != (0, 0, 0):
                        top = [top[0] + c[0], top[1] + c[1], top[2] + c[2], top[3] + 1]
            elif y + 1 < H and kind[y + 1][x] == 0:
                for c in (px[i, j] for j in range(12, 16) for i in range(16)):
                    face = [face[0] + c[0], face[1] + c[1], face[2] + c[2], face[3] + 1]
    T = [v / max(1, top[3]) for v in top[:3]]
    F = [v / max(1, face[3]) for v in face[:3]]

    def dist2(c, ref):
        return sum((a - b) ** 2 for a, b in zip(c, ref))
    face_of = {}

    def face_row(cx, p):
        m = layout.metatile(cx, p // 16)
        if m not in face_of:
            px = image(m)
            face_of[m] = [sum(1 for i in range(16) if dist2(px[i, j], F) < dist2(px[i, j], T))
                          >= FACE_SHARE for j in range(16)]
        return face_of[m][p % 16]
    stone_of = {}

    def stone(x, y):
        """Drawn as the masses are (not the snow round the cave)."""
        m = layout.metatile(x, y)
        if m not in stone_of:
            px = image(m)
            near = sum(1 for j in range(16) for i in range(16)
                       if min(dist2(px[i, j], T), dist2(px[i, j], F)) < STONE_NEAR ** 2)
            stone_of[m] = near >= STONE_SHARE * 256
        return stone_of[m]

    # Up each lattice column: a foot is a mass's first row north of a floor,
    # or of a rock drawn over the floor in front of it (the mass behind rises
    # from the floor again). Its face is the run of face rows there.
    rows_px = H * 16
    cols = []
    for i in range(W * STEP + 1):
        cx = min(i * STEP, W * 16 - 1) // 16
        cols.append([3 if kind[p // 16][cx] == 1 and small(cx, p // 16) else kind[p // 16][cx]
                     for p in range(rows_px)])

    def is_foot(kinds, p):
        return kinds[p] in (1, 3) and p + 1 < rows_px and \
            (kinds[p + 1] == 0 or kinds[p + 1] == 4 - kinds[p])

    def face_at(cx, kinds, p):
        """The face at a foot: its rows, and the rows under it before it."""
        band, gap, own = 0, 0, kinds[p]
        while p >= 0 and kinds[p] == own:
            if face_row(cx, p):
                band += 1
            elif band or gap >= FOOT_GAP:
                break
            else:
                gap += 1
            p -= 1
        return band, gap

    # One mass, one top: its faces (its feet along a row of cells) are each
    # as tall as the median of their columns, and the mass as the median of
    # its faces; every face climbs to it, its drawing rescaled. A foot with
    # no face drawn along it (the snow outside the cave beside its rocks)
    # stays down; a mass with none anywhere climbs 1:1 to its cap.
    feet = []
    for i, kinds in enumerate(cols):
        cx = min(i * STEP, W * 16 - 1) // 16
        for p in range(rows_px):
            if is_foot(kinds, p):
                feet.append((mass[p // 16][cx], p // 16, i, p, face_at(cx, kinds, p)[0]))
    feet.sort()
    faces = []
    for f in feet:
        if faces and faces[-1][-1][:2] == f[:2] and faces[-1][-1][2] + 1 == f[2]:
            faces[-1].append(f)
        else:
            faces.append([f])
    drawn, tall = [], {}
    for run in faces:
        bands = [f[4] for f in run if f[4]]
        drawn.append(sorted(bands)[len(bands) // 2] if len(bands) * 2 >= len(run) else 0)
        if drawn[-1]:
            tall.setdefault(run[0][0], []).extend([drawn[-1]] * len(run))
    mass_h = {g: sorted(v)[len(v) // 2] for g, v in tall.items()}
    stands = {}
    for run, h in zip(faces, drawn):
        for f in run:
            stands[(f[2], f[3])] = mass_h.get(f[0], -1) if h or f[0] not in mass_h else 0

    # the height each column's points reach (None: blocked with no floor
    # south of it yet)
    up = {}
    for i, kinds in enumerate(cols):
        cx = min(i * STEP, W * 16 - 1) // 16
        at = [None] * rows_px
        ground = climb = None
        for p in range(rows_px - 1, -1, -1):
            k = kinds[p]
            if k == 0:
                ground = climb = floor_at(cx, p)
                at[p] = climb
                continue
            if k == 2:
                ground = climb = None
                at[p] = 0
                continue
            if ground is None:
                continue
            if is_foot(kinds, p):
                h = stands.get((i, p), -1)
                old = rim[p // 16][cx] or h < 0
                band, gap = face_at(cx, kinds, p) if h > 0 else (0, 0)
                if not band:
                    band, gap = h, 0        # no face drawn here: the face's rows 1:1
                done, scale = -gap, h / float(band) if band else 0.0
                climb = ground
            if old:
                # a rim, flush with the plateau it bounds; a mass with no face
                climb += 1
                at[p] = climb
            else:
                done += 1
                at[p] = ground + max(0, min(done, band)) * scale
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

    # a wall stands to ROOM_CAP at most, anything else a cell over its floor;
    # a rim between a plateau and the floor below is flush with the plateau
    cap = [[ROOM_CAP] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if kind[y][x] != 1:
                continue
            cap[y][x] = max(ROOM_CAP, base[y][x] + FURNITURE_CAP) if wallcell[y][x] \
                else base[y][x] + FURNITURE_CAP
            if rim[y][x]:
                cap[y][x] = min(cap[y][x], max(floor_n[ny][nx] for nx, ny in near4(x, y)
                                               if kind[ny][nx] == 0))
    # blocked with no floor south: rock beside the floor (a wall east or west
    # of it, the rocks along the cave's south wall) stands as tall as its
    # mass; the ground round the cave stays down, and so does the rock south
    # of the cave; the rock whose column never meets a floor is the walls'
    open_col = [any(kind[y][x] == 0 for y in range(H)) for x in range(W)]
    for key, v in list(up.items()):
        if v is None:
            cx = min(key[0] * STEP, W * 16 - 1) // 16
            cy = min(key[1] * STEP, rows_px - 1) // 16
            own = base[cy][cx] + mass_h.get(mass[cy][cx], FURNITURE_CAP)
            if not stone(cx, cy):
                up[key] = base[cy][cx]
            elif any(kind[ny][nx] == 0 for nx, ny in near4(cx, cy)):
                up[key] = own
                if not wallcell[cy][cx]:
                    cap[cy][cx] = min(cap[cy][cx], own)
            else:
                up[key] = 0 if open_col[cx] else own
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
