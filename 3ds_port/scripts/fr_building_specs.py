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
        # the drawn top in front of the tower (rows 55..80), then plain
        # paving behind it: the drawing's rows above are the tower's face
        edges={0: Proj(81, 112), 1: Strip((55, 81), repeat=(72, 74)), 2: stone}, skip=(3,),
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


# ── Celadon City ───────────────────────────────────────────────────────────

def celadon_block(cells, rows, roof_extra):
    """Celadon's green blocks, from a kit: a top edge, one or two rows of
    flat roof, then floors of facade. In the 5-row block:

        rows  8-13   the roof's back rim
        rows 14-34   its panels, lines every 8 rows (20, 28)
        rows 35-38   the front rim; rows 39-41 the parapet's face
        rows 42-79   facade: floors of windows, doors, the base

    A block with `roof_extra` more rows of roof has all of it that much
    lower. The block keeps its whole footprint; the roof grows back with
    more panels.
    """
    width, height = cells * 16, rows * 16
    shift = 16 * roof_extra
    facade_top = 42 + shift

    def parts(art):
        front_z, back_z = height, 16
        wall_top = height - facade_top
        plaster = Tile(0, 56 + shift, 24, 60 + shift, top=wall_top)
        walls = Prism(
            "walls", 0, width,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(facade_top, height), 2: plaster}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, plaster, front_z)])
        roof = flat_roof("roof", 0, width, front_z, back_z, wall_top, (39 + shift, 42 + shift),
                         Strip((14 + shift, 39 + shift), repeat=(21 + shift, 29 + shift),
                               start=21 + shift, tail=(8 + shift, 14 + shift)),
                         Tile(0, 39 + shift, 8, 42 + shift))
        return [walls, roof], art
    return parts


def celadon_exact(cells, rows, roof_extra):
    width, height, shift = cells * 16, rows * 16, 16 * roof_extra
    return [(0, 42 + shift, width, height), (0, 39 + shift, width, 42 + shift),
            (0, 14 + shift, width, 39 + shift)]


def celadon_dept_store(art):
    """The Department Store (cells 9..17 x 5..15), 144 x 176:

        rows  0-4    the roof's back rim
        rows  5-55   the grey roof, its pattern 8 rows tall
        x 32..112:   the penthouse at the roof's front - its top (a yellow
                     panel) on rows 4..35, its face on 36..55
        rows 56-65   the parapet; rows 66-164 the facade, glass bays
                     between pink columns, the doors
    """
    front_z, back_z = 164, 16
    wall_top = front_z - 66
    roof_y = wall_top + 10
    pink = Tile(4, 100, 8, 140, top=wall_top)
    walls = Prism(
        "walls", 1, 143,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(66, 166), 2: pink}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, pink, front_z)])
    roof = flat_roof("roof", 0, 144, front_z, back_z, wall_top, (56, 66),
                     Strip((5, 56), repeat=(24, 32), tail=(0, 5)), Tile(8, 56, 16, 66))
    zp, yp = front_z - 1, front_z - 1 - 36
    grey = Tile(36, 42, 44, 50, top=yp)
    penthouse = Prism(
        "penthouse", 32, 112, [(zp, roof_y), (zp, yp), (60, yp), (60, roof_y)],
        edges={0: Proj(36, 56), 1: Strip((14, 36), repeat=(20, 24), tail=(4, 14)), 2: grey},
        skip=(3,), caps=[Band(roof_y, yp + 1, grey, zp)])
    return [walls, roof, penthouse], art


DEPT_STORE_EXACT = [(8, 66, 136, 160), (0, 56, 144, 66), (32, 36, 112, 56)]


def game_corner(art):
    """The Game Corner (cells 31..37 x 17..21), 112 x 96:

        rows  0-8    a border of lights round the roof's back
        rows  9-48   the flat roof, skylights every 16 rows
        rows 49-56   its rounded front edge and eave
        rows 57-79   facade
        x 40..71:    the entrance arch, standing forward of the facade: its
                     sign on rows 45..56, its posts (x 40-47, 64-71) down
                     to row 85
    """
    front_z, back_z = 80, 16
    wall_top = 23
    white = Tile(8, 60, 16, 64, top=wall_top)
    walls = Prism(
        "walls", 0, 112,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(57, 80), 2: white}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, white, front_z)])
    roof = flat_roof("roof", 0, 112, front_z, back_z, wall_top, (49, 57),
                     Strip((9, 49), repeat=(17, 33), start=24, tail=(0, 9)), Tile(8, 49, 16, 57))
    za, zb = 86, 82
    arch = Prism("arch", 40, 72, [(za, 29), (za, 41), (zb, 41), (zb, 29)],
                 edges={0: Proj(45, 57)}, skip=(3,),
                 caps=[Band(29, 42, Tile(44, 50, 48, 56, top=41), za)])
    post = Tile(41, 70, 47, 80, top=29)
    posts = [Prism(name, x0, x0 + 8, [(za, 0), (za, 29), (zb, 29), (zb, 0)],
                   edges={0: Proj(57, 86), 2: post}, skip=(1, 3), caps=[Band(0, 30, post, za)])
             for name, x0 in (("post_w", 40), ("post_e", 64))]
    return [walls, roof, arch] + posts, art


GAME_CORNER_EXACT = [(8, 57, 40, 80), (72, 57, 104, 80), (4, 49, 40, 57), (72, 49, 108, 57),
                     (8, 9, 104, 41), (40, 45, 72, 57), (40, 57, 48, 86), (64, 57, 72, 86)]


def prize_corner(art):
    """The prize exchange (cells 38..40 x 17..20), 48 x 64: a flat roof on
    rows 9..32, its rounded edge on 33..38, the facade on 39..63."""
    front_z, back_z = 64, 16
    wall_top = 25
    white = Tile(8, 44, 14, 48, top=wall_top)
    walls = Prism(
        "walls", 0, 48,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(39, 64), 2: white}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, white, front_z)])
    roof = flat_roof("roof", 0, 48, front_z, back_z, wall_top, (33, 39),
                     Strip((9, 33), repeat=(9, 17), tail=(0, 9)), Tile(8, 33, 14, 39))
    return [walls, roof], art


PRIZE_CORNER_EXACT = [(8, 39, 40, 64), (4, 33, 44, 39), (8, 13, 40, 27)]


