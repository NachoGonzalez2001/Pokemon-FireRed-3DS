#!/usr/bin/env python3
"""FireRed building models, one reading of the drawing per building type.

Same contract as the Emerald port's voxel_building_specs.py: a spec names the
layout and cell rectangle of a reference copy, the ground metatiles around
it, the parts that rebuild it and the art rectangles the model must reproduce
pixel for pixel in the GBA's projection (u = X, v = Z - Y). Row and column
numbers are pixels of the building's art rectangle.

FireRed draws differently from Emerald in one way that matters here: a hipped
roof's side slopes are drawn as vertical stripes - the courses seen end on,
a lit yellow hip to the west and a shaded red one to the east - not as more
of the front slope. `hip_band` turns those drawn columns into rows so the
hips are laid with their own courses: the same pixels, transposed, appended
below the art where the projection never reads them.

Pallet Town's houses (cells 5..9 x 3..7 and 14..18 x 3..7), 80 x 80:

    row   8       ridge line (grey outline)
    rows  9-13    top of the front slope, the irregular first course
    rows 14-39    front slope: courses of 8 rows (lines at 19/20, 27/28,
                  35/36), x 12..66; hips x 0..11 (west) and 67..79 (east)
    rows 40-43    fascia: dark line, red board, navy and grey edge
    rows 44-47    the wall's top in the eave's shade (grey, light grey)
    rows 48-79    facade: siding, windows, door; corner posts x 1..7, 72..79

The house stands on four collision rows (z 16..80), twice what the drawing's
depth reads, so the front slope keeps its drawn courses and grows by more of
them; the roof's own top rows ride up to the ridge as a tail.

Professor Oak's lab (cells 13..19 x 9..13), 112 x 80:

    rows  8-10    back parapet top     rows 11-14  its inner face (dark)
    rows 15-39    flat roof of panels, 8 x 8, lines at rows 20/28/36
    row  40       shadow line at the front parapet
    rows 41-42    front parapet top    rows 43-47  roof slab front
    rows 48-79    facade: brick, four portholes, two windows, the door
    x 80..103, rows 10..38: the rooftop machine - a box (top rows 10..24,
    front rows 25..35) with fins either side and its drawn shadow

The Pokemon Center (5 x 5 cells, Pewter's 15..19 x 21..25) and the Poke Mart
(4 x 4, Viridian's 34..37 x 16..19) are one building in two sizes and two
paint jobs, Emerald's shape: an octagonal plan (8-px chamfers), a roof band
rising 6 at 45 degrees, a flat top of 4 x 4 panels. Mart / Center rows:

    rows  2-7 / 10-15   the top's back rim
    rows  8-31 / 16-39  the panels (lines every 4 rows from 8 / 16)
    rows 32-43 / 40-51  the band, the emblem plate drawn over its middle
    rows 44-63 / 52-79  walls: fascia, glass, sign, door, plinth
    x 1-6 and the last 7 columns: the band's sides, drawn as stripes

The Center's top row of cells is each town's own tileset (the roof's back
over that town's ground), so only the rows below it must match.
"""

import math

from PIL import Image

from voxel_building import (Band, Frustum, HipRoof, Prism, Proj, Strip, Tile, SHADE_ART,
                            SHADE_BACK, SHADE_EAST, SHADE_WEST, strip_face, _unit)

GRASS = 0x011            # gTileset_General's plain grass, under every house
PATH = 0x296             # Pallet Town's light path
PALLET_GROUND = [GRASS, 0x009, PATH, 0x28E, 0x29E, 0x295, 0x297, 0x2C6, 0x2C7, 0x2BE,
                 0x2BF, 0x2CE, 0x2AE]


# ── art bands ──────────────────────────────────────────────────────────────

def extend(art, rows):
    """The art with `rows` transparent rows appended; returns (image, first)."""
    w, h = art.size
    out = Image.new("RGBA", (w, h + rows), (0, 0, 0, 0))
    out.paste(art, (0, 0))
    return out, h


def hip_band(art, top, columns, sample_row, length):
    """Write a hip's drawn columns as rows at `top`.

    `columns` lists the art columns from the eave inwards (up the hip); each
    becomes one uniform row, the eave column at the bottom. The last four
    columns are the hip's course period and repeat upwards until the band is
    `length` rows tall. Returns the (a, b) rows for a Strip.
    """
    px = art.load()
    w = art.size[0]
    seq = [px[x, sample_row] for x in columns]
    period = seq[-4:]
    while len(seq) < length:
        seq.append(period[(len(seq) - len(columns)) % 4])
    for i, c in enumerate(seq):
        y = top + length - 1 - i
        for x in range(w):
            px[x, y] = c
    return (top, top + length)


class KeepStrip(Strip):
    """A Strip that reads columns [keep_lo, keep_hi) as drawn (u = X) and
    takes everything outside them from `wrap`, cyclically: a front slope
    whose drawn middle must stay exact while the triangles beyond it (where
    the art draws the hips) carry on with clean courses."""

    def __init__(self, *args, keep=None, **kw):
        super().__init__(*args, **kw)
        self.keep = keep

    def u_pieces(self, s0, s1):
        if self.keep is None:
            return super().u_pieces(s0, s1)
        lo, hi = self.keep
        out = []
        if s0 < lo:
            out += super().u_pieces(s0, min(s1, lo))
        if s1 > lo and s0 < hi:
            out.append((max(s0, lo), min(s1, hi), self.offset))
        if s1 > hi:
            out += super().u_pieces(max(s0, hi), s1)
        return out


# ── a hipped roof whose four slopes take their own courses ─────────────────

