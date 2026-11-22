#!/usr/bin/env python3
"""Find, in another language's FireRed ROM, the text of the English build.

    python tools/lang/lang_overlay.py --tree C:/fr3ds/upstream --en-rom <English ROM> \
        --rom <language ROM> --out C:/fr3ds/lang/es/overlay

Run on the maintainer's machine after an English build of the tree. The
English build's game data is made of symbols (the C units' read-only data, the
event scripts and their text) and of files (graphics, tilesets, layouts).

1. Every symbol is placed in the English ROM: by its bytes, and then again
   with the pointers it holds filled in from the symbols already placed,
   until nothing more is found.
2. The symbols whose bytes the language ROM shares (script bytecode, tables)
   are placed there the same way; between two of them, the scripts' text
   follows in the same order in both ROMs.
3. Both ROMs run the same code over the same tables, so the words that point
   at a piece of data in one point at its counterpart in the other: every
   placed symbol, and every stretch of code both ROMs share, pairs English
   addresses with the language's. The text, names and pictures the English
   build holds are then read from the language ROM at their counterparts.

The output is the language overlay, a folder that build_lang.py applies to a
copy of the tree:

    overlay.json   {"c": {"<object>|<section>": hex}, "asm": {label: hex},
                    "files": [tree paths], "lang": code, "rom_sha1": ...}
    files/<path>   the language ROM's version of each tree file
    misses.txt     what was left in English, and why

The overlay holds bytes of the language ROM: it stays on this machine, like
the ROMs themselves, and is never committed or published. What reaches the
player is the language's executable and its recipe, which only name places in
that ROM.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "port_common"))

ROM_BASE = 0x08000000
LANG_CODES = {"BPRJ": "ja", "BPRS": "es", "BPRD": "de", "BPRF": "fr", "BPRI": "it", "BPRE": "en"}
EOS = 0xFF
MAX_SCAN = 400        # occurrences of a search key looked at before giving up

# Tables with text inside records: (record size, [(field offset, field size)]).
# None: the whole table is the language's (name arrays, layouts, font widths).
TABLES = {
    "gSpeciesNames": None,
    "gMoveNames": None,
    "gAbilityNames": None,
    "gTypeNames": None,
    "gTrainerClassNames": None,
    "sEasyChatWordsByLetterPointers": None,
    "sBg1EndGraphic": None,
    "gItems": (44, [(0, 14)]),
    "gTrainers": (40, [(4, 12)]),
    "gBerries": (28, [(0, 7)]),
    "gPokedexEntries": (36, [(0, 12)]),
    "sInGameTrades": None,
    "sInGameTradeMailMessages": None,
}
# Easy Chat words are each language's own, not translations: the slot of a
# word ID holds "¿QUÉ TAL?" where the English game has "YES". Their tables pair
# the words of one ID, and those pairs translate Easy Chat words only.
EASY_CHAT = re.compile(r"EasyChat|ECPhrase|ECWord")
TABLE_PATTERNS = [re.compile(p) for p in (
    r"^sTrainerTowerFloor_\w+$",
    r"^sEasyChatGroup_\w+$",
    r"^sFont\w*LatinGlyphWidths$",
    r"^s\w*WindowTemplates?(_\w+)?$",
    r"^sWindowTemplate_\w+$",
)]


def log(msg: str) -> None:
    print("lang_overlay: " + msg, flush=True)


def tool(name: str) -> str:
    exe = name + (".exe" if sys.platform == "win32" else "")
    for base in (os.environ.get("DEVKITARM", ""), "C:/devkitPro/devkitARM", "/opt/devkitpro/devkitARM"):
        if base and (Path(base) / "bin" / exe).is_file():
            return str(Path(base) / "bin" / exe)
    return name


def nm_symbols(elf: Path) -> dict[str, int]:
    out = subprocess.check_output([tool("arm-none-eabi-nm"), "--defined-only", str(elf)],
                                  text=True, errors="ignore")
    syms = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3:
            syms[p[2]] = int(p[0], 16)
    return syms


# ---------------------------------------------------------------- the English build

class Symbol:
    __slots__ = ("region", "off", "size", "name", "key", "data", "sites", "en", "xx", "new")

    def __init__(self, region, off, size, name, key):
        self.region, self.off, self.size, self.name, self.key = region, off, size, name, key
        self.data = b""
        self.sites: list[tuple[int, int, int]] = []   # (offset, target region id, target payload offset)
        self.en: int | None = None   # ROM offsets
        self.xx: int | None = None
        self.new: bytes | None = None

    @property
    def mask(self) -> bytes:
        m = bytearray(self.size)
        for site, _, _ in self.sites:
            m[site:site + 4] = b"\1\1\1\1"
        return bytes(m)


class Region:
    def __init__(self, rid: int, name: str, payload: bytes, syms: list[Symbol]):
        self.rid, self.name, self.payload = rid, name, payload
        self.syms = sorted(syms, key=lambda s: s.off)
        self.starts = [s.off for s in self.syms]

    def at(self, off: int) -> tuple[Symbol | None, int]:
        i = bisect.bisect_right(self.starts, off) - 1
        if i < 0:
            return None, 0
        s = self.syms[i]
        if off >= s.off + max(s.size, 1):
            return None, 0
        return s, off - s.off


def gamedata_symbols(port: Path) -> list[Symbol]:
    elf = port / "build" / "gamedata_image.elf"
    out = subprocess.check_output([tool("arm-none-eabi-nm"), "-S", "-n", "--defined-only", str(elf)],
                                  text=True, errors="ignore")
    start = end = None
    syms = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[2] == "__ctr_gamedata":
            start = int(p[0], 16)
        elif len(p) == 3 and p[2] == "__ctr_gamedata_end":
            end = int(p[0], 16)
        elif len(p) == 4 and p[2] in "RrDd":
            syms.append((int(p[0], 16), int(p[1], 16), p[3]))
    sections = {}
    pending = None
    for line in (port / "build" / "gamedata_image.map").read_text(errors="ignore").splitlines():
        m = re.match(r"^ (\.rodata\S*)(?:\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+))?\s*$", line)
        if m:
            if m.group(2):
                sections[int(m.group(2), 16)] = (m.group(4), m.group(1), int(m.group(3), 16))
                pending = None
            else:
                pending = m.group(1)
            continue
        if pending:
            m = re.match(r"^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+)\s*$", line)
            if m:
                sections[int(m.group(1), 16)] = (m.group(3), pending, int(m.group(2), 16))
            pending = None
    result, seen = [], set()
    for addr, size, name in syms:
        if not (start <= addr < end) or not size or addr in seen:
            continue
        seen.add(addr)
        sec = sections.get(addr)
        key = None
        if sec and sec[2] == size and sec[1].endswith("." + name):
            key = "%s|%s" % (sec[0], sec[1])   # alone in its section: it can be resized
        result.append(Symbol(0, addr - start, size, name, key))
    return result


SCRIPT_OBJECTS = ["battle_ai_scripts", "battle_anim_scripts", "battle_scripts_1", "battle_scripts_2",
                  "event_scripts", "field_effect_scripts"]   # gen_script_bundle.py's order


def script_symbols(port: Path) -> list[Symbol]:
    """Every label of the scripts' region, local ones too (a file may keep its
    text under local labels), at its offset in the payload: the objects'
    script_data sections one after another, each padded to a word."""
    blob = blob_symbols(port)
    globals_at = {s.off: s.name for s in blob}
    labels: dict[int, str] = {}
    base = 0
    for stem in SCRIPT_OBJECTS:
        obj = port / "build" / "root" / "data" / (stem + ".o")
        if not obj.is_file():
            return blob
        out = subprocess.check_output([tool("arm-none-eabi-objdump"), "-h", "-t", str(obj)],
                                      text=True, errors="ignore")
        size = None
        for line in out.splitlines():
            p = line.split()
            if len(p) >= 3 and p[1] == "script_data" and p[0].isdigit():
                size = int(p[2], 16)
            m = re.match(r"^([0-9a-f]{8}) ([lg])\s+script_data\s+[0-9a-f]+ (\w+)$", line)
            if m and not m.group(3).startswith(".L"):
                off = base + int(m.group(1), 16)
                if off in globals_at:
                    labels[off] = globals_at[off]   # the name the bundle gives that place
                elif off not in labels:
                    labels[off] = m.group(3)
        if size is None:
            return blob
        base += (size + 3) // 4 * 4
    names = [s.name for s in blob]
    if any(labels.get(s.off) != s.name for s in blob):
        return blob   # the layout is not the bundle's: keep the global labels only
    counts: dict[str, int] = {}
    for n in labels.values():
        counts[n] = counts.get(n, 0) + 1
    offs = sorted(labels)
    out_syms = []
    for i, off in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else base
        name = labels[off]
        if end > off:
            # a local name two files share cannot be written back by name
            key = name if counts[name] == 1 or name in names else None
            out_syms.append(Symbol(1, off, end - off, name, key))
    return out_syms


def blob_symbols(port: Path) -> list[Symbol]:
    off, name, out = 0, None, []
    for line in (port / "build" / "3ds_script_blob.s").read_text().splitlines():
        m = re.match(r"^(\w+):$", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^\s*\.space (\d+)", line)
        if m:
            n = int(m.group(1))
            if name and name != "__ctr_script_blob" and n:
                out.append(Symbol(1, off, n, name, name))
            off += n
            name = None
    return out


def load_regions(port: Path) -> list[Region]:
    romfs = port / "romfs"
    exe = nm_symbols(port / "firered3ds.elf")
    bases = [(exe["__ctr_gamedata"], exe["__ctr_gamedata_end"]),
             (exe["__ctr_script_blob"], exe["__ctr_script_blob_end"])]
    regions = []
    for rid, (name, syms) in enumerate((("gamedata", gamedata_symbols(port)),
                                        ("scripts", script_symbols(port)))):
        stem = "gamedata/gamedata" if rid == 0 else "scripts/scripts"
        payload = (romfs / (stem + ".bin")).read_bytes()
        regions.append(Region(rid, name, payload, syms))
    for rid, stem in enumerate(("gamedata/gamedata", "scripts/scripts")):
        reg = regions[rid]
        raw = (romfs / (stem + ".rel")).read_bytes()
        _, _, _, _, n_int, n_ext = struct.unpack_from("<4sIIIII", raw, 0)
        sites = struct.unpack_from("<%dI" % (n_int + n_ext), raw, 24)
        for k, site in enumerate(sites):
            value = struct.unpack_from("<I", reg.payload, site)[0]
            target = (rid, value) if k < n_int else None
            if target is None:
                for tid, (lo, hi) in enumerate(bases):
                    if lo <= value < hi:
                        target = (tid, value - lo)
            s, rel = reg.at(site)
            if s is None or rel + 4 > s.size:
                continue
            s.sites.append((rel, target[0] if target else -1, target[1] if target else 0))
    for reg in regions:
        for s in reg.syms:
            s.data = reg.payload[s.off:s.off + s.size]
    return regions


# ---------------------------------------------------------------- searching

def find_all(rom: bytes, data: bytes, mask: bytes, limit: int = 8, min_run: int = 4) -> list[int]:
    """The places (up to `limit`) holding data, masked bytes aside."""
    n = len(data)
    runs, i = [], 0
    while i < n:
        if mask[i]:
            i += 1
            continue
        j = i
        while j < n and not mask[j]:
            j += 1
        runs.append((j - i, i))
        i = j
    if not runs:
        return []
    ln, at = max(runs)
    if ln < min_run:
        return []
    key = data[at:at + ln]
    checks = [(i, k) for k, i in runs if i != at]
    hits, scanned = [], 0
    p = rom.find(key)
    while p >= 0 and len(hits) < limit and scanned < MAX_SCAN:
        scanned += 1
        base = p - at
        if base >= 0 and base + n <= len(rom) and \
                all(rom[base + i:base + i + k] == data[i:i + k] for i, k in checks):
            hits.append(base)
        p = rom.find(key, p + 1)
    if scanned >= MAX_SCAN:
        hits.append(-1)   # too common to tell
    return hits


def is_pointer(w: int, rom_len: int) -> bool:
    return ROM_BASE <= w < ROM_BASE + rom_len


class PointerMap:
    """English ROM address -> language ROM address, by votes."""

    def __init__(self):
        self.votes: dict[int, Counter] = defaultdict(Counter)

    def add(self, en: int, xx: int, weight: int = 1) -> None:
        self.votes[en][xx] += weight

    def get(self, en: int) -> int | None:
        c = self.votes.get(en)
        if not c:
            return None
        top = c.most_common(2)
        if len(top) > 1 and top[1][1] * 2 > top[0][1]:
            return None   # no clear winner
        return top[0][0]


def align_words(en: bytes, xx: bytes, pmap: PointerMap, k: int = 8) -> int:
    """Pair the pointer words of every stretch both ROMs share (pointers aside)."""
    ne, nx = len(en) // 4, len(xx) // 4
    ew = struct.unpack("<%dI" % ne, en[:ne * 4])
    xw = struct.unpack("<%dI" % nx, xx[:nx * 4])
    P = -1
    et = [P if is_pointer(w, len(en)) else w for w in ew]
    xt = [P if is_pointer(w, len(xx)) else w for w in xw]

    def grams(t):
        out = {}
        for i in range(len(t) - k):
            g = tuple(t[i:i + k])
            if g.count(P) > k // 2 or len(set(g)) < 3:
                continue
            out[g] = -1 if g in out else i
        return out
    gx = grams(xt)
    anchors = sorted((i, gx[g]) for g, i in grams(et).items() if i >= 0 and gx.get(g, -1) >= 0)
    aligned = {}
    for i, j in anchors:
        for d in range(k):
            aligned[i + d] = j + d
    for (i1, j1), (i2, j2) in zip(anchors, anchors[1:]):
        if j1 - i1 == j2 - i2 and 0 < i2 - i1 <= 256:
            for i in range(i1, i2):
                aligned.setdefault(i, j1 + i - i1)
    pairs = 0
    for i, j in aligned.items():
        if et[i] == P and xt[j] == P:
            pmap.add(ew[i], xw[j])
            pairs += 1
    return pairs


def expected(s: Symbol, regions: list[Region], which: str) -> tuple[bytes, bytes]:
    """The symbol's bytes as a ROM holds them: pointers to placed symbols filled in."""
    data = bytearray(s.data)
    mask = bytearray(s.size)
    for rel, tid, toff in s.sites:
        t, k = regions[tid].at(toff) if tid >= 0 else (None, 0)
        addr = getattr(t, which) if t is not None else None
        if addr is None or (which == "xx" and k and t.new is not None):
            mask[rel:rel + 4] = b"\1\1\1\1"
        else:
            struct.pack_into("<I", data, rel, ROM_BASE + addr + k)
    return bytes(data), bytes(mask)


