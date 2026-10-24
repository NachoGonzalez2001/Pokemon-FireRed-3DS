"""The inputs of the voxel generators, described for the builder.

The FireRed generators (3ds_port/scripts/fr_gen_relief.py, fr_gen_trees.py,
fr_export_buildings.py) read a handful of files from the decomp tree: tileset
art and palettes, metatiles, metatile attributes, layout blockdata and
borders, layouts.json, the maps' map.json and scripts.inc, three tileset
headers and one metatile behaviour. The builder rebuilds exactly those files
from the player's ROM in a temporary tree and runs the same generators there.

Binary inputs become recipe entries (ROM copies, LZ77 streams); the JSON and
header files become metadata: names, paths and the ROM offsets of the
structures (MapLayout, MapHeader, Tileset) whose fields the builder reads
back from the ROM. No field value of those structures is stored here.

There is no symbol table of the original game to take those offsets from (it
is built with agbcc, which this project does not use): they are found in the
ROM at release time, each structure by the pointers to its own data, and every
one is checked against the decomp's values before it is recorded.
"""

from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path

ROM_BASE = 0x08000000


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def metatiles_h(root: Path) -> list[list[str]]:
    """[symbol, path] of every INCBIN in src/data/tilesets/metatiles.h."""
    return [list(m) for m in re.findall(r'const u\d+ (gMeta\w+)\[\]\s*=\s*INCBIN_U\d+\("([^"]+)"\)',
                                         _read(root, "src/data/tilesets/metatiles.h"))]


def headers_h(root: Path) -> list[list[str]]:
    """[tileset, tiles symbol, metatiles symbol, attributes symbol] per Tileset."""
    out = []
    text = _read(root, "src/data/tilesets/headers.h")
    for name, body in re.findall(r"const struct Tileset (gTileset_\w+)\s*=\s*\{(.*?)\};", text, re.S):
        def field(key):
            m = re.search(r"\.%s\s*=\s*(\w+)" % key, body)
            return m.group(1) if m else ""
        out.append([name, field("tiles"), field("metatiles"), field("metatileAttributes")])
    return out


def graphics_h(root: Path) -> list[list[str]]:
    """[tiles symbol, path] of every tileset's tiles INCBIN in graphics.h."""
    return [list(m) for m in re.findall(r'const u32 (gTilesetTiles_\w+)\[\]\s*=\s*INCBIN_U32\("([^"]+)"\)',
                                         _read(root, "src/data/tilesets/graphics.h"))]


def graphics_dirs(root: Path) -> list[str]:
    """Every folder a tileset's tiles and palettes are read from (fr_art.graphics_dir)."""
    dirs = [os.path.dirname(path) for _, path in graphics_h(root)]
    dirs += [os.path.dirname(path) for _, path in metatiles_h(root)]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def binary_inputs(root: Path) -> list[str]:
    files: list[str] = []
    layouts = json.loads(_read(root, "data/layouts/layouts.json"))["layouts"]
    for entry in layouts:
        for key in ("blockdata_filepath", "border_filepath"):
            if key in entry:
                files.append(entry[key])
    files += [path for _, path in metatiles_h(root)]
    for folder in graphics_dirs(root):
        # Only what exists: the generators test for these files, so the
        # builder's tree must hold exactly the same set as the build's.
        if (root / folder / "tiles.4bpp").exists():
            files.append(folder + "/tiles.4bpp")
        for i in range(16):
            if (root / folder / "palettes" / ("%02d.gbapal" % i)).exists():
                files.append(folder + "/palettes/%02d.gbapal" % i)
    seen, ordered = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered


def _finds(rom: bytes, needle: bytes, align: int = 1) -> list[int]:
    out, at = [], rom.find(needle)
    while at >= 0:
        if at % align == 0:
            out.append(at)
        at = rom.find(needle, at + 1)
    return out


def _pointer_sites(rom: bytes, target: int) -> list[int]:
    return _finds(rom, struct.pack("<I", ROM_BASE + target), 4)


def _tileset_data(root: Path) -> dict[str, tuple[bytes, bytes]]:
    """Each tileset's own metatiles and attributes, as the decomp has them."""
    paths = dict((s, p) for s, p in metatiles_h(root))
    out = {}
    for name, _, mt_sym, attr_sym in headers_h(root):
        mt, attr = paths.get(mt_sym), paths.get(attr_sym)
        if mt and attr:
            out[name] = ((root / mt).read_bytes(), (root / attr).read_bytes())
    return out


def _is_tileset(rom: bytes, ptr: int, data: tuple[bytes, bytes] | None, name: str) -> bool:
    """`ptr` is a Tileset struct with these metatiles and attributes (NULL: 0)."""
    if name in (None, "NULL", "0"):
        return ptr == 0
    if data is None or not ROM_BASE <= ptr < ROM_BASE + len(rom) - 0x18:
        return False
    base = ptr - ROM_BASE
    mt, attr = (struct.unpack_from("<I", rom, base + k)[0] - ROM_BASE for k in (0x0C, 0x14))
    return rom[mt:mt + len(data[0])] == data[0] and rom[attr:attr + len(data[1])] == data[1]


