#!/usr/bin/env python3
"""Pack FireRed's General tree as the voxel tree texture.

A FireRed tree is two metatiles wide and three tall: the tip (00E/00F, its
top layer over grass), the crown (01E/01F) and the base (026/027), where the
crown's lower leaves meet the shadow on the grass. In a wood the rows repeat
every two metatiles, the base of one tree carrying the tip of the next.

The voxel world stands the whole tree up as one card (voxel_tree.c), so the
texture holds the tree's own drawing taken off the tileset - no new art:

    (0, 0)   32x48  the card: tip and crown top layers, the base's leaves
    (32, 0)  32x16  the base's ground: grass, and the shadow under the card

and the props of the General tileset that stand up the same way - signs,
rocks, bushes, flowers, fences, the south-facing ledges - each a 16x16
slot of its upper layer (see PROPS), packed where the tree leaves room.
With --table the slots are also written as voxel_props_table.h, which
voxel_tree.c reads; keep the two in step by regenerating both.

Palette 0 of General: 1-4 leaves, 5-6 trunk, 8/D/E grass, F shadow.
"""

import argparse
import json
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fr_art  # noqa: E402

DIM = 512        # wide
DIM_H = 1024     # tall: the rooms' art under the props'
GRASS = {0x8, 0xD, 0xE}
SHADOW = 0xF