def nearest_delta(placed: list[tuple[int, int]], en: int) -> int | None:
    i = bisect.bisect_right(placed, (en, 1 << 40)) - 1
    if i < 0:
        return None
    return placed[i][1] - placed[i][0]


_TRIED: dict[tuple[str, int, int], tuple[bytes, bytes, int]] = {}


def place(regions, rom: bytes, which: str, candidates, rounds: int = 6) -> int:
    """Place symbols in a ROM by their bytes; ambiguous ones by their neighbours."""
    total = 0
    for _ in range(rounds):
        found = 0
        for reg in regions:
            prev = None
            order = reg.syms
            for idx, s in enumerate(order):
                if getattr(s, which) is not None or not candidates(s):
                    continue
                data, mask = expected(s, regions, which)
                key = (which, reg.rid, s.off)
                tried = _TRIED.get(key)
                if tried and tried[0] == data and tried[1] == mask:
                    hits = tried[2]
                else:
                    hits = [h for h in find_all(rom, data, mask) if h >= 0]
                    _TRIED[key] = (data, mask, hits)
                if not hits:
                    continue
                pick = None
                if len(hits) == 1:
                    pick = hits[0]
                elif hits and reg.rid == 1:
                    # Scripts sit in source order: the one right after the previous symbol.
                    before = order[idx - 1] if idx else None
                    after = order[idx + 1] if idx + 1 < len(order) else None
                    for h in hits:
                        if before is not None and getattr(before, which) is not None and \
                                before.off + before.size == s.off and \
                                getattr(before, which) + sym_len(before, which) == h:
                            pick = h
                        if after is not None and getattr(after, which) is not None and \
                                h + s.size == getattr(after, which):
                            pick = h
                if pick is not None:
                    setattr(s, which, pick)
                    found += 1
                prev = s
        found += place_targets(regions, rom, which)
        total += found
        if not found:
            break
    return total