CELADON_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x165, 0x166, 0x167, 0x16D,
                  0x16E, 0x16F, 0x175, 0x176, 0x177, 0x195, 0x196, 0x19D, 0x19E, 0x0D7,
                  0x00E, 0x00F, 0x01E, 0x01F, 0x016, 0x017, 0x024, 0x025, 0x026, 0x027]
CELADON_BLOCKS = [(4, 4, 5, 8, 1), (18, 4, 7, 8, 1), (27, 4, 7, 8, 1),
                  (34, 7, 4, 5, 0), (38, 7, 4, 5, 0), (42, 7, 4, 5, 0),
                  (44, 17, 4, 5, 0), (48, 17, 4, 5, 0), (4, 25, 4, 5, 0), (16, 25, 4, 5, 0),
                  (32, 25, 4, 5, 0), (36, 25, 4, 5, 0), (40, 25, 4, 5, 0), (44, 25, 4, 5, 0),
                  (48, 25, 4, 5, 0), (20, 26, 4, 4, 0)]


# ── General's route house ──────────────────────────────────────────────────

def route_house(art):
    """The blue-roofed house of General's own tiles (Celadon's restaurant,
    the houses on Routes 2, 12 and 16), 96 x 48:

        row   0      the ridge line
        rows  1-23   the front slope, courses ending in lines at 4/5,
                     11/12 and 19/20; hips drawn as stripes, x 0-11 lit and
                     84-95 shaded
        rows 24-26   fascia; rows 27-31 the wall's top in the eave's shade
        rows 32-47   facade: windows, the door
    """
    art, band0 = extend(art, 96)
    hip_w = hip_band(art, band0, list(range(0, 12)), 15, 48)
    hip_e = hip_band(art, band0 + 48, list(range(95, 83, -1)), 15, 48)
    front_z, back_z = 48, 0
    overhang = 2
    wall_top = front_z + overhang - 27
    courses = (12, 84)
    roof = FrHipRoof(
        "roof", 0, 96, zf=front_z + overhang, zb=back_z + 2, y0=wall_top,
        fascia=Strip((24, 27), wrap=courses),
        slope=KeepStrip((1, 24), repeat=(12, 20), start=19, wrap=courses, keep=(12, 84)),
        teeth=(0, 1), cap=(0, 1), pitch=HOUSE_PITCH, run=12,
        ridge_u=(12, 84), end_tile=Tile(12, 0, 13, 1),
        hip_w=Strip(hip_w, wrap=(0, 40)), hip_e=Strip(hip_e, wrap=(0, 40)))
    plaster = Tile(16, 27, 24, 48, top=wall_top)
    corner = Tile(1, 27, 4, 48, top=wall_top)
    walls = Prism(
        "walls", 1, 95,
        [(front_z, 0), (front_z, wall_top), (back_z + 4, wall_top), (back_z + 4, 0)],
        edges={0: Proj(27, 48), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z + 4)])
    return [walls, roof], art


ROUTE_HOUSE_EXACT = [(4, 27, 92, 48), (12, 1, 84, 24)]


# ── Fuchsia City ───────────────────────────────────────────────────────────

def fuchsia_house(art):
    """Fuchsia's grey houses (cells 13..17 x 28..31), 80 x 64: Lavender's
    shape - a rim (8-9), a flat roof of panels (10-38, lines every 8 rows
    from 20), the parapet (39-41) and the facade (42-63)."""
    front_z, back_z = 64, 16
    wall_top = 22
    plaster = Tile(40, 58, 48, 61, top=wall_top)
    walls = Prism(
        "walls", 0, 80,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(42, 64), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z)])
    roof = flat_roof("roof", 0, 80, front_z, back_z, wall_top, (39, 42),
                     Strip((14, 39), repeat=(21, 29), start=21, tail=(8, 14)), Tile(10, 40, 26, 42))
    return [walls, roof], art


def thatch_house(cells, rows):
    """Fuchsia's thatched houses (the Warden's, the Safari Zone's gate):

        rows  9-52   the thatch, flat, its tufts every 8 rows from 13;
                     borders x 0-9 and the last 9 columns
        rows 53-56   the thatch's front edge; rows 57-60 a grey fascia
        rows 61-     facade
    """
    width, height = cells * 16, rows * 16

    def parts(art):
        front_z, back_z = height, 16
        wall_top = height - 61
        plaster = Tile(3, 72, 19, 77, top=wall_top)
        walls = Prism(
            "walls", 0, width,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(61, height), 2: plaster}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, plaster, front_z)])
        roof = flat_roof("roof", 0, width, front_z, back_z, wall_top, (53, 61),
                         Strip((13, 53), repeat=(13, 21), start=20, tail=(9, 13)),
                         Tile(12, 53, 20, 61))
        return [walls, roof], art
    return parts


def thatch_exact(cells, rows):
    width, height = cells * 16, rows * 16
    return [(0, 61, width, height), (0, 53, width, 61), (0, 13, width, 53)]


FUCHSIA_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x0CE, 0x0BE, 0x0EE, 0x0F5,
                  0x0D3, 0x0D4, 0x0D5, 0x071, 0x072, 0x0F4, 0x01C, 0x01D, 0x014, 0x015,
                  0x024, 0x025, 0x28E, 0x0DC]


# ── Saffron City ───────────────────────────────────────────────────────────

def saffron_house(cells, front_z):
    """Saffron's yellow houses under green hipped roofs, 16 * cells wide;
    every variant draws the same roof:

        row   8      the ridge line
        rows  9-39   the front slope, courses ending in lines at 12/13,
                     19/20 .. (8 rows); hips x 0-11 lit, the last 12 shaded
        rows 40-42   fascia; rows 43-47 the wall's top in the eave's shade
        rows 48-     facade, one or two floors down to `front_z`
    """
    width = cells * 16

    def parts(art):
        art, band0 = extend(art, 96)
        hip_w = hip_band(art, band0, list(range(0, 12)), 25, 48)
        hip_e = hip_band(art, band0 + 48, list(range(width - 1, width - 13, -1)), 25, 48)
        back_z, overhang = 16, 2
        wall_top = front_z + overhang - 43
        courses = (12, width - 12)
        roof = FrHipRoof(
            "roof", 0, width, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
            fascia=Strip((40, 43), wrap=courses),
            slope=KeepStrip((9, 40), repeat=(13, 21), start=16, wrap=courses,
                            keep=(12, width - 12)),
            teeth=(8, 9), cap=(8, 9), pitch=HOUSE_PITCH, run=12,
            ridge_u=(12, width - 12), end_tile=Tile(12, 8, 13, 9),
            hip_w=Strip(hip_w, wrap=(0, 40)), hip_e=Strip(hip_e, wrap=(0, 40)))
        # the facade's yellow siding, which every variant draws on rows 48..56
        plaster = Tile(24, 48, 40, 56, top=wall_top)
        corner = Tile(1, 43, 3, front_z, top=wall_top)
        walls = Prism(
            "walls", 1, width - 1,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(43, front_z), 2: plaster}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, plaster, front_z, front=corner, back=corner, z1=back_z)])
        return [walls, roof], art
    return parts


