"""Resolve merge-file conflict blocks by keeping the first (port) side."""
import re
import sys

for path in sys.argv[1:]:
    t = open(path, encoding="utf-8", errors="surrogateescape").read()
    t, n = re.subn(r"<<<<<<< [^\n]*\n(.*?)=======\n.*?>>>>>>> [^\n]*\n", r"\1", t, flags=re.S)
    open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n").write(t)
    print(path, n, "resolved")