class FrHipRoof(HipRoof):
    """HipRoof with a Strip per slope: `slope` for the front (and back),
    `hip_w` / `hip_e` for the side slopes."""

    def __init__(self, *args, hip_w=None, hip_e=None, back=None, **kw):
        super().__init__(*args, **kw)
        self.hip_w = hip_w or self.slope
        self.hip_e = hip_e or self.slope
        self.back = back or self.slope

    def emit(self, mesh):
        x0, x1, zf, zb, y0, ye = self.x0, self.x1, self.zf, self.zb, self.y0, self.ye
        xa, xb = x0 + self.run, x1 - self.run
        zr, zq, yr = self.z_rf, self.z_rb, self.yr
        n = self.name
        up = (0.0, 1.0, 0.0)
        fas = self.fascia
        strip_face(mesh, [(x0, y0, zf), (x1, y0, zf), (x1, ye, zf), (x0, ye, zf)],
                   (0, y0, zf), (1, 0, 0), up, fas, SHADE_ART, n + ".fascia_s")
        strip_face(mesh, [(x1, y0, zb), (x0, y0, zb), (x0, ye, zb), (x1, ye, zb)],
                   (0, y0, zb), (1, 0, 0), up, fas, SHADE_BACK, n + ".fascia_n")
        strip_face(mesh, [(x0, y0, zb), (x0, y0, zf), (x0, ye, zf), (x0, ye, zb)],
                   (x0, y0, 0), (0, 0, 1), up, fas, SHADE_WEST, n + ".fascia_w")
        strip_face(mesh, [(x1, y0, zf), (x1, y0, zb), (x1, ye, zb), (x1, ye, zf)],
                   (x1, y0, 0), (0, 0, 1), up, fas, SHADE_EAST, n + ".fascia_e")
        t_s = _unit((0, self.rise, -(zf - zr)))
        t_n = _unit((0, self.rise, (zf - zr)))
        t_w = _unit((self.run, self.rise, 0))
        t_e = _unit((-self.run, self.rise, 0))
        strip_face(mesh, [(x0, ye, zf), (x1, ye, zf), (xb, yr, zr), (xa, yr, zr)],
                   (0, ye, zf), (1, 0, 0), t_s, self.slope, SHADE_ART, n + ".slope_s")
        strip_face(mesh, [(x1, ye, zb), (x0, ye, zb), (xa, yr, zq), (xb, yr, zq)],
                   (0, ye, zb), (1, 0, 0), t_n, self.back, SHADE_BACK, n + ".slope_n")
        # FireRed draws both hips (lit yellow, shaded red): their own art
        # already carries the light, so they keep it as drawn
        strip_face(mesh, [(x0, ye, zb), (x0, ye, zf), (xa, yr, zr), (xa, yr, zq)],
                   (x0, ye, 0), (0, 0, 1), t_w, self.hip_w, SHADE_ART, n + ".hip_w")
        strip_face(mesh, [(x1, ye, zf), (x1, ye, zb), (xb, yr, zq), (xb, yr, zr)],
                   (x1, ye, 0), (0, 0, 1), t_e, self.hip_e, SHADE_ART, n + ".hip_e")
        if not self.ridge:
            return
        yt = self.yt
        lo, hi = self.ridge_u
        teeth = Strip(self.teeth, offset=lo - xa)
        cap = Strip(self.cap, offset=lo - xa)
        strip_face(mesh, [(xa, yr, zr), (xb, yr, zr), (xb, yt, zr), (xa, yt, zr)],
                   (0, yr, zr), (1, 0, 0), up, teeth, SHADE_ART, n + ".teeth")
        strip_face(mesh, [(xa, yt, zr), (xb, yt, zr), (xb, yt, zq), (xa, yt, zq)],
                   (0, yt, zr), (1, 0, 0), (0, 0, -1), cap, SHADE_ART, n + ".cap")


# ── Pallet Town ────────────────────────────────────────────────────────────

HOUSE_PITCH = 28.0
FACADE_HOUSE_PLASTER = (8, 16)     # siding columns with no window, door or post


def pallet_house(art):
    """Both Pallet houses (the player's and the rival's draw the same)."""
    art, band0 = extend(art, 96)
    hip_w = hip_band(art, band0, list(range(0, 12)), 20, 48)
    hip_e = hip_band(art, band0 + 48, list(range(79, 67, -1)), 20, 48)

    front_z, back_z = 80, 16       # collision rows 4..7
    overhang = 2
    wall_top = 38                  # up under the eave (y0 of the roof)
    roof = FrHipRoof(
        "roof", 0, 80, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
        fascia=Strip((40, 44), wrap=(16, 60)),
        # the drawn courses from the eave, more of the 8-row course, and the
        # drawn top rows riding up to the ridge
        slope=KeepStrip((14, 40), repeat=(21, 29), start=28, tail=(9, 14),
                        wrap=(16, 60), keep=(12, 67)),
        back=Strip((14, 40), repeat=(21, 29), start=28, tail=(9, 14), wrap=(16, 60)),
        teeth=(8, 9), cap=(8, 9), pitch=HOUSE_PITCH, run=12,
        ridge_u=(12, 68), end_tile=Tile(12, 8, 13, 9),
        hip_w=Strip(hip_w, wrap=(0, 40)), hip_e=Strip(hip_e, wrap=(0, 40)))

    px0, px1 = FACADE_HOUSE_PLASTER
    plaster = Tile(px0, 48, px1, 80, top=32)
    corner = Tile(1, 48, 8, 80, top=32)
    ground_floor = Prism(
        "walls", 1, 80,
        [(front_z, 0), (front_z, 32), (back_z, 32), (back_z, 0)],
        edges={0: Proj(48, 80), 2: plaster}, skip=(1, 3),
        caps=[Band(0, 32, plaster, front_z, front=corner, back=corner, z1=back_z)])
    # The wall's top in the eave's shade. At the corners (x < 8, x >= 72)
    # the art draws the roof's tips over it, so those ends take the clean
    # shade band rather than the tips' red.
    shade = Tile(px0, 44, px1, 48, top=36)
    band_poly = [(front_z, 32), (front_z, wall_top), (back_z, wall_top), (back_z, 32)]
    eave_band = [
        Prism("eave_w", 1, 8, band_poly, edges={0: shade, 2: shade}, skip=(1, 3),
              east=False, caps=[Band(32, wall_top + 1, shade, front_z)]),
        Prism("eave_band", 8, 72, band_poly, edges={0: Proj(44, 48), 2: shade},
              skip=(1, 3), caps=None),
        Prism("eave_e", 72, 80, band_poly, edges={0: shade, 2: shade}, skip=(1, 3),
              west=False, caps=[Band(32, wall_top + 1, shade, front_z)]),
    ]
    return [ground_floor] + eave_band + [roof], art