def saffron_apartments(art):
    """Saffron's yellow apartment blocks (cells 19..23 x 25..30), 80 x 96:

        rows  1-4    the roof's back border
        rows  5-36   a roof garden inside a yellow border
        x 49..71:    the stair hut on the roof - its top on rows 2..16,
                     its face on 17..31
        rows 37-40   the border's front; rows 41-44 the parapet
        rows 45-95   facade, three floors
    """
    front_z, back_z = 96, 16
    wall_top = front_z - 45
    roof_y = wall_top + 4
    yellow = Tile(8, 57, 72, 61, top=wall_top)
    walls = Prism(
        "walls", 0, 80,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(45, 96), 2: yellow}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, yellow, front_z)])
    roof = flat_roof("roof", 0, 80, front_z, back_z, wall_top, (41, 45),
                     Strip((5, 41), repeat=(33, 35), tail=(1, 5)), Tile(8, 41, 16, 45))
    zh = roof_y + 31
    yh = zh - 17
    hut_side = Tile(52, 20, 60, 26, top=yh)
    hut = Prism(
        "stair_hut", 49, 71, [(zh, roof_y), (zh, yh), (zh - 15, yh), (zh - 15, roof_y)],
        edges={0: Proj(17, 32), 1: Strip((3, 17), repeat=(6, 8)), 2: hut_side}, skip=(3,),
        caps=[Band(roof_y, yh + 1, hut_side, zh)])
    return [walls, roof, hut], art


SAFFRON_APARTMENTS_EXACT = [(2, 45, 78, 96), (0, 41, 80, 45), (0, 5, 49, 37), (49, 17, 71, 32)]


def silph_co(art):
    """Silph Co. (cells 29..37 x 16..30), 144 x 240:

        rows  0-79   the roof: pink panels either side of a glass vault
                     (x 48..95, its crown on rows 0..8)
        rows 80-84   the roof's front edge
        rows 85-229  the tower's face, nine floors of windows
        x 50..93:    the entrance, standing forward, its door on rows
                     205..238

    Nine floors stand taller than the follow camera rides: from the path
    behind it the tower would fill the screen. Four floors (rows 101..164)
    are taken out of the drawing and everything above them moved down, so
    the tower is five floors tall. A footprint the whole rect deep would
    make a block thirteen cells long: the tower is as deep as its drawn
    roof, and the cells behind it are paving.
    """
    cut = 64
    short = Image.new("RGBA", art.size, (0, 0, 0, 0))
    short.paste(art.crop((0, 0, 144, 101)), (0, cut))
    short.paste(art.crop((0, 101 + cut, 144, 240)), (0, 101 + cut))
    art = short
    front_z = 230
    back_z = front_z - 80
    face = 85 + cut
    wall_top = front_z - face
    glass = Tile(26, face + 5, 58, face + 11, top=wall_top)
    walls = Prism(
        "walls", 0, 144,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(face, 230), 2: glass}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, glass, front_z)])
    roof = flat_roof("roof", 0, 144, front_z, back_z, wall_top, (80 + cut, face),
                     Strip((9 + cut, 80 + cut), repeat=(40 + cut, 44 + cut), tail=(cut, 9 + cut)),
                     Tile(8, 80 + cut, 16, face))
    porch = Prism(
        "entrance", 50, 94, [(239, 0), (239, 34), (front_z, 34), (front_z, 0)],
        edges={0: Proj(205, 239)}, skip=(2, 3),
        caps=[Band(0, 35, Tile(52, 214, 56, 222, top=34), 239)])
    return [walls, roof, porch], art


SILPH_EXACT = [(8, 149, 136, 205), (0, 144, 144, 149), (50, 205, 94, 230)]


def fighting_dojo(art):
    """The Fighting Dojo (cells 37..42 x 8..12), 96 x 80:

        rows 10-17   the ridge's broad cap
        rows 19-51   the front slope, gold tiles in courses
        rows 52-53   fascia; rows 54-71 facade, windows and the sign
        x 40..71:    the porch, a cell forward, its little roof on rows
                     48..55 and its posts down to row 79
    """
    front_z, back_z = 72, 16
    overhang = 2
    wall_top = front_z + overhang - 54
    tiles = (8, 40)
    roof = HipRoof(
        "roof", 0, 96, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
        fascia=Strip((52, 54), wrap=tiles),
        slope=Strip((20, 52), repeat=(24, 32), tail=(18, 20), wrap=tiles),
        teeth=(12, 18), cap=(10, 12), pitch=25.0, run=4,
        ridge_u=(4, 92), end_tile=Tile(4, 12, 8, 18))
    plaster = Tile(16, 64, 40, 69, top=wall_top)
    walls = Prism(
        "walls", 1, 95,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(54, 72), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z)])
    porch = Prism(
        "porch", 40, 72, [(80, 0), (80, 32), (72, 32), (72, 0)],
        edges={0: Proj(48, 80)}, skip=(2, 3),
        caps=[Band(0, 33, Tile(42, 64, 46, 72, top=32), 80)])
    return [walls, roof, porch], art


DOJO_EXACT = [(2, 54, 40, 72), (72, 54, 94, 72), (8, 21, 40, 52), (72, 21, 88, 52), (40, 48, 72, 80)]


SAFFRON_GROUND = [GRASS, 0x2E9, 0x2E3, 0x2E5, 0x2EC, 0x2F3, 0x2F4, 0x2F5, 0x2EB, 0x2ED,
                  0x2E4, 0x20F, 0x20E, 0x2F1, 0x229, 0x228, 0x216, 0x2E8, 0x220]
# (x, y, rows, front): one copy of each distinct house - the two-floor
# ones, the low ones, the row along the south edge (its facade stops at row
# 56); the identical copies are found by their metatiles and share it
SAFFRON_HOUSES = ([(x, y, 5, 80) for (x, y) in ((17, 10), (21, 10), (46, 17), (41, 34))]
                  + [(x, y, 4, 64) for (x, y) in ((22, 18), (50, 8))]
                  + [(19, 41, 4, 56)])
