#!/usr/bin/env python3
"""Move the GBA script sections out of the 3DS executable and into RomFS.

The reason is the executable format: `script_data` interleaves bytecode with 32-bit pointers, so
its relocations land on unaligned addresses and `3dsxtool` rejects them outright
("Unaligned relocation!").

ctr_bundle.py holds the mechanism, which the song data shares. This file is the
script half of it: which objects, which section, and the keep table the scripts
need because nothing in the executable calls their handlers any more.

Outputs (consumed by 3ds_port/src/3ds_script_loader.c):
  build/3ds_script_blob.s   the reserved region and its symbols
  build/3ds_script_keep.s   a GC root for every handler the scripts call
  romfs/scripts/scripts.bin the payload
  romfs/scripts/scripts.rel the header and relocation sites
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ctr_bundle import Bundle

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "3ds_port"

# Every object whose script_data carries unaligned relocations.
SCRIPT_OBJECTS = [
    "data/battle_ai_scripts.o",
    "data/battle_anim_scripts.o",
    "data/battle_scripts_1.o",
    "data/battle_scripts_2.o",
    "data/contest_ai_scripts.o",
    "data/event_scripts.o",
    "data/field_effect_scripts.o",
]

BUNDLE = Bundle(tag="gen_script_bundle", magic=b"C3SB", section="script_data",
                blob_symbol="__ctr_script_blob",
                payload_name="scripts.bin", reloc_name="scripts.rel")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-dir", default=str(PORT))
    parser.add_argument("--build-dir", default=None, help="directory holding data/*.o")
    parser.add_argument("--elf", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--blob", action="store_true", help="emit the reserved region")
    parser.add_argument("--bundle", action="store_true", help="emit the RomFS payload")
    args = parser.parse_args()

    port = Path(args.port_dir).resolve()
    build_dir = Path(args.build_dir).resolve() if args.build_dir else port / "build" / "root"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else port / "romfs" / "scripts"
    elf = Path(args.elf).resolve() if args.elf else port / "emerald3ds.elf"
    tmp = port / "build" / "scripts.tmp"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    if not (args.blob or args.bundle):
        parser.error("choose --blob and/or --bundle")

    objects = [build_dir / rel for rel in SCRIPT_OBJECTS]
    sections, offsets, size = BUNDLE.load(objects, tmp)
    if args.blob:
        BUNDLE.write_blob_asm(offsets, size, port / "build" / "3ds_script_blob.s")
        BUNDLE.write_keep_asm(sections, offsets, port / "build" / "3ds_script_keep.s",
                              "__ctr_script_keep")
    if args.bundle:
        BUNDLE.write_bundle(sections, offsets, size, elf, out_dir)


if __name__ == "__main__":
    main()
