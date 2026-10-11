"""List interior pointers into INCBIN assets: `&ASSET[i]`, `ASSET[i]` and
`ASSET + n` uses outside the INCBIN definition itself.

In the port an INCBIN is a 4-byte stub resolved at runtime; an offset applied
to the stub lands in unrelated memory. Each hit must resolve the base first
(PORT_RES(ASSET)[i]) or carry the offset some other way.

usage: python interior_scan.py [tree]   (default C:/fr3ds/upstream)
"""
import re
import sys
from pathlib import Path

tree = Path(sys.argv[1] if len(sys.argv) > 1 else "C:/fr3ds/upstream")
files = sorted((tree / "src").rglob("*.c")) + sorted((tree / "src").rglob("*.h"))
files += sorted((tree / "include").rglob("*.h"))

decl = re.compile(r"\b(\w+)\s*\[[^\]]*\]\s*=\s*INCBIN_\w+\s*\(")
names = set()
texts = {}
for f in files:
    t = f.read_text(encoding="utf-8", errors="replace")
    texts[f] = t
    names.update(decl.findall(t))

ident = re.compile(r"\b[A-Za-z_]\w*\b")
after = re.compile(r"\s*(\[|\+\s*[\w(])")
hits = 0
for f, t in texts.items():
    for no, line in enumerate(t.splitlines(), 1):
        if "INCBIN_" in line or "PORT_RES(" in line or line.lstrip().startswith("extern"):
            continue
        for m in ident.finditer(line):
            if m.group() in names and after.match(line, m.end()):
                hits += 1
                print(f"{f.relative_to(tree).as_posix()}:{no}: {line.strip()[:150]}")
                break
print(f"{len(names)} INCBIN assets, {hits} interior uses", file=sys.stderr)
