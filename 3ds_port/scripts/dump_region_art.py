#!/usr/bin/env python3
"""Read a tileset's metatiles as the console's atlas composes them.

Layer 0 opaque, layer 1 keyed on colour index 0, palettes chosen by palette
number as the GBA and the atlas choose them. The building and relief
generators (voxel_building.py, gen_voxel_relief.py) read their art through
this, so a model is judged against exactly the pixels the game draws.
"""

import os
import re
import struct

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NUM_PRIMARY = 512
TILES_PER_TILESET = 512


# The generators build a LayoutArt per layout (thousands per run) over a few
# dozen tilesets: the files are read and parsed once per process.
_INCBIN = {}
_U16 = {}
_GRAPHICS = {}


def incbin_map(pattern):
    if pattern not in _INCBIN:
        _INCBIN[pattern] = _incbin_map(pattern)
    return dict(_INCBIN[pattern])


def _incbin_map(pattern):
    text = open(os.path.join(ROOT, "src", "data", "tilesets", "metatiles.h"),
                encoding="utf-8").read()
    out = {"gTileset_" + n: os.path.join(ROOT, p)
           for n, p in re.findall(pattern, text)}
    # A tileset whose data goes by another name: gTileset_Building is drawn
    # from gMetatiles_InsideBuilding. headers.h says which.
    headers = open(os.path.join(ROOT, "src", "data", "tilesets", "headers.h"),
                   encoding="utf-8").read()
    for name, body in re.findall(r"const struct Tileset (gTileset_\w+)\s*=\s*\{(.*?)\};",
                                 headers, re.S):
        m = re.search(r"\.metatiles\s*=\s*gMetatiles_(\w+)", body)
        if m and name not in out and "gTileset_" + m.group(1) in out:
            out[name] = out["gTileset_" + m.group(1)]
    return out


def read_u16(path):
    if path not in _U16:
        raw = open(path, "rb").read()
        _U16[path] = struct.unpack("<%dH" % (len(raw) // 2), raw[:len(raw) // 2 * 2])
    return list(_U16[path])


def tileset_dir(name):
    """data/tilesets/<primary|secondary>/<snake_name>/ from the C symbol."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name[len("gTileset_"):]).lower()
    for kind in ("primary", "secondary"):
        path = os.path.join(ROOT, "data", "tilesets", kind, snake)
        if os.path.isdir(path):
            return path
    return None


def load_graphics(name):
    """4bpp tile bytes and sixteen 16-colour palettes, as RGB triples (shared:
    callers only read them)."""
    if name not in _GRAPHICS:
        _GRAPHICS[name] = _load_graphics(name)
    return _GRAPHICS[name]


def _load_graphics(name):
    base = tileset_dir(name)
    if base is None:
        return b"", []
    tiles = open(os.path.join(base, "tiles.4bpp"), "rb").read() \
        if os.path.exists(os.path.join(base, "tiles.4bpp")) else b""
    palettes = []
    for i in range(16):
        path = os.path.join(base, "palettes", "%02d.gbapal" % i)
        if not os.path.exists(path):
            palettes.append([(255, 0, 255)] * 16)
            continue
        raw = open(path, "rb").read()
        entries = struct.unpack("<16H", raw[:32])
        palettes.append([(((c) & 31) * 255 // 31,
                          ((c >> 5) & 31) * 255 // 31,
                          ((c >> 10) & 31) * 255 // 31) for c in entries])
    return tiles, palettes


class Tilesets:
    def __init__(self, primary, secondary):
        self.pt, self.pp = load_graphics(primary)
        self.st, self.sp = load_graphics(secondary)

    def subtile(self, tile_id, palette_id):
        """One 8x8 block as a list of (rgb, index) pairs, row major."""
        if tile_id < TILES_PER_TILESET:
            tiles, palettes, local = self.pt, self.pp, tile_id
        else:
            tiles, palettes, local = self.st, self.sp, tile_id - TILES_PER_TILESET
        out = []
        base = local * 32
        if base + 32 > len(tiles):
            return [((255, 0, 255), 0)] * 64
        # Emerald's palette split: 0-5 primary, 6-12 secondary, whichever
        # tileset the subtile came from - as the GBA and voxel_atlas.c
        # LookupColor do. Jagged Pass draws General tiles in Lavaridge's
        # palettes; read by the tile's own tileset they came out black.
        palettes = self.pp if palette_id < 6 else self.sp
        pal = palettes[palette_id] if palette_id < len(palettes) else [(255, 0, 255)] * 16
        for y in range(8):
            for x in range(8):
                packed = tiles[base + y * 4 + x // 2]
                idx = (packed >> 4) if (x & 1) else (packed & 0xF)
                out.append((pal[idx], idx))
        return out


def metatile_image(entries, ts):
    """16x16 RGBA, layers composed the way voxel_atlas.c composes them."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    px = img.load()
    for layer in range(2):
        for quad in range(4):
            entry = entries[layer * 4 + quad]
            tile_id = entry & 0x3FF
            flip_x = bool(entry & 0x400)
            flip_y = bool(entry & 0x800)
            palette_id = (entry >> 12) & 0xF
            data = ts.subtile(tile_id, palette_id)
            ox, oy = (quad & 1) * 8, (quad >> 1) * 8
            for y in range(8):
                for x in range(8):
                    sx = 7 - x if flip_x else x
                    sy = 7 - y if flip_y else y
                    rgb, idx = data[sy * 8 + sx]
                    if layer != 0 and idx == 0:
                        continue
                    px[ox + x, oy + y] = (rgb[0], rgb[1], rgb[2], 255)
    return img