# the house beside Silph Co.: its east column is the tower's, so it is the
# same house three cells wide (cells 26..28 x 17..21), its door kept
SAFFRON_NARROW_HOUSE = (26, 17, 3, 5, 80)


# ── General's gatehouses ───────────────────────────────────────────────────

def paint_door(art, x, y, w=16, h=28):
    """A glass door, drawn into the art where nothing else reads: the gates'
    side doors face east and west, and the GBA never draws them. Colours
    from the facade: its dark outline, grey frame and two glass blues."""
    px = art.load()
    dark, frame = px[1, 79], px[2, 51]
    glass, shade = px[14, 53], px[12, 53]
    for j in range(h):
        for i in range(w):
            if i in (0, w - 1) or j == 0:
                c = dark
            elif i in (1, w - 2) or j == 1 or j == h // 2:
                c = frame
            else:
                c = glass if j < h // 2 else shade
            px[x + i, y + j] = c
    return Tile(x, y, x + w, y + h, top=h)


def gatehouse(cells, rows, side_doors=False, extra=0):
    """The route gates and the Underground Path's huts, General's own tiles:
    a grey corrugated roof falling to the front (rows 0..42, its ribs the
    same on every row), its eave (43..46), and the facade from row 47 down
    to the rect's bottom - glass, brick, the passage or a door, the pillars
    at either end drawn on it."""
    width, front_z = cells * 16, rows * 16
    s = 16 * extra                 # Route 2's gates have a row more of roof

    def parts(art):
        back_z = 16
        wall_top = front_z - 47 - s
        brick = Tile(8, 61 + s, 24, 65 + s, top=wall_top)
        walls = Prism(
            "walls", 0, width,
            [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
            edges={0: Proj(47 + s, front_z), 2: brick}, skip=(1, 3),
            caps=[Band(0, wall_top + 1, brick, front_z)])
        y1 = wall_top + 4
        rib_end = Tile(8, 43 + s, 24, 47 + s, top=y1)
        roof = Prism(
            "roof", 0, width,
            [(front_z, wall_top), (front_z, y1), (back_z, y1 + 12), (back_z, wall_top)],
            edges={0: Proj(43 + s, 47 + s), 1: Strip((2, 43 + s), repeat=(10, 14), tail=(0, 2)),
                   2: rib_end},
            skip=(3,), caps=[Band(wall_top, y1 + 13, rib_end, front_z)])
        parts = [walls, roof]
        if side_doors:
            # The east-west gates are entered at either end, on their fourth
            # row of cells: a door on each end wall there.
            art, band0 = extend(art, 32)
            door = paint_door(art, 0, band0)
            for name, x0, x1 in (("door_w", -1, 0), ("door_e", width, width + 1)):
                parts.append(Prism(name, x0, x1, [(64, 0), (64, 28), (48, 28), (48, 0)],
                                   skip=(0, 1, 2, 3), caps=[Band(0, 29, door, 64)]))
        return parts, art
    return parts


def gatehouse_exact(cells, rows, extra=0):
    width, front_z, s = cells * 16, rows * 16, 16 * extra
    return [(8, 47 + s, width - 8, front_z), (0, 43 + s, width, 47 + s), (0, 4, width, 40 + s)]


GATE_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x0E7, 0x0E6, 0x00E, 0x00F, 0x01E,
               0x01F, 0x016, 0x017, 0x00D, 0x0EE, 0x0EF, 0x0EC, 0x0ED, 0x18D, 0x18E, 0x138,
               0x13C, 0x140, 0x144, 0x0F4, 0x0F7, 0x0D4, 0x0D5, 0x0E4, 0x002]
GATEHOUSES = [("gate_passage_6", "LAYOUT_SAFFRON_CITY", (32, 0), 6, 6, False),
              ("gate_side_6", "LAYOUT_SAFFRON_CITY", (2, 24), 6, 5, True),
              ("gate_passage_5", "LAYOUT_ROUTE12", (12, 16), 5, 6, False),
              ("underground_hut", "LAYOUT_ROUTE5", (30, 28), 4, 4, False)]


# ── Cinnabar Island ────────────────────────────────────────────────────────

def pokemon_mansion(art):
    """The Pokemon Mansion (cells 5..11 x 0..3, its roof running off the
    map), 112 x 64:

        rows  0-23   the roof, three chimneys on it (x 18-29, 50-61, 82-93:
                     tops on rows 2..11, faces on 12..22)
        rows 24-31   the eave; rows 32-62 the facade, two floors
        x 40..71:    the porch - its top on rows 34..49, its face (the
                     door) on 50..69
    """
    front_z, back_z = 63, 0
    wall_top = 31
    roof_y = wall_top + 8
    stone = Tile(8, 46, 40, 48, top=wall_top)
    walls = Prism(
        "walls", 0, 112,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(32, 63), 2: stone}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, stone, front_z)])
    roof = flat_roof("roof", 0, 112, front_z, back_z, wall_top, (24, 32),
                     Strip((1, 24), repeat=(1, 2)), Tile(8, 24, 16, 32))
    zc = 22 + roof_y
    yc = zc - 12
    brick = Tile(20, 4, 28, 10, top=yc)
    chimneys = [Prism("chimney_%d" % x0, x0, x0 + 12,
                      [(zc, roof_y), (zc, yc), (zc - 10, yc), (zc - 10, roof_y)],
                      edges={0: Proj(12, 23), 1: Strip((2, 12)), 2: brick}, skip=(3,),
                      caps=[Band(roof_y, yc + 1, brick, zc)])
                for x0 in (18, 50, 82)]
    porch = Prism("porch", 40, 72, [(70, 0), (70, 20), (54, 20), (54, 0)],
                  edges={0: Proj(50, 70), 1: Proj(34, 50)}, skip=(2, 3),
                  caps=[Band(0, 21, Tile(41, 52, 47, 62, top=20), 70)])
    return [walls, roof, porch] + chimneys, art


MANSION_EXACT = [(2, 32, 40, 63), (72, 32, 110, 63), (0, 24, 112, 32), (40, 34, 72, 70),
                 (18, 12, 30, 23), (50, 12, 62, 23), (82, 12, 94, 23)]


