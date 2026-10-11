#!/usr/bin/env python3

"""Run mapjson for every map whose header/events/connections includes are missing."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAPS_DIR = ROOT / "data" / "maps"
LAYOUTS_JSON = ROOT / "data" / "layouts" / "layouts.json"
MAPJSON = ROOT / "tools" / "mapjson" / ("mapjson.exe" if os.name == "nt" else "mapjson")


def main() -> None:
    if not MAPJSON.exists():
        raise SystemExit(f"mapjson tool not found: {MAPJSON}")

    generated = 0
    for map_json in sorted(MAPS_DIR.glob("*/map.json")):
        out_dir = map_json.parent
        needed = [
            out_dir / "header.inc",
            out_dir / "events.inc",
            out_dir / "connections.inc",
        ]

        if all(p.exists() for p in needed):
            continue

        subprocess.check_call(
            [
                str(MAPJSON),
                "map",
                "emerald",
                str(map_json),
                str(LAYOUTS_JSON),
                str(out_dir),
            ]
        )
        generated += 1

    print(f"gen_missing_map_includes: generated {generated} map include set(s)")


if __name__ == "__main__":
    main()
