#!/usr/bin/env python3
"""Write a small synthetic data pack with the builder's writer, for pak_test.c."""

import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "builder"))
from emerald3ds_builder import pak  # noqa: E402

FILES = [
    ("maps/layouts.bin", bytes(range(256)) * 3),
    ("graphics/fonts/normal.latfont", b"\x11\x22" * 1000),
    ("gamedata/gamedata.bin", b"G" * 4097),
    ("voxel/relief.bin", b""),
]
ROM_SHA1 = bytes.fromhex("f3ae088181bf583e55daf962a92bb46f4f1d07b7")

out = Path(sys.argv[1])
abi = pak.engine_abi([(p, len(d), zlib.crc32(d) & 0xFFFFFFFF) for p, d in FILES])
pak.write_pak(out, FILES, abi, ROM_SHA1)
print("%08x" % abi)
