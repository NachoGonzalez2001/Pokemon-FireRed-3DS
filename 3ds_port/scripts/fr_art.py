#!/usr/bin/env python3
"""FireRed tileset art, read straight from a pokefirered checkout.

The FireRed counterpart of the Emerald port's dump_region_art.py, with the
same interface (incbin_map, read_u16, Tilesets, ROOT, metatile_image) so the
geometry kernel (voxel_building.py) runs on it unchanged. What differs:

  - FireRed splits tiles and metatiles at 640 (Emerald: 512) and palettes at
    7 (Emerald: 6): include/fieldmap.h NUM_*_IN_PRIMARY.
  - Metatile attributes are 32-bit (INCBIN_U32): behaviour is bits 0-8,
    terrain 9-13, encounter type 24-26, layer type 29-30.
  - An unbuilt checkout carries the art as indexed tiles.png and JASC .pal
    files, not tiles.4bpp / .gbapal; both are read directly. A JASC colour is
    reduced to the GBA's 5 bits per channel (as gbagfx does) and widened back
    exactly as the Emerald scripts widen a .gbapal, so a colour compares equal
    whichever source it came from.

ROOT is the pokefirered checkout: $POKEFIRERED, else ../../../pokefirered
beside this project.
"""

import os
import re
import struct

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get("POKEFIRERED") or
                       os.path.join(HERE, "..", "..", "..", "pokefirered"))
NUM_PRIMARY = 640          # metatiles in a primary tileset
TILES_PER_TILESET = 640    # 8x8 tiles in a primary tileset
PALS_IN_PRIMARY = 7

# 32-bit metatile attributes (include/global.fieldmap.h, src/fieldmap.c)
ATTR_BEHAVIOR_MASK = 0x000001FF
ATTR_TERRAIN_MASK = 0x00003E00
ATTR_TERRAIN_SHIFT = 9
ATTR_ENCOUNTER_MASK = 0x07000000
ATTR_ENCOUNTER_SHIFT = 24
ATTR_LAYER_MASK = 0x60000000
ATTR_LAYER_SHIFT = 29

_INCBIN = {}
_U16 = {}
_U32 = {}
_GRAPHICS = {}


def incbin_map(pattern):
    """gTileset_X -> file path for every INCBIN in metatiles.h matching
    `pattern`. The Emerald scripts ask with INCBIN_U16 for both metatiles and
    attributes; FireRed's attributes are INCBIN_U32, so the macro name is
    matched loosely."""
    pattern = pattern.replace("INCBIN_U16", "INCBIN_U(?:16|32)")
    if pattern not in _INCBIN:
        _INCBIN[pattern] = _incbin_map(pattern)
    return dict(_INCBIN[pattern])


def _incbin_map(pattern):
    text = open(os.path.join(ROOT, "src", "data", "tilesets", "metatiles.h"),
                encoding="utf-8").read()
    out = {"gTileset_" + n: os.path.join(ROOT, p) for n, p in re.findall(pattern, text)}
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