def place_targets(regions, rom: bytes, which: str) -> int:
    """What a placed symbol points at is where its pointer says, when the bytes
    there are the target's: text that is in the ROM more than once (two moves
    with the same description) gets the copy its table uses."""
    found = 0
    for reg in regions:
        for s in reg.syms:
            base = getattr(s, which)
            if base is None:
                continue
            for rel, tid, toff in s.sites:
                if tid < 0:
                    continue
                t, k = regions[tid].at(toff)
                if t is None or k or getattr(t, which) is not None:
                    continue
                if which == "xx" and t.new is not None:
                    continue
                at = struct.unpack_from("<I", rom, base + rel)[0] - ROM_BASE
                if not 0 <= at <= len(rom) - t.size:
                    continue
                data, mask = expected(t, regions, which)
                if all(mask[i] or rom[at + i] == data[i] for i in range(t.size)):
                    setattr(t, which, at)
                    found += 1
    return found


def sym_len(s: Symbol, which: str) -> int:
    """The symbol's length in that ROM (its text may be the language's)."""
    if which == "xx" and s.new is not None and s.region == 1:
        return len(s.new)
    return s.size


def code_mask(rom: bytes, start: int, end: int) -> bytearray:
    """Bytes that differ between two builds of the same code: ROM and RAM
    addresses in literal pools, and Thumb BL offsets."""
    mask = bytearray(end - start)
    for i in range(start - start % 4, end, 4):
        if i >= start and i + 4 <= end and rom[i + 3] in (0x02, 0x03, 0x08, 0x09):
            mask[i - start:i - start + 4] = b"\1\1\1\1"
    for i in range(start - start % 2, end - 1, 2):
        if i >= start and (struct.unpack_from("<H", rom, i)[0] >> 11) in (0x1E, 0x1F):
            mask[i - start:i - start + 2] = b"\1\1"
    return mask


