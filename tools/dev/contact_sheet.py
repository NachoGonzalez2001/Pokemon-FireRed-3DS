"""Tile frame dumps (frame_NNNN.raw) into labelled contact sheets.

usage: python contact_sheet.py DUMP_DIR OUT_PREFIX [COLS] [PER_SHEET]
Writes OUT_PREFIX_0.png, OUT_PREFIX_1.png, ... at native 240x160 per frame.
"""
import struct
import sys
from pathlib import Path
from PIL import Image, ImageDraw

W, H = 240, 160
src = Path(sys.argv[1])
prefix = sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 4
per = int(sys.argv[4]) if len(sys.argv) > 4 else 16


def frame(path):
    px = struct.unpack("<%dH" % (W * H), path.read_bytes()[:W * H * 2])
    img = Image.new("RGB", (W, H))
    img.putdata([((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3) for c in px])
    return img


dumps = sorted(src.glob("frame_*.raw"), key=lambda p: int(p.stem.split("_")[1]))
for s in range(0, len(dumps), per):
    chunk = dumps[s:s + per]
    rows = (len(chunk) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (W + 4), rows * (H + 16)), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(chunk):
        x, y = (i % cols) * (W + 4), (i // cols) * (H + 16)
        sheet.paste(frame(p), (x, y + 14))
        draw.text((x + 2, y + 1), p.stem, fill=(255, 255, 0))
    out = f"{prefix}_{s // per}.png"
    sheet.save(out)
    print(out, chunk[0].stem, "..", chunk[-1].stem)