HOUSE_EXACT = [(1, 48, 80, 80), (8, 44, 72, 48), (12, 40, 68, 44), (12, 14, 67, 40)]


def oaks_lab(art):
    front_z, back_z = 80, 16       # collision rows 10..13
    roof_y = 37                    # the slab's top: rows 41..42 lie on it
    brick = Tile(40, 50, 48, 78, top=30)
    post = Tile(0, 48, 4, 80, top=32)

    walls = Prism(
        "walls", 0, 112,
        [(front_z, 0), (front_z, roof_y), (back_z, roof_y), (back_z, 0)],
        edges={0: Proj(43, 80), 2: Tile(40, 43, 48, 80, top=roof_y)}, skip=(1, 3),
        caps=[Band(0, 32, brick, front_z, front=post, back=post, z1=back_z),
              Band(32, roof_y + 1, Tile(40, 43, 48, 48, top=roof_y), front_z)])

    # The flat roof, front to back: the parapet top and the shadow line, the
    # drawn panels, more panels (period 8), and the first panel row under the
    # back parapet. Over the machine (x 80..104) the panels come from clean
    # columns, period-aligned, so its drawn shadow is not painted on the roof.
    back_parapet = 2
    def top(name, xa, xb, wrap=None):
        return Prism(
            name, xa, xb,
            [(front_z, roof_y - 1), (front_z, roof_y), (back_z + back_parapet, roof_y),
             (back_z + back_parapet, roof_y - 1)],
            edges={1: Strip((21, 43), repeat=(21, 29), start=28, tail=(15, 21), wrap=wrap)},
            skip=(0, 2, 3), caps=None)
    roofs = [top("roof_w", 0, 80), top("roof_m", 80, 104, wrap=(16, 40)),
             top("roof_e", 104, 112)]

    # the back parapet: its dark inner face (rows 11..14) and its top (9..10)
    parapet_h = 4
    zb0, zb1 = back_z, back_z + back_parapet
    parapet = Prism(
        "parapet", 0, 112,
        [(zb1, roof_y), (zb1, roof_y + parapet_h), (zb0, roof_y + parapet_h), (zb0, roof_y)],
        edges={0: Tile(4, 11, 76, 15), 1: Strip((9, 11)), 2: Tile(4, 11, 76, 15)},
        skip=(3,), caps=[Band(roof_y, roof_y + parapet_h + 1, Tile(4, 9, 6, 11), zb1)])

    # The machine: front at z 73 (its bottom row 35 meets the roof there),
    # 15 deep (its top is drawn on rows 10..24) and 11 tall.
    mz, md, mh = 73, 15, 11
    maroon = Tile(86, 25, 96, 31, top=roof_y + mh)
    machine = Prism(
        "machine", 84, 98,
        [(mz, roof_y), (mz, roof_y + mh), (mz - md, roof_y + mh), (mz - md, roof_y)],
        edges={2: maroon}, skip=(3,),
        caps=[Band(roof_y, roof_y + mh + 1, maroon, mz)])
    fins = [Prism(
        name, xa, xb,
        [(mz, roof_y), (mz, roof_y + mh), (mz - md, roof_y + mh), (mz - md, roof_y)],
        edges={2: Tile(xa, 25, xb, 31, top=roof_y + mh)}, skip=(3,),
        caps=[Band(roof_y, roof_y + mh + 1, Tile(xa, 25, xb, 31, top=roof_y + mh), mz)])
        for name, xa, xb in (("fin_w", 80, 84), ("fin_e", 98, 102))]
    return [walls] + roofs + [parapet, machine] + fins, art


LAB_EXACT = [(0, 41, 112, 80), (4, 21, 80, 41), (104, 21, 112, 41), (84, 10, 98, 36)]



# ── the Pokemon Center and the Poke Mart ──────────────────────────────────

def center_or_mart(width, height, top_rows, tail, wall_side, band_side):
    """`width` x `height` px of art; `top_rows` the drawn panels (a, b), b the
    top's front edge; the band below it rises 6 to there. The sides take
    `wall_side` and `band_side`, read where the facade and the band are plain
    (no sign, no emblem plate)."""
    front, back, c = height, 16, 8
    rise = 6
    wall_top = height - (top_rows[1] + 2 * rise)
    plan = [(c, front), (width - c, front), (width, front - c), (width, back + c),
            (width - c, back), (c, back), (0, back + c), (0, front - c)]
    a, b = top_rows
    return [Frustum(
        "body", plan, wall_top=wall_top, wall_side=wall_side,
        band_rise=rise,
        band_side=band_side,
        top=Strip((a, b), repeat=(a, a + 4), tail=tail, wrap=(8, width - 8)))]


def poke_mart(art):
    return center_or_mart(64, 64, (8, 32), (3, 8), Strip((48, 64), wrap=(26, 31)),
                          Strip((38, 44), wrap=(9, 15))), art


def pokemon_center(art):
    return center_or_mart(80, 80, (16, 40), (11, 16), Strip((64, 80), wrap=(25, 31)),
                          Strip((45, 52), wrap=(12, 20))), art


