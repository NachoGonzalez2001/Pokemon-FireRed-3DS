"""Mega Evolution battle sprites for the port, from the DS-style 64x64 sprite pack.

usage: python mega_sprites.py PACK_DIR POKEFIRERED_DIR OUT_C

PACK_DIR is a copy of the DS-Style 64x64 Pokemon Sprite Resource (its
sprites-processed/ folder is read). POKEFIRERED_DIR is the pokefirered tree: each
mega's feet are put on the same row as its base form's (the base form's
front/back y_offset). A mega too tall for that row is moved down in its box
until its top fits, and gets its own y_offset (gMegaYOffsets) that the battle
uses to lift the sprite by the same rows, so its feet stay where the base
form's are and nothing is cut.

Every form gets one 16-colour palette shared by its front and back pictures,
as on the GBA (index 0 transparent), and a shiny palette read off the shiny
pictures at the same pixels. Writes OUT_C: 4bpp tiles and palettes (BGR555).
The MEGA key's Key Stone is the port's own icon (tools/dev/ui_icons.py).

The order of FORMS is the order of MEGA_FORM_* in include/battle_mega.h.
"""
import os
import re
import sys
from collections import Counter

from PIL import Image

FORMS = [  # pack name, base species
    ("venusaur-mega", "VENUSAUR"),
    ("charizard-mega-x", "CHARIZARD"),
    ("charizard-mega-y", "CHARIZARD"),
    ("blastoise-mega", "BLASTOISE"),
    ("beedrill-mega", "BEEDRILL"),
    ("pidgeot-mega", "PIDGEOT"),
    ("alakazam-mega", "ALAKAZAM"),
    ("slowbro-mega", "SLOWBRO"),
    ("gengar-mega", "GENGAR"),
    ("kangaskhan-mega", "KANGASKHAN"),
    ("pinsir-mega", "PINSIR"),
    ("gyarados-mega", "GYARADOS"),
    ("aerodactyl-mega", "AERODACTYL"),
    ("mewtwo-mega-x", "MEWTWO"),
    ("mewtwo-mega-y", "MEWTWO"),
    ("heracross-mega", "HERACROSS"),
    ("dragonite-mega", "DRAGONITE"),
    ("ampharos-mega", "AMPHAROS"),
    ("steelix-mega", "STEELIX"),
    ("scizor-mega", "SCIZOR"),
    ("houndoom-mega", "HOUNDOOM"),
    ("tyranitar-mega", "TYRANITAR"),
    ("sceptile-mega", "SCEPTILE"),
    ("blaziken-mega", "BLAZIKEN"),
    ("swampert-mega", "SWAMPERT"),
    ("gardevoir-mega", "GARDEVOIR"),
    ("sableye-mega", "SABLEYE"),
    ("mawile-mega", "MAWILE"),
    ("aggron-mega", "AGGRON"),
    ("medicham-mega", "MEDICHAM"),
    ("manectric-mega", "MANECTRIC"),
    ("sharpedo-mega", "SHARPEDO"),
    ("camerupt-mega", "CAMERUPT"),
    ("altaria-mega", "ALTARIA"),
    ("banette-mega", "BANETTE"),
    ("absol-mega", "ABSOL"),
    ("glalie-mega", "GLALIE"),
    ("salamence-mega", "SALAMENCE"),
    ("metagross-mega", "METAGROSS"),
    ("latias-mega", "LATIAS"),
    ("latios-mega", "LATIOS"),
    ("rayquaza-mega", "RAYQUAZA"),
    ("meganium-mega", "MEGANIUM"),
    ("feraligatr-mega", "FERALIGATR"),
    ("skarmory-mega", "SKARMORY"),
    ("clefable-mega", "CLEFABLE"),
    ("victreebel-mega", "VICTREEBEL"),
    ("starmie-mega", "STARMIE"),
]


def y_offsets(path):
    text = open(path, encoding="utf-8").read()
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"\[SPECIES_(\w+)\]\s*=\s*\{[^}]*?\.y_offset\s*=\s*(\d+)", text)}


def load(pack, kind, name):
    return Image.open(os.path.join(pack, "sprites-processed", kind, name + ".png")).convert("RGBA")


def opaque(px):
    return px[3] >= 128


def fit(im, offset):
    """The base form's y_offset, or less when the picture would not fit."""
    box = im.getbbox()
    return min(offset, 64 - (box[3] - box[1]))


def seat(im, offset):
    """The picture moved up or down so offset rows stay clear below it."""
    box = im.getbbox()
    shift = (64 - offset) - box[3]
    assert box[1] + shift >= 0, "picture cut at the top"
    out = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    out.paste(im, (0, shift))
    return out