def code_context(en: bytes, xx: bytes, site: int) -> int | None:
    """The language ROM's pointer at the place of the English one at `site`:
    several windows around it are tried, and those that are found must agree."""
    found = set()
    for before, after in ((96, 32), (48, 16), (0, 64), (64, 0), (24, 24)):
        x = _context(en, xx, site, before, after)
        if x is not None:
            found.add(x)
    return found.pop() if len(found) == 1 else None


def _context(en: bytes, xx: bytes, site: int, before: int, after: int) -> int | None:
    start, end = max(0, site - before), min(len(en), site + 4 + after)
    data = en[start:end]
    mask = code_mask(en, start, end)
    mask[site - start:site - start + 4] = b"\1\1\1\1"
    hits = [h for h in find_all(xx, data, bytes(mask), limit=2, min_run=12) if h >= 0]
    if len(hits) != 1:
        return None
    w = struct.unpack_from("<I", xx, hits[0] + site - start)[0]
    return w - ROM_BASE if is_pointer(w, len(xx)) else None


# ---------------------------------------------------------------- the language's bytes

def read_string(rom: bytes, off: int, limit: int = 4096) -> bytes | None:
    end = rom.find(bytes([EOS]), off, off + limit)
    if end < 0:
        return None
    return rom[off:end + 1]


def lz_length(rom: bytes, off: int) -> int | None:
    """Length of the LZ77 stream at off, or None."""
    if off < 0 or off + 4 > len(rom) or rom[off] != 0x10:
        return None
    size = rom[off + 1] | rom[off + 2] << 8 | rom[off + 3] << 16
    if not 0 < size <= 0x40000:
        return None
    pos, out = off + 4, 0
    try:
        while out < size:
            flags = rom[pos]
            pos += 1
            for bit in range(8):
                if out >= size:
                    break
                if flags & (0x80 >> bit):
                    out += (rom[pos] >> 4) + 3
                    pos += 2
                else:
                    pos += 1
                    out += 1
    except IndexError:
        return None
    return pos - off


def text_body(data: bytes) -> bytes:
    return data.rstrip(b"\0")


def is_string(data: bytes) -> bool:
    body = text_body(data)
    return len(body) >= 1 and body[-1] == EOS and EOS not in body[:-1]


def table_spec(name: str):
    if name in TABLES:
        return True, TABLES[name]
    if any(p.match(name) for p in TABLE_PATTERNS):
        return True, None
    return False, None


