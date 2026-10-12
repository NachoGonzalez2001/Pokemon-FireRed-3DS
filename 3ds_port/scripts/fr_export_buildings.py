#!/usr/bin/env python3
"""Write FireRed's buildings.bin: the models of fr_building_specs, placed
wherever their drawing appears, in the Emerald port's VXB7 format.

    python fr_export_buildings.py --output romfs/voxel/buildings.bin

The models and their proofs are fr_gen_buildings'; the export and the search
for placements are gen_voxel_buildings', which reads FireRed's layouts through
voxel_building (fr_art).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fr_gen_buildings  # noqa: E402
import gen_voxel_buildings as gvb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--only")
    args = ap.parse_args()
    models = fr_gen_buildings.build_models(args.only)
    for m in models:
        # what gen_voxel_buildings.build_models sets: every cell of the
        # rectangle is the model's unless its spec says otherwise
        w, h = m.spec["rect"][2], m.spec["rect"][3]
        if not hasattr(m, "owned"):
            m.owned = m.spec.get("owned") or {(i, j) for i in range(w) for j in range(h)}
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    gvb.export(models, args.output)
    print("wrote", args.output, "with", len(models), "models")


if __name__ == "__main__":
    main()
