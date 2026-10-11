import re, pathlib, collections
root = pathlib.Path(r"C:\fr3ds\upstream\src")
syms = set()
for p in list(root.rglob("*.c")) + list(root.rglob("*.h")):
    t = p.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(r"(\w+)\s*(?:\[[^\]]*\])+\s*=\s*INCBIN_[US]\d+\s*\(", t):
        syms.add(m.group(1))
print("INCBIN symbols:", len(syms))
uses = collections.Counter()
calls = collections.Counter()
for p in root.rglob("*.c"):
    t = p.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(r"sizeof\s*\(\s*(\w+)\s*\)", t):
        if m.group(1) in syms:
            uses[p.name] += 1
            # the call this sizeof sits in
            line_start = t.rfind("\n", 0, m.start()) + 1
            line = t[line_start:t.find("\n", m.end())]
            c = re.search(r"(\w+)\s*\(", line)
            calls[c.group(1) if c else "?"] += 1
print("sizeof(INCBIN) uses:", sum(uses.values()), "in", len(uses), "files")
print("by call:", calls.most_common(15))
