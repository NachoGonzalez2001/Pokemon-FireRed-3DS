"""The Pokemon that follows the player: its sprites, fetched at install time.

The walking and standing animations of the 386 Pokemon of the game come from
PMD SpriteCollab (https://github.com/PMDCollab/SpriteCollab), a public
repository of Pokemon Mystery Dungeon style sprites, at a pinned commit so
every install gets the same files. Most of them are Spike Chunsoft's own
sprites from the Mystery Dungeon games, so neither this repository nor its
releases carry any: the builder downloads them on the player's computer, as
it reads the player's ROM, and writes followers.bin and
followers-credits.txt next to the game on the SD card. Without a connection
the game is installed all the same, without its follower.

followers.bin (little endian), read by src/voxel/voxel_follower.c:

    "FRFW" u32 version (1) u32 count (387: national dex numbers 0..386)
    u32 offset[count] u32 size[count]      (0, 0: no sprites for that number)
    entry: two animations, walking then standing, each
        u8 frames (per direction, at most 16) u8 pad[3]
        u16 palette[16]                    (GBA BGR555, index 0 transparent)
        u8 durations[16]                   (sixtieths of a second)
        frame[8 * frames], direction major (down, down-right, right,
            up-right, up, up-left, left, down-left), each
            s8 dx s8 dy                    (its top left from the ground point)
            u8 w u8 h u32 offset           (4 bpp pixels, low nibble first,
                                            row by row, from the entry start)
"""

from __future__ import annotations

import concurrent.futures
import io
import os
import struct
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

COMMIT = "7df3fd29224c28cb1d54c056ef7c9fd295017d5d"
SOURCE = "https://raw.githubusercontent.com/PMDCollab/SpriteCollab/%s/" % COMMIT
SPECIES = 386
FILES = ("AnimData.xml", "Walk-Anim.png", "Walk-Shadow.png", "Idle-Anim.png", "Idle-Shadow.png",
         "credits.txt")
OPTIONAL = {"Idle-Anim.png", "Idle-Shadow.png"}
MAX_FRAMES = 16
MAX_DIM = 128            # the game's follower cell in the sprite atlas
DIRECTIONS = 8
VERSION = 1
OUTPUTS = ("followers.bin", "followers-credits.txt")


class FollowerError(Exception):
    pass