def read_u32(path):
    if path not in _U32:
        raw = open(path, "rb").read()
        _U32[path] = struct.unpack("<%dI" % (len(raw) // 4), raw[:len(raw) // 4 * 4])
    return list(_U32[path])


def metatile_attributes(tileset):
    """The 32-bit attribute table of a tileset symbol (empty if unknown)."""
    path = incbin_map(r"gMetatileAttributes_(\w+)\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)").get(tileset)
    return read_u32(path) if path else []


def tileset_dir(name):
    """data/tilesets/<primary|secondary>/<snake_name>/ from the C symbol."""
    path = incbin_map(r"gMetatiles_(\w+)\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)").get(name)
    if path:
        return os.path.dirname(path)
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name[len("gTileset_"):]).lower()
    for kind in ("primary", "secondary"):
        path = os.path.join(ROOT, "data", "tilesets", kind, snake)
        if os.path.isdir(path):
            return path
    return None


def _widen(c5):
    return c5 * 255 // 31


def read_jasc(path):
    lines = open(path, encoding="ascii").read().split()
    if lines[:2] != ["JASC-PAL", "0100"]:
        raise ValueError("%s: not a JASC palette" % path)
    count = int(lines[2])
    vals = [int(v) for v in lines[3:3 + count * 3]]
    pal = [tuple(_widen(vals[i * 3 + k] >> 3) for k in range(3)) for i in range(count)]
    return (pal + [(255, 0, 255)] * 16)[:16]


def _tiles_from_png(path):
    """An indexed tiles.png as 4bpp bytes in GBA order (low nibble = left)."""
    im = Image.open(path)
    if im.mode != "P":
        raise ValueError("%s: tiles.png is not indexed" % path)
    w, h = im.size
    px = im.load()
    out = bytearray()
    for ty in range(h // 8):
        for tx in range(w // 8):
            for y in range(8):
                for x in range(0, 8, 2):
                    lo = px[tx * 8 + x, ty * 8 + y] & 0xF
                    hi = px[tx * 8 + x + 1, ty * 8 + y] & 0xF
                    out.append(lo | (hi << 4))
    return bytes(out)


def load_graphics(name):
    if name not in _GRAPHICS:
        _GRAPHICS[name] = _load_graphics(name)
    return _GRAPHICS[name]


def graphics_dir(name):
    """Where a tileset's tiles and palettes are: its header's .tiles symbol's
    INCBIN, not its metatiles' folder - Silph Co. draws with the
    Condominiums' graphics, and read from its own folder it had none."""
    headers = open(os.path.join(ROOT, "src", "data", "tilesets", "headers.h"),
                   encoding="utf-8").read()
    m = re.search(r"const struct Tileset %s\s*=\s*\{(.*?)\};" % re.escape(name), headers, re.S)
    if m:
        sym = re.search(r"\.tiles\s*=\s*(\w+)", m.group(1))
        if sym:
            gfx = open(os.path.join(ROOT, "src", "data", "tilesets", "graphics.h"),
                       encoding="utf-8").read()
            inc = re.search(r"%s\[\]\s*=\s*INCBIN_U\d+\(\"([^\"]+)\"" % re.escape(sym.group(1)), gfx)
            if inc:
                return os.path.dirname(os.path.join(ROOT, inc.group(1)))
    return tileset_dir(name)


def _load_graphics(name):
    base = graphics_dir(name)
    if base is None:
        return b"", []
    if os.path.exists(os.path.join(base, "tiles.4bpp")):
        tiles = open(os.path.join(base, "tiles.4bpp"), "rb").read()
    elif os.path.exists(os.path.join(base, "tiles.png")):
        tiles = _tiles_from_png(os.path.join(base, "tiles.png"))
    else:
        tiles = b""
    palettes = []
    for i in range(16):
        gba = os.path.join(base, "palettes", "%02d.gbapal" % i)
        jasc = os.path.join(base, "palettes", "%02d.pal" % i)
        if os.path.exists(gba):
            entries = struct.unpack("<16H", open(gba, "rb").read()[:32])
            palettes.append([(_widen(c & 31), _widen((c >> 5) & 31), _widen((c >> 10) & 31))
                             for c in entries])
        elif os.path.exists(jasc):
            palettes.append(read_jasc(jasc))
        else:
            palettes.append([(255, 0, 255)] * 16)
    return tiles, palettes


class Tilesets:
    def __init__(self, primary, secondary):
        self.pt, self.pp = load_graphics(primary)
        self.st, self.sp = load_graphics(secondary)

    def subtile(self, tile_id, palette_id):
        """One 8x8 block as a list of (rgb, index) pairs, row major."""
        if tile_id < TILES_PER_TILESET:
            tiles, local = self.pt, tile_id
        else:
            tiles, local = self.st, tile_id - TILES_PER_TILESET
        base = local * 32
        if base + 32 > len(tiles):
            return [((255, 0, 255), 0)] * 64
        # FireRed's palette split: 0-6 primary, 7-12 secondary, whichever
        # tileset the tile itself came from (fieldmap.c CopyTilesetPalettes).
        palettes = self.pp if palette_id < PALS_IN_PRIMARY else self.sp
        pal = palettes[palette_id] if palette_id < len(palettes) else [(255, 0, 255)] * 16
        out = []
        for y in range(8):
            for x in range(8):
                packed = tiles[base + y * 4 + x // 2]
                idx = (packed >> 4) if (x & 1) else (packed & 0xF)
                out.append((pal[idx], idx))
        return out


def metatile_image(entries, ts):
    """16x16 RGBA: layer 0 opaque, layer 1 keyed on colour index 0."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    px = img.load()
    for layer in range(2):
        for quad in range(4):
            entry = entries[layer * 4 + quad]
            data = ts.subtile(entry & 0x3FF, (entry >> 12) & 0xF)
            fx, fy = bool(entry & 0x400), bool(entry & 0x800)
            ox, oy = (quad & 1) * 8, (quad >> 1) * 8
            for y in range(8):
                for x in range(8):
                    rgb, idx = data[(7 - y if fy else y) * 8 + (7 - x if fx else x)]
                    if layer != 0 and idx == 0:
                        continue
                    px[ox + x, oy + y] = rgb + (255,)
    return img
