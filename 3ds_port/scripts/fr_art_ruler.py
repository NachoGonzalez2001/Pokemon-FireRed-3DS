#!/usr/bin/env python3
"""A building's art (ground keyed out) enlarged with a pixel ruler.

    python fr_art_ruler.py LAYOUT x y w h out.png --ground 0x28E,0x296 [--scale 8]
                           [--rows a-b]

Prints, for every art row (or the rows asked for), its run-length colours, so
a spec can be read off the drawing row by row.
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voxel_building as vb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("w", type=int)
    ap.add_argument("h", type=int)
    ap.add_argument("out")
    ap.add_argument("--ground", required=True)
    ap.add_argument("--scale", type=int, default=8)
    ap.add_argument("--rows", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    ground = [int(g, 0) for g in a.ground.split(",")]
    lay = vb.LayoutArt(a.layout)
    art = lay.building_art(a.x, a.y, a.w, a.h, lay.ground_tiles(ground))
    W, H = art.size
    s = a.scale
    pad = 28
    sheet = Image.new("RGB", (W * s + pad, H * s + pad), (30, 30, 30))
    checker = Image.new("RGB", (W, H))
    cp = checker.load()
    for y in range(H):
        for x in range(W):
            cp[x, y] = (70, 70, 70) if (x // 4 + y // 4) % 2 else (90, 90, 90)
    checker.paste(art, (0, 0), art)
    sheet.paste(checker.resize((W * s, H * s), Image.NEAREST), (pad, pad))
    d = ImageDraw.Draw(sheet)
    for x in range(0, W + 1, 4):
        col = (255, 80, 80) if x % 16 == 0 else (120, 120, 120)
        d.line([(pad + x * s, pad - (8 if x % 16 == 0 else 4)), (pad + x * s, pad)], fill=col)
        if x % 8 == 0:
            d.text((pad + x * s + 1, 2), str(x), fill=(255, 255, 0))
    for y in range(0, H + 1, 4):
        col = (255, 80, 80) if y % 16 == 0 else (120, 120, 120)
        d.line([(pad - (8 if y % 16 == 0 else 4), pad + y * s), (pad, pad + y * s)], fill=col)
        if y % 4 == 0:
            d.text((1, pad + y * s + 1), str(y), fill=(255, 255, 0))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out)
    if a.quiet:
        return
    px = art.load()
    names = {}
    lo, hi = (0, H)
    if a.rows:
        lo, hi = (int(v) for v in a.rows.split("-"))
        hi += 1
    for y in range(lo, hi):
        runs = []
        x = 0
        while x < W:
            c = px[x, y]
            k = x
            while k < W and px[k, y] == c:
                k += 1
            if c[3] < 128:
                key = "."
            else:
                rgb = "%02x%02x%02x" % c[:3]
                key = names.setdefault(rgb, chr(ord("A") + len(names)) if len(names) < 26
                                       else chr(ord("a") + len(names) - 26))
            runs.append("%s%d" % (key, k - x))
            x = k
        print("%3d %s" % (y, " ".join(runs)))
    print("colours:", " ".join("%s=%s" % (v, k) for k, v in names.items()))


if __name__ == "__main__":
    main()
