#!/usr/bin/env python3
"""Give the game's objects another language's text before the link.

    python scripts/lang_patch_objects.py --overlay <overlay.json> build/root/src/*.o ...

A language build (tools/lang/build_lang.py) compiles the English game and then
replaces, object by object, the read-only data the language overlay names
("<object>|<section>": new bytes). Every game symbol sits in its own section
(-fdata-sections), so a string can grow or shrink: the link places it, and
every reference follows. Relocation sites keep the object's own bytes (the
addends), so tables of pointers stay as they were compiled.

Objects the overlay does not name are left untouched. Running it again with
the same overlay changes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def objcopy() -> str:
    exe = "arm-none-eabi-objcopy" + (".exe" if sys.platform == "win32" else "")
    for base in (os.environ.get("DEVKITARM", ""), "C:/devkitPro/devkitARM", "/opt/devkitpro/devkitARM"):
        if base and (Path(base) / "bin" / exe).is_file():
            return str(Path(base) / "bin" / exe)
    return exe


def sections(blob: bytes) -> dict[str, tuple[int, int, int, int]]:
    """name -> (type, offset, size, index) of an ELF32 little-endian object."""
    shoff, = struct.unpack_from("<I", blob, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", blob, 0x2E)
    heads = [struct.unpack_from("<IIIIIIIIII", blob, shoff + i * shentsize) for i in range(shnum)]
    strtab = heads[shstrndx]
    names = blob[strtab[4]:strtab[4] + strtab[5]]
    out = {}
    for i, h in enumerate(heads):
        name = names[h[0]:names.index(b"\0", h[0])].decode()
        out[name] = (h[1], h[4], h[5], i)
    return out


def reloc_sites(blob: bytes, secs: dict, name: str) -> list[int]:
    rel = secs.get(".rel" + name)
    if not rel:
        return []
    _, off, size, _ = rel
    return [struct.unpack_from("<I", blob, off + i)[0] for i in range(0, size, 8)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overlay", type=Path, required=True)
    ap.add_argument("objects", nargs="*", help="objects, or @file listing them (space separated)")
    args = ap.parse_args()
    objects: list[Path] = []
    for arg in args.objects:
        if arg.startswith("@"):
            objects += [Path(p) for p in Path(arg[1:]).read_text(encoding="utf-8").split()]
        else:
            objects.append(Path(arg))
    args.objects = objects

    overlay = json.loads(args.overlay.read_text(encoding="utf-8"))["c"]
    by_object: dict[str, dict[str, bytes]] = {}
    for key, value in overlay.items():
        obj, sec = key.split("|", 1)
        by_object.setdefault(obj.replace("\\", "/"), {})[sec] = bytes.fromhex(value)

    patched = sections_done = 0
    with tempfile.TemporaryDirectory() as tmp:
        for path in args.objects:
            wanted = by_object.get(path.as_posix())
            if not wanted:
                continue
            blob = path.read_bytes()
            secs = sections(blob)
            updates = []
            for n, (sec, new) in enumerate(sorted(wanted.items())):
                if sec not in secs:
                    raise SystemExit("lang_patch_objects: %s has no section %s" % (path, sec))
                _, off, size, _ = secs[sec]
                old = blob[off:off + size]
                buf = bytearray(new)
                for site in reloc_sites(blob, secs, sec):
                    if site + 4 > len(buf):
                        raise SystemExit("lang_patch_objects: %s %s: a relocation past the new size"
                                         % (path, sec))
                    buf[site:site + 4] = old[site:site + 4]
                if bytes(buf) == old:
                    continue
                data = Path(tmp) / ("%d.bin" % n)
                data.write_bytes(bytes(buf))
                updates += ["--update-section", "%s=%s" % (sec, data)]
                sections_done += 1
            # A few dozen sections per run: Windows caps a command line at 32 KiB.
            for i in range(0, len(updates), 80):
                subprocess.check_call([objcopy()] + updates[i:i + 80] + [str(path)])
            if updates:
                patched += 1
    print("lang_patch_objects: %d sections in %d objects" % (sections_done, patched))


if __name__ == "__main__":
    main()