MART_EXACT = [(8, 32, 56, 64), (12, 8, 52, 32)]
CENTER_EXACT = [(8, 40, 72, 80), (12, 16, 68, 40)]
TOWN_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x00E, 0x00F, 0x01E, 0x01F,
               0x016, 0x017, 0x026, 0x027, 0x0E6, 0x0E7, 0x165, 0x167, 0x16D, 0x16F,
               0x1B8, 0x1B9]



# ── Viridian City ──────────────────────────────────────────────────────────

def viridian_house(art):
    """Viridian's green houses (cells 24..28 x 8..11), 80 x 64:

        rows  8-15   the back slope's corrugated sheets, lit
        rows 16-19   the ridge: a light line, then its front
        rows 20-41   the front slope, its ribs running front to back
        rows 42-45   the sheets' drip edge and the fascia's outline
        rows 46-63   facade: eave shade, windows, the shutter, the door
        x 48..65, rows 8..39: a chimney stack with a window, its front
        standing on the front slope where its row 39 meets the sheets

    The sheets' ribs repeat every 4 columns and are the same on every row,
    so the slopes grow to the real depth with more of the same rows.
    """
    front_z, back_z = 64, 16       # collision rows 1..3
    overhang = 2
    wall_top = 20                  # the fascia (rows 42..45) hides 44..45
    ribs = (4, 44)                 # a whole number of 4-px ribs, no chimney
    roof = HipRoof(
        "roof", 0, 80, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
        fascia=Strip((42, 46), wrap=ribs),
        slope=Strip((21, 42), repeat=(21, 25), tail=(20, 21), wrap=ribs),
        teeth=(18, 20), cap=(16, 18), pitch=25.0, run=4,
        ridge_u=(4, 44), end_tile=Tile(4, 16, 8, 20))

    plaster = Tile(33, 46, 41, 64, top=wall_top)
    corner = Tile(1, 46, 3, 64, top=wall_top)
    walls = Prism(
        "walls", 1, 79,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(46, 64), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z)])

    # The chimney: its front's bottom row (39) is 3 rows above the drip
    # edge; standing 2 up the slope keeps that row clear of the sheets. Its
    # top is drawn on rows 8..10 and grows backwards.
    zc, yc = roof.slope_point(2)
    yt = zc - 11
    depth = 14
    brick = Tile(51, 24, 61, 31, top=yt)
    chimney = Prism(
        "chimney", 48, 66,
        [(zc, yc - 6), (zc, yt), (zc - depth, yt), (zc - depth, yc - 6)],
        edges={0: Proj(11, 40), 1: Strip((9, 11), repeat=(9, 10), tail=(8, 9)), 2: brick},
        skip=(3,), caps=[Band(-64, 200, brick, zc)])
    return [walls, roof, chimney], art


def viridian_house_planters(art):
    """The same house (cells 24..28 x 15..19) with planters along its front,
    a cell deep, either side of the door: boxes on rows 64..71, their
    flowers on 56..63 as their top."""
    parts, art = viridian_house(art)
    box = Tile(3, 64, 13, 72, top=8)
    planters = [Prism(name, x0, x1, [(72, 0), (72, 8), (64, 8), (64, 0)],
                      edges={0: Proj(64, 72)}, skip=(3,), caps=[Band(0, 9, box, 72)])
                for name, x0, x1 in (("planter_w", 1, 16), ("planter_e", 32, 79))]
    return parts + planters, art


VIRIDIAN_PLANTERS_EXACT = [(3, 46, 77, 56), (16, 56, 32, 64), (4, 21, 44, 42),
                           (48, 11, 66, 40), (1, 56, 16, 72), (32, 56, 79, 72)]


VIRIDIAN_HOUSE_EXACT = [(3, 46, 77, 64), (4, 21, 44, 42), (48, 11, 66, 40)]
def gym(cells):
    """The Gym, General's own (metatiles 139..15E): the same building 6, 7
    or 8 cells wide, the extra bays added before its east end. Viridian's
    (cells 33..38 x 6..10), 96 x 80:

        rows  1-3    the roof's back rim (each town's own tileset)
        rows  4-41   flat roof, gold stripes every 2 rows, a rim drawn
                     round it (x 0-5 and the last 6 columns)
        rows 42-46   the cornice
        rows 47-71   facade: windows, the GYM plate over the entrance
        x 40..72, rows 64..79: the entrance, standing half a cell forward
        of the facade, its double door; its top is the plate's lower rows
    """
    width = cells * 16

    def parts(art):
        front_z, back_z = 72, 16
        wall_top = 25              # the facade's top outline is row 47
        roof_y = wall_top + 5      # the cornice, rows 42..46
        plaster = Tile(26, 56, 38, 60, top=wall_top)
        corner = Tile(1, 47, 7, 72, top=wall_top)
        walls = Prism(
            "walls", 1, width - 1,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(47, 72), 2: plaster}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z)])
        cornice = Tile(10, 42, 18, 47, top=roof_y)
        roof = Prism(
            "roof", 0, width,
            [(front_z, wall_top), (front_z, roof_y), (back_z, roof_y), (back_z, wall_top)],
            edges={0: Proj(42, 47), 1: Strip((4, 42), repeat=(22, 24), tail=(1, 4)),
                   2: cornice},
            skip=(3,), caps=[Band(wall_top, roof_y + 1, cornice, front_z)])
        pillar = Tile(42, 66, 46, 74, top=16)
        entrance = Prism(
            "entrance", 40, 72, [(80, 0), (80, 16), (72, 16), (72, 0)],
            edges={0: Proj(64, 80)}, skip=(2, 3), caps=[Band(0, 17, pillar, 80)])
        return [walls, roof, entrance], art
    return parts


def gym_exact(cells):
    width = cells * 16
    return [(2, 47, width - 2, 72), (40, 64, 72, 80), (0, 42, width, 47), (0, 22, width, 42)]