def cinnabar_lab(art):
    """The Pokemon Lab (cells 5..11 x 6..9), 112 x 64: a capsule - walls
    on rows 39..63 whose ends turn round (drawn as 16-px chamfers), a band
    of roof rising 6 (rows 27..38) and the rounded top (3..26)."""
    front, back, c = 64, 16, 16
    plan = [(c, front), (112 - c, front), (112, front - c), (112, back + c),
            (112 - c, back), (c, back), (0, back + c), (0, front - c)]
    return [Frustum(
        "body", plan, wall_top=25, wall_side=Strip((40, 62), wrap=(24, 40)),
        band_rise=7, band_side=Strip((25, 39), wrap=(24, 40)),
        top=Strip((3, 25), repeat=(9, 17), wrap=(16, 96)))], art


CINNABAR_LAB_EXACT = [(16, 39, 96, 64), (16, 25, 96, 39)]
CINNABAR_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x0D9, 0x0DA, 0x0D3, 0x0D4, 0x0D5,
                   0x0DB, 0x0DC, 0x0DD, 0x12C]


# ── Indigo Plateau ─────────────────────────────────────────────────────────

def pokemon_league(art):
    """The Pokemon League (cells 6..16 x 0..6, its roof running off the
    map), 176 x 112:

        rows  0-57   the roof's ribs, the same on every row
        rows 58-64   the eave
        rows 65-103  facade: windows, the pines planted along it
        x 66..109:   the entrance, two cells forward - its gabled top drawn
                     on rows 64..95, its doors on 96..111
    """
    front_z, back_z = 104, 0
    wall_top = front_z - 65
    stone = Tile(20, 66, 40, 70, top=wall_top)
    walls = Prism(
        "walls", 0, 176,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(65, 104), 2: stone}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, stone, front_z)])
    roof = flat_roof("roof", 0, 176, front_z, back_z, wall_top, (58, 65),
                     Strip((1, 58), repeat=(10, 14)), Tile(8, 58, 16, 65))
    porch = Prism("entrance", 66, 110, [(112, 0), (112, 16), (80, 16), (80, 0)],
                  edges={0: Proj(96, 112), 1: Proj(64, 96)}, skip=(2, 3),
                  caps=[Band(0, 17, Tile(70, 100, 76, 110, top=16), 112)])
    return [walls, roof, porch], art


LEAGUE_EXACT = [(2, 65, 66, 104), (110, 65, 174, 104), (0, 58, 176, 65), (66, 64, 110, 112),
                (0, 4, 176, 56)]


def league_gate(art):
    """The Pokemon League's front gate on Route 22 (cells 4..12 x 0..6), the
    League's own build in nine cells, 144 x 112:

        rows  0-49   the roof's ribs, the same on every row
        rows 50-56   the eave
        rows 57-95   facade: windows, the pines planted along it
        x 53..90:    the entrance - a canopy over it (its dome drawn on rows
                     59..77) on two pillars (x 55..57, 86..88, down to row
                     105), the doors in the facade behind
        x 48..95, rows 96..111: the white steps before it
    """
    front_z, back_z = 96, 0
    wall_top = front_z - 57
    wood = Tile(3, 72, 12, 80, top=wall_top)
    walls = Prism(
        "walls", 0, 144,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(57, 96), 2: wood}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, wood, front_z)])
    roof = flat_roof("roof", 0, 144, front_z, back_z, wall_top, (50, 57),
                     Strip((1, 50), repeat=(10, 14)), Tile(8, 50, 16, 57))
    # the canopy slopes up to the facade: its top is the dome as drawn
    dome = Tile(60, 62, 70, 66)
    canopy = Prism("canopy", 53, 91, [(106, 25), (106, 28), (96, 37), (96, 25)],
                   edges={0: Proj(), 1: Proj()}, skip=(2, 3),
                   caps=[Band(25, 38, dome, 106)])
    post = Tile(55, 85, 58, 95)
    pillars = [Prism(name, x0, x0 + 3, [(106, 0), (106, 25), (103, 25), (103, 0)],
                     edges={0: Proj()}, skip=(1, 2, 3), caps=[Band(0, 26, post, 106)])
               for name, x0 in (("pillar_w", 55), ("pillar_e", 86))]
    steps = Prism("steps", 48, 96, [(112, 0), (112, 2), (96, 2), (96, 0)],
                  edges={0: Proj(), 1: Proj()}, skip=(2, 3),
                  caps=[Band(0, 3, Tile(50, 100, 60, 104), 112)])
    return [walls, roof, canopy] + pillars + [steps], art


LEAGUE_GATE_EXACT = [(3, 57, 53, 96), (91, 57, 141, 96), (0, 50, 144, 57), (0, 4, 144, 48)]


# ── Sevii Islands ──────────────────────────────────────────────────────────

def sevii_house(art):
    """The purple houses of Islands 1-3 (One Island's cells 7..11 x 8..11),
    80 x 64: the back slope's sheets, light (rows 9-16), the ridge (17-20),
    the front slope's purple ribs (21-42), the fascia (43-45) and the
    facade (46-63)."""
    front_z, back_z = 64, 16
    overhang = 2
    wall_top = front_z + overhang - 46
    ribs = (4, 76)
    roof = FrHipRoof(
        "roof", 0, 80, zf=front_z + overhang, zb=back_z - overhang, y0=wall_top,
        fascia=Strip((43, 46), wrap=ribs),
        slope=Strip((21, 43), repeat=(21, 25), wrap=ribs),
        back=Strip((10, 17), repeat=(11, 15), wrap=ribs),
        teeth=(18, 21), cap=(17, 18), pitch=25.0, run=4,
        ridge_u=(4, 76), end_tile=Tile(4, 18, 8, 21))
    plaster = Tile(66, 58, 78, 61, top=wall_top)
    walls = Prism(
        "walls", 1, 79,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(46, 64), 2: plaster}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, plaster, front_z)])
    return [walls, roof], art


def sevii_harbor(art):
    """The islands' harbour office (Two Island's cells 8..12 x 9..13),
    80 x 80: its orange roof of ribbed sheets (rows 1..40), the roof's
    front edge (41..46), the facade (47..71). The pier boards behind it and
    the red posts either side over the water are the map's."""
    front_z, back_z = 72, 16
    wall_top = front_z - 47
    roof = flat_roof("roof", 0, 80, front_z, back_z, wall_top, (41, 47),
                     Strip((2, 41), repeat=(9, 17), tail=(1, 2)), Tile(8, 41, 16, 47))
    grey = Tile(4, 62, 12, 66, top=wall_top)
    walls = Prism(
        "walls", 0, 80,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(47, 72), 2: grey}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, grey, front_z)])
    return [walls, roof], art


