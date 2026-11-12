# The port's own UI icons: vector shapes drawn at 8x, outlined, then box-filtered down.
import math
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageChops

S = 8


class Ic:
    def __init__(s, n=28):
        s.n = n
        s.im = Image.new('RGBA', (n * S, n * S), (0, 0, 0, 0))

    def mask(s, fn, clip=None):
        m = Image.new('L', s.im.size, 0)
        fn(ImageDraw.Draw(m), 255)
        return ImageChops.multiply(m, clip) if clip else m

    def paint(s, m, top, bot=None, y0=0, y1=None, alpha=255):
        bot = bot or top
        y1 = s.n if y1 is None else y1
        g = Image.new('RGBA', s.im.size)
        d = ImageDraw.Draw(g)
        for j in range(s.im.height):
            t = min(1, max(0, (j / S - y0) / max(.01, y1 - y0)))
            d.line([(0, j), (s.im.width, j)], fill=tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(3)) + (255,))
        g.putalpha(m.point(lambda v: v * alpha // 255))
        s.im.alpha_composite(g)

    def rr(s, x0, y0, x1, y1, r, top, bot=None, clip=None, alpha=255):
        m = s.mask(lambda d, f: d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], r * S, fill=f), clip)
        s.paint(m, top, bot, y0, y1, alpha)
        return m

    def circ(s, cx, cy, r, top, bot=None, clip=None, alpha=255):
        m = s.mask(lambda d, f: d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=f), clip)
        s.paint(m, top, bot, cy - r, cy + r, alpha)
        return m

    def ell(s, x0, y0, x1, y1, top, bot=None, clip=None, alpha=255):
        m = s.mask(lambda d, f: d.ellipse([x0 * S, y0 * S, x1 * S, y1 * S], fill=f), clip)
        s.paint(m, top, bot, y0, y1, alpha)

    def poly(s, pts, top, bot=None, clip=None, alpha=255):
        m = s.mask(lambda d, f: d.polygon([(x * S, y * S) for x, y in pts], fill=f), clip)
        ys = [p[1] for p in pts]
        s.paint(m, top, bot, min(ys), max(ys), alpha)
        return m

    def line(s, pts, w, c, clip=None, alpha=255):
        m = s.mask(lambda d, f: d.line([(x * S, y * S) for x, y in pts], fill=f, width=int(w * S), joint='curve'), clip)
        s.paint(m, c, alpha=alpha)

    def done(s, stroke):
        o = Image.new('RGBA', s.im.size, stroke + (255,))
        a = s.im.getchannel('A')
        for _ in range(2):
            a = a.filter(ImageFilter.MaxFilter(5))
        o.putalpha(a)
        o.alpha_composite(s.im)
        return o.resize((s.n, s.n), Image.BOX)


def dex():
    c = Ic()
    b = c.rr(5, 2, 23, 26, 3, (244, 84, 84), (172, 26, 40))
    c.rr(5, 2, 7, 26, 2, (140, 16, 30), (120, 14, 26), b)
    c.poly([(7, 10), (15, 10), (18, 7), (23, 7), (23, 11.5), (7, 11.5)], (160, 24, 36), None, b)
    c.circ(11, 6.2, 4, (250, 250, 250), (200, 206, 216))
    c.circ(11, 6.2, 2.9, (120, 210, 255), (24, 110, 214))
    c.circ(10, 5.2, 1, (255, 255, 255))
    for x, col in ((16.2, (255, 96, 96)), (18.8, (255, 214, 72)), (21.2, (96, 224, 120))):
        c.circ(x, 4.2, .95, col)
    c.rr(8.5, 13, 21, 21.2, 1.2, (46, 50, 62))
    s = c.rr(9.5, 14, 20, 20.2, .6, (176, 240, 214), (96, 200, 170))
    c.poly([(9.5, 20.2), (15.5, 14), (20, 14), (13, 20.2)], (225, 255, 240), None, s, alpha=150)
    c.rr(8.5, 22.5, 13, 24.3, .8, (56, 60, 72))
    c.circ(19.5, 23.4, 1.3, (60, 64, 76))
    return c.done((84, 12, 24))


