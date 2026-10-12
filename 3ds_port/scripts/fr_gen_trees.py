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

Palette 0 of General: 1-4 leaves, 5-6 trunk, 8/D/E grass, F shadow.
"""

import argparse
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fr_art  # noqa: E402

DIM = 128
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
    return image


def pack(image):
    pixels = bytearray(DIM * DIM * 2)
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
    args = parser.parse_args()
    root = Path(os.environ.get("POKEFIRERED", port.parent))
    image = build(root)
    pixels = pack(image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pixels)
    if args.png:
        from PIL import Image
        preview = Image.new("RGBA", (64, 48))
        for (x, y), rgb in image.items():
            preview.putpixel((x, y), tuple(rgb) + (255,))
        preview.resize((256, 192), Image.NEAREST).save(args.png)
    print(f"voxel trees: {DIM}x{DIM}, {len(pixels)} bytes -> {args.output}")


if __name__ == "__main__":
    main()