def network_center(art):
    """One Island's Pokemon Net Center (cells 11..17 x 0..5), 112 x 96: the
    Center's shape - an octagonal plan, a band rising 6 (rows 57..68, its
    round emblem drawn over the middle) and a flat top of orange grid
    (rows 9..56) - on a facade of rows 69..93."""
    front, back, c = 94, 16, 8
    plan = [(c, front), (112 - c, front), (112, front - c), (112, back + c),
            (112 - c, back), (c, back), (0, back + c), (0, front - c)]
    return [Frustum(
        "body", plan, wall_top=25, wall_side=Strip((70, 92), wrap=(16, 40)),
        band_rise=6, band_side=Strip((57, 69), wrap=(16, 40)),
        top=Strip((13, 57), repeat=(17, 21), tail=(9, 13), wrap=(8, 104)))], art


def two_island_shop(art):
    """Two Island's shop (cells 37..41 x 6..9), 80 x 64: a flat roof inside
    a border (rows 1..36), the parapet with the shop's sign (37..46), the
    facade (47..63)."""
    front_z, back_z = 64, 16
    wall_top = front_z - 47
    roof = flat_roof("roof", 0, 80, front_z, back_z, wall_top, (37, 47),
                     Strip((5, 37), repeat=(7, 9), tail=(1, 5)), Tile(4, 39, 20, 47))
    stone = Tile(4, 50, 24, 56, top=wall_top)
    walls = Prism(
        "walls", 0, 80,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(47, 64), 2: stone}, skip=(1, 3),
        caps=[Band(0, wall_top + 1, stone, front_z)])
    return [walls, roof], art


SEVII_GROUND = [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x0C5, 0x0C6, 0x0C4, 0x0BE]


def sea_cottage(art):
    """Bill's Sea Cottage (Route 25, cells 49..53 x 1..4), 80 x 64: a gable
    end and a chimney stack drawn over the roof in a way no simple roof
    reads, so its whole roof (rows 0..44) is laid on the box's top, exact at
    the GBA's angle, over the facade (45..63)."""
    front_z = 64
    wall_top = front_z - 45
    back_z = wall_top
    plaster = Tile(4, 47, 12, 61, top=wall_top)
    walls = Prism(
        "walls", 0, 80,
        [(front_z, 0), (front_z, wall_top), (back_z, wall_top), (back_z, 0)],
        edges={0: Proj(45, 64), 1: Proj(0, 45), 2: plaster}, skip=(3,),
        caps=[Band(0, wall_top + 1, plaster, front_z)])
    return [walls], art


def blocked_cells(layout_id, x, y, w, h):
    """The cells of a rect the player cannot walk on: a model that owns only
    those leaves the walkable edge of its rect drawn as the map draws it."""
    from voxel_building import LayoutArt
    layout = LayoutArt(layout_id)
    return {(i, j) for j in range(h) for i in range(w)
            if layout.blocks[(y + j) * layout.w + x + i] & 0xC00}


def pokemon_tower_top(art):
    """The Pokemon Tower's roof (Route 10, cells 15..21 x 72..79): the tower
    runs off Lavender's top into the route's last rows, eight more floors
    and a domed roof. All of it would stand thirteen cells high, over the
    follow camera's head, so the floors are left out: the roof seen from
    above - the octagon and its dome, rows 8..55 - is moved down over the
    floors' rows (80..127) and laid on the lower tower's top (86 px up),
    where those rows land at the GBA's angle. Lavender's tower stands 86 px
    into Lavender, which begins 128 px below these cells. The route's cells
    are left to the mountain round them."""
    capped = art.copy()
    capped.paste(art.crop((0, 8, art.size[0], 56)), (0, 80))
    # round the octagon the drawing is the grass beyond the roof, keyed
    # out: each row's gaps take the roof's own edge beside them
    px = capped.load()
    for y in range(80, 128):
        row = [px[x, y] for x in range(capped.size[0])]
        solid = [x for x in range(6, 106) if row[x][3] >= 128]
        if not solid:
            continue
        for x in range(6, 106):
            if row[x][3] < 128:
                near = min(solid, key=lambda s: abs(s - x))
                px[x, y] = row[near]
    art = capped
    z = 128 + 86
    y0, y1 = 86, 90
    rim = Tile(10, 52, 30, 56, top=y1)
    cap = Prism(
        "roof", 6, 106, [(z, y0), (z, y1), (z - 48, y1), (z - 48, y0)],
        edges={0: rim, 1: Proj(80, 128), 2: rim}, skip=(3,),
        caps=[Band(y0, y1 + 1, rim, z)])
    return [cap], art


