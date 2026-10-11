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
print("DISPCNT=%04x BG0..3CNT=%04x %04x %04x %04x WIN0H=%04x WIN1H=%04x WIN0V=%04x WIN1V=%04x "
      "WININ=%04x WINOUT=%04x MOSAIC=%04x BLDCNT=%04x BLDALPHA=%04x BLDY=%04x"
      % (regs[0], regs[4], regs[5], regs[6], regs[7], regs[0x20], regs[0x21], regs[0x22], regs[0x23],
         regs[0x24], regs[0x25], regs[0x26], regs[0x28], regs[0x29], regs[0x2A]))
print("pal:", " ".join("%04x" % p for p in pal))
