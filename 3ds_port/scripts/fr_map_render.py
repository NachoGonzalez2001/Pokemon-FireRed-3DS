#!/usr/bin/env python3
"""Render a FireRed layout flat, as the GBA draws it, for inspection.

    python fr_map_render.py LAYOUT_PALLET_TOWN out.png [--scale 3] [--grid]
                            [--info]

--grid overlays the cell lattice with coordinates every cell; --info prints
each cell's metatile, collision, elevation and behaviour.
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fr_art  # noqa: E402


def load_layout(layout_id):
    layouts = json.load(open(os.path.join(fr_art.ROOT, "data", "layouts", "layouts.json"),
                             encoding="utf-8"))["layouts"]
    return next(e for e in layouts if e.get("id") == layout_id)


class FrLayout:
    def __init__(self, layout_id):
        e = load_layout(layout_id)
        self.id = layout_id
        self.w, self.h = e["width"], e["height"]
        self.blocks = fr_art.read_u16(os.path.join(fr_art.ROOT, e["blockdata_filepath"]))
        self.primary, self.secondary = e["primary_tileset"], e["secondary_tileset"]
        mts = fr_art.incbin_map(r"gMetatiles_(\w+)\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)")
        self.pm = fr_art.read_u16(mts[self.primary])
        self.sm = fr_art.read_u16(mts[self.secondary])
        self.pa = fr_art.metatile_attributes(self.primary)
        self.sa = fr_art.metatile_attributes(self.secondary)
        self.ts = fr_art.Tilesets(self.primary, self.secondary)
        self._img = {}

    def raw(self, x, y):
        return self.blocks[y * self.w + x]

    def metatile(self, x, y):
        return self.raw(x, y) & 0x3FF

    def collision(self, x, y):
        return (self.raw(x, y) >> 10) & 3

    def elevation(self, x, y):
        return (self.raw(x, y) >> 12) & 0xF

    def entries(self, m):
        if m < fr_art.NUM_PRIMARY:
            return self.pm[m * 8:m * 8 + 8]
        k = m - fr_art.NUM_PRIMARY
        return self.sm[k * 8:k * 8 + 8]

    def attributes(self, m):
        if m < fr_art.NUM_PRIMARY:
            return self.pa[m] if m < len(self.pa) else 0
        k = m - fr_art.NUM_PRIMARY
        return self.sa[k] if k < len(self.sa) else 0

    def behaviour(self, x, y):
        return self.attributes(self.metatile(x, y)) & fr_art.ATTR_BEHAVIOR_MASK

    def metatile_image(self, m):
        if m not in self._img:
            e = self.entries(m)
            self._img[m] = fr_art.metatile_image(e, self.ts) if len(e) == 8 \
                else Image.new("RGBA", (16, 16), (255, 0, 255, 255))
        return self._img[m]

    def render(self):
        img = Image.new("RGBA", (self.w * 16, self.h * 16), (0, 0, 0, 255))
        for y in range(self.h):
            for x in range(self.w):
                img.paste(self.metatile_image(self.metatile(x, y)), (x * 16, y * 16))
        return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("out")
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--info", action="store_true")
    a = ap.parse_args()
    lay = FrLayout(a.layout)
    img = lay.render().resize((lay.w * 16 * a.scale, lay.h * 16 * a.scale), Image.NEAREST)
    if a.grid:
        d = ImageDraw.Draw(img)
        s = 16 * a.scale
        for x in range(lay.w + 1):
            d.line([(x * s, 0), (x * s, lay.h * s)], fill=(255, 0, 0, 120))
        for y in range(lay.h + 1):
            d.line([(0, y * s), (lay.w * s, y * s)], fill=(255, 0, 0, 120))
        for y in range(lay.h):
            for x in range(lay.w):
                col = (255, 255, 0) if lay.collision(x, y) else (0, 255, 255)
                d.text((x * s + 2, y * s + 1), "%d,%d" % (x, y), fill=col)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    img.convert("RGB").save(a.out)
    print("%s: %dx%d cells, %s + %s -> %s" % (lay.id, lay.w, lay.h, lay.primary,
                                              lay.secondary, a.out))
    if a.info:
        for y in range(lay.h):
            print(" ".join("%03X%s%X:%02X" % (lay.metatile(x, y), "#" if lay.collision(x, y) else ".",
                                             lay.elevation(x, y), lay.behaviour(x, y))
                           for x in range(lay.w)))


if __name__ == "__main__":
    main()