VIRIDIAN_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x165, 0x166, 0x167, 0x16D,
                   0x16E, 0x16F, 0x175, 0x176, 0x177, 0x195, 0x196, 0x19D, 0x19E]



# ── Pewter City ────────────────────────────────────────────────────────────

def pewter_house(art):
    """Pewter's slate houses (cells 32..36 x 8..11), 80 x 64:

        rows  9-15   the back slope, light (snow-white courses)
        rows 16-20   the ridge: its top line, its front, the slope's first line
        rows 21-43   the front slope, slate courses of 4 rows (lines at 23,
                     27 .. 43), verge trims x 0-3 and 76-79
        rows 44-46   the eave
        rows 47-63   facade: windows, the door, siding
    """
    front_z, back_z = 64, 16
    overhang = 2
    wall_top = 19                  # under the eave, rows 44..46
    slate = (8, 72)
    roof = HipRoof(
        "roof", 0, 80, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
        fascia=Strip((44, 47), wrap=slate),
        slope=Strip((21, 44), repeat=(24, 28), start=24, tail=(20, 21), wrap=slate),
        teeth=(17, 20), cap=(16, 17), pitch=25.0, run=4,
        ridge_u=(8, 72), end_tile=Tile(8, 17, 12, 20))
    plaster = Tile(33, 47, 41, 64, top=wall_top)
    corner = Tile(1, 47, 3, 64, top=wall_top)
    walls = Prism(
        "walls", 1, 79,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(47, 64), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z)])
    return [walls, roof], art


PEWTER_HOUSE_EXACT = [(3, 47, 77, 64), (4, 21, 76, 44)]
def pewter_annex(art):
    """The museum's annex (cells 23..27 x 1..4), 80 x 64:

        row   1      the ridge line
        rows  2-15   the back slope, light pink sheets
        rows 16-42   the front slope, darker, the sheets' ribs every 4 px
        rows 43-45   fascia, rows 46-47 the eave's shade
        rows 48-63   facade: posts, windows, the door
        x 72..79     the east end's white pillar, drawn over the roof's end
    """
    front_z, back_z = 64, 16
    overhang = 2
    wall_top = 20
    sheets = (0, 72)
    roof = FrHipRoof(
        "roof", 0, 80, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
        fascia=Strip((43, 46), wrap=sheets),
        slope=Strip((16, 43), repeat=(16, 20), wrap=sheets),
        back=Strip((2, 16), repeat=(2, 6), wrap=sheets),
        teeth=(1, 2), cap=(1, 2), pitch=25.0, run=4,
        ridge_u=(0, 72), end_tile=Tile(0, 1, 4, 2))
    plaster = Tile(23, 46, 32, 64, top=wall_top)
    corner = Tile(0, 46, 2, 64, top=wall_top)
    walls = Prism(
        "walls", 0, 79,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(46, 64), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z)])
    return [walls, roof], art


PEWTER_ANNEX_EXACT = [(0, 46, 79, 64), (4, 16, 72, 43)]


def pewter_museum(art):
    """The Museum of Science (cells 12..22 x 0..6), 176 x 128:

        rows 10-23   the upper roof's back slope, light pink sheets
        rows 24-47   its front slope, darker; rows 48-50 its eave
        rows 51-55   a clerestory of small windows
        rows 56-65   the lower roof, rows 66-71 its eave and the cornice
        rows 72-95   facade: arched windows between columns
        x 0..7 / 168..175, rows 8..69: white end walls standing above it
        all; x 8..15 / 160..167, rows 13..55: a second pair, on the lower
        roof, framing the upper one
        x 64..111: the porch - its top drawn on rows 72..95 over the
        facade, its front (columns, the door) on 96..119; the steps below
        are the map's own
    """
    front_z, back_z = 96, 16
    wall_top = 24
    plaster = Tile(1, 72, 3, 96, top=wall_top)
    walls = Prism(
        "walls", 1, 175,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(72, 96), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z)])
    # the lower roof: its eave (rows 66..71) and its slope (56..65) up to the
    # clerestory, drawn as the GBA sees them
    lower = Prism(
        "lower_roof", 8, 168,
        [(front_z, wall_top), (front_z, 30), (92, 36), (back_z, 36), (back_z, wall_top)],
        edges={0: Proj(66, 72), 1: Proj(56, 66), 3: Tile(16, 60, 24, 64, top=36)},
        skip=(2, 4), caps=[Band(wall_top, 37, Tile(16, 60, 24, 64, top=36), front_z)])
    clerestory = Prism(
        "clerestory", 16, 160, [(92, 36), (92, 42), (20, 42), (20, 36)],
        edges={0: Proj(51, 56)}, skip=(1, 2, 3), caps=None)
    sheets = (16, 160)
    roof = FrHipRoof(
        "roof", 16, 160, zf=93, zb=19, y0=42,
        fascia=Strip((48, 51), wrap=sheets),
        slope=Strip((24, 48), repeat=(24, 28), wrap=sheets),
        back=Strip((15, 24), repeat=(15, 19), wrap=sheets),
        teeth=(23, 24), cap=(23, 24), pitch=25.0, run=4,
        ridge_u=(16, 160), end_tile=Tile(16, 23, 20, 24))
    # the end walls follow the roof up to the ridge and down behind it, a
    # little above the sheets: gables, read as the drawing's white strips
    white = Tile(2, 30, 6, 44, top=roof.yt)
    column = Strip((30, 44), wrap=(1, 7))
    ends = []
    for name, x0, x1, z, y0, rows, lift in (("end_w", 0, 8, front_z, wall_top, (9, 70), 4),
                                            ("end_e", 168, 176, front_z, wall_top, (9, 70), 4),
                                            ("frame_w", 8, 16, 92, 36, (13, 56), 2),
                                            ("frame_e", 160, 168, 92, 36, (13, 56), 2)):
        eave, ridge = roof.ye + lift, roof.yt + lift
        poly = [(z, y0), (z, eave), (roof.z_rf, ridge), (roof.z_rb, ridge),
                (back_z, eave), (back_z, y0)]
        ends.append(Prism(
            name, x0, x1, poly,
            edges={0: Proj(*rows), 1: Proj(*rows), 2: Proj(*rows), 3: column, 4: column},
            skip=(5,), caps=[Band(y0, ridge + 1, white, z)]))
    porch = Prism(
        "porch", 64, 112, [(120, 0), (120, 24), (front_z, 24), (front_z, 0)],
        edges={0: Proj(96, 120), 1: Proj(72, 96)}, skip=(2, 3),
        caps=[Band(0, 25, Tile(66, 98, 69, 118, top=24), 120)])
    return [walls, lower, clerestory, roof, porch] + ends, art


