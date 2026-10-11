"""Seams between a cell and the one south of it that rise southward with
nothing under them: the camera sees through the step (a black dash).

    python cracks.py relief.bin [layout index]"""
import sys
import reliefbin


def cracks(path, only=None):
    L, C = reliefbin.load(path)
    out = []
    for lid, d in L.items():
        if only and lid != only:
            continue
        g = d["grids"]
        for (x, y), a in g.items():
            b = g.get((x, y + 1))
            if b is None:
                continue
            rise = max(b[0][i] - a[4][i] for i in range(5))
            covered = (lid, x, y + 1) in C and C[(lid, x, y + 1)]["variant"] == 0xFFFF
            if rise > 0.5 and not covered:
                out.append((lid, x, y, rise))
    return out


if __name__ == "__main__":
    found = cracks(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
    print(len(found), "open steps", found[:30])
