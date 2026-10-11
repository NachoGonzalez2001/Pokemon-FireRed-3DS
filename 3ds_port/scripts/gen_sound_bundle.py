#!/usr/bin/env python3
"""Move the MP2K song data out of the 3DS executable and into RomFS.

A song is a byte stream of MP2K commands, and one of those commands (PATT, the
pattern call) carries a 32-bit pointer to another point in the same stream. The
pointer lands wherever the preceding commands leave it, so about nine hundred
relocations per song are unaligned and 3dsxtool refuses the whole image. This
is the same problem the scripts have, and it takes the same answer: the region
is reserved in .bss with every song symbol at its real offset, so gSongTable in
data/sound_data.s already points at the right addresses, and the loader fills
it from RomFS before AgbMain runs.

Only the songs move. The voice groups, the key-split and cry tables and the
samples themselves have no pointers inside byte streams, so their relocations
are all aligned and data/sound_data.s stays linked where m4a can read it.

No keep table is needed here, unlike the scripts: everything a song refers to
is a voice group, and gSongTable and the voice groups are all reachable from
the executable already.

Outputs (consumed by 3ds_port/src/3ds_script_loader.c):
  build/3ds_song_blob.s    the reserved region and its song symbols
  romfs/sound/songs.bin    the payload
  romfs/sound/songs.rel    the header and relocation sites
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ctr_bundle import Bundle

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "3ds_port"

BUNDLE = Bundle(tag="gen_sound_bundle", magic=b"C3AB", section=".rodata",
                blob_symbol="__ctr_song_blob",
                payload_name="songs.bin", reloc_name="songs.rel")


def song_objects(build_dir: Path) -> list[Path]:
    songs = build_dir / "sound" / "songs"
    # Sorted so the payload is reproducible: the layout is decided here and the
    # blob the executable reserves has to match it byte for byte.
    found = sorted(songs.glob("*.o")) + sorted((songs / "midi").glob("*.o"))
    if not found:
        raise SystemExit("gen_sound_bundle: no song objects under %s" % songs)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-dir", default=str(PORT))
    parser.add_argument("--build-dir", default=None, help="directory holding sound/songs/*.o")
    parser.add_argument("--elf", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--blob", action="store_true", help="emit the reserved region")
    parser.add_argument("--bundle", action="store_true", help="emit the RomFS payload")
    args = parser.parse_args()

    port = Path(args.port_dir).resolve()
    build_dir = Path(args.build_dir).resolve() if args.build_dir else port / "build" / "root"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else port / "romfs" / "sound"
    elf = Path(args.elf).resolve() if args.elf else port / "emerald3ds.elf"
    tmp = port / "build" / "songs.tmp"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    if not (args.blob or args.bundle):
        parser.error("choose --blob and/or --bundle")

    sections, offsets, size = BUNDLE.load(song_objects(build_dir), tmp)
    if args.blob:
        BUNDLE.write_blob_asm(offsets, size, port / "build" / "3ds_song_blob.s")
    if args.bundle:
        BUNDLE.write_bundle(sections, offsets, size, elf, out_dir)


if __name__ == "__main__":
    main()