PEWTER_MUSEUM_EXACT = [(1, 72, 175, 96), (64, 96, 112, 120), (16, 56, 160, 72),
                       (16, 51, 160, 56), (20, 24, 156, 51)]
PEWTER_MUSEUM_OWNED = ({(i, j) for i in range(11) for j in range(6)}
                       | {(i, 6) for i in (4, 5, 6)})


PEWTER_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x1B8, 0x1B9, 0x1BB, 0x1C0,
                 0x1C1, 0x1C9, 0x1CA, 0x0E6]


# ── Cerulean City ──────────────────────────────────────────────────────────

def cerulean_house(cells):
    """Cerulean's blue houses, built from a kit: an end, as many middles
    as the width takes, the other end; doors and windows swapped into the
    facade row. 16 * cells x 64, the rows of every width:

        row   8      the ridge line
        rows  9-39   the front slope: courses of 4 rows (lines at 11 .. 39)
        x 0-10 / the last 12 columns: the hips, drawn as stripes, lit to the
                     west and shaded to the east, the eave running diagonally
        rows 40-42   fascia, rows 43-47 the wall's top in the eave's shade
        rows 48-63   facade: siding, windows, the sliding door, green posts

    The top row of cells is mostly the map's - fences, flowers, trees behind
    the roof - so only the three rows below it are the model's.
    """
    width = cells * 16

    def parts(art):
        art, band0 = extend(art, 96)
        hip_w = hip_band(art, band0, list(range(0, 11)), 30, 48)
        hip_e = hip_band(art, band0 + 48, list(range(width - 1, width - 13, -1)), 30, 48)
        front_z, back_z = 64, 16
        overhang = 2
        courses = (12, width - 12)     # clear of both hips, whole 4-px tiles
        wall_top = 23              # the fascia is rows 40..42
        roof = FrHipRoof(
            "roof", 0, width, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
            fascia=Strip((40, 43), wrap=courses),
            slope=KeepStrip((9, 40), repeat=(12, 16), start=12, wrap=courses,
                            keep=(11, width - 12)),
            back=Strip((9, 40), repeat=(12, 16), start=12, wrap=courses),
            teeth=(8, 9), cap=(8, 9), pitch=HOUSE_PITCH, run=11,
            ridge_u=(12, width - 12), end_tile=Tile(12, 8, 13, 9),
            hip_w=Strip(hip_w, wrap=(0, 40)), hip_e=Strip(hip_e, wrap=(0, 40)))
        plaster = Tile(9, 43, 17, 64, top=wall_top)
        corner = Tile(1, 43, 4, 64, top=wall_top)
        walls = Prism(
            "walls", 1, width - 1,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(43, 64), 2: plaster}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z)])
        return [walls, roof], art
    return parts


def cerulean_exact(cells):
    width = cells * 16
    return [(4, 43, width - 4, 64), (12, 9, width - 12, 40)]


def cerulean_bike_shop(art):
    """The bike shop (cells 12..15 x 23..28), 64 x 96:

        rows  8-12   the glass roof's back frame
        rows 13-50   glass panels, a pattern 8 rows tall; frame x 0-4, 59-63
        row  51      the front frame; rows 52-55 the parapet's face
        rows 56-95   facade: windows, the striped awning (72-86), its posts
                     and the shop in its shade (87-95), all drawn flat

    The awning is drawn on the facade and stays there: as a box it would
    stand outside the shop's cells.
    """
    front_z, back_z = 96, 16
    wall_top = 40
    grey = Tile(5, 56, 9, 64, top=wall_top)
    walls = Prism(
        "walls", 1, 63,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(56, 96), 2: grey}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, grey, front_z)])
    frame = Tile(0, 52, 4, 56, top=wall_top + 4)
    roof = Prism(
        "roof", 0, 64,
        [(front_z, wall_top), (front_z, wall_top + 4), (back_z, wall_top + 4), (back_z, wall_top)],
        edges={0: Proj(52, 56), 1: Strip((13, 52), repeat=(13, 21), start=20, tail=(8, 13)),
               2: frame},
        skip=(3,), caps=[Band(wall_top, wall_top + 5, frame, front_z)])
    return [walls, roof], art


BIKE_SHOP_EXACT = [(1, 56, 63, 96), (0, 52, 64, 56), (0, 13, 64, 52)]


CERULEAN_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x0D3, 0x0D4, 0x0D5, 0x005,
                   0x0F5, 0x0E4, 0x0DB, 0x0DC, 0x0DD]
CERULEAN_HOUSES = [(8, 8, 7), (15, 8, 6), (28, 8, 7), (38, 7, 6), (13, 14, 7), (21, 25, 6),
                   (31, 25, 5)]


# ── Lavender Town ──────────────────────────────────────────────────────────

