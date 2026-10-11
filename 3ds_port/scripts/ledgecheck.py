"""Ledges and berry soil compared between two relief.bin files: their
lattices, over each map's base, and their cut records must be the same.

    python ledgecheck.py OLD.bin NEW.bin [LAYOUT ...]"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reliefbin  # noqa: E402
import voxel_cells as vc  # noqa: E402
import gen_voxel_relief as g  # noqa: E402


def main():
    old, oc = reliefbin.load(sys.argv[1])
    new, nc = reliefbin.load(sys.argv[2])
    L = json.load(open(os.path.join(g.vb.ROOT, "data", "layouts", "layouts.json"), encoding="utf-8"))["layouts"]
    names = sys.argv[3:] or [L[i - 1]["id"] for i in sorted(set(old) | set(new))]
    berry = vc.behaviours()["MB_BERRY_TREE_SOIL"]
    total = bad = 0
    for name in names:
        idx = [e["id"] for e in L].index(name) + 1
        lay = g.open_roles(name)
        art = g.vb.LayoutArt(name)
        cells = set(g.ledge_cells(lay)) | {(x, y) for y in range(lay.h) for x in range(lay.w)
                                          if lay.behaviour(x, y) == berry or art.metatile(x, y) in g.DIRT}
        o, n = old.get(idx, {}), new.get(idx, {})

        def rel(t, c):
            v = t.get("grids", {}).get(c)
            return None if v is None else [[x + t.get("base", 0) for x in r] for r in v]
        def rec(t, c):
            r = t.get((idx,) + c)
            return None if r is None else {k: v for k, v in r.items() if k != "variant"}
        diff = sorted(c for c in cells if rel(o, c) != rel(n, c) or rec(oc, c) != rec(nc, c))
        total += len(cells)
        bad += len(diff)
        if diff:
            print("%-32s %d of %d differ %s" % (name, len(diff), len(cells), diff[:8]))
    print("ledge/berry cells %d, differ %d" % (total, bad))


main()
