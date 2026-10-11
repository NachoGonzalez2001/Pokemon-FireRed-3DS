"""List VBlank/HBlank callbacks that read through a pointer their file frees.

A screen frees its data (FREE_AND_SET_NULL, Free) while its blanking callback
is still installed until the next screen sets its own; the callback then reads
through NULL. On the GBA that lands in the BIOS; on the 3DS it faults.

usage: python blank_uaf_scan.py [tree]
"""
import re
import sys
from pathlib import Path

tree = Path(sys.argv[1] if len(sys.argv) > 1 else "C:/fr3ds/upstream")
func = re.compile(r"(?m)^(?:static\s+)?void\s+(\w*(?:VBlank|HBlank|VBlankCB|HBlankCB)\w*)\s*\(void\)\s*\n\{")
freed = re.compile(r"(?:FREE_AND_SET_NULL(?:_IF_SET)?|FREE_IF_NOT_NULL|Free)\(\s*(s\w+|g\w+)\s*\)")
deref = re.compile(r"\b(s\w+|g\w+)->")


def body(text, start):
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return text[i:]


callees_cache = {}
for f in sorted((tree / "src").glob("*.c")):
    t = f.read_text(encoding="utf-8", errors="replace")
    frees = set(freed.findall(t))
    if not frees:
        continue
    funcs = {m.group(1): m.start() for m in func.finditer(t)}
    for name, start in funcs.items():
        b = body(t, start)
        hits = sorted(set(deref.findall(b)) & frees)
        # one level of static helpers called from the callback
        for callee in re.findall(r"\b(\w+)\s*\(\s*\)\s*;", b):
            m = re.search(r"(?m)^static\s+\w+\s+%s\s*\(void\)\s*\n\{" % re.escape(callee), t)
            if m:
                hits += sorted(set(deref.findall(body(t, m.start()))) & frees)
        if hits and "SetVBlankCallback(NULL)" not in b:
            print(f"{f.name}: {name} reads {', '.join(sorted(set(hits)))}")
