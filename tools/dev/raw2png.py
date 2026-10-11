import struct, sys
from PIL import Image
raw = open(sys.argv[1], "rb").read()
W, H = 240, 160
px = struct.unpack("<%dH" % (W * H), raw[:W * H * 2])
img = Image.new("RGB", (W, H))
img.putdata([((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3) for c in px])
img.resize((W * 3, H * 3), Image.NEAREST).save(sys.argv[2])
regs = struct.unpack("<48H", raw[W * H * 2:W * H * 2 + 0x60])
pal = struct.unpack("<32H", raw[W * H * 2 + 0x60:W * H * 2 + 0xA0])
print("nonzero pixels:", sum(1 for c in px if c & 0x7FFF), "distinct:", len(set(c & 0x7FFF for c in px)))
print("regs:", " ".join("%04x" % r for r in regs[:16]))
print("pal:", " ".join("%04x" % p for p in pal))
