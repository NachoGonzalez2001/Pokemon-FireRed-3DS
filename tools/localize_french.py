#!/usr/bin/env python3
"""Stage the BPRF localization from a user's clean French ROM.

The checked-in manifest (tools/locales/french.json.gz) contains source
positions, ROM offsets, symbol names and sizes - never game text or graphics.
Everything the French version needs is read from the player's own cartridge:
the dialogs, the menu and Pokedex texts, the latin fonts with their width
tables, and the 63 graphics whose pixels differ between the English and the
French ROM.

Run after tools/bootstrap.py applied the pinned source patches and before
`make -C 3ds_port`, because the staged files must be newer than the assets they
replace in the decomp's own generation rules.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))
from firered3ds_builder.rom import FRENCH_SHA1, load_rom
from firered3ds_builder.recipe import lz77_decompress

def encoded(data: bytes) -> str:
    return ",".join("0x%02X" % byte for byte in data)


def stage(tree: Path, rom_path: Path) -> None:
    manifest = json.loads(gzip.decompress((ROOT / "tools/locales/french.json.gz").read_bytes()))
    rom = load_rom(rom_path, supported=(FRENCH_SHA1,))
    if rom.sha1 != manifest["rom_sha1"] or rom.sha1 != FRENCH_SHA1:
        raise ValueError("This localization requires the clean French BPRF ROM")
    source = rom.data
    writes: dict[Path, bytes] = {}

    for relative, file in manifest["files"].items():
        path = tree / relative
        text = path.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != file["sha256"]:
            raise ValueError("Source differs from the pinned patched tree: " + relative)
        previous_end = 0
        for start, end, offset, size, kind in sorted(file["edits"]):
            if not previous_end <= start < end <= len(text) or not 0 <= offset < offset + size <= len(source):
                raise ValueError("Overlapping or out-of-range edit: " + relative)
            previous_end = end
        for start, end, offset, size, kind in sorted(file["edits"], reverse=True):
            data = source[offset:offset + size]
            if kind in ("c", "u8array"):
                replacement = "{" + encoded(data) + "}"
            elif kind == "asm":
                replacement = "\n\t.byte " + encoded(data) + "\n"
            else:
                raise ValueError("Unknown edit kind: " + kind)
            text = text[:start] + replacement + text[end:]
        writes[path] = text.encode()

    for relative, offset, size in manifest["graphics"]:
        if not 0 <= offset < offset + size <= len(source):
            raise ValueError("Graphic outside ROM: " + relative)
        writes[tree / relative] = source[offset:offset + size]
        if relative.endswith(".lz"):
            writes[tree / relative[:-3]] = lz77_decompress(source, offset)

    for path, data in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (tree / ".firered3ds-locale").write_text("BPRF experimental\n")
    skipped = ", ".join(item[0] for item in manifest["graphics_skipped"]) or "none"
    print("French game data staged (%d files, %d graphics); kept English: %s"
          % (len(manifest["files"]), len(manifest["graphics"]), skipped))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    args = parser.parse_args()
    stage(args.tree.resolve(), args.rom.resolve())


if __name__ == "__main__":
    main()