def flat_roof(name, x0, x1, front_z, back_z, y0, parapet, top, side):
    """A flat roof slab: its front face is art rows `parapet` (a, b) as the
    GBA sees them, its top the Strip `top` laid back from the front edge."""
    y1 = y0 + parapet[1] - parapet[0]
    return Prism(
        name, x0, x1, [(front_z, y0), (front_z, y1), (back_z, y1), (back_z, y0)],
        edges={0: Proj(*parapet), 1: top, 2: side}, skip=(3,),
        caps=[Band(y0, y1 + 1, side, front_z)])


def lavender_house(art):
    """Lavender's purple houses (cells 8..12 x 8..11), 80 x 64:

        rows  8-9    the roof's back rim
        rows 10-38   the flat roof: a border (10-13, 35-38) round a panel
        rows 39-41   the parapet's face, rows 42-43 the eave line
        rows 44-63   facade: yellow corner posts, windows, the door
    """
    front_z, back_z = 64, 16
    wall_top = 22
    plaster = Tile(10, 56, 26, 61, top=wall_top)
    walls = Prism(
        "walls", 0, 80,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(42, 64), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z)])
    roof = flat_roof("roof", 0, 80, front_z, back_z, wall_top, (39, 42),
                     Strip((14, 39), repeat=(20, 24), tail=(9, 14)), Tile(10, 40, 26, 42))
    return [walls, roof], art


def pokemon_tower(art):
    """The Pokemon Tower (cells 15..21 x 0..6), 112 x 112:

        rows 81-110  the podium's front: the ground floor, its door
        rows 55-80   the podium's top, in front of the tower (and, at the
                     sides, x 0-5 / 106-111, on up behind it)
        rows  0-54   the tower's face, floor after floor of windows, running
                     off the top of the map

    So a podium the whole footprint deep, and on it a tower 55 px taller.
    """
    front_z, back_z = 112, 24
    podium_y = 31
    stone = Tile(3, 30, 6, 40, top=podium_y)
    podium = Prism(
        "podium", 0, 112,
        [(front_z, 0), (front_z, podium_y), (back_z, podium_y), (back_z, 0)],
        edges={0: Proj(81, 112), 1: Proj(0, 81), 2: stone}, skip=(3,),
        caps=[Band(0, podium_y + 1, stone, front_z)])
    tower_z, tower_y = 86, 86
    windows = Tile(22, 16, 38, 32, top=tower_y)
    tower = Prism(
        "tower", 6, 106,
        [(tower_z, podium_y), (tower_z, tower_y), (back_z + 8, tower_y), (back_z + 8, podium_y)],
        edges={0: Proj(0, 56), 1: stone, 2: windows}, skip=(3,),
        caps=[Band(podium_y, tower_y + 1, windows, tower_z)])
    return [podium, tower], art


POKEMON_TOWER_EXACT = [(6, 0, 106, 55), (0, 55, 112, 112)]


LAVENDER_HOUSE_EXACT = [(0, 42, 80, 64), (0, 39, 80, 42), (0, 14, 80, 39)]


# ── Vermilion City ─────────────────────────────────────────────────────────

def shed_house(cells, ribs=(10, 38), eave=(38, 42), facade_top=42, rise=12):
    """A house under one corrugated slope falling to the front, its ribs
    running front to back (Vermilion's orange houses, the Fan Club):

        rows  8-9    the sheets' back ends
        rows 10-37   the ribs, the same on every row
        rows 38-41   the sheets' front ends over the eave
        rows 42-63   facade
    """
    width = cells * 16

    def parts(art):
        front_z, back_z = 64, 16
        wall_top = front_z - facade_top
        plaster = Tile(4, 44, 12, 56, top=wall_top)
        walls = Prism(
            "walls", 0, width,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(facade_top, 64), 2: plaster}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, plaster, front_z)])
        y1 = wall_top + eave[1] - eave[0]
        a, b = ribs
        rib_end = Tile(0, eave[0], 8, eave[1], top=y1)
        roof = Prism(
            "roof", 0, width,
            [(front_z, wall_top), (front_z, y1), (back_z, y1 + rise), (back_z, wall_top)],
            edges={0: Proj(*eave), 1: Strip((a, b), repeat=(a + 8, a + 12), tail=(a - 2, a)),
                   2: rib_end},
            skip=(3,), caps=[Band(wall_top, y1 + rise + 1, rib_end, front_z)])
        return [walls, roof], art
    return parts


def shed_exact(cells, ribs=(10, 38), facade_top=42):
    width = cells * 16
    return [(0, facade_top, width, 64), (0, ribs[1], width, facade_top), (0, ribs[0] + 4, width, ribs[1])]


def canopy(art):
    """Vermilion's harbour canopies (3 x 4 cells): a roof on four posts over
    the path. Top rows 28..41, its edge 42..47, the front posts (x 1-4 and
    44-47) 48..61; the back posts stand hidden behind."""
    z, y0, y1 = 62, 14, 20
    roof = flat_roof("roof", 0, 48, z, 28, y0, (42, 48),
                     Strip((29, 42), repeat=(30, 34), tail=(28, 29)), Tile(0, 42, 8, 48))
    post = Tile(1, 53, 5, 61, top=y0)
    posts = [Prism("post_%d_%d" % (x0, zf), x0, x0 + 4,
                   [(zf, 0), (zf, y0), (zf - 4, y0), (zf - 4, 0)],
                   edges={0: Proj(48, 62), 2: post}, skip=(1, 3), caps=[Band(0, y0 + 1, post, zf)])
             for x0 in (1, 44) for zf in (z, 34)]
    return [roof] + posts, art


CANOPY_EXACT = [(0, 29, 48, 48), (1, 48, 5, 62), (44, 48, 48, 62)]


VERMILION_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x115, 0x12B, 0x12C, 0x1DF]
VERMILION_HOUSES = [(8, 3, 5), (18, 3, 4), (25, 3, 5), (18, 14, 4), (27, 21, 4), (11, 14, 5)]