def _download(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def fetch(cache: Path | None = None, progress=None, workers: int = 8) -> dict:
    """{(number, name): bytes or None} for every species and file, plus
    (0, "credit_names.txt"). `cache` keeps the downloads (tests, reruns)."""
    jobs = [(n, name) for n in range(1, SPECIES + 1) for name in FILES] + [(0, "credit_names.txt")]
    out: dict = {}

    def one(job):
        n, name = job
        rel = name if n == 0 else "sprite/%04d/%s" % (n, name)
        path = cache / rel if cache else None
        if path is not None and path.exists():
            return job, path.read_bytes()
        if path is not None and path.with_suffix(path.suffix + ".missing").exists():
            return job, None
        data = _download(SOURCE + rel)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is None:
                path.with_suffix(path.suffix + ".missing").write_bytes(b"")
            else:
                path.write_bytes(data)
        return job, data

    try:
        with concurrent.futures.ThreadPoolExecutor(workers) as pool:
            for i, (job, data) in enumerate(pool.map(one, jobs)):
                out[job] = data
                if progress and i % 50 == 0:
                    progress(i / len(jobs))
    except OSError as exc:
        raise FollowerError("The follower sprites could not be downloaded: %s" % exc) from exc
    for n in range(1, SPECIES + 1):
        for name in FILES:
            if out.get((n, name)) is None and name not in OPTIONAL:
                raise FollowerError("SpriteCollab has no %s for Pokemon #%d." % (name, n))
    return out


def _anims(xml: bytes) -> dict:
    root = ET.fromstring(xml)
    anims = {}
    for a in root.iter("Anim"):
        name = a.findtext("Name")
        if a.find("CopyOf") is not None:
            anims[name] = ("copy", a.findtext("CopyOf"))
        else:
            anims[name] = (int(a.findtext("FrameWidth")), int(a.findtext("FrameHeight")),
                           [int(d.text) for d in a.iter("Duration")])
    return anims


def _bgr555(rgba) -> int:
    r, g, b, _ = rgba
    return (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10


def _anchor(shadow: Image.Image, box) -> tuple[float, float]:
    """The ground point of a frame: the middle of its shadow marker."""
    bb = shadow.crop(box).getbbox()
    w, h = box[2] - box[0], box[3] - box[1]
    if bb is None:
        return w / 2, h * 0.75
    return (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2


def _frames(sheet: bytes, size) -> int:
    fw, _, durations = size
    return min(len(durations), Image.open(io.BytesIO(sheet)).width // fw, MAX_FRAMES)


def _pack_anim(sheet: bytes, shadow: bytes | None, size, pixels: bytearray, base: int) -> bytes:
    """One animation: its header and frame records; its pixels go into
    `pixels`, whose first byte is `base` bytes from the entry start."""
    fw, fh, durations = size
    image = Image.open(io.BytesIO(sheet)).convert("RGBA")
    marker = Image.open(io.BytesIO(shadow)).convert("RGBA") if shadow else None
    frames = _frames(sheet, size)
    colours = sorted({p for p in image.getdata() if p[3] > 0})
    if len(colours) > 15:
        raise FollowerError("a sheet with %d colours" % len(colours))
    index = {c: i + 1 for i, c in enumerate(colours)}
    palette = [0] + [_bgr555(c) for c in colours] + [0] * (15 - len(colours))
    head = struct.pack("<B3x", frames) + struct.pack("<16H", *palette)
    head += bytes(min(d, 255) for d in durations[:frames]) + bytes(MAX_FRAMES - frames)
    records = b""
    for d in range(DIRECTIONS):
        for f in range(frames):
            box = (f * fw, d * fh, (f + 1) * fw, (d + 1) * fh)
            ax, ay = _anchor(marker, box) if marker else (fw / 2, fh * 0.75)
            frame = image.crop(box)
            bb = frame.getbbox() or (0, 0, 1, 1)
            bb = (bb[0], bb[1], min(bb[2], bb[0] + MAX_DIM), min(bb[3], bb[1] + MAX_DIM))
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            px = frame.load()
            packed = bytearray((w * h + 1) // 2)
            for y in range(h):
                for x in range(w):
                    p = px[bb[0] + x, bb[1] + y]
                    i = index[p] if p[3] > 0 else 0
                    k = y * w + x
                    packed[k // 2] |= i << ((k & 1) * 4)
            offset = base + len(pixels)
            pixels += packed
            pixels += bytes((-len(pixels)) % 4)
            records += struct.pack("<bbBBI", int(round(bb[0] - ax)), int(round(bb[1] - ay)), w, h, offset)
    return head + records


def _anim_bytes(n: int, files: dict, name: str):
    """(sheet, shadow, size) of an animation, a copy resolved to its source."""
    anims = _anims(files[(n, "AnimData.xml")])
    a = anims.get(name)
    if a is None or a[0] == "copy" or files.get((n, name + "-Anim.png")) is None:
        source = a[1] if a and a[0] == "copy" else "Walk"
        return files[(n, source + "-Anim.png")], files.get((n, source + "-Shadow.png")), anims[source]
    return files[(n, name + "-Anim.png")], files.get((n, name + "-Shadow.png")), a


def pack(files: dict) -> bytes:
    count = SPECIES + 1
    entries = []
    for n in range(1, SPECIES + 1):
        anims = [_anim_bytes(n, files, "Walk"), _anim_bytes(n, files, "Idle")]
        heads = [52 + 8 * DIRECTIONS * _frames(sheet, size) for sheet, _, size in anims]
        pixels = bytearray()
        base = sum(heads)
        body = b"".join(_pack_anim(sheet, shadow, size, pixels, base) for sheet, shadow, size in anims)
        assert len(body) == base, (n, len(body), base)
        entries.append(body + bytes(pixels))
    table = 12 + 8 * count
    offsets, sizes, cursor = [0], [0], table
    for e in entries:
        offsets.append(cursor)
        sizes.append(len(e))
        cursor += len(e)
    return (b"FRFW" + struct.pack("<II", VERSION, count) + struct.pack("<%dI" % count, *offsets)
            + struct.pack("<%dI" % count, *sizes) + b"".join(entries))


def credits(files: dict) -> str:
    """Every artist of the sprites used, as SpriteCollab credits them."""
    names = {}
    for line in (files.get((0, "credit_names.txt")) or b"").decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) >= 2:
            names[cols[1]] = (cols[0], cols[2] if len(cols) > 2 else "")
    lines = ["Pokemon follower sprites: PMD SpriteCollab, https://github.com/PMDCollab/SpriteCollab",
             "(commit %s). Community sprites are CC BY-NC 4.0; sprites credited to" % COMMIT,
             "CHUNSOFT are Spike Chunsoft's, from the Pokemon Mystery Dungeon games.",
             "Downloaded by the builder on this computer; not part of the release.", ""]
    for n in range(1, SPECIES + 1):
        who = []
        for line in (files.get((n, "credits.txt")) or b"").decode("utf-8", "replace").splitlines():
            cols = line.split("\t")
            if len(cols) >= 5 and ({"Walk", "Idle"} & set(cols[4].split(","))):
                name, contact = names.get(cols[1], (cols[1], ""))
                entry = name + (" (%s)" % contact if contact and contact != name else "")
                if entry not in who:
                    who.append(entry)
        lines.append("#%03d: %s" % (n, ", ".join(who) or "unknown"))
    return "\n".join(lines) + "\n"


def default_cache() -> Path:
    """Where the downloads are kept between installs: an update of the game
    fetches nothing again (the commit is pinned)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "FireRed3DS" / ("spritecollab-" + COMMIT[:12])


def build(out_dir: Path, cache: Path | None = None, progress=None) -> dict:
    """Fetches and writes followers.bin and followers-credits.txt into
    out_dir. Raises FollowerError when the sprites cannot be had."""
    if cache is None:
        cache = default_cache()
    try:
        files = fetch(cache, progress)
    except FollowerError:
        raise
    except Exception as exc:     # no connection, a proxy, a full disk
        raise FollowerError("The follower sprites could not be downloaded: %s" % exc) from exc
    data = pack(files)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "followers.bin").write_bytes(data)
    (out_dir / "followers-credits.txt").write_text(credits(files), encoding="utf-8")
    return {"bytes": len(data), "species": SPECIES}