def translate(s: Symbol, xx: bytes, x: int) -> tuple[bytes | None, str]:
    """The language's version of an English symbol found at x in its ROM."""
    d = s.data
    if is_string(d):
        new = read_string(xx, x)
        if new is None:
            return None, "bad string"
        if s.region == 1:
            return new, "string"
        return new + b"\0" * (len(d) - len(text_body(d))), "string"
    known, spec = table_spec(s.name)
    if not known:
        return None, "kept"
    theirs = xx[x:x + len(d)]
    mask = s.mask
    if spec is None:
        return bytes(theirs[i] if not mask[i] else d[i] for i in range(len(d))), "table"
    stride, fields = spec
    buf = bytearray(d)
    for base in range(0, len(d) - stride + 1, stride):
        for fo, fl in fields:
            buf[base + fo:base + fo + fl] = theirs[base + fo:base + fo + fl]
    return bytes(buf), "table"


# ---------------------------------------------------------------- files

def tree_files(tree: Path) -> list[str]:
    import staging
    import vtree_manifest
    romfs = tree / "3ds_port" / "romfs"
    paths = {rel for rel, _ in staging.data_files(romfs) if (tree / rel).is_file()}
    paths.update(vtree_manifest.binary_inputs(tree))
    return sorted(paths)


TILESET_FIELDS = {"tiles": 0x04, "palettes": 0x08, "metatiles": 0x0C, "metatileAttributes": 0x14}


def tileset_file(tree: Path, xx: bytes, rel: str, size: int) -> bytes | None:
    """A tileset's file, reached in the language ROM through a layout that uses
    the tileset: its map is the same in both ROMs, its Tileset struct points at
    the file (the graphics with text on signs differ)."""
    label = None
    for header in ("src/data/tilesets/graphics.h", "src/data/tilesets/metatiles.h", "src/graphics.c"):
        if not (tree / header).is_file():
            continue
        text = (tree / header).read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'(\w+)\[\]\s*=\s*INCBIN_\w+\("([^"]+)"\)', text):
            if m.group(2) == rel:
                label = m.group(1)
    if label is None:
        return None
    heads = (tree / "src/data/tilesets/headers.h").read_text(encoding="utf-8", errors="ignore")
    owner = field = None
    for m in re.finditer(r"const struct Tileset (\w+)\s*=\s*\{(.*?)\};", heads, re.S):
        for f, value in re.findall(r"\.(\w+)\s*=\s*(\w+)", m.group(2)):
            if value == label and f in TILESET_FIELDS:
                owner, field = m.group(1), TILESET_FIELDS[f]
    if owner is None:
        return None
    layouts = json.loads((tree / "data/layouts/layouts.json").read_text(encoding="utf-8"))["layouts"]
    results = set()
    for entry in layouts:
        if "name" not in entry or owner not in (entry["primary_tileset"], entry["secondary_tileset"]):
            continue
        which = 0x10 if entry["primary_tileset"] == owner else 0x14
        blocks = (tree / entry["blockdata_filepath"]).read_bytes()
        p = xx.find(blocks)
        while p >= 0:
            needle = struct.pack("<I", ROM_BASE + p)
            q = xx.find(needle)
            while q >= 0:
                base = q - 0x0C
                if base >= 0 and q % 4 == 0:
                    w, h = struct.unpack_from("<ii", xx, base)
                    if (w, h) == (entry["width"], entry["height"]):
                        ts = struct.unpack_from("<I", xx, base + which)[0] - ROM_BASE
                        if 0 <= ts < len(xx) - 0x18:
                            at = struct.unpack_from("<I", xx, ts + field)[0] - ROM_BASE
                            if 0 <= at < len(xx):
                                if rel.endswith(".lz"):
                                    n = lz_length(xx, at)
                                    if n is not None:
                                        results.add(xx[at:at + n] + b"\0" * ((-n) % 4 if size % 4 == 0 else 0))
                                else:
                                    results.add(xx[at:at + size])
                q = xx.find(needle, q + 1)
            p = xx.find(blocks, p + 1)
    return results.pop() if len(results) == 1 else None


