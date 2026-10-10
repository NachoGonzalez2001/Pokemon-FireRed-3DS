#!/usr/bin/env python3
"""Build FireRed's building models and prove them against their drawing.

    python fr_gen_buildings.py --preview build/pilot [--only NAME] [--town LAYOUT]

For every spec in fr_building_specs.SPECS: compose its art from the layout
(ground keyed out), build the parts, render the model in the GBA projection
and compare it with the art over the spec's exact rectangles (ortho_check),
and check that no face stretches a texel (density_check). With --preview it
also writes *_ortho.png (art | 45-degree render | differences) and views from
the voxel renderer's cameras; --town renders a whole layout with every model
placed wherever its drawing appears.
"""

import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voxel_building as vb  # noqa: E402
import fr_building_specs as specs  # noqa: E402

CAMERAS = [
    ("game", dict(pitch=40.0, yaw=0.0, distance=12.0)),
    ("yaw35", dict(pitch=35.0, yaw=35.0, distance=9.0)),
    ("yaw-50", dict(pitch=30.0, yaw=-50.0, distance=8.0)),
    ("back", dict(pitch=35.0, yaw=160.0, distance=10.0)),
    ("high", dict(pitch=62.0, yaw=15.0, distance=8.0)),
    ("low", dict(pitch=15.0, yaw=20.0, distance=8.0)),
]

_LAYOUTS = {}


def layout_art(lid):
    if lid not in _LAYOUTS:
        _LAYOUTS[lid] = vb.LayoutArt(lid)
    return _LAYOUTS[lid]


def build_models(only=None):
    models = []
    for spec in specs.SPECS:
        if only and not spec["name"].startswith(only):
            continue
        layout = layout_art(spec["layout"])
        x, y, w, h = spec["rect"]
        art = layout.building_art(x, y, w, h, layout.ground_tiles(spec["ground"]))
        parts, art = spec["parts"](art)
        model = vb.Model(spec["name"], art, parts, (w, h), spec["ground"][0])
        model.spec, model.layout = spec, layout
        models.append(model)
    return models


def find_placements(model):
    """Every (x, y) in the model's layout where the same metatiles repeat."""
    layout = model.layout
    x0, y0, w, h = model.spec["rect"]
    want = [[layout.metatile(x0 + i, y0 + j) for i in range(w)] for j in range(h)]
    out = []
    for y in range(layout.h - h + 1):
        for x in range(layout.w - w + 1):
            if all(layout.metatile(x + i, y + j) == want[j][i]
                   for j in range(h) for i in range(w)):
                out.append((x, y))
    return out


def preview(model, out_dir):
    layout = model.layout
    x, y, w, h = model.spec["rect"]
    override = {(x + i, y + j): model.ground_metatile for i in range(w) for j in range(h)}
    ground, gtex = vb.ground_tris(layout, x - 8, y - 6, x + w + 8, y + h + 8, override, None)
    house = vb.model_world_tris(model, x, y)
    paths = []
    for name, c in CAMERAS:
        target = (x + w / 2.0, 0.8, y + h / 2.0)
        cam = vb.Camera(target, pitch=c["pitch"], yaw=c["yaw"], distance=c["distance"])
        img = vb.render_scene(cam, [(ground, gtex), (house, model.art)], scale=2)
        path = os.path.join(out_dir, "%s_%s.png" % (model.name, name))
        img.save(path)
        paths.append(path)
    return paths


def town_preview(models, layout_id, out_dir, views):
    layout = layout_art(layout_id)
    override, items = {}, []
    for m in models:
        if m.spec["layout"] != layout_id:
            continue
        _, _, w, h = m.spec["rect"]
        for (px, py) in find_placements(m):
            for j in range(h):
                for i in range(w):
                    override[(px + i, py + j)] = m.ground_metatile
            items.append((vb.model_world_tris(m, px, py), m.art))
    ground, gtex = vb.ground_tris(layout, 0, 0, layout.w, layout.h, override, None)
    paths = []
    for name, target, c in views:
        cam = vb.Camera(target, **c)
        img = vb.render_scene(cam, [(ground, gtex)] + items, scale=2)
        path = os.path.join(out_dir, "town_%s_%s.png" % (layout_id.lower(), name))
        img.save(path)
        paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", metavar="DIR")
    ap.add_argument("--only")
    ap.add_argument("--town")
    ap.add_argument("--no-views", action="store_true")
    a = ap.parse_args()
    models = build_models(a.only)
    failed = False
    for m in models:
        out = os.path.join(a.preview, m.name + "_ortho.png") if a.preview else None
        if out:
            os.makedirs(a.preview, exist_ok=True)
        wrong, missing, extra = vb.ortho_check(m, out, exact=m.spec["exact"])
        bad = vb.density_check(m)
        places = find_placements(m)
        print("%-14s %5d tris  ortho: %d wrong, %d missing, %d extra  density: %d bad  "
              "placed at %s" % (m.name, m.triangle_count(), wrong, missing, extra, len(bad), places))
        for tag, along, down, shear in bad[:8]:
            print("    density %s along=%.3f down=%.3f shear=%.3f" % (tag, along, down, shear))
        if wrong or missing or extra or bad:
            failed = True
        if a.preview and not a.no_views:
            preview(m, a.preview)
    if a.town and a.preview:
        lay = layout_art(a.town)
        cx, cz = lay.w / 2.0, lay.h / 2.0
        views = [
            ("game", (cx, 0.0, cz), dict(pitch=40.0, yaw=0.0, distance=22.0, fov=45.0)),
            ("yaw30", (cx, 0.0, cz), dict(pitch=38.0, yaw=30.0, distance=22.0, fov=45.0)),
            ("closeup", (11.0, 0.5, 9.5), dict(pitch=30.0, yaw=-25.0, distance=11.0, fov=45.0)),
            ("lab", (16.5, 0.5, 12.0), dict(pitch=28.0, yaw=25.0, distance=10.0, fov=45.0)),
        ]
        town_preview(models, a.town, a.preview, views)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
