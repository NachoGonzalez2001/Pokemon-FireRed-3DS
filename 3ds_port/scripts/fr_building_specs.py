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
"""

import math

from PIL import Image

from voxel_building import (Band, HipRoof, Prism, Proj, Strip, Tile, SHADE_ART, SHADE_BACK,
                            SHADE_EAST, SHADE_WEST, strip_face, _unit)

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
]