def ball():
    c = Ic()
    o = c.circ(14, 14, 12.2, (255, 255, 255))
    c.rr(0, 0, 28, 14, 0, (255, 92, 86), (198, 30, 40), o)
    c.rr(0, 14, 28, 28, 0, (250, 250, 252), (186, 192, 206), o)
    c.ell(5, 3.6, 13, 8.2, (255, 190, 186), None, o, alpha=190)
    c.rr(0, 12.8, 28, 15.4, 0, (36, 38, 48), None, o)
    c.circ(14, 14, 4.7, (36, 38, 48))
    c.circ(14, 14, 3.2, (255, 255, 255), (206, 212, 224))
    c.circ(14, 14, 1.5, (240, 242, 248), (255, 255, 255))
    return c.done((36, 30, 44))


def bag():
    c = Ic()
    c.line([(10, 8), (10.4, 4.4), (12, 2.4), (16, 2.4), (17.6, 4.4), (18, 8)], 1.9, (150, 84, 34))
    c.rr(3.6, 11, 7, 23, 1.6, (176, 100, 40), (136, 74, 28))
    c.rr(21, 11, 24.4, 23, 1.6, (176, 100, 40), (136, 74, 28))
    b = c.rr(5.6, 6, 22.4, 26.4, 4, (246, 174, 84), (206, 118, 44))
    c.rr(5.6, 6, 22.4, 13.8, 4, (216, 128, 50), (186, 100, 38), b)
    c.rr(5.6, 13.2, 22.4, 14.4, 0, (146, 80, 30), None, b)
    c.rr(8.6, 7, 14, 8, .5, (255, 212, 150), None, b, alpha=170)
    c.rr(12, 11, 16, 16.4, .8, (255, 226, 112), (220, 160, 44))
    p = c.rr(8.2, 17.4, 19.8, 24.6, 2, (255, 198, 116), (226, 142, 62))
    c.rr(8.2, 17.4, 19.8, 18.4, 0, (176, 100, 40), None, p)
    return c.done((92, 48, 20))


def card():
    c = Ic()
    b = c.rr(1.6, 5.4, 26.4, 23.4, 2.4, (252, 252, 255), (216, 222, 234))
    c.rr(1.6, 5.4, 26.4, 10, 0, (98, 168, 250), (42, 104, 214), b)
    c.rr(4, 11.6, 11.4, 20.8, 1, (206, 226, 252), (160, 196, 244))
    c.circ(7.7, 14.2, 1.9, (44, 76, 148))
    s = c.mask(lambda d, f: d.rectangle([4 * S, 11.6 * S, 11.4 * S, 20.8 * S], fill=f))
    c.ell(4.4, 16.8, 11, 24, (44, 76, 148), None, s)
    for y, x1 in ((13, 23.8), (16, 23.8), (19, 19)):
        c.rr(13.4, y, x1, y + 1.2, .6, (144, 152, 170))
    c.circ(5, 7.7, 1.1, (255, 226, 112))
    return c.done((24, 42, 96))


def save():
    c = Ic()
    b = c.poly([(3.6, 4.6), (4.6, 3.6), (20.6, 3.6), (24.4, 7.4), (24.4, 23.4), (23.4, 24.4), (4.6, 24.4), (3.6, 23.4)], (86, 148, 244), (34, 84, 186))
    c.rr(8.6, 3.6, 19.4, 10.6, .6, (236, 240, 248), (178, 186, 202), b)
    c.rr(14.8, 4.8, 17.6, 9.4, .4, (42, 56, 92))
    l = c.rr(6.8, 13.4, 21.2, 24.4, .6, (255, 255, 255), (216, 222, 234), b)
    for y in (15.8, 18.2, 20.6):
        c.rr(8.6, y, 19.4, y + .9, .4, (160, 170, 190), None, l)
    return c.done((16, 36, 92))


def gear():
    c = Ic()
    pts = []
    t = 8
    step = 2 * math.pi / t
    for i in range(t):
        a = step * i - math.pi / 2
        for da, r in ((-.46, 9.2), (-.26, 12.8), (.26, 12.8), (.46, 9.2)):
            aa = a + da * step
            pts.append((14 + r * math.cos(aa), 14 + r * math.sin(aa)))
    c.poly(pts, (232, 238, 246), (116, 128, 150))
    c.circ(14, 14, 7.2, (156, 168, 188), (214, 222, 234))
    c.circ(14, 14, 5.8, (226, 232, 240), (160, 172, 192))
    c.circ(14, 14, 3.3, (44, 50, 66), (70, 80, 100))
    return c.done((42, 50, 68))


