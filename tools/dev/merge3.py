"""3-way merge Emerald-port changes into FireRed files.

usage: merge3.py <emerald_ref_root> <emerald_patch> <fr_tree> <relpath>...

For each relpath: base = pokeemerald original, ours = base + the Emerald port
patch hunks for that file, theirs = FireRed's committed version (BOM removed).
The merged result (with conflict markers if any) is written into fr_tree.
"""
import os
import re
import subprocess
import sys
import tempfile

ref, patch, tree = sys.argv[1:4]
files = sys.argv[4:]
text = open(patch, encoding="utf-8", errors="surrogateescape").read()
chunks = re.split(r"(?m)^(?=diff --git )", text)


def git(*a, cwd=None, inp=None):
    return subprocess.run(["git", "-c", "core.autocrlf=false", *a], cwd=cwd, input=inp,
                          capture_output=True)


for rel in files:
    chunk = next((c for c in chunks if c.startswith("diff --git a/%s b/" % rel)), None)
    if chunk is None:
        print("%s: no hunks in patch" % rel)
        continue
    with tempfile.TemporaryDirectory() as td:
        base = open(os.path.join(ref, rel), "rb").read().replace(b"\r\n", b"\n")
        os.makedirs(os.path.join(td, os.path.dirname(rel)), exist_ok=True)
        open(os.path.join(td, rel), "wb").write(base)
        git("init", "-q", cwd=td)
        r = git("apply", "--whitespace=nowarn", "-", cwd=td,
                inp=chunk.encode("utf-8", "surrogateescape"))
        if r.returncode:
            print("%s: patch does not apply to the Emerald base: %s" % (rel, r.stderr.decode()[:300]))
            continue
        ours = os.path.join(td, rel)
        basef = os.path.join(td, "base.tmp")
        open(basef, "wb").write(base)
        theirs = git("show", "HEAD:" + rel, cwd=tree).stdout
        if theirs.startswith(b"\xef\xbb\xbf"):
            theirs = theirs[3:]
        theirsf = os.path.join(td, "theirs.tmp")
        open(theirsf, "wb").write(theirs.replace(b"\r\n", b"\n"))
        # merge-file writes into its first argument
        r = subprocess.run(["git", "merge-file", "-L", "emerald-port", "-L", "emerald", "-L", "firered",
                            ours, basef, theirsf], capture_output=True)
        out = open(ours, "rb").read()
        open(os.path.join(tree, rel), "wb").write(out)
        print("%s: %s" % (rel, "clean" if r.returncode == 0 else "%d conflict(s)" % r.returncode))
