#!/usr/bin/env python3
"""A spot of a map as the console draws it, in seconds and without the console.

The geometry is the game's own: tests/voxel_mesh_dump.c runs the C emitters
(terrain and relief, trees and props, rooms' pieces, models) over the layout
with the romfs/voxel files of this tree. The camera is voxel_camera.c's and the
textures carry the console's colour grade. Not drawn: sprites, the map's
connections, water and tile animation, the sun's shadows and the time of day.

Run it from the build tree, whose romfs holds the generated data, and keep its
pictures local: they show art taken from the ROM.

    python voxel_view.py LAYOUT_PALLET_TOWN 12,8 --out v.png
        the game's view from cell 12,8 and the same from either side
    python voxel_view.py LAYOUT_PALLET_PLAYERS_HOUSE_2F 5,4 --views game,high --zoom 150
        other views, nearer (see VIEWS)
    python voxel_view.py LAYOUT_PALLET_TOWN 12,8 --shape --crop 0.2,0.1,0.8,0.8
        each surface by the way it faces, its edges drawn, on part of the screen
    python voxel_view.py LAYOUT_PALLET_TOWN 12,8 --dump-only
        the triangle counts of each pass

The dump is rebuilt whenever a source it is made from is newer (msys2 gcc on
the PATH or in C:/msys64/ucrt64/bin).
"""

import argparse
import glob
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import voxel_building as vb  # noqa: E402
import voxel_relief_lines as vl  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

DUMP = os.path.join(PORT, "build", "voxel_mesh_dump.exe")
DUMP_SOURCES = ["tests/voxel_mesh_dump.c", "src/voxel/voxel_mesh_builder.c", "src/voxel/voxel_tree.c",
                "src/voxel/voxel_room.c", "src/voxel/voxel_sign.c", "src/voxel/voxel_building.c",
                "src/voxel/voxel_relief.c", "src/voxel/voxel_grade.c", "src/3ds_video_decode.c"]
DUMP_HEADERS = ["src/voxel/voxel_room_table.h", "src/voxel/voxel_props_table.h", "src/voxel/voxel_world.h"]

# name: (yaw, pitch or None for the player's): the tour's three views and two more
VIEWS = {"game": (0.0, None), "left": (-55.0, None), "right": (55.0, None),
         "low": (0.0, 18.0), "high": (0.0, 72.0)}
GAME_PITCH = 34.0              # the setting's value on the console in use
BARE_FIRST = vl.CUT_FIRST + 512  # voxel_atlas.h: a metatile without its upper layer


