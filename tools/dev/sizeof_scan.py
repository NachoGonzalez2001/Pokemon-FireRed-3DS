"""List sizeof() uses on INCBIN arrays (one-element stubs in the 3DS build).

    python tools/dev/sizeof_scan.py [--all]

Without --all, LoadPalette calls are left out (palette.c resolves those).
"""
import pathlib
import re
import sys

root = pathlib.Path(r"C:\fr3ds\upstream\src")
syms = set()
for p in list(root.rglob("*.c")) + list(root.rglob("*.h")):
    t = p.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(r"(\w+)\s*(?:\[[^\]]*\])+\s*=\s*INCBIN_[US]\d+\s*\(", t):
        syms.add(m.group(1))
show_all = "--all" in sys.argv
count = 0
for p in sorted(root.rglob("*.c")):
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    for i, line in enumerate(lines, 1):
        for m in re.finditer(r"sizeof\s*\(\s*(\w+)\s*\)", line):
            if m.group(1) not in syms:
                continue
            if not show_all and "LoadPalette" in line:
                continue
            count += 1
            print("%s:%d: %s" % (p.name, i, line.strip()))
print("total:", count)