SPECS = [
    {
        "name": "pallet_house",
        "layout": "LAYOUT_PALLET_TOWN",
        "rect": (5, 3, 5, 5),
        "ground": PALLET_GROUND,
        "parts": pallet_house,
        "exact": HOUSE_EXACT,
    },
    {
        "name": "oaks_lab",
        "layout": "LAYOUT_PALLET_TOWN",
        "rect": (13, 9, 7, 5),
        "ground": PALLET_GROUND,
        "parts": oaks_lab,
        "exact": LAB_EXACT,
    },
    {
        "name": "pokemon_center",
        "layout": "LAYOUT_PEWTER_CITY",
        "rect": (15, 21, 5, 5),
        "match_rows": (1, 5),
        "ground": TOWN_GROUND,
        "parts": pokemon_center,
        "exact": CENTER_EXACT,
    },
    {
        "name": "poke_mart",
        "layout": "LAYOUT_VIRIDIAN_CITY",
        "rect": (34, 16, 4, 4),
        "ground": TOWN_GROUND,
        "parts": poke_mart,
        "exact": MART_EXACT,
    },
    {
        "name": "viridian_house",
        "layout": "LAYOUT_VIRIDIAN_CITY",
        "rect": (24, 8, 5, 4),
        "ground": VIRIDIAN_GROUND,
        "parts": viridian_house,
        "exact": VIRIDIAN_HOUSE_EXACT,
    },
    {
        "name": "viridian_house_planters",
        "layout": "LAYOUT_VIRIDIAN_CITY",
        "rect": (24, 15, 5, 5),
        "ground": VIRIDIAN_GROUND,
        "parts": viridian_house_planters,
        "exact": VIRIDIAN_PLANTERS_EXACT,
    },
    {
        "name": "gym_6",
        "layout": "LAYOUT_VIRIDIAN_CITY",
        "rect": (33, 6, 6, 5),
        "match_rows": (1, 5),
        "ground": VIRIDIAN_GROUND,
        "parts": gym(6),
        "exact": gym_exact(6),
    },
    {
        "name": "pewter_house",
        "layout": "LAYOUT_PEWTER_CITY",
        "rect": (32, 8, 5, 4),
        "ground": PEWTER_GROUND,
        "parts": pewter_house,
        "exact": PEWTER_HOUSE_EXACT,
    },
    {
        "name": "gym_7",
        "layout": "LAYOUT_PEWTER_CITY",
        "rect": (12, 12, 7, 5),
        "match_rows": (1, 5),
        "ground": PEWTER_GROUND,
        "parts": gym(7),
        "exact": gym_exact(7),
    },
    {
        "name": "gym_8",
        "layout": "LAYOUT_CELADON_CITY",
        "rect": (8, 26, 8, 5),
        "match_rows": (1, 5),
        "ground": TOWN_GROUND,
        "parts": gym(8),
        "exact": gym_exact(8),
    },
    {
        "name": "pewter_annex",
        "layout": "LAYOUT_PEWTER_CITY",
        "rect": (23, 1, 5, 4),
        "ground": PEWTER_GROUND,
        "parts": pewter_annex,
        "exact": PEWTER_ANNEX_EXACT,
    },
    {
        "name": "pewter_museum",
        "layout": "LAYOUT_PEWTER_CITY",
        "rect": (12, 0, 11, 8),
        "ground": PEWTER_GROUND,
        "owned": PEWTER_MUSEUM_OWNED,
        "parts": pewter_museum,
        "exact": PEWTER_MUSEUM_EXACT,
    },
]

SPECS += [
    {
        "name": "cerulean_house_%d_%d" % (x, y),
        "layout": "LAYOUT_CERULEAN_CITY",
        "rect": (x, y, cells, 4),
        "ground": CERULEAN_GROUND,
        "owned": {(i, j) for i in range(cells) for j in range(1, 4)},
        "parts": cerulean_house(cells),
        "exact": cerulean_exact(cells),
    }
    for (x, y, cells) in CERULEAN_HOUSES
]

SPECS.append({
    "name": "cerulean_bike_shop",
    "layout": "LAYOUT_CERULEAN_CITY",
    "rect": (12, 23, 4, 6),
    "ground": CERULEAN_GROUND,
    "parts": cerulean_bike_shop,
    "exact": BIKE_SHOP_EXACT,
})

SPECS.append({
    "name": "lavender_house",
    "layout": "LAYOUT_LAVENDER_TOWN",
    "rect": (8, 8, 5, 4),
    "match_rows": (1, 4),
    "ground": [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004],
    "parts": lavender_house,
    "exact": LAVENDER_HOUSE_EXACT,
})
SPECS.append({
    "name": "pokemon_tower",
    "layout": "LAYOUT_LAVENDER_TOWN",
    "rect": (15, 0, 7, 7),
    "ground": [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004],
    "parts": pokemon_tower,
    "exact": POKEMON_TOWER_EXACT,
})
SPECS += [
    {
        "name": "vermilion_house_%d_%d" % (x, y),
        "layout": "LAYOUT_VERMILION_CITY",
        "rect": (x, y, cells, 4),
        "ground": VERMILION_GROUND,
        "owned": {(i, j) for i in range(cells) for j in range(1, 4)},
        "parts": shed_house(cells),
        "exact": shed_exact(cells),
    }
    for (x, y, cells) in VERMILION_HOUSES
]
SPECS += [
    {
        "name": "vermilion_canopy_%d_%d" % (x, y),
        "layout": "LAYOUT_VERMILION_CITY",
        "rect": (x, y, 3, 4),
        "ground": VERMILION_GROUND + [0x1B8, 0x1B9, 0x1BA, 0x1C0, 0x1C1, 0x1C2, 0x302, 0x303],
        "at": [("LAYOUT_VERMILION_CITY", x, y)],
        "parts": canopy,
        "exact": CANOPY_EXACT,
    }
    for (x, y) in ((35, 20), (22, 33))
]