def build_dump():
    stamps = [os.path.getmtime(os.path.join(PORT, f)) for f in DUMP_SOURCES + DUMP_HEADERS]
    if os.path.exists(DUMP) and os.path.getmtime(DUMP) >= max(stamps):
        return
    env = dict(os.environ)
    env["PATH"] = "C:/msys64/ucrt64/bin" + os.pathsep + env.get("PATH", "")
    os.makedirs(os.path.dirname(DUMP), exist_ok=True)
    cmd = ["gcc", "-std=c99", "-O2", "-Iinclude", "-Isrc/voxel", "-DPORT_LOG(...)=((void)0)",
           "-DVOXEL_HOST_FILES", '-DVOXEL_BUILDINGS_PATH="romfs/voxel/buildings.bin"',
           '-DVOXEL_RELIEF_PATH=(getenv("VOXEL_RELIEF") ? getenv("VOXEL_RELIEF") : "romfs/voxel/relief.bin")',
           '-DSIGN_MASK_PATH="romfs/voxel/signposts.bin"'] + DUMP_SOURCES + ["-lm", "-o", DUMP]
    r = subprocess.run(cmd, cwd=PORT, env=env, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("building voxel_mesh_dump failed:\n" + r.stderr[-2000:])


def map_type(layout_id):
    for path in glob.glob(os.path.join(vb.ROOT, "data", "maps", "*", "map.json")):
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("layout") == layout_id:
            return m.get("map_type", "")
    return ""


class Texture:
    """A dumped RGBA5551 texture as an image; its UVs are fractions of it."""

    def __init__(self, data, at):
        self.w, self.h = struct.unpack_from("<II", data, at)
        self.end = at + 8 + self.w * self.h * 2
        self.img = None
        if self.w:
            raw = struct.unpack_from("<%dH" % (self.w * self.h), data, at + 8)
            self.img = Image.new("RGBA", (self.w, self.h))
            self.img.putdata([rgba(v) for v in raw])
            self.px = self.img.load()


def rgba(v):
    return ((v >> 11) & 31) << 3, ((v >> 6) & 31) << 3, ((v >> 1) & 31) << 3, 255 if v & 1 else 0


class Scene:
    """The dump's passes: [(triangles, texture, scale of its UVs)]."""

    def __init__(self, layout_id):
        build_dump()
        entry = next(e for e in vl.layouts() if e.get("id") == layout_id)
        index = vl.layouts().index(entry) + 1
        self.w, self.h = entry["width"], entry["height"]
        self.layout_id = layout_id
        blocks = vb.read_u16(os.path.join(vb.ROOT, entry["blockdata_filepath"]))
        border = vb.read_u16(os.path.join(vb.ROOT, entry["border_filepath"]))
        kind = map_type(layout_id)
        indoor = 1 if kind in ("MAP_TYPE_INDOOR", "MAP_TYPE_SECRET_BASE") else 2 if kind == "MAP_TYPE_UNDERGROUND" else 0
        tmp = os.path.join(PORT, "build", "view_%d" % os.getpid())
        with open(tmp + ".in", "wb") as f:
            f.write(struct.pack("<HHH", index, self.w, self.h))
            f.write(struct.pack("<%dH" % (self.w * self.h), *[b & 0x3FF for b in blocks[:self.w * self.h]]))
            f.write(struct.pack("<HH", indoor, entry["primary_tileset"] == "gTileset_General"))
            f.write(struct.pack("<4H", *[b & 0x3FF for b in border[:4]]))
            f.write(entry["secondary_tileset"].encode("ascii").ljust(64, b"\0"))
        r = subprocess.run([DUMP, tmp + ".in", tmp + ".out", "all"], cwd=PORT, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("voxel_mesh_dump failed (%d): %s" % (r.returncode, r.stderr))
        with open(tmp + ".out", "rb") as f:
            data = f.read()
        os.remove(tmp + ".in")
        os.remove(tmp + ".out")
        self.counts = struct.unpack_from("<III", data)
        n = sum(self.counts)
        vals = struct.unpack_from("<%df" % (n * 6), data, 12)
        verts = [vals[i * 6:i * 6 + 6] for i in range(n)]
        at = 12 + n * 24
        trees = Texture(data, at)
        page = Texture(data, trees.end)
        grade = struct.unpack_from("<32768H", data, page.end)
        tris = [tuple(verts[i:i + 3]) for i in range(0, n - n % 3, 3)]
        a, b = self.counts[0] // 3, (self.counts[0] + self.counts[1]) // 3
        self.atlas = GradedAtlas(layout_id, grade)
        s = vl.GRID * 16
        self.passes = [("terrain", tris[:a], None, (s, s)),
                       ("trees and pieces", tris[a:b], trees, (trees.w, trees.h)),
                       ("models", tris[b:], page, (page.w, page.h))]

    def ground_at(self, x, y):
        best = 0.0
        for tri in self.passes[0][1]:
            for (vx, vy, vz, _, _, _) in tri:
                if x <= vx <= x + 1 and y <= vz <= y + 1:
                    best = max(best, vy)
        return best

    def distance(self):
        # voxel_camera.c AdaptDistance, before the zoom
        return 8.0 + min(5.0, max(self.w, self.h) * 0.2)


class GradedAtlas(vl.Atlas):
    """The terrain's atlas in the console's graded colours."""

    def __init__(self, layout_id, grade):
        super().__init__(layout_id)
        self.grade = grade

    def tile(self, aid):
        if aid >= BARE_FIRST:
            return self.art.cell_image(aid - BARE_FIRST, layers=(0,))
        return super().tile(aid)

    def need(self, aid):
        if aid in self.done:
            return
        self.done.add(aid)
        t = self.tile(aid)
        if t is None:
            return
        t = t.convert("RGBA")
        px = t.load()
        for j in range(t.size[1]):
            for i in range(t.size[0]):
                r, g, b, al = px[i, j]
                v = self.grade[(r >> 3) | (g >> 3) << 5 | (b >> 3) << 10]
                px[i, j] = rgba(v)[:3] + (al,)
        self.img.paste(t, ((aid % vl.GRID) * 16, (aid // vl.GRID) * 16))


def facing(tri):
    """A surface's colour by the way it faces: tops pale, south faces mid,
    west and east brown, north dark, slants red."""
    a, b, c = [p[:3] for p in tri]
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = sum(k * k for k in n) ** 0.5 or 1.0
    nx, ny, nz = [abs(k) / length for k in n]
    if ny > 0.95:
        return (222, 226, 214)
    if nz > 0.95:
        return (120, 150, 190)
    if nx > 0.95:
        return (150, 96, 60)
    return (214, 60, 56)


def render(scene, target, yaw, pitch, distance, scale, crop, shape):
    W, H = 400 * scale, 240 * scale
    cam = vb.Camera(target, pitch=pitch, yaw=yaw, distance=distance, fov=35.0, width=W, height=H)
    ox, oy = 0, 0
    if crop:
        ox, oy = int(crop[0] * W), int(crop[1] * H)
        W, H = int(crop[2] * W) - ox, int(crop[3] * H) - oy
    ras = vl.Raster(W, H, bg=(0, 0, 0))
    reach = distance * 2.2
    owner = 0
    colours = {}
    for name, tris, texture, (su, sv) in scene.passes:
        if texture is None:
            for t in tris:
                scene.atlas.need(vl.atlas_id(t))
            img, px = scene.atlas.img, scene.atlas.img.load()
        elif texture.img is None:
            continue
        else:
            img, px = texture.img, texture.px
        for tri in tris:
            owner += 1
            mx = sum(p[0] for p in tri) / 3 - target[0]
            mz = sum(p[2] for p in tri) / 3 - target[2]
            if abs(mx) > reach or abs(mz) > reach:
                continue
            vs = []
            for (x, y, z, u, v, _) in tri:
                pr = cam.project((x, y, z))
                if pr is None:
                    break
                sx, sy, d, iw = pr
                # a texture's first row is the top of the PICA's: v = 1 (TEX_V)
                row = v if texture is None else 1.0 - v
                vs.append((sx - ox, sy - oy, d, iw, u * su * iw, row * sv * iw))
            else:
                colours[owner] = facing(tri)
                shade = min(1.0, sum(p[5] for p in tri) / 3)
                ras.draw(vs, img, px, shade, owner)
    if not shape:
        return ras.image()
    out = Image.new("RGB", (W, H))
    out.putdata([colours.get(o, (0, 0, 0)) for o in ras.tri])
    p = out.load()
    for y in range(H - 1):
        for x in range(W - 1):
            o = ras.tri[y * W + x]
            if o != ras.tri[y * W + x + 1] and colours.get(o) != colours.get(ras.tri[y * W + x + 1]) \
               or o != ras.tri[(y + 1) * W + x] and colours.get(o) != colours.get(ras.tri[(y + 1) * W + x]):
                p[x, y] = (24, 24, 30)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout")
    ap.add_argument("at", help="the cell the camera follows: X,Y")
    ap.add_argument("--out", default="view.png")
    ap.add_argument("--views", default="game,left,right", help=",".join(VIEWS))
    ap.add_argument("--pitch", type=float, default=GAME_PITCH)
    ap.add_argument("--zoom", type=float, default=100.0, help="percent, as the option")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--crop", help="part of each view: x0,y0,x1,y1 as fractions")
    ap.add_argument("--shape", action="store_true", help="surfaces by the way they face")
    ap.add_argument("--dump-only", action="store_true")
    args = ap.parse_args()
    x, y = [int(v) for v in args.at.split(",")]
    scene = Scene(args.layout)
    print("%s %dx%d: %s" % (args.layout, scene.w, scene.h,
                            ", ".join("%d %s" % (len(p[1]), p[0]) for p in scene.passes)))
    if args.dump_only:
        return
    crop = [float(v) for v in args.crop.split(",")] if args.crop else None
    distance = scene.distance() * 100.0 / args.zoom
    target = (float(x), scene.ground_at(x, y), float(y))
    shots = []
    for name in args.views.split(","):
        yaw, pitch = VIEWS[name]
        shots.append((name, render(scene, target, yaw, args.pitch if pitch is None else pitch,
                                   distance, args.scale, crop, args.shape)))
    w, h = shots[0][1].size
    cols = 2 if len(shots) > 1 else 1
    sheet = Image.new("RGB", (cols * w + (cols - 1) * 6, ((len(shots) + cols - 1) // cols) * (h + 6)), (60, 0, 60))
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(shots):
        at = ((i % cols) * (w + 6), (i // cols) * (h + 6))
        sheet.paste(im, at)
        d.text((at[0] + 4, at[1] + 3), name, fill=(255, 255, 0))
    sheet.save(args.out)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
