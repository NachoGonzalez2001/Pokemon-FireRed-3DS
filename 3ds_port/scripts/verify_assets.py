#!/usr/bin/env python3
"""Validate the generated RomFS resource index before it is packed.

A wrong index does not fail the build: it makes the game read one asset as
another, which is the class of bug this check exists to make impossible to ship
silently. Every row is verified against the file it names.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

PORT = Path(__file__).resolve().parents[1]
ROW = struct.Struct("<III")


def fail(problems: list[str], message: str) -> None:
    problems.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fs-dir", default=str(PORT / "romfs"))
    parser.add_argument("--max-report", type=int, default=10)
    args = parser.parse_args()

    fs = Path(args.fs_dir).resolve()
    index_path = fs / "assets" / "asset_index.bin"
    map_path = fs / "assets" / "asset_map.txt"
    ptr_path = fs / "assets" / "asset_ptr_index.bin"
    problems: list[str] = []

    if not index_path.exists() or not map_path.exists():
        print(f"verify_assets: missing {index_path.name}/{map_path.name}", file=sys.stderr)
        return 1

    raw = index_path.read_bytes()
    blob = map_path.read_bytes()
    if len(raw) % ROW.size:
        print("verify_assets: asset_index.bin is not a whole number of rows", file=sys.stderr)
        return 1

    rows = [ROW.unpack_from(raw, off) for off in range(0, len(raw), ROW.size)]
    addresses = [row[0] for row in rows]
    if addresses != sorted(addresses):
        fail(problems, "asset_index.bin is not sorted by address; binary search would miss rows")
    # Two symbols can share an address when the linker places equal-sized stubs
    # of unreferenced data together. The lookup then picks either row, which is
    # only harmless while both rows describe the same number of bytes.
    by_address: dict[int, set[int]] = {}
    for addr, size, _ in rows:
        by_address.setdefault(addr, set()).add(size)
    warnings = 0
    for addr, sizes in by_address.items():
        if len(sizes) == 1:
            warnings += 1 if addresses.count(addr) > 1 else 0
        else:
            fail(problems, f"{addr:08X}: shared by assets of different sizes {sorted(sizes)}")
    if warnings:
        print(f"verify_assets: {warnings} address(es) shared by equal-sized assets")

    checked = 0
    for addr, size, path_offset in rows:
        if path_offset >= len(blob):
            fail(problems, f"{addr:08X}: path offset {path_offset} outside asset_map.txt")
            continue
        end = blob.find(b"\n", path_offset)
        uri = blob[path_offset:end if end >= 0 else len(blob)].decode("ascii", "replace").strip()
        if not uri or uri.startswith("/") or ":" in uri or ".." in uri.split("/"):
            fail(problems, f"{addr:08X}: path '{uri}' is not a relative data path")
            continue
        target = fs / uri
        if not target.exists():
            fail(problems, f"{addr:08X}: missing payload {uri}")
            continue
        actual = target.stat().st_size
        if actual != size:
            fail(problems, f"{addr:08X}: {uri} is {actual} bytes, index says {size}")
            continue
        checked += 1

    pointer_rows = 0
    if ptr_path.exists():
        praw = ptr_path.read_bytes()
        if len(praw) % ROW.size:
            fail(problems, "asset_ptr_index.bin is not a whole number of rows")
        else:
            prows = [ROW.unpack_from(praw, off) for off in range(0, len(praw), ROW.size)]
            pointer_rows = len(prows)
            if [p[0] for p in prows] != sorted(p[0] for p in prows):
                fail(problems, "asset_ptr_index.bin is not sorted by pointer")
            known = set(addresses)
            index_by_addr = {row[0]: row[1] for row in rows}
            for ptr, base, offset in prows:
                if base not in known:
                    fail(problems, f"pointer {ptr:08X} refers to unknown base {base:08X}")
                elif offset >= index_by_addr[base]:
                    fail(problems, f"pointer {ptr:08X}: offset {offset} outside its {index_by_addr[base]}-byte asset")

    print(f"verify_assets: {checked}/{len(rows)} assets verified, {pointer_rows} pointer rows")
    if problems:
        print(f"verify_assets: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems[: args.max_report]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