def file_overlay(tree: Path, en: bytes, xx: bytes, pmap: PointerMap, out: Path, misses: list) -> list[str]:
    from firered3ds_builder.recipe import lz77_decompress
    done, stats = [], Counter()
    for rel in tree_files(tree):
        d = (tree / rel).read_bytes()
        if len(d) < 16:
            continue
        lz_path = tree / (rel + ".lz")
        compressed = rel.endswith(".lz")
        if not compressed and lz_path.is_file() and en.find(d) < 0:
            continue   # the ROM holds it compressed: see its .lz
        if xx.find(d) >= 0:
            continue
        hits, p = [], en.find(d)
        while p >= 0 and len(hits) < 4:
            hits.append(p)
            p = en.find(d, p + 1)
        if not hits:
            stats["not in the English ROM"] += 1
            misses.append(("file not in the English ROM", rel))
            continue
        news = set()
        for at in hits:
            x = pmap.get(ROM_BASE + at)
            if x is None:
                continue
            x -= ROM_BASE
            if compressed:
                n = lz_length(xx, x)
                if n is None:
                    continue
                new = xx[x:x + n]
                if len(d) > (lz_length(en, at) or len(d)):
                    new += b"\0" * ((-n) % 4)   # the tree's file is padded to a word
            else:
                new = xx[x:x + len(d)]
            news.add(new)
        if not news and rel.startswith("data/tilesets/"):
            found = tileset_file(tree, xx, rel, len(d))
            if found is not None:
                news.add(found)
        if len(news) != 1:
            stats["unmapped" if not news else "ambiguous"] += 1
            misses.append(("file unmapped" if not news else "file ambiguous", rel))
            continue
        new = news.pop()
        targets = [(rel, new)]
        if compressed:
            raw = rel[:-3]
            if (tree / raw).is_file():
                targets.append((raw, lz77_decompress(new, 0)))
        for path, blob in targets:
            dst = out / "files" / path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(blob)
            done.append(path)
        stats["replaced"] += 1
    log("files: " + ", ".join("%s %d" % kv for kv in sorted(stats.items())))
    return done


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", type=Path, required=True, help="the English build's tree")
    ap.add_argument("--en-rom", type=Path, required=True)
    ap.add_argument("--rom", type=Path, required=True, help="the language's ROM")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    t0 = time.time()

    port = args.tree / "3ds_port"
    en = args.en_rom.read_bytes()
    xx = args.rom.read_bytes()
    code = xx[0xAC:0xB0].decode("ascii", "replace")
    if code not in LANG_CODES or en[0xAC:0xB0] != b"BPRE":
        raise SystemExit("lang_overlay: expected an English FireRed and another language's (got %s)" % code)
    lang = LANG_CODES[code]
    log("%s ROM (%s)" % (lang, code))
    sys.path.insert(0, str(ROOT / "builder"))

    regions = load_regions(port)
    syms = [s for reg in regions for s in reg.syms]
    log("%d symbols (%d game data, %d scripts)" % (len(syms), len(regions[0].syms), len(regions[1].syms)))

    pmap = PointerMap()
    log("code and tables both ROMs share: %d pointer pairs" % align_words(en, xx, pmap))

    n = place(regions, en, "en", lambda s: True)
    log("placed in the English ROM: %d of %d (%.0fs)" % (n, len(syms), time.time() - t0))

    report = Counter()
    misses: list[tuple[str, str]] = []

    easy_chat: set[int] = set()   # English addresses of Easy Chat words
    debug = {int(v, 16) for v in os.environ.get("LANG_OVERLAY_DEBUG", "").split(",") if v}
    sources: dict[int, list] = defaultdict(list)

    def harvest():
        for s in syms:
            if s.en is None or s.xx is None:
                continue
            for rel, tid, toff in s.sites:
                a = struct.unpack_from("<I", en, s.en + rel)[0]
                b = struct.unpack_from("<I", xx, s.xx + rel)[0]
                if is_pointer(a, len(en)) and is_pointer(b, len(xx)):
                    pmap.add(a, b, 4)
                    if EASY_CHAT.search(s.name):
                        easy_chat.add(a)
                    if a in debug:
                        sources[a].append((s.name, rel, hex(b)))

    def nearby(s):
        """A pointer table the code reaches at an offset (table - first id): the
        pointers just before it give the language's place, which its own sites
        confirm (every one a pointer there, everything else the same)."""
        keys = sorted_keys()
        a = ROM_BASE + s.en
        i = bisect.bisect_left(keys, a - 0x400)
        found = set()
        mask = s.mask
        while i < len(keys) and keys[i] < a + s.size:
            x = pmap.get(keys[i])
            i += 1
            if x is None:
                continue
            cand = a + (x - keys[i - 1]) - ROM_BASE
            if cand in found or not 0 <= cand <= len(xx) - s.size:
                continue
            ok = all(is_pointer(struct.unpack_from("<I", xx, cand + rel)[0], len(xx)) for rel, _, _ in s.sites)
            if ok and all(mask[k] or xx[cand + k] == en[s.en + k] for k in range(s.size)):
                found.add(cand)
        return ROM_BASE + found.pop() if len(found) == 1 else None

    _keys = []

    def sorted_keys():
        if len(_keys) != len(pmap.votes):
            _keys[:] = sorted(pmap.votes)
        return _keys

    def resolve():
        got = 0
        for s in syms:
            if s.en is None or s.xx is not None or s.new is not None:
                continue
            x = pmap.get(ROM_BASE + s.en)
            if x is None and s.sites and not is_string(s.data):
                x = nearby(s)
            if x is None:
                continue
            if not is_string(s.data) and not table_spec(s.name)[0]:
                s.xx = x - ROM_BASE   # a table both ROMs point at: its pointers pair up
                got += 1
                continue
            new, kind = translate(s, xx, x - ROM_BASE)
            if new is None:
                continue
            s.xx, s.new = x - ROM_BASE, new
            got += 1
        return got

    def walk():
        """Text between two placed script symbols: the language's, in the same order."""
        got = 0
        for reg in regions[1:]:
            order = reg.syms
            for i in range(1, len(order)):
                s, before = order[i], order[i - 1]
                if s.xx is not None or before.xx is None or s.en is None or before.en is None:
                    continue
                if before.off + before.size != s.off or before.en + before.size != s.en:
                    continue
                x = before.xx + sym_len(before, "xx")
                if is_string(s.data):
                    new = read_string(xx, x)
                    if new is None:
                        continue
                    after = order[i + 1] if i + 1 < len(order) else None
                    if after is not None and after.xx is not None and after.xx != x + len(new):
                        continue
                    s.xx, s.new = x, new
                    got += 1
                else:
                    data, mask = expected(s, regions, "xx")
                    if all(mask[k] or xx[x + k] == data[k] for k in range(s.size)):
                        s.xx = x
                        got += 1
        return got

    for round_no in range(8):
        same = place(regions, xx, "xx", lambda s: s.en is not None and s.new is None)
        harvest()
        mapped = resolve()
        walked = walk()
        log("round %d: %d placed as they are, %d through pointers, %d in order (%.0fs)"
            % (round_no + 1, same, mapped, walked, time.time() - t0))
        if not (same or mapped or walked):
            break

    for a in sorted(debug):
        log("debug %08x: votes %s, from %s" % (a, dict(pmap.votes.get(a, {})), sources.get(a)))
        for s in syms:
            if s.en is not None and ROM_BASE + s.en == a:
                log("debug %08x is %s (%s)" % (a, s.name, s.region))

    # The Easy Chat words of each initial letter: the language's own lists, as
    # long as its table says (each language has other words under each letter).
    by_en = {s.en: s for s in syms if s.en is not None and s.region == 0}
    for t in syms:
        if t.name != "sEasyChatWordsByLetterPointers" or t.en is None or t.xx is None:
            continue
        for k in range(0, t.size - 7, 8):
            a = struct.unpack_from("<I", en, t.en + k)[0] - ROM_BASE
            b, n = struct.unpack_from("<II", xx, t.xx + k)
            lst = by_en.get(a)
            if lst is not None and lst.key and is_pointer(b, len(xx)) and 0 < n < 4096:
                lst.xx = b - ROM_BASE
                lst.new = xx[lst.xx:lst.xx + 2 * n]
                lst.new += bytes(1) * ((-len(lst.new)) % 4 if len(lst.data) % 4 == 0 else 0)

    # Text the English ROM holds more than once: what most of its copies became.
    shared = 0
    for s in syms:
        if s.en is not None or len(text_body(s.data)) < 3:
            continue
        if not is_string(s.data) and not (table_spec(s.name)[0] and not s.sites):
            continue   # text, or a table of plain values (font widths) both ROMs repeat
        body = text_body(s.data) if is_string(s.data) else s.data
        hits, p = [], en.find(body)
        while p >= 0 and len(hits) < 32:
            hits.append(p)
            p = en.find(body, p + 1)
        news: dict[bytes, list] = {}
        word = bool(EASY_CHAT.search(s.name))
        hits = [h for h in hits if ((ROM_BASE + h) in easy_chat) == word]
        for h in hits:
            x = pmap.get(ROM_BASE + h)
            if x is not None:
                new, _ = translate(s, xx, x - ROM_BASE)
                if new is not None:
                    news.setdefault(new, []).append((h, x - ROM_BASE))
        ranked = sorted(news.items(), key=lambda kv: -len(kv[1]))
        if ranked and (len(ranked) == 1 or len(ranked[0][1]) > len(ranked[1][1])):
            new, places = ranked[0]
            s.en, s.xx = places[0]
            s.new = new
            shared += 1
    log("text the English ROM holds more than once: %d" % shared)

    # Text right after a translated string in the English ROM is right after its
    # translation in the language's (the strings of one unit sit together).
    def end_of(rom: bytes, start: int, length: int) -> int:
        p = start + length
        while p % 4 and p < len(rom) and rom[p] == 0:
            p += 1
        return p
    # Both neighbours must agree: lists sorted by their text (the Easy Chat
    # words) are in another order in each language.
    neighbours = 0
    for _ in range(4):
        by_end, by_start = {}, {}
        for t in syms:
            if t.en is not None and t.xx is not None and t.new is not None and is_string(t.data):
                by_end[end_of(en, t.en, len(text_body(t.data)))] = t
                by_start[t.en] = t
        got = 0
        for s in syms:
            if s.new is not None or not is_string(s.data) or len(text_body(s.data)) < 2:
                continue
            body = text_body(s.data)
            found = {}
            p = en.find(body)
            while p >= 0 and len(found) < 4:
                t = by_end.get(p)
                after = by_start.get(end_of(en, p, len(body)))
                if ((ROM_BASE + p) in easy_chat) != bool(EASY_CHAT.search(s.name)):
                    t = None
                if t is not None and after is not None:
                    x = end_of(xx, t.xx, len(text_body(t.new)))
                    new, _ = translate(s, xx, x)
                    if new is not None and end_of(xx, x, len(text_body(new))) == after.xx:
                        found.setdefault(new, (p, x))
                p = en.find(body, p + 1)
            if len(found) == 1:
                new, (p, x) = found.popitem()
                s.en, s.xx, s.new = p, x, new
                got += 1
        neighbours += got
        if not got:
            break
    log("text found next to its neighbours: %d" % neighbours)

    # Text only the code points at, from code that moved: the bytes around each
    # pointer (other pointers and branch offsets aside) are found in the
    # language's ROM, and the word at the same place there is its pointer.
    by_code = 0
    for s in syms:
        if s.en is None or s.new is not None or not is_string(s.data):
            continue
        news = set()
        needle = struct.pack("<I", ROM_BASE + s.en)
        p = en.find(needle)
        while p >= 0 and len(news) < 2:
            if p % 4 == 0:
                x = code_context(en, xx, p)
                if x is not None:
                    new, _ = translate(s, xx, x)
                    if new is not None:
                        news.add((new, x))
            p = en.find(needle, p + 1)
        if len({n for n, _ in news}) == 1:
            s.new, s.xx = next(iter(news))
            by_code += 1
    log("text found through the code around its pointer: %d" % by_code)

    # Text whose pointer sits in a literal pool next to pointers already paired:
    # the same pool in the language's ROM, found through a paired neighbour.
    by_pool = 0
    for s in syms:
        if s.en is None or s.new is not None or not is_string(s.data):
            continue
        news = set()
        needle = struct.pack("<I", ROM_BASE + s.en)
        p = en.find(needle)
        while p >= 0:
            if p % 4 == 0:
                for d in range(-32, 36, 4):
                    if not d:
                        continue
                    q = p + d
                    if not 0 <= q <= len(en) - 4:
                        continue
                    target = pmap.get(struct.unpack_from("<I", en, q)[0])
                    if target is None:
                        continue
                    pool = struct.pack("<I", target)
                    r = xx.find(pool)
                    sites = []
                    while r >= 0 and len(sites) < 4:
                        if r % 4 == 0:
                            sites.append(r)
                        r = xx.find(pool, r + 1)
                    if len(sites) != 1:
                        continue
                    at = sites[0] - d
                    if 0 <= at <= len(xx) - 4:
                        w = struct.unpack_from("<I", xx, at)[0]
                        if is_pointer(w, len(xx)):
                            new, _ = translate(s, xx, w - ROM_BASE)
                            if new is not None:
                                news.add((new, w - ROM_BASE))
            p = en.find(needle, p + 1)
        if len({n for n, _ in news}) == 1:
            s.new, s.xx = next(iter(news))
            by_pool += 1
    log("text found through a literal pool: %d" % by_pool)

    # A run of strings between two paired ones: when the language's ROM holds
    # as many strings between the same two, they pair in order.
    def strings_in(rom: bytes, start: int, end: int) -> list[tuple[int, bytes]] | None:
        out, p = [], start
        while p < end:
            q = rom.find(bytes([EOS]), p, end)
            if q < 0:
                return None
            out.append((p, rom[p:q + 1]))
            p = end_of(rom, q, 1)
        return out if p == end else None

    placed = sorted((t for t in syms if t.region == 0 and t.en is not None and t.xx is not None
                     and t.new is not None and is_string(t.data)), key=lambda t: t.en)
    runs: dict[int, bytes] = {}
    for t, u in zip(placed, placed[1:]):
        a, b = end_of(en, t.en, len(text_body(t.data))), u.en
        c, d = end_of(xx, t.xx, len(text_body(t.new))), u.xx
        if not (0 < b - a <= 2048 and 0 < d - c <= 4096):
            continue
        ens, xxs = strings_in(en, a, b), strings_in(xx, c, d)
        if ens and xxs and len(ens) == len(xxs) and len(ens) <= 16:
            for (pe, _), (_, sx) in zip(ens, xxs):
                runs[pe] = sx
    by_run = 0
    for s in syms:
        if s.new is not None or not is_string(s.data) or s.region != 0:
            continue
        body = text_body(s.data)
        news, where = set(), None
        p = en.find(body)
        while p >= 0:
            if p in runs:
                where = p
                news.add(runs[p] + b"\0" * (len(s.data) - len(body)))
            p = en.find(body, p + 1)
        if len(news) == 1:
            s.new = news.pop()
            if s.en is None:
                s.en = where
            by_run += 1
    log("text found in runs between paired strings: %d" % by_run)

    overlay = {"c": {}, "asm": {}}
    for s in syms:
        if s.en is None:
            if is_string(s.data):
                report["text not in the English ROM"] += 1
                misses.append(("not in the English ROM", s.name))
            continue
        if s.new is None:
            if s.xx is not None:
                known, _ = table_spec(s.name)
                if known:
                    s.new, _ = translate(s, xx, s.xx)
            elif is_string(s.data) or table_spec(s.name)[0]:
                report["unmapped"] += 1
                misses.append(("unmapped", s.name))
                continue
        if s.new is None or s.new == s.data:
            continue
        if s.region == 0:
            if s.key is None:
                report["not resizable"] += 1
                misses.append(("not alone in its section", s.name))
                continue
            overlay["c"][s.key] = s.new.hex()
            report["game data"] += 1
        elif is_string(s.data) and s.key:
            overlay["asm"][s.key] = s.new.hex()
            report["script text"] += 1
    log("overlay: " + ", ".join("%s %d" % kv for kv in sorted(report.items())))

    args.out.mkdir(parents=True, exist_ok=True)
    files = file_overlay(args.tree, en, xx, pmap, args.out, misses)
    overlay.update({"lang": lang, "code": code, "rom_sha1": hashlib.sha1(xx).hexdigest(), "files": files})
    (args.out / "overlay.json").write_text(json.dumps(overlay, indent=0, sort_keys=True), encoding="utf-8")
    (args.out / "misses.txt").write_text("".join("%s\t%s\n" % m for m in misses), encoding="utf-8")
    log("%s: %d C symbols, %d script texts, %d files (%.0fs)"
        % (args.out, len(overlay["c"]), len(overlay["asm"]), len(files), time.time() - t0))


if __name__ == "__main__":
    main()