def forest_gate_roof(art):
    """The gate at Viridian Forest's south edge, of which the forest's map
    holds only the roof (cells 24..34 x 63..68): the gate's corrugated
    sheets, falling to the front, off the map's end."""
    roof = Prism(
        "roof", 0, 176, [(96, 0), (96, 53), (0, 65), (0, 0)],
        edges={1: Strip((10, 14), repeat=(10, 14)), 0: Tile(8, 10, 24, 14)}, skip=(2, 3),
        caps=[Band(0, 66, Tile(8, 10, 24, 14), 96)])
    return [roof], art

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
        "quads": {},
        "parts": canopy,
        "exact": CANOPY_EXACT,
    }
    for (x, y) in ((35, 20), (22, 33))
]
SPECS += [
    {
        "name": "celadon_block_%d_%d" % (x, y),
        "layout": "LAYOUT_CELADON_CITY",
        "rect": (x, y, cells, rows),
        "ground": CELADON_GROUND,
        "owned": {(i, j) for i in range(cells) for j in range(rows)},
        "parts": celadon_block(cells, rows, extra),
        "exact": celadon_exact(cells, rows, extra),
    }
    for (x, y, cells, rows, extra) in CELADON_BLOCKS
]
SPECS.append({
    "name": "celadon_dept_store",
    "layout": "LAYOUT_CELADON_CITY",
    "rect": (9, 5, 9, 11),
    "ground": CELADON_GROUND,
    "owned": {(i, j) for i in range(9) for j in range(10)},
    "parts": celadon_dept_store,
    "exact": DEPT_STORE_EXACT,
})
SPECS += [
    {
        "name": "celadon_game_corner",
        "layout": "LAYOUT_CELADON_CITY",
        "rect": (31, 17, 7, 6),
        "ground": CELADON_GROUND,
        "owned": {(i, j) for i in range(7) for j in range(5)},
        "parts": game_corner,
        "exact": GAME_CORNER_EXACT,
    },
    {
        "name": "celadon_prize_corner",
        "layout": "LAYOUT_CELADON_CITY",
        "rect": (38, 17, 3, 4),
        "ground": CELADON_GROUND,
        "owned": {(i, j) for i in range(3) for j in range(4)},
        "parts": prize_corner,
        "exact": PRIZE_CORNER_EXACT,
    },
]
# the block standing in front of (20, 26): its top rim is drawn in that
# block's last row, which stays the other's
SPECS.append({
    "name": "celadon_block_20_29",
    "layout": "LAYOUT_CELADON_CITY",
    "rect": (20, 29, 4, 6),
    "ground": CELADON_GROUND,
    "owned": {(i, j) for i in range(4) for j in range(1, 6)},
    "parts": celadon_block(4, 6, 0),
    "exact": celadon_exact(4, 6, 0),
})
SPECS.append({
    "name": "route_house",
    "layout": "LAYOUT_CELADON_CITY",
    "rect": (24, 16, 6, 3),
    "ground": CELADON_GROUND,
    "parts": route_house,
    "exact": ROUTE_HOUSE_EXACT,
})
SPECS += [
    {
        "name": "fuchsia_house",
        "layout": "LAYOUT_FUCHSIA_CITY",
        "rect": (13, 28, 5, 4),
        "match_rows": (1, 4),
        "ground": FUCHSIA_GROUND,
        "parts": fuchsia_house,
        "exact": [(0, 42, 80, 64), (0, 39, 80, 42), (0, 14, 80, 39)],
    },
    {
        "name": "fuchsia_wardens_house",
        "layout": "LAYOUT_FUCHSIA_CITY",
        "rect": (26, 12, 6, 5),
        "ground": FUCHSIA_GROUND,
        "parts": thatch_house(6, 5),
        "exact": thatch_exact(6, 5),
    },
    {
        "name": "fuchsia_safari_gate",
        "layout": "LAYOUT_FUCHSIA_CITY",
        "rect": (22, 0, 6, 6),
        "ground": FUCHSIA_GROUND,
        "parts": thatch_house(6, 6),
        "exact": thatch_exact(6, 6),
    },
]
SPECS += [
    {
        "name": "saffron_house_%d_%d" % (x, y),
        "layout": "LAYOUT_SAFFRON_CITY",
        "rect": (x, y, 4, rows),
        "ground": SAFFRON_GROUND,
        "parts": saffron_house(4, front),
        "exact": [(3, 43, 61, front), (12, 9, 52, 40)],
    }
    for (x, y, rows, front) in SAFFRON_HOUSES
]
SPECS.append({
    "name": "saffron_apartments",
    "layout": "LAYOUT_SAFFRON_CITY",
    "rect": (19, 25, 5, 6),
    "ground": SAFFRON_GROUND,
    "parts": saffron_apartments,
    "exact": SAFFRON_APARTMENTS_EXACT,
})
SPECS += [
    {
        "name": name,
        "layout": layout,
        "rect": (x, y, cells, rows),
        "ground": GATE_GROUND,
        "parts": gatehouse(cells, rows, doors),
        "exact": gatehouse_exact(cells, rows),
    }
    for (name, layout, (x, y), cells, rows, doors) in GATEHOUSES
]
SPECS.append({
    "name": "silph_co",
    "layout": "LAYOUT_SAFFRON_CITY",
    "rect": (29, 16, 9, 15),
    "ground": SAFFRON_GROUND,
    "parts": silph_co,
    "exact": SILPH_EXACT,
})
SPECS.append({
    "name": "fighting_dojo",
    "layout": "LAYOUT_SAFFRON_CITY",
    "rect": (37, 8, 6, 5),
    "ground": SAFFRON_GROUND,
    "parts": fighting_dojo,
    "exact": DOJO_EXACT,
})
SPECS += [
    {
        "name": "pokemon_mansion",
        "layout": "LAYOUT_CINNABAR_ISLAND",
        "rect": (5, 0, 7, 5),
        "ground": CINNABAR_GROUND,
        # the porch stands on the steps, which stay the map's: owned, they
        # took the ground round the Mansion, which is the shore
        "owned": {(i, j) for i in range(7) for j in range(4)},
        "parts": pokemon_mansion,
        "exact": MANSION_EXACT,
    },
    {
        "name": "cinnabar_lab",
        "layout": "LAYOUT_CINNABAR_ISLAND",
        "rect": (5, 6, 7, 4),
        "ground": CINNABAR_GROUND,
        "parts": cinnabar_lab,
        "exact": CINNABAR_LAB_EXACT,
    },
]
SPECS.append({
    "name": "pokemon_league",
    "layout": "LAYOUT_INDIGO_PLATEAU_EXTERIOR",
    "rect": (6, 0, 11, 7),
    "ground": [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004],
    "parts": pokemon_league,
    "exact": LEAGUE_EXACT,
})
SPECS.append({
    "name": "league_gate",
    "layout": "LAYOUT_ROUTE22",
    "rect": (4, 0, 9, 7),
    "ground": [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x005],
    "parts": league_gate,
    "exact": LEAGUE_GATE_EXACT,
})

# every copy, found by its drawing (the islands draw them with three tilesets,
# and the doors move): each stands on its own art
SEVII_HOUSES = [("LAYOUT_ONE_ISLAND", 18, 6), ("LAYOUT_ONE_ISLAND", 7, 8), ("LAYOUT_TWO_ISLAND", 32, 6),
                ("LAYOUT_THREE_ISLAND", 3, 3), ("LAYOUT_THREE_ISLAND", 11, 3),
                ("LAYOUT_THREE_ISLAND", 11, 9), ("LAYOUT_THREE_ISLAND", 12, 16),
                ("LAYOUT_FOUR_ISLAND", 24, 11), ("LAYOUT_FOUR_ISLAND", 32, 20),
                ("LAYOUT_FOUR_ISLAND", 24, 23), ("LAYOUT_FIVE_ISLAND", 11, 3),
                ("LAYOUT_SIX_ISLAND", 15, 14), ("LAYOUT_SEVEN_ISLAND", 10, 6),
                ("LAYOUT_THREE_ISLAND", 2, 28)]
