"""Convert bottom-screen canvas dumps (bottom_NNNN.raw: RGB565, 320x240,
column-major, each column bottom-to-top) to PNG, or tile several into one.

usage: python bottom2png.py OUT.png DUMP.raw [DUMP.raw ...]
"""
import struct
import sys
from PIL import Image, ImageDraw

W, H = 320, 240


def load(path):
    px = struct.unpack("<%dH" % (W * H), open(path, "rb").read()[:W * H * 2])
    img = Image.new("RGB", (W, H))
    data = [(0, 0, 0)] * (W * H)
    for x in range(W):
        for j in range(H):
            c = px[x * H + j]
            y = H - 1 - j
            data[y * W + x] = ((c >> 11) << 3, ((c >> 5) & 63) << 2, (c & 31) << 3)
    img.putdata(data)
    return img


out, paths = sys.argv[1], sys.argv[2:]
cols = min(3, len(paths))
rows = (len(paths) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (W + 4), rows * (H + 16)), (40, 40, 40))
draw = ImageDraw.Draw(sheet)
for i, p in enumerate(paths):
    x, y = (i % cols) * (W + 4), (i // cols) * (H + 16)
    sheet.paste(load(p), (x, y + 14))
    draw.text((x + 2, y + 1), p.replace("\\", "/").split("/")[-1], fill=(255, 255, 0))
sheet.save(out)
print(out)