def palette_for(images):
    colours = Counter()
    for im in images:
        colours.update(p[:3] for p in im.getdata() if opaque(p))
    if len(colours) <= 15:
        return sorted(colours, key=lambda c: -colours[c])
    # too many: quantise both pictures together to 15
    strip = Image.new("RGB", (64 * len(images), 64), (0, 0, 0))
    mask = Image.new("L", strip.size, 0)
    for i, im in enumerate(images):
        strip.paste(im.convert("RGB"), (64 * i, 0))
        mask.paste(im.getchannel("A").point(lambda a: 255 if a >= 128 else 0), (64 * i, 0))
    pixels = [strip.getpixel((x, y)) for y in range(64) for x in range(strip.width) if mask.getpixel((x, y))]
    sample = Image.new("RGB", (len(pixels), 1))
    sample.putdata(pixels)
    q = sample.quantize(15, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:45]
    return [tuple(pal[i:i + 3]) for i in range(0, 45, 3)]


def nearest(pal, c):
    return min(range(len(pal)), key=lambda i: sum((a - b) ** 2 for a, b in zip(pal[i], c)))


def indices(im, pal):
    lut = {}
    out = []
    for p in im.getdata():
        if not opaque(p):
            out.append(0)
            continue
        c = p[:3]
        if c not in lut:
            lut[c] = nearest(pal, c) + 1
        out.append(lut[c])
    return out


def tiles(idx):
    data = bytearray()
    for ty in range(8):
        for tx in range(8):
            for y in range(8):
                for x in range(0, 8, 2):
                    a = idx[(ty * 8 + y) * 64 + tx * 8 + x]
                    b = idx[(ty * 8 + y) * 64 + tx * 8 + x + 1]
                    data.append(a | b << 4)
    return data


def bgr555(c):
    r, g, b = (v >> 3 for v in c)
    return r | g << 5 | b << 10


def shiny_palette(pal, pairs):
    votes = [Counter() for _ in pal]
    for idx, shiny in pairs:
        for i, p in zip(idx, shiny.getdata()):
            if i and opaque(p):
                votes[i - 1][p[:3]] += 1
    return [v.most_common(1)[0][0] if v else pal[i] for i, v in enumerate(votes)]


def words(data):
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]



def main(pack, root, out):
    front = y_offsets(os.path.join(root, "src/data/pokemon_graphics/front_pic_coordinates.h"))
    back = y_offsets(os.path.join(root, "src/data/pokemon_graphics/back_pic_coordinates.h"))
    lines = ["/* Generated by tools/dev/mega_sprites.py from the DS-Style 64x64 Pokemon Sprite",
             " * Resource (Gen VI, PokeCommunity; artists credited in NOTICE.md). Fan art,",
             " * not from the game. */",
             '#include "global.h"', "",
             "const u32 gMegaPics[%d][2][0x200] = {" % len(FORMS)]
    pals = []
    offsets = []
    for name, species in FORMS:
        fo = fit(load(pack, "front", name), front[species])
        bo = fit(load(pack, "back", name), back[species])
        offsets.append((fo, bo))
        f = seat(load(pack, "front", name), fo)
        b = seat(load(pack, "back", name), bo)
        fs = seat(load(pack, "front-shiny", name), fo)
        bs = seat(load(pack, "back-shiny", name), bo)
        pal = palette_for([f, b])
        fi, bi = indices(f, pal), indices(b, pal)
        shiny = shiny_palette(pal, [(fi, fs), (bi, bs)])
        pals.append((pal, shiny))
        lines.append("    { /* %s */" % name)
        for idx in (fi, bi):
            w = words(tiles(idx))
            lines.append("        {")
            for i in range(0, len(w), 8):
                lines.append("            " + ",".join("0x%08X" % v for v in w[i:i + 8]) + ",")
            lines.append("        },")
        lines.append("    },")
        print("%-18s %2d colours, y_offset %d/%d (base %d/%d)" % (
            name, len(pal), fo, bo, front[species], back[species]))
    lines += ["};", "", "const u16 gMegaPalettes[%d][2][16] = {" % len(FORMS)]
    for (pal, shiny), (name, _) in zip(pals, FORMS):
        row = lambda p: "{ 0x0000," + ",".join("0x%04X" % bgr555(c) for c in p) + ",0x0000" * (15 - len(p)) + " }"
        lines.append("    { %s, %s }, /* %s */" % (row(pal), row(shiny), name))
    lines += ["};", "", "/* Front and back y_offset of each form (see gMonFrontPicCoords). */",
              "const u8 gMegaYOffsets[%d][2] = {" % len(FORMS)]
    for (fo, bo), (name, _) in zip(offsets, FORMS):
        lines.append("    { %2d, %2d }, /* %s */" % (fo, bo, name))
    lines += ["};", ""]
    open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print("wrote", out)


if __name__ == "__main__":
    main(*sys.argv[1:4])
