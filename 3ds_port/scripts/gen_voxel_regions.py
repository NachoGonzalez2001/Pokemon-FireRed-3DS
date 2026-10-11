#!/usr/bin/env python3
"""What every cell of every layout is, for the console's signposts.

The roles come from voxel_cells.py. The console only reads them to find
signposts; the rest are kept so that a layout's classification can be
inspected in one file.

OUTPUT  romfs/voxel/regions.bin
"""

import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voxel_cells  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PORT = os.path.join(ROOT, "3ds_port")


def load_roles_enum(header):
    """VOXEL_ROLE_* from voxel_regions.h, so the two never drift apart."""
    text = open(header, encoding="utf-8").read()
    out = {}
    for name, value in re.findall(r"#define\s+VOXEL_ROLE_(\w+)\s+(\d+)", text):
        if name != "COUNT":
            out[name.lower()] = int(value)
    if not out:
        raise SystemExit("gen_voxel_regions: no VOXEL_ROLE_* in %s" % header)
    return out


def roles_of(layout, roles_enum):
    """The role of every cell of the layout, row major."""
    return bytes(roles_enum[layout.role_at(x, y)]
                 for y in range(layout.h) for x in range(layout.w))


def main():
    header = os.path.join(PORT, "src", "voxel", "voxel_regions.h")
    roles_enum = load_roles_enum(header)

    events = voxel_cells.MapEvents()
    with open(os.path.join(ROOT, "data", "layouts", "layouts.json"),
              encoding="utf-8") as f:
        layouts = json.load(f)["layouts"]

    entries, blobs, skipped = [], [], 0
    payload = 0
    counts = {}
    # Layout ids are the position in this table, one-based: LAYOUT_NONE is 0.
    for index, entry in enumerate(layouts, start=1):
        blockdata = os.path.join(ROOT, entry["blockdata_filepath"])
        if not os.path.exists(blockdata):
            skipped += 1
            continue
        layout = voxel_cells.Layout(entry, events)
        if len(layout.blocks) < layout.w * layout.h:
            skipped += 1
            continue
        role_bytes = roles_of(layout, roles_enum)
        entries.append((index, layout.w, layout.h, payload))
        blobs.append(role_bytes)
        payload += len(role_bytes)
        for b in role_bytes:
            counts[b] = counts.get(b, 0) + 1

    header_bytes = bytearray(b"VXR5")
    header_bytes += struct.pack("<HH", len(entries), 0)
    table_bytes = 4 + 4 + len(entries) * 12
    for layout_id, width, height, role_at in entries:
        header_bytes += struct.pack("<HHHHI", layout_id, width, height, 0,
                                    table_bytes + role_at)

    out_path = os.path.join(PORT, "romfs", "voxel", "regions.bin")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(header_bytes)
        for blob in blobs:
            f.write(blob)

    names = {v: k for k, v in roles_enum.items()}
    total = os.path.getsize(out_path)
    sys.stderr.write("gen_voxel_regions: %d layouts, %d skipped, %.1f KiB\n"
                     % (len(entries), skipped, total / 1024.0))
    sys.stderr.write("  roles: %s\n" % "  ".join(
        "%s=%d" % (names.get(k, k), v)
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
