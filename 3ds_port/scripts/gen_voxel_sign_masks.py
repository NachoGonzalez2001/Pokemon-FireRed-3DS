#!/usr/bin/env python3
"""Generate the independent ROMFS signpost mask sidecar.

This intentionally does not alter regions.bin. Signposts are thin objects and
are indexed by layout-local cell, not stored as structure regions.
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voxel_cells  # noqa: E402
from voxel_sign_mask import head_mask, metatile_mask  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PORT = os.path.join(ROOT, "3ds_port")
OUT = os.path.join(PORT, "romfs", "voxel", "signposts.bin")


def head_ground(layout, pair, x, y):
    """The ground under a sign's head: the head cell's drawing without it.

    A walkable neighbour that draws nothing on its upper layer and the same
    lower layer is the head cell's ground exactly; failing that the commonest
    such neighbour. The map holds it, so its atlas does too.
    """
    own = pair.layer_pixels(layout.metatile(x, y), 0)
    counts = {}
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if (dx, dy) in ((0, 0), (0, 1)) or layout.off_map(nx, ny) or layout.blocked(nx, ny):
                continue
            m = layout.metatile(nx, ny)
            if pair.layer_pixels(m, 1):
                continue
            if pair.layer_pixels(m, 0) == own:
                return m
            counts[m] = counts.get(m, 0) + 1
    if counts:
        return max(counts, key=counts.get)
    return layout.metatile(x, y + 2) if not layout.off_map(x, y + 2) else 0


def main():
    with open(os.path.join(ROOT, "data", "layouts", "layouts.json"),
              encoding="utf-8") as stream:
        layouts = json.load(stream)["layouts"]
    events = voxel_cells.MapEvents()
    pairs = {}
    records = []
    for layout_id, entry in enumerate(layouts, start=1):
        layout = voxel_cells.Layout(entry, events)
        key = (layout.primary, layout.secondary)
        if not layout.outdoor:
            continue
        if key not in pairs:
            pairs[key] = voxel_cells.pair_for(*key)
        pair = pairs[key]
        for y in range(layout.h):
            for x in range(layout.w):
                if layout.role_at(x, y) != "signpost":
                    continue
                rows = metatile_mask(pair, layout, x, y)
                head, ground = [0] * 16, 0
                if y > 0 and not layout.blocked(x, y - 1):
                    head = head_mask(pair, rows, layout.metatile(x, y - 1))
                    if any(head):
                        ground = head_ground(layout, pair, x, y - 1)
                records.append((layout_id, x, y, rows, head, ground))
    records.sort(key=lambda item: (item[0], item[2], item[1]))
    # The runtime uses the numeric layout id, not the string map name.
    # layouts.json ids are numeric in the generated map table.
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as stream:
        # VXS2: a record is the sign's cell, its 16 mask rows, the 16 rows of
        # its head in the cell north of it (a lamp's lantern; 0 for none) and
        # the metatile that cell's ground is drawn with instead
        stream.write(b"VXS2")
        stream.write(struct.pack("<I", len(records)))
        for layout_id, x, y, rows, head, ground in records:
            stream.write(struct.pack("<HHH16H16HH", int(layout_id), x, y, *rows, *head, ground))
    print("voxel sign masks: %d records, %d with a head -> %s"
          % (len(records), sum(1 for r in records if any(r[4])), OUT))


if __name__ == "__main__":
    main()
