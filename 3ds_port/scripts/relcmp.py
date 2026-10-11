"""Which layouts two relief.bin files differ in (variants by content)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reliefbin
a, ac = reliefbin.load(sys.argv[1]); b, bc = reliefbin.load(sys.argv[2])
L = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "data", "layouts", "layouts.json")))["layouts"]
strip = lambda d: {k: v for k, v in d.items() if k != "variant"}
for idx in sorted(set(a) | set(b)):
    ga, gb = a.get(idx, {}), b.get(idx, {})
    ca = {k: strip(v) for k, v in ac.items() if k[0] == idx}
    cb = {k: strip(v) for k, v in bc.items() if k[0] == idx}
    if ga.get("grids") != gb.get("grids") or ga.get("base") != gb.get("base") or ca != cb:
        dg = sum(1 for c in set(ga.get("grids", {})) | set(gb.get("grids", {}))
                 if ga.get("grids", {}).get(c) != gb.get("grids", {}).get(c))
        dc = sum(1 for c in set(ca) | set(cb) if ca.get(c) != cb.get(c))
        print("changed %-36s grids %d, cut records %d" % (L[idx - 1]["id"], dg, dc))
