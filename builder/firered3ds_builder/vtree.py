"""Rebuild, from the player's ROM, the files the voxel generators read.

The FireRed generators (fr_gen_relief.py, fr_gen_trees.py,
fr_export_buildings.py) were written against the decomp tree's layout:
tileset art and palettes in data/tilesets, blockdata and borders in
data/layouts, layouts.json, a map.json (and scripts.inc) per map, three C
headers naming every tileset's files and one metatile behaviour. This module
writes exactly that layout into a temporary directory:

* binary inputs come from the recipe's `inputs` entries (ROM copies and LZ77
  streams, each checked against its CRC);
* layouts.json and every map.json are read back from the ROM's own MapLayout
  and MapHeader structures, whose offsets the recipe names
  (tools/vtree_manifest.py);
* metatiles.h, headers.h, graphics.h, metatile_behaviors.h and the maps'
  scripts.inc are reduced to the lines the generators parse.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from .errors import BuilderError
from .recipe import Recipe, build_entry

ROM_BASE = 0x08000000


def _ptr(rom: bytes, off: int) -> int | None:
    value = struct.unpack_from("<I", rom, off)[0]
    if value == 0:
        return None
    if not ROM_BASE <= value < ROM_BASE + len(rom):
        raise BuilderError("The ROM does not have the expected structure (bad pointer at %#x)." % off)
    return value - ROM_BASE


def read_layout(rom: bytes, off: int, tilesets: dict[int, str]) -> dict:
    width, height = struct.unpack_from("<ii", rom, off)
    primary = _ptr(rom, off + 0x10)
    secondary = _ptr(rom, off + 0x14)
    return {"width": width, "height": height,
            "primary_tileset": tilesets.get(primary, "NULL") if primary is not None else "NULL",
            "secondary_tileset": tilesets.get(secondary, "NULL") if secondary is not None else "NULL"}


def layouts_json(rom: bytes, meta: dict) -> dict:
    tilesets = {off: name for name, off in meta["tilesets"].items()}
    out = []
    for item in meta["layouts"]:
        if "rom" not in item:
            out.append({"id": item["id"]} if "id" in item else {})
            continue
        entry = {"id": item["id"], "name": item["name"]}
        entry.update(read_layout(rom, item["rom"], tilesets))
        entry["border_filepath"] = item["border_filepath"]
        entry["blockdata_filepath"] = item["blockdata_filepath"]
        out.append(entry)
    return {"layouts_table_label": meta["layouts_table_label"], "layouts": out}


def map_json(rom: bytes, off: int, item: dict, meta: dict) -> dict:
    layout_id = struct.unpack_from("<H", rom, off + 0x12)[0]
    map_type = rom[off + 0x17]
    layouts = meta["layouts"]
    layout = layouts[layout_id - 1].get("id", "LAYOUT_NONE") if 0 < layout_id <= len(layouts) else "LAYOUT_NONE"
    return {"id": item["id"], "name": item["name"], "layout": layout,
            "map_type": meta["map_types"].get(str(map_type), "MAP_TYPE_NONE")}


def headers(meta: dict) -> dict[str, str]:
    """The C headers, reduced to the lines the generators parse."""
    metatiles = "".join(
        'const %s %s[] = %s("%s");\n' % (("u32", sym, "INCBIN_U32", path) if sym.startswith("gMetatileAttributes")
                                          else ("u16", sym, "INCBIN_U16", path))
        for sym, path in meta["metatiles_h"])
    tilesets = "".join(
        "const struct Tileset %s =\n{\n    .tiles = %s,\n    .metatiles = %s,\n    .metatileAttributes = %s,\n};\n\n"
        % (name, tiles, mts, attrs) for name, tiles, mts, attrs in meta["headers_h"])
    graphics = "".join('const u32 %s[] = INCBIN_U32("%s");\n' % (sym, path) for sym, path in meta["graphics_h"])
    behaviours = "".join("#define %s 0x%02X\n" % (name, value) for name, value in meta["behaviours"].items())
    return {"src/data/tilesets/metatiles.h": metatiles,
            "src/data/tilesets/headers.h": tilesets,
            "src/data/tilesets/graphics.h": graphics,
            "include/constants/metatile_behaviors.h": behaviours}


def build_tree(rom: bytes, recipe: Recipe, root: Path, progress=None) -> None:
    meta = recipe.vtree
    if not meta or not recipe.inputs:
        raise BuilderError("The release's recipe has no 3D scenery inputs.", code="recipe_unreadable")
    total = len(recipe.inputs)
    for i, entry in enumerate(recipe.inputs):
        data = build_entry(entry, rom, recipe.literals, recipe.bitmaps)
        if len(data) != entry["size"] or zlib.crc32(data) & 0xFFFFFFFF != entry["crc"]:
            raise BuilderError("A 3D scenery input does not match this release: %s" % entry["path"],
                               code="data_rebuild_failed")
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if progress and i % 200 == 0:
            progress(0.8 * i / max(total, 1))
    for rel, text in headers(meta).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    layouts = root / "data" / "layouts" / "layouts.json"
    layouts.parent.mkdir(parents=True, exist_ok=True)
    layouts.write_text(json.dumps(layouts_json(rom, meta), indent=2), encoding="utf-8")
    for item in meta["maps"]:
        folder = root / "data" / "maps" / item["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "map.json").write_text(json.dumps(map_json(rom, item["rom"], item, meta), indent=2),
                                         encoding="utf-8")
        switched = meta["script_layouts"].get(item["folder"])
        if switched:
            (folder / "scripts.inc").write_text("".join("\tsetmaplayoutindex %s\n" % l for l in switched),
                                                encoding="utf-8")
    if progress:
        progress(1.0)
