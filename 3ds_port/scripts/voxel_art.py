#!/usr/bin/env python3
"""Tileset art as pixels: decode a metatile of a map's tileset pair.

Reads the decomp-layout files (tiles.4bpp, palettes/*.gbapal, metatiles.bin)
the build and the builder both provide, and answers what a metatile's lower
and upper layers draw, pixel by pixel.

    python voxel_art.py gTileset_General 16 18 24 26    prints drawn-pixel counts
"""

import os
import re
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CELL = 16                 # a metatile edge, in pixels
TILES_PER_TILESET = 512


def _incbin(pattern):
    text = open(os.path.join(ROOT, "src", "data", "tilesets", "metatiles.h"),
                encoding="utf-8").read()
    return {"gTileset_" + n: os.path.join(ROOT, p)
            for n, p in re.findall(pattern, text)}


METATILES = _incbin(r"gMetatiles_(\w+)\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)")
ATTRIBUTES = _incbin(r"gMetatileAttributes_(\w+)\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)")


def read_u16(path):
    raw = open(path, "rb").read()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw[:len(raw) // 2 * 2]))


def tileset_dir(symbol):
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", symbol[len("gTileset_"):]).lower()
    for kind in ("primary", "secondary"):
        path = os.path.join(ROOT, "data", "tilesets", kind, snake)
        if os.path.isdir(path):
            return path
    return None


class Graphics:
    """One tileset's 4bpp tiles and sixteen palettes, as RGB888."""

    def __init__(self, symbol):
        base = tileset_dir(symbol)
        self.tiles = b""
        self.palettes = []
        if base is None:
            return
        path = os.path.join(base, "tiles.4bpp")
        if os.path.exists(path):
            self.tiles = open(path, "rb").read()
        for i in range(16):
            pal = os.path.join(base, "palettes", "%02d.gbapal" % i)
            if not os.path.exists(pal):
                self.palettes.append(None)
                continue
            raw = open(pal, "rb").read()[:32]
            self.palettes.append([
                (((c) & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31,
                 ((c >> 10) & 31) * 255 // 31)
                for c in struct.unpack("<16H", raw)])


_GRAPHICS = {}


def graphics(symbol):
    """One Graphics per tileset per process: Pairs only read it."""
    if symbol not in _GRAPHICS:
        _GRAPHICS[symbol] = Graphics(symbol)
    return _GRAPHICS[symbol]


class Pair:
    """A primary/secondary tileset pair: what one map draws from."""

    def __init__(self, primary, secondary):
        self.gfx = (graphics(primary), graphics(secondary))
        self.meta = (read_u16(METATILES[primary]) if primary in METATILES else [],
                     read_u16(METATILES[secondary]) if secondary in METATILES else [])
        self.attr = (read_u16(ATTRIBUTES[primary]) if primary in ATTRIBUTES else [],
                     read_u16(ATTRIBUTES[secondary]) if secondary in ATTRIBUTES else [])
        self._layers = {}     # (metatile, layer) -> layer_pixels, asked again and again

    def entries(self, metatile):
        which = 0 if metatile < TILES_PER_TILESET else 1
        index = metatile - which * TILES_PER_TILESET
        table = self.meta[which]
        if (index + 1) * 8 > len(table):
            return None
        return table[index * 8:index * 8 + 8]

    def attribute(self, metatile):
        which = 0 if metatile < TILES_PER_TILESET else 1
        index = metatile - which * TILES_PER_TILESET
        table = self.attr[which]
        return table[index] if index < len(table) else 0

    def subtile(self, tile_id, palette_id):
        """8x8 as (rgb, index) pairs, row major, or None where unreadable.

        Tiles split at tile id 512, palettes independently at palette id 6,
        exactly as voxel_atlas.c LookupColor. A primary subtile can use a
        secondary palette (and vice versa).
        """
        which = 0 if tile_id < TILES_PER_TILESET else 1
        local = tile_id - which * TILES_PER_TILESET
        gfx = self.gfx[which]
        base = local * 32
        if base + 32 > len(gfx.tiles):
            return None
        palettes = self.gfx[0 if palette_id < 6 else 1].palettes
        pal = palettes[palette_id] if palette_id < len(palettes) else None
        if pal is None:
            return None
        out = []
        for y in range(8):
            for x in range(8):
                packed = gfx.tiles[base + y * 4 + x // 2]
                idx = (packed >> 4) if (x & 1) else (packed & 0xF)
                out.append((pal[idx], idx))
        return out

    def layer_pixels(self, metatile, layer):
        """Drawn pixels of one layer: {(x, y): rgb}. Index 0 is not drawn.

        Layer 0 is the metatile's lower half and layer 1 the upper. Index 0 is
        skipped on BOTH, unlike the atlas, which floods layer 0's index 0 with
        the backdrop colour to get an opaque tile: here the question is what
        the artist DREW, and an index-0 pixel is where they drew nothing.
        """
        key = (metatile, layer)
        if key not in self._layers:
            self._layers[key] = self._layer_pixels(metatile, layer)
        return dict(self._layers[key])

    def _layer_pixels(self, metatile, layer):
        entries = self.entries(metatile)
        out = {}
        if entries is None:
            return out
        for quad in range(4):
            entry = entries[layer * 4 + quad]
            data = self.subtile(entry & 0x3FF, (entry >> 12) & 0xF)
            if data is None:
                continue
            flip_x, flip_y = bool(entry & 0x400), bool(entry & 0x800)
            ox, oy = (quad & 1) * 8, (quad >> 1) * 8
            for y in range(8):
                for x in range(8):
                    sx = 7 - x if flip_x else x
                    sy = 7 - y if flip_y else y
                    rgb, idx = data[sy * 8 + sx]
                    if idx == 0:
                        continue
                    out[(ox + x, oy + y)] = rgb
        return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    symbol = sys.argv[1]
    pair = Pair(symbol, symbol)
    for m in [int(v, 0) for v in sys.argv[2:]] or list(range(0, 64)):
        print("%-4d lower=%3d upper=%3d" % (m, len(pair.layer_pixels(m, 0)), len(pair.layer_pixels(m, 1))))


if __name__ == "__main__":
    main()
