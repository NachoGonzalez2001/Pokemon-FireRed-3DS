#!/usr/bin/env python3
"""Move the game's linked read-only data out of the executable.

The linker script (emerald3ds.ld.in) gathers the .rodata of every game
translation unit into one output section, .gamedata. The build links twice
with the same objects and the same layout: once with the section's contents
(the image, build/gamedata_image.elf) and once with the section reserved as
NOLOAD (the shipped executable). This script checks that both links placed
every symbol at the same address, then takes the section's bytes and its
relocation sites from the image and writes the bundle the console loads into
the reserved region before AgbMain (3ds_port/src/3ds_script_loader.c):

  romfs/gamedata/gamedata.bin   the payload (game data)
  romfs/gamedata/gamedata.rel   header and relocation sites (engine file)

The payload uses the same position-independent encoding as the script and
song bundles (scripts/ctr_bundle.py): pointers into the region are stored as
region-relative offsets, pointers elsewhere as link-time addresses.
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctr_bundle import HEADER, REFERENCE_SYMBOL, VERSION, elf_symbols, tool  # noqa: E402

MAGIC = b"C3GD"
SECTION = ".gamedata"


def sections(elf: Path) -> dict[str, tuple[str, int, int, int]]:
    out = subprocess.check_output([tool("arm-none-eabi-readelf"), "-S", "-W", str(elf)], text=True)
    found = {}
    for line in out.splitlines():
        m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", line)
        if m:
            found[m.group(1)] = (m.group(2), int(m.group(3), 16), int(m.group(4), 16), int(m.group(5), 16))
    return found


def global_symbols(elf: Path) -> dict[str, int]:
    """Global symbols by name. Local labels are not compared: the NOLOAD link
    does not keep every local label of a section without contents."""
    out = subprocess.check_output([tool("arm-none-eabi-nm"), "--defined-only", str(elf)],
                                  text=True, errors="ignore")
    result = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].isupper():
            result[parts[2]] = int(parts[0], 16)
    return result


def relocations(elf: Path, section: str) -> list[tuple[int, str]]:
    out = subprocess.check_output([tool("arm-none-eabi-readelf"), "-r", "-W", str(elf)],
                                  text=True, errors="ignore")
    found = []
    inside = False
    for line in out.splitlines():
        if line.startswith("Relocation section"):
            inside = ("'.rel%s'" % section) in line
            continue
        if not inside:
            continue
        m = re.match(r"^([0-9a-f]{8})\s+[0-9a-f]+\s+(R_ARM_\w+)", line)
        if m:
            found.append((int(m.group(1), 16), m.group(2)))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", type=Path, required=True, help="link with the section's contents")
    ap.add_argument("--elf", type=Path, required=True, help="shipped link, section NOLOAD")
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    img_secs = sections(args.image)
    elf_secs = sections(args.elf)
    if SECTION not in img_secs or SECTION not in elf_secs:
        raise SystemExit("gen_gamedata_bundle: %s missing from a link" % SECTION)
    kind, start, offset, size = img_secs[SECTION]
    if kind != "PROGBITS" or elf_secs[SECTION][0] != "NOBITS":
        raise SystemExit("gen_gamedata_bundle: expected PROGBITS in the image and NOBITS in the executable")
    if (start, size) != (elf_secs[SECTION][1], elf_secs[SECTION][3]):
        raise SystemExit("gen_gamedata_bundle: %s differs between the two links" % SECTION)
    a, b = global_symbols(args.image), global_symbols(args.elf)
    diff = sorted(name for name in set(a) | set(b) if a.get(name) != b.get(name))
    if diff:
        raise SystemExit("gen_gamedata_bundle: the two links disagree on %d global symbols, e.g. %s"
                         % (len(diff), diff[:10]))

    blob = args.image.read_bytes()
    payload = bytearray(blob[offset:offset + size])
    end = start + size
    internal, external = [], []
    unknown = {}
    for site, kind in relocations(args.image, SECTION):
        rel = site - start
        if kind in ("R_ARM_ABS32", "R_ARM_TARGET1"):
            value = struct.unpack_from("<I", payload, rel)[0]
            if start <= value <= end:
                struct.pack_into("<I", payload, rel, value - start)
                internal.append(rel)
            else:
                external.append(rel)
        else:
            unknown[kind] = unknown.get(kind, 0) + 1
    if unknown:
        raise SystemExit("gen_gamedata_bundle: unsupported relocation types %s" % unknown)

    symbols = elf_symbols(args.elf)
    if REFERENCE_SYMBOL not in symbols:
        raise SystemExit("gen_gamedata_bundle: %s not found" % REFERENCE_SYMBOL)
    internal.sort()
    external.sort()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "gamedata.bin").write_bytes(payload)
    with (args.out_dir / "gamedata.rel").open("wb") as f:
        f.write(HEADER.pack(MAGIC, VERSION, len(payload), symbols[REFERENCE_SYMBOL],
                            len(internal), len(external)))
        f.write(b"".join(struct.pack("<I", x) for x in internal))
        f.write(b"".join(struct.pack("<I", x) for x in external))
    print("gen_gamedata_bundle: payload=%d bytes, internal=%d, external=%d, region at %08X"
          % (len(payload), len(internal), len(external), start))


if __name__ == "__main__":
    main()