SEVII_HARBORS = [("LAYOUT_TWO_ISLAND", 8, 9), ("LAYOUT_FOUR_ISLAND", 8, 29),
                 ("LAYOUT_FIVE_ISLAND", 10, 15), ("LAYOUT_SIX_ISLAND", 9, 24),
                 ("LAYOUT_SEVEN_ISLAND", 14, 14)]
SPECS += [
    {
        "name": "sevii_house_%s_%d_%d" % (lid[7:].lower(), x, y),
        "layout": lid,
        "rect": (x, y, 5, 4),
        "ground": SEVII_GROUND,
        "owned": {(i, j) for i in range(5) for j in range(4)},
        "parts": sevii_house,
        "exact": [(2, 46, 78, 64), (4, 21, 76, 43)],
    }
    for (lid, x, y) in SEVII_HOUSES
] + [
    {
        "name": "sevii_harbor_%s" % lid[7:].lower(),
        "layout": lid,
        "rect": (x, y, 5, 5),
        "ground": SEVII_GROUND + [0x273, 0x274, 0x26F, 0x278],
        "owned": {(i, j) for i in range(5) for j in range(5)},
        "parts": sevii_harbor,
        "exact": [(0, 47, 80, 72), (0, 41, 80, 47), (0, 2, 80, 41)],
    }
    for (lid, x, y) in SEVII_HARBORS
]
SPECS.append({
    "name": "network_center",
    "layout": "LAYOUT_ONE_ISLAND",
    "rect": (11, 0, 7, 6),
    "ground": SEVII_GROUND,
    "parts": network_center,
    "exact": [(8, 69, 104, 94), (8, 57, 104, 69), (12, 17, 100, 57)],
})
SPECS += [
    {
        "name": "two_island_shop",
        "layout": "LAYOUT_TWO_ISLAND",
        "rect": (37, 6, 5, 4),
        "ground": SEVII_GROUND,
        "parts": two_island_shop,
        "exact": [(0, 47, 80, 64), (0, 37, 80, 47), (0, 5, 80, 37)],
    },
    {
        "name": "four_island_daycare",
        "layout": "LAYOUT_FOUR_ISLAND",
        "rect": (11, 10, 4, 4),
        "ground": SEVII_GROUND + [0x00D, 0x0E6],
        "parts": shed_house(4, ribs=(11, 41), eave=(41, 45), facade_top=45),
        "exact": shed_exact(4, ribs=(11, 41), facade_top=45),
    },
]
SPECS += [
    {
        "name": "route5_daycare",
        "layout": "LAYOUT_ROUTE5",
        "rect": (21, 21, 5, 5),
        "ground": [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x0F4, 0x0BD, 0x0C5, 0x0BE, 0x0C6],
        "parts": saffron_house(5, 80),
        "exact": [(3, 43, 77, 80), (12, 9, 68, 40)],
    },
    {
        "name": "sea_cottage",
        "layout": "LAYOUT_ROUTE25",
        "rect": (49, 1, 5, 4),
        "ground": [GRASS, 0x008, 0x009, 0x010, 0x001, 0x004, 0x07C, 0x0B5, 0x0B4, 0x01D, 0x01C,
                   0x024, 0x025, 0x0E7, 0x169, 0x16A, 0x16B, 0x16C],
        "parts": sea_cottage,
        "exact": [(0, 45, 80, 64), (0, 8, 80, 45)],
    },
]
# Saffron paints the Mart's top row and corners with its own paving
SPECS.append({
    "name": "poke_mart_saffron",
    "layout": "LAYOUT_SAFFRON_CITY",
    "rect": (38, 18, 4, 4),
    "ground": SAFFRON_GROUND,
    "parts": poke_mart,
    "exact": MART_EXACT,
})

# Silph Co. stands on the front of its rect; behind it, where nine floors of
# tower stood in the drawing, the cells are walls with nothing on them. Four
# of Saffron's own two-floor houses fill them, set down on that paving.
SPECS.append({
    "name": "saffron_filler_houses",
    "layout": "LAYOUT_SAFFRON_CITY",
    "rect": (17, 10, 4, 5),
    "ground": SAFFRON_GROUND,
    "at": [("LAYOUT_SAFFRON_CITY", x, y) for x in (29, 33) for y in (16, 21)],
    "quads": {},
    "parts": saffron_house(4, 80),
    "exact": [(3, 43, 61, 80), (12, 9, 52, 40)],
})
SPECS.append({
    "name": "saffron_house_narrow",
    "layout": "LAYOUT_SAFFRON_CITY",
    "rect": SAFFRON_NARROW_HOUSE[:4],
    "ground": SAFFRON_GROUND,
    "owned": {(i, j) for i in range(3) for j in range(5)},
    "parts": saffron_house(3, 80),
    "exact": [(3, 43, 45, 80), (12, 9, 36, 40)],
})
# Route 2's two gates, eight cells wide and a row of roof taller
SPECS += [
    {
        "name": name,
        "layout": "LAYOUT_ROUTE2",
        "rect": (2, y, 8, rows),
        "ground": GATE_GROUND,
        "parts": gatehouse(8, rows, extra=1),
        "exact": gatehouse_exact(8, rows, extra=1),
    }
    for (name, y, rows) in (("gate_route2_north", 14, 6), ("gate_route2_south", 45, 7))
]
SPECS += [
    {
        "name": "gate_route2_east",
        "layout": "LAYOUT_ROUTE2",
        "rect": (16, 42, 6, 5),
        "ground": GATE_GROUND,
        "parts": gatehouse(6, 5),
        "exact": gatehouse_exact(6, 5),
    },
    {
        "name": "pokemon_tower_top",
        "layout": "LAYOUT_ROUTE10",
        "rect": (15, 72, 7, 8),
        "ground": [GRASS, 0x001, 0x004, 0x008, 0x009, 0x010, 0x070, 0x071, 0x072, 0x073],
        "parts": pokemon_tower_top,
        "force_ground": 0x071,     # the mountain the route's cells are
        "owned": blocked_cells("LAYOUT_ROUTE10", 15, 72, 7, 8),
        "exact": [],
    },
    {
        "name": "forest_gate_roof",
        "layout": "LAYOUT_VIRIDIAN_FOREST",
        "rect": (24, 63, 11, 6),
        "ground": [GRASS],
        "parts": forest_gate_roof,
        "exact": [],
    },
]