def texel_offset(x, y):
    """8x8 Morton tiles, matching CtrVideo_Texel (top row is v=1)."""
    morton = sum(((x >> bit) & 1) << (2 * bit) |
                 ((y >> bit) & 1) << (2 * bit + 1) for bit in range(3))
    return ((y // 8) * (DIM // 8) + x // 8) * 64 + morton


def layer(ts, entries, which):
    """16x16 (rgb, index) of one layer of a metatile; index 0 is clear."""
    out = [[None] * 16 for _ in range(16)]
    for q in range(4):
        entry = entries[which * 4 + q]
        data = ts.subtile(entry & 0x3FF, (entry >> 12) & 0xF)
        fx, fy = bool(entry & 0x400), bool(entry & 0x800)
        for y in range(8):
            for x in range(8):
                out[(q >> 1) * 8 + y][(q & 1) * 8 + x] = data[(7 - y if fy else y) * 8 + (7 - x if fx else x)]
    return out


# The upper layer of each stands up as a card (voxel_tree.c); the ground
# drawn under it is the same metatile without that layer.
SIGNS = [0x002, 0x003, 0x160, 0x168, 0x161, 0x169]   # 160 over 168: the Gym's sign; 161 over 169
ROCKS = [0x0A7, 0x0AF, 0x0B7]
BUSHES = [0x005, 0x0FA, 0x0FB]
FLOWERS = [0x004]
FENCES = [0x0DE, 0x0DF] + list(range(0x0E6, 0x0F4)) + [0x0F6, 0x0F7, 0x0F8, 0x0F9, 0x0FC, 0x0FD,
                                                         0x135, 0x136]
MB_JUMP_SOUTH = 0x3B
TIP_FENCES = {0x0D6: 0x010, 0x0D7: 0x011}
# A town's own props that use none of General's tiles
# the stone fence; the pens' sign
EXTRA_PROPS = {"gTileset_FuchsiaCity": [0x28E, 0x28F, 0x296],
               # the grey statues by Victory Road and the League: base, head
               "gTileset_IndigoPlateau": [0x29F, 0x2EF, 0x2B6, 0x2B7]}
# the ground under a prop whose own lower layer is not what it stands on (the
# statues' pedestals draw an orange slab under them)
PROP_GROUND = {"gTileset_IndigoPlateau": {0x29F: 0x010, 0x2EF: 0x010}}
# A town's grey fences drawn on the lower layer over grass: keyed off the
# grass, the cell's ground plain grass (Fuchsia's by the pond)
LOWER_FENCES = {"gTileset_FuchsiaCity": {0x336: 0x010, 0x337: 0x010, 0x33F: 0x010}}
# Drawn from above, raised as a low block rather than stood up: the hedge
# walls of Fuchsia's Pokemon pens
LOWER_BLOCKS = {0x13D: 0x008, 0x13E: 0x008, 0x13F: 0x008}
HEDGE_FACE = 9      # its first row of front face: above it, its top seen from above
BLOCKS = {"gTileset_FuchsiaCity": [0x290, 0x291, 0x292, 0x293, 0x294, 0x295, 0x29B, 0x29C]}


def south_ledges(root):
    """Every south-facing ledge (a jump behaviour) drawn on the upper layer."""
    blob = (root / "data/tilesets/primary/general/metatiles.bin").read_bytes()
    attrs = (root / "data/tilesets/primary/general/metatile_attributes.bin").read_bytes()
    return [i for i in range(len(blob) // 16)
            if struct.unpack_from("<I", attrs, i * 4)[0] & 0x1FF == MB_JUMP_SOUTH
            and any(struct.unpack_from("<8H", blob, i * 16)[4:])]


def prop_ids(root):
    """The props, and every south-facing ledge."""
    ids = SIGNS + ROCKS + BUSHES + FLOWERS + FENCES + south_ledges(root)
    return sorted(set(ids), key=ids.index)


FENCES += [0x0F4, 0x0F5]   # the white posts of a fence running north-south
# The mailbox has no metatile of its own in General: each town draws it from
# these General tiles in metatiles of its own tileset.
MAILBOX_TILES = {0x150, 0x151, 0x160, 0x161, 0x170, 0x171}


def prop_slots():
    """16x16 slots of the texture clear of the tree (x < 64, y < 48)."""
    for sy in range(DIM_H // 16):
        for sx in range(DIM // 16):
            if not (sx < 4 and sy < 3):
                yield sx * 16, sy * 16


def outdoor_secondaries(root):
    """The secondary tilesets of every outdoor layout on General."""
    layouts = json.load(open(root / "data/layouts/layouts.json", encoding="utf-8"))["layouts"]
    names = sorted({l["secondary_tileset"] for l in layouts
                    if l.get("primary_tileset") == "gTileset_General"
                    and l.get("secondary_tileset") not in (None, "NULL", "0")})
    return [n for n in names if fr_art.tileset_dir(n)]


def build_props(root, ts, metatile, image):
    """Each prop's upper layer into a slot (the same drawing shares one).
    Returns [(set, id, x, y, r0, r1, ground)] and the tilesets `set` counts
    from (0 is General): the opaque rows r0..r1 of the slot, and a metatile
    drawing the same lower layer with nothing over it (its own when none)."""
    blob = (root / "data/tilesets/primary/general/metatiles.bin").read_bytes()
    general = [struct.unpack_from("<8H", blob, i * 16) for i in range(len(blob) // 16)]
    slots = prop_slots()
    seen = {}
    out = []

    ledges = set(south_ledges(root))

    def place(tiles, set_index, mid, e, plain, block=False, lower=None):
        top = layer(tiles, e, 1)
        base = layer(tiles, e, 0)
        if lower is not None:
            # drawn on the lower layer: what is the grass's colour is ground
            top = [[(rgb, 0 if rgb in grass else 1) for rgb, idx in line] for line in base]
        # the flowers' upper layer repeats the grass round them: what draws
        # the same colour as the ground below is ground, not the prop
        for y in range(16):
            for x in range(16):
                if lower is None and top[y][x][1] and top[y][x][0] == base[y][x][0]:
                    top[y][x] = (top[y][x][0], 0)
        rows = [y for y in range(16) if any(top[y][x][1] for x in range(16))]
        if not rows:
            return None
        # a ledge stands as its face alone
        ledge = set_index == 0 and mid in ledges
        key = (block,) + tuple(top[y][x][0] if top[y][x][1] else None
                               for y in range(16) for x in range(16))
        if key not in seen:
            sx, sy = next(slots)
            seen[key] = (sx, sy)
            for y in range(16):
                for x in range(16):
                    rgb, idx = top[y][x]
                    if idx:
                        image[(sx + x, sy + y)] = rgb
                    elif block and lower is None:
                        # a block's top is the whole drawing, ground and all
                        image[(sx + x, sy + y)] = base[y][x][0]
        sx, sy = seen[key]
        cols = [x for x in range(16) if any(top[y][x][1] for y in range(16))]
        # a fence running north-south is drawn as a line of posts, one a
        # cell: thin and the cell's whole height. The console builds those
        # as posts and rails rather than standing the drawing up.
        # (the wooden posts are 7 px wide; a fence's end piece drawn front on
        # starts below the cell's top row, so it is never taken for one)
        post = int(len(cols) <= 8 and rows[0] == 0 and rows[-1] == 15)
        # flowers are drawn from above: standing up they would be a hedge
        # as tall as the fences, so they lean back, low, instead
        if mid in FLOWERS and set_index == 0:
            post = 2
        if ledge:
            post = 3
        if block:
            post = 4
        centre = (cols[0] + cols[-1] + 1) // 2
        # a post's fence seen side on: the fence of its material drawn front on
        # (the towns' lower-layer fences are all grey)
        metal = lower is not None or any((v >> 12) == 2 for v in e[4:] if v & 0x3FF)
        ground = lower if lower is not None else plain.get(e[:4], mid)
        out.append([set_index, mid, sx, sy, rows[0], rows[-1] + 1, ground, post,
                    centre, 0x0E7 if metal else 0x0E6])
        return e

    plain = {}
    for i, e in enumerate(general):
        if not any(e[4:]):
            plain.setdefault(e[:4], i)
    allowed = set(MAILBOX_TILES)
    for mid in prop_ids(root):
        e = place(ts, 0, mid, general[mid], plain)
        # towns draw fences, signs and mailboxes from General's tiles; not
        # bushes or rocks, whose tiles are the trees' and the mountains'
        if e and (mid in FENCES or mid in SIGNS or mid == 0x005):
            allowed |= {v & 0x3FF for v in e[4:] if v & 0x3FF}
    allowed -= {0}
    # General's own pieces drawn from the same tiles: corners, ends, a bush
    # against something
    listed = {p[1] for p in out}
    for i, e in enumerate(general):
        if i not in listed and any(v & 0x3FF for v in e[4:])            and all((v & 0x3FF) in allowed for v in e[4:] if v & 0x3FF):
            place(ts, 0, i, e, plain)
    grass = set()
    for g in (0x010, 0x011):
        for line in layer(ts, general[g], 0):
            grass |= {rgb for rgb, idx in line}
    sets = []
    for name in outdoor_secondaries(root):
        path = os.path.join(fr_art.tileset_dir(name), "metatiles.bin")
        sec = [struct.unpack_from("<8H", open(path, "rb").read(), i * 16)
               for i in range(os.path.getsize(path) // 16)]
        local = dict(plain)
        for i, e in enumerate(sec):
            if not any(e[4:]):
                local.setdefault(e[:4], 0x280 + i)
        found = [i for i, e in enumerate(sec)
                 if any(v & 0x3FF for v in e[4:])
                 and all((v & 0x3FF) in allowed for v in e[4:] if v & 0x3FF)]
        found += [m - 0x280 for m in EXTRA_PROPS.get(name, [])]
        blocks = [m - 0x280 for m in BLOCKS.get(name, [])]
        lower = LOWER_FENCES.get(name, {})
        if not found and not blocks and not lower:
            continue
        sets.append(name)
        tiles = fr_art.Tilesets("gTileset_General", name)
        for i in found:
            place(tiles, len(sets), 0x280 + i, sec[i], local)
            if 0x280 + i in PROP_GROUND.get(name, {}) and out and out[-1][1] == 0x280 + i:
                out[-1][6] = PROP_GROUND[name][0x280 + i]
        for i in blocks:
            place(tiles, len(sets), 0x280 + i, sec[i], local, block=True)
        for m, ground in lower.items():
            place(tiles, len(sets), m, sec[m - 0x280], local, lower=ground)
    # General's hedge drawn whole on the lower layer, from above (Vermilion's
    # long one by the Mart): a low block over plain grass
    for m, ground in LOWER_BLOCKS.items():
        place(ts, 0, m, general[m], plain, block=True, lower=ground)
    for p in out:
        if p[0] == 0 and p[1] in LOWER_BLOCKS:
            p[7], p[8] = 5, HEDGE_FACE
    # A tree's tip over a fence (0D6/0D7): the fence is on the lower layer,
    # drawn over the grass. It stands up on its own, keyed off the grass;
    # the tree's card carries the tip, and the cell's ground is plain grass.
    for mid, ground in TIP_FENCES.items():
        base = layer(ts, general[mid], 0)
        art = [[(rgb, 0 if rgb in grass else 1) for rgb, idx in line] for line in base]
        rows = [y for y in range(16) if any(art[y][x][1] for x in range(16))]
        cols = [x for x in range(16) if any(art[y][x][1] for y in range(16))]
        sx, sy = next(slots)
        for y in range(16):
            for x in range(16):
                if art[y][x][1]:
                    image[(sx + x, sy + y)] = art[y][x][0]
        out.append([0, mid, sx, sy, rows[0], rows[-1] + 1, ground, 0,
                    (cols[0] + cols[-1] + 1) // 2, 0x0E6])
    slot_of = {p[1]: (p[2], p[3], p[4]) for p in out if p[0] == 0}
    for p in out:
        sx, sy, sr = slot_of[p[9]]
        p[9:] = [sx, sy, sr]
    return [tuple(p) for p in out], sets


def write_table(props, sets, path):
    lines = ["/* Generated by scripts/fr_gen_trees.py --table: where each prop's",
             " * upper layer is in the tree texture, the rows it fills, and the",
             " * metatile drawn under it (its own: then the console draws it bare);",
             " * `set` 0 is General, others index",
             " * sPropTilesets. Regenerate with the texture. */",
             "#ifndef CTR_VOXEL_PROPS_TABLE_H", "#define CTR_VOXEL_PROPS_TABLE_H", "",
             "struct Tileset;"]
    lines += ["extern const struct Tileset %s;" % n for n in sets]
    lines += ["", "static const struct Tileset *const sPropTilesets[] = {", "    NULL,"]
    lines += ["    &%s," % n for n in sets]
    lines += ["};", "",
              "static const struct",
              "{",
              "    unsigned char set;",
              "    unsigned short id, x, y, r0, r1, ground;",
              "    /* 1: a north-south fence post (its column `centre`), built as the",
              "     * fence drawn front on at sx, sy from row sr, turned along it;",
              "     * 2: leans back, low; 3: a ledge, its face alone (its drawing kept",
              "     * flat too); 4: a low block over rows r0..r1, the drawing on top;",
              "     * 5: a block drawn whole, its top rows above row `centre`, its",
              "     * face below it */",
              "    unsigned char kind, centre;",
              "    unsigned short sx, sy, sr;",
              "} sProps[] = {"]
    for p in props:
        lines.append("    { %2d, 0x%03X, %3d, %3d, %2d, %2d, 0x%03X, %d, %2d, %3d, %3d, %2d }," % p)
    lines += ["};", "", "#endif", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def build(root):
    ts = fr_art.Tilesets("gTileset_General", "gTileset_PalletTown")
    blob = (root / "data/tilesets/primary/general/metatiles.bin").read_bytes()

    def metatile(i):
        return struct.unpack_from("<8H", blob, i * 16)

    image = {}  # (x, y) -> rgb, opaque texels only
    for half, (tip, crown, base) in enumerate(((0x00E, 0x01E, 0x026), (0x00F, 0x01F, 0x027))):
        ox = half * 16
        for row, mid in enumerate((tip, crown)):
            top = layer(ts, metatile(mid), 1)
            for y in range(16):
                for x in range(16):
                    rgb, idx = top[y][x]
                    if idx:
                        image[(ox + x, row * 16 + y)] = rgb
        ground = layer(ts, metatile(base), 0)
        shadow_rgb = next(rgb for line in ground for rgb, idx in line if idx == SHADOW)
        for y in range(16):
            for x in range(16):
                rgb, idx = ground[y][x]
                if idx in GRASS or idx == SHADOW:
                    image[(32 + ox + x, y)] = rgb
                else:
                    # the leaves and the trunk stand up on the card; the
                    # ground under them is in their shade
                    image[(ox + x, 32 + y)] = rgb
                    image[(32 + ox + x, y)] = shadow_rgb
    props = build_props(root, ts, metatile, image)
    rooms = build_rooms(root, image)
    return image, props, rooms


def build_rooms(root, image):
    """The rooms' pieces (fr_gen_rooms.py), their art in the slots the props
    left: the same drawing shares one."""
    import fr_gen_rooms
    used = {(x // 16 * 16, y // 16 * 16) for (x, y) in image}
    free = (s for s in prop_slots() if s not in used)
    seen = {}

    def place(art):
        key = tuple(tuple(row) for row in art)
        if key not in seen:
            sx, sy = next(free)
            for y in range(16):
                for x in range(16):
                    if art[y][x] is not None:
                        image[(sx + x, sy + y)] = tuple(art[y][x][:3])
            seen[key] = (sx, sy)
        return seen[key]

    return fr_gen_rooms.build(str(root), place)


def pack(image):
    pixels = bytearray(DIM * DIM_H * 2)
    for (x, y), rgb in image.items():
        r, g, b = rgb
        value = (r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | 1
        struct.pack_into("<H", pixels, 2 * texel_offset(x, y), value)
    return pixels


def main():
    port = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=port / "romfs/voxel/trees.rgba5551")
    parser.add_argument("--png", type=Path, help="also write a preview")
    parser.add_argument("--table", type=Path, help="write voxel_props_table.h")
    args = parser.parse_args()
    root = Path(os.environ.get("POKEFIRERED", port.parent))
    image, props, rooms = build(root)
    if args.table:
        write_table(props[0], props[1], args.table)
        import fr_gen_rooms
        fr_gen_rooms.write_table(rooms, args.table.parent / "voxel_room_table.h")
    pixels = pack(image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pixels)
    if args.png:
        from PIL import Image
        preview = Image.new("RGBA", (DIM, DIM_H))
        for (x, y), rgb in image.items():
            preview.putpixel((x, y), tuple(rgb) + (255,))
        preview.resize((DIM * 2, DIM_H * 2), Image.NEAREST).save(args.png)
    print(f"voxel trees: {DIM}x{DIM_H}, {len(pixels)} bytes -> {args.output}")


if __name__ == "__main__":
    main()