def locate_layouts(root: Path, rom: bytes) -> tuple[dict[str, int], dict[str, int], dict[str, list[int]]]:
    """MapLayout struct offsets, by their map pointer, checked field by field;
    and the Tileset struct offsets they point at. Tilesets are taken from the
    layouts, not searched: the unused dummies share their data."""
    sets = _tileset_data(root)
    out, tilesets, copies = {}, {}, {}
    for entry in json.loads(_read(root, "data/layouts/layouts.json"))["layouts"]:
        if "name" not in entry:
            continue
        blocks = (root / entry["blockdata_filepath"]).read_bytes()
        border = (root / entry["border_filepath"]).read_bytes()
        found = set()
        for m in _finds(rom, blocks, 2):
            for site in _pointer_sites(rom, m):
                base = site - 0x0C
                w, h, b, _, p, s = struct.unpack_from("<iiIIII", rom, base)
                if (w, h) != (entry["width"], entry["height"]):
                    continue
                if rom[b - ROM_BASE:b - ROM_BASE + len(border)] != border:
                    continue
                if not _is_tileset(rom, p, sets.get(entry["primary_tileset"]), entry["primary_tileset"]):
                    continue
                if not _is_tileset(rom, s, sets.get(entry["secondary_tileset"]), entry["secondary_tileset"]):
                    continue
                found.add((base, p - ROM_BASE, s - ROM_BASE))
        # copies of one struct (a layout listed twice) read back the same
        if not found or len({(p, s) for _, p, s in found}) != 1:
            raise SystemExit("vtree_manifest: layout %s found %d times in the ROM" % (entry["id"], len(found)))
        copies[entry["id"]] = sorted(b for b, _, _ in found)
        base, p, s = min(found)
        p, s = max(p, -1), max(s, -1)
        out[entry["id"]] = base
        for name, off in ((entry["primary_tileset"], p), (entry["secondary_tileset"], s)):
            if name in ("NULL", "0"):
                continue
            if tilesets.setdefault(name, off) != off:
                raise SystemExit("vtree_manifest: %s is two structs in the ROM" % name)
    if len(set(tilesets.values())) != len(tilesets):
        raise SystemExit("vtree_manifest: two tilesets share one struct")
    return out, tilesets, copies


def map_types(root: Path) -> dict[int, str]:
    text = _read(root, "include/constants/map_types.h")
    return {int(v): k for k, v in re.findall(r"#define\s+(MAP_TYPE_\w+)\s+(\d+)", text)}


def locate_maps(root: Path, rom: bytes, layouts: dict[str, list[int]]) -> list[dict]:
    """A MapHeader for every map folder: the one pointing at its layout with
    its layout id and map type. Maps alike in all three share one header
    offset - the generators read nothing else."""
    layout_ids = [e.get("id") for e in json.loads(_read(root, "data/layouts/layouts.json"))["layouts"]]
    types = {v: k for k, v in map_types(root).items()}
    groups = json.loads(_read(root, "data/maps/map_groups.json"))
    out = []
    for group in groups["group_order"]:
        for folder in groups[group]:
            mj = json.loads(_read(root, "data/maps/%s/map.json" % folder))
            layout = mj.get("layout")
            if layout not in layouts:
                continue
            want_id = layout_ids.index(layout) + 1
            want_type = types[mj["map_type"]]
            found = None
            for site in (s for copy in layouts[layout] for s in _pointer_sites(rom, copy)):
                if struct.unpack_from("<H", rom, site + 0x12)[0] == want_id and rom[site + 0x17] == want_type:
                    found = site
                    break
            if found is None:
                raise SystemExit("vtree_manifest: no map header for %s" % folder)
            out.append({"folder": folder, "id": mj["id"], "name": mj["name"], "rom": found})
    return out


def script_layouts(root: Path) -> dict[str, list[str]]:
    """The layouts a map's scripts switch it to (setmaplayoutindex)."""
    out = {}
    maps = root / "data" / "maps"
    for folder in sorted(os.listdir(maps)):
        path = maps / folder / "scripts.inc"
        if path.exists():
            found = re.findall(r"setmaplayoutindex\s+(LAYOUT_\w+)", path.read_text(encoding="utf-8"))
            if found:
                out[folder] = sorted(set(found))
    return out


def behaviours(root: Path) -> dict[str, int]:
    """The metatile behaviours the generators name."""
    text = _read(root, "include/constants/metatile_behaviors.h")
    out = {}
    for name in ("MB_CAVE_DOOR",):
        m = re.search(r"#define %s\s+(0x[0-9A-Fa-f]+|\d+)" % name, text)
        out[name] = int(m.group(1), 0)
    return out


def metadata(root: Path, rom: bytes) -> dict:
    layouts_off, tilesets, copies = locate_layouts(root, rom)
    layouts = json.loads(_read(root, "data/layouts/layouts.json"))
    meta: dict = {
        "metatiles_h": metatiles_h(root),
        "headers_h": headers_h(root),
        "graphics_h": graphics_h(root),
        "tilesets": tilesets,
        "layouts_table_label": layouts.get("layouts_table_label", "gMapLayouts"),
        "layouts": [],
        "map_types": {str(k): v for k, v in map_types(root).items()},
        "script_layouts": script_layouts(root),
        "behaviours": behaviours(root),
    }
    for entry in layouts["layouts"]:
        item = {"id": entry["id"]} if "id" in entry else {}
        if "name" in entry:
            item.update(name=entry["name"], blockdata_filepath=entry["blockdata_filepath"],
                        border_filepath=entry["border_filepath"], rom=layouts_off[entry["id"]])
        meta["layouts"].append(item)
    meta["maps"] = locate_maps(root, rom, copies)
    return meta
