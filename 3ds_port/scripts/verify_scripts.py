#!/usr/bin/env python3
"""Check an externalised bundle against the executable that will load it.

A wrong entry here does not fail the build: it makes the game run bytes that are
not opcodes, which is the hardest failure to diagnose. Every
relocation site and every target is therefore verified before packing.

The song bundle is built the same way and checked by the same code; the
defaults below are the script one, and the options name the other.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path

PORT = Path(__file__).resolve().parents[1]
HEADER = struct.Struct("<4sIIIII")
VERSION = 1


def tool(name: str) -> str:
    devkitarm = os.environ.get("DEVKITARM", "/opt/devkitpro/devkitARM")
    for candidate in (Path(devkitarm) / "bin" / name, Path(devkitarm) / "bin" / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return name


def elf_symbols(elf: Path) -> dict[str, int]:
    out = subprocess.check_output([tool("arm-none-eabi-readelf"), "--wide", "--symbols", str(elf)],
                                  text=True, errors="ignore")
    symbols: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        # "Num: Value Size Type Bind Vis Ndx Name"; the header row also ends
        # its first field with a colon, so the address has to parse as hex.
        if len(parts) < 8 or not parts[0].endswith(":") or parts[6] == "UND":
            continue
        try:
            address = int(parts[1], 16)
        except ValueError:
            continue
        symbols[parts[7]] = address
    return symbols


def loaded_range(elf: Path) -> tuple[int, int]:
    out = subprocess.check_output([tool("arm-none-eabi-readelf"), "--wide", "--segments", str(elf)],
                                  text=True, errors="ignore")
    low, high = None, 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[0] != "LOAD":
            continue
        start = int(parts[2], 16)
        size = int(parts[5], 16)
        low = start if low is None else min(low, start)
        high = max(high, start + size)
    if low is None:
        raise SystemExit("verify bundle: the executable has no loadable segments")
    return low, high


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", default=str(PORT / "emerald3ds.elf"))
    parser.add_argument("--out-dir", default=str(PORT / "romfs" / "scripts"))
    parser.add_argument("--tag", default="verify_scripts")
    parser.add_argument("--magic", default="C3SB")
    parser.add_argument("--payload", default="scripts.bin")
    parser.add_argument("--reloc", default="scripts.rel")
    parser.add_argument("--blob-symbol", default="__ctr_script_blob")
    parser.add_argument("--require", action="append", default=None,
                        help="symbol that must sit word aligned inside the region")
    args = parser.parse_args()

    tag = args.tag
    wanted_magic = args.magic.encode("ascii")
    required = args.require
    if required is None:
        required = ["gScriptCmdTable", "gSpecials", "gSpecialVars", "gStdScripts"]

    elf = Path(args.elf)
    out = Path(args.out_dir)
    payload = (out / args.payload).read_bytes()
    relocs = (out / args.reloc).read_bytes()
    symbols = elf_symbols(elf)
    problems: list[str] = []

    magic, version, size, reference, internal, external = HEADER.unpack_from(relocs, 0)
    if magic != wanted_magic or version != VERSION:
        print("%s: unknown bundle format" % tag, file=sys.stderr)
        return 1
    if size != len(payload):
        problems.append(f"header says {size} payload bytes, file has {len(payload)}")
    expected = HEADER.size + 4 * (internal + external)
    if len(relocs) != expected:
        problems.append(f"relocation table is {len(relocs)} bytes, expected {expected}")

    start = symbols.get(args.blob_symbol)
    end = symbols.get(args.blob_symbol + "_end")
    if start is None or end is None:
        problems.append("the executable does not reserve " + args.blob_symbol)
    elif end - start != len(payload):
        problems.append(f"reserved region is {end - start} bytes, payload is {len(payload)}")

    if symbols.get("AgbMain") != reference:
        problems.append("the recorded reference address is not AgbMain's; rebasing would be wrong")

    low, high = loaded_range(elf)
    sites = struct.unpack_from(f"<{internal + external}I", relocs, HEADER.size)
    bad_site = bad_internal = bad_external = 0
    for index, site in enumerate(sites):
        if site + 4 > len(payload):
            bad_site += 1
            continue
        target = struct.unpack_from("<I", payload, site)[0]
        if index < internal:
            if target >= len(payload):
                bad_internal += 1
        elif not (low <= target < high):
            bad_external += 1
    if bad_site:
        problems.append(f"{bad_site} relocation site(s) outside the payload")
    if bad_internal:
        problems.append(f"{bad_internal} internal target(s) outside the payload")
    if bad_external:
        problems.append(f"{bad_external} external target(s) outside the loaded image")

    # The tables the engine dereferences immediately must be inside the region
    # and word aligned, or the first dispatch reads nonsense.
    for name in required:
        address = symbols.get(name)
        if address is None:
            problems.append(f"{name} is not defined")
        elif start is not None and not (start <= address < end):
            problems.append(f"{name} is outside the reserved region")
        elif address % 4:
            problems.append(f"{name} is not word aligned")

    print(f"{tag}: {len(payload)} bytes, {internal} internal + {external} external "
          f"relocations verified")
    if problems:
        print(f"{tag}: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems[:10]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