def shoe():
    c = Ic()
    u = c.poly([(3.4, 7.2), (6, 6.2), (10, 6.2), (12.4, 9.6), (16.6, 12.2), (22.4, 13.8), (25.4, 16.6), (25.8, 20), (3, 20)], (252, 86, 80), (196, 28, 40))
    c.poly([(7, 20), (12.5, 12.5), (15.5, 14), (11.5, 20)], (255, 236, 160), (250, 200, 80), u)
    c.ell(20.6, 14.2, 28, 22, (255, 255, 255), (214, 220, 232), u)
    c.rr(3, 6, 10, 8.4, 0, (56, 60, 74), None, u)
    for x, y in ((12.6, 9.2), (14.7, 10.5), (16.8, 11.7)):
        c.line([(x, y), (x - 1.4, y + 2.1)], 1, (255, 255, 255))
    c.rr(2.2, 19.2, 26.6, 24.4, 2.2, (255, 255, 255), (186, 194, 208))
    c.rr(2.2, 22.4, 26.6, 23.2, .3, (120, 130, 150))
    return c.done((70, 14, 26))


def lens():
    c = Ic()
    c.circ(14, 14, 12.6, (255, 255, 255), (196, 202, 214))
    c.circ(14, 14, 9.8, (36, 60, 110))
    c.circ(14, 14, 8.8, (112, 214, 255), (18, 98, 210))
    c.circ(14, 18.6, 4.2, (150, 236, 255), None, alpha=110)
    c.ell(8.2, 7.6, 14.6, 12.6, (255, 255, 255), None, alpha=235)
    return c.done((94, 12, 26))


def keystone():
    """The Key Stone of Mega Evolution: a swirled stone set in a bracelet."""
    c = Ic()
    c.rr(1.2, 10.2, 26.8, 17.8, 3.6, (238, 242, 250), (132, 142, 164))
    c.rr(1.2, 13.4, 26.8, 14.6, .5, (104, 114, 136))
    c.circ(14, 14, 10.4, (252, 252, 255), (150, 160, 184))
    stone = c.circ(14, 14, 8.2, (255, 112, 196), (110, 70, 220))
    c.ell(5.4, 7.0, 15.6, 15.8, (110, 226, 150), None, clip=stone, alpha=215)
    c.ell(12.4, 12.4, 23.0, 22.6, (84, 168, 255), None, clip=stone, alpha=215)
    c.circ(14, 14, 3.2, (255, 238, 120), None, alpha=235)
    c.ell(9.0, 7.8, 13.6, 11.6, (255, 255, 255), None, alpha=235)
    return c.done((58, 36, 92))


ALL = dict(Dex=dex, Ball=ball, Bag=bag, Card=card, Save=save, Gear=gear, Shoe=shoe, Lens=lens, Key=keystone)


def get(name, size=None):
    im = ALL[name]()
    return im if size is None or size == im.width else im.resize((size, size), Image.LANCZOS)


SIZES = [('Dex', 26), ('Ball', 26), ('Bag', 26), ('Card', 26), ('Save', 26), ('Gear', 26), ('Shoe', 20), ('Lens', 22),
         ('Bag', 28), ('Shoe', 28), ('Key', 22)]


def main(path):
    out = ['/* Generated by tools/dev/ui_icons.py: own art of the port, not from the game. */',
           'typedef struct { u8 size; const u16 *rgb; const u8 *alpha; } UiIcon;', '']
    for name, size in SIZES:
        px = get(name, size).load()
        rgb, alpha = [], []
        for y in range(size):
            for x in range(size):
                r, g, b, a = px[x, y]
                rgb.append((r >> 3) << 11 | (g >> 2) << 5 | b >> 3)
                alpha.append(a)
        tag = '%s%d' % (name, size)
        for kind, vals, fmt in (('u16', rgb, '0x%04X'), ('u8', alpha, '%d')):
            out.append('static const %s sIcon%s_%s[] = {' % (kind, tag, 'rgb' if kind == 'u16' else 'a'))
            for i in range(0, len(vals), 16):
                out.append('    ' + ','.join(fmt % v for v in vals[i:i + 16]) + ',')
            out.append('};')
        out.append('static const UiIcon sIcon%s = { %d, sIcon%s_rgb, sIcon%s_a };' % (tag, size, tag, tag))
        out.append('')
    with open(path, 'w', newline=chr(10)) as f:
        f.write(chr(10).join(out))


if __name__ == '__main__':
    main(sys.argv[1])
