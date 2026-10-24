"""Host tests for the builder. They use synthetic data only: no ROM is needed
and none may ever be committed. Run: python -m unittest discover builder/tests
"""

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firered3ds_builder import pak, recipe as rcp, rom as romlib, vtree  # noqa: E402
from firered3ds_builder.build import Payload, build_pack
from firered3ds_builder.errors import BuilderError  # noqa: E402
from firered3ds_builder.install import install  # noqa: E402


def lz77_literal(data: bytes) -> bytes:
    """A valid GBA LZ77 stream that stores everything as literals."""
    out = bytearray([0x10, len(data) & 0xFF, (len(data) >> 8) & 0xFF, (len(data) >> 16) & 0xFF])
    for i in range(0, len(data), 8):
        out.append(0)
        out += data[i:i + 8]
    while len(out) % 4:
        out.append(0)
    return bytes(out)


class PakTests(unittest.TestCase):
    def test_roundtrip_and_verify(self):
        files = [("maps/layouts.bin", b"\x01\x02" * 100), ("graphics/a.4bpp", bytes(range(256))),
                 ("gamedata/gamedata.bin", b"")]
        abi = pak.engine_abi([(p, len(d), zlib.crc32(d) & 0xFFFFFFFF) for p, d in files])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "x.pak"
            info = pak.write_pak(out, files, abi, b"\x11" * 20)
            self.assertEqual(info["entries"], 3)
            with pak.PakReader(out) as reader:
                self.assertEqual(reader.abi, abi)
                self.assertEqual(reader.verify(), 3)
                self.assertEqual(reader.read("graphics/a.4bpp"), bytes(range(256)))
                offsets = [e.offset for e in reader.entries.values()]
                self.assertTrue(all(o % pak.ALIGN == 0 for o in offsets))

    def test_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "x.pak"
            pak.write_pak(out, [("a/b", b"hello world" * 10)], 7, b"\0" * 20)
            raw = bytearray(out.read_bytes())
            raw[-20] ^= 0xFF
            out.write_bytes(raw)
            with pak.PakReader(out) as reader:
                with self.assertRaises(pak.PakError):
                    reader.verify()
            raw[20] ^= 0xFF   # header
            out.write_bytes(raw)
            with self.assertRaises(pak.PakError):
                pak.PakReader(out)

    def test_rejects_bad_paths(self):
        for bad in ("/abs", "../up", "c:/x", ""):
            with self.assertRaises(pak.PakError):
                pak.normalise(bad)

    def test_path_id_is_fnv1a64(self):
        # Reference value: FNV-1a 64 of "a".
        self.assertEqual(pak.path_id("a"), 0xaf63dc4c8601ec8c)


class RecipeTests(unittest.TestCase):
    def test_all_operations(self):
        rom = bytearray(range(256)) * 16
        packed = lz77_literal(b"ABCDEFGHIJ")
        rom[1024:1024 + len(packed)] = packed
        # records of 4 bytes {a, b, pad, pad} become 2 bytes {b, a}
        records = bytes([1, 2, 0, 0, 3, 4, 0, 0])
        rom[2048:2056] = records
        bitmap = [8 + i for i in range(8)] + [i for i in range(8)]
        literals = b"LITPTR"
        entry = {"path": "x", "ops": [["C", 16, 4], ["F", 0xAA, 3], ["L", 0, 3], ["Z", 1024],
                                      ["R", 2048, 4, 2, 2, 0]],
                 "patches": [[4, 3, 3]]}
        expected = bytes(rom[16:20]) + b"PTR" + b"LIT" + b"ABCDEFGHIJ" + bytes([2, 1, 4, 3])
        entry["size"] = len(expected)
        entry["crc"] = zlib.crc32(expected) & 0xFFFFFFFF
        self.assertEqual(rcp.build_entry(entry, bytes(rom), literals, [bitmap]), expected)

    def test_mismatch_raises(self):
        entry = {"path": "x", "ops": [["F", 1, 4]], "size": 4, "crc": 0}
        with self.assertRaises(rcp.RecipeError):
            rcp.build_entry(entry, b"", b"", [])

    def test_container_roundtrip(self):
        r = rcp.Recipe(engine_abi=5, rom_sha1="00" * 20, release="t",
                       entries=[{"path": "a", "size": 1, "crc": 2, "ops": [["F", 0, 1]]}],
                       literals=b"xyz")
        back = rcp.Recipe.from_bytes(r.to_bytes())
        self.assertEqual((back.engine_abi, back.entries, back.literals), (5, r.entries, b"xyz"))


class RomTests(unittest.TestCase):
    def _write(self, tmp, data, name="game.gba"):
        path = Path(tmp) / name
        path.write_bytes(data)
        return path

    def test_wrong_rom_is_rejected_with_its_name(self):
        data = bytearray(b"\xff" * romlib.ROM_SIZE)
        data[0xA0:0xB0] = b"POKEMON EMERBPEE"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BuilderError) as ctx:
                romlib.load_rom(self._write(tmp, bytes(data)))
            self.assertIn("Emerald", ctx.exception.message)

    def test_modified_firered_is_rejected(self):
        data = bytearray(b"\xff" * romlib.ROM_SIZE)
        data[0xA0:0xB0] = b"POKEMON FIREBPRE"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BuilderError) as ctx:
                romlib.load_rom(self._write(tmp, bytes(data)))
            self.assertIn("not an unmodified", ctx.exception.message)
            self.assertIn(romlib.SUPPORTED_SHA1, str(ctx.exception))

    def test_requires_the_exact_hash_even_when_trimmed_or_zipped(self):
        # Synthetic fixtures substitute the known clean hash, not the validation.
        data = bytearray(b"\xff" * romlib.ROM_SIZE)
        data[0xA0:0xB0] = b"POKEMON FIREBPRE"
        sha = hashlib.sha1(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(romlib.ROM_PROFILES, {"BPRE": sha}):
            full = self._write(tmp, data)
            trimmed = self._write(tmp, data[:0xC0], "trimmed.gba")
            zipped = Path(tmp) / "game.zip"
            with zipfile.ZipFile(zipped, "w") as zf:
                zf.writestr("game.gba", data[:0xC0])
            for path in (full, trimmed, zipped):
                loaded = romlib.load_rom(path)
                self.assertEqual((loaded.code, loaded.sha1, loaded.data), ("BPRE", sha, data))

    def test_zip_must_hold_one_rom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("a.gba", b"1")
                zf.writestr("b.gba", b"2")
            with self.assertRaises(BuilderError):
                romlib.load_rom(path)


WEB_PAYLOAD_TOOL = Path(__file__).resolve().parents[2] / "tools" / "build_web_payload.py"


class VariantPayloadTests(unittest.TestCase):
    @unittest.skipUnless(WEB_PAYLOAD_TOOL.exists(), "tools/build_web_payload.py (the web builder) is not here yet")
    def test_build_picks_the_variant_made_from_the_rom(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
        import build_web_payload
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                synthetic = build_web_payload.make_synthetic(Path(tmp) / "s")
            payload = Payload(synthetic["payload"])
            self.assertEqual([v.root.name for v in payload.variants()], ["payload", "es"])
            for rom, name in ((synthetic["rom"], "payload"), (synthetic["rom_es"], "es")):
                data = rom.read_bytes() + b"\xff" * (romlib.ROM_SIZE - rom.stat().st_size)
                sha = hashlib.sha1(data).hexdigest()
                checked = romlib.Rom(data=data, sha1=sha, title="SYNTHETIC", code="TEST", source=rom)
                info = build_pack(rom, payload, Path(tmp) / ("%s.pak" % name), runner="inprocess",
                                  rom=checked)
                self.assertEqual(info["payload"].root.name, name)
                self.assertEqual(info["payload"].voxelgen, synthetic["payload"] / "voxelgen")
                with pak.PakReader(Path(tmp) / ("%s.pak" % name)) as reader:
                    self.assertEqual(reader.rom_sha1.hex(), sha)


class InstallTests(unittest.TestCase):
    def test_install_writes_the_app_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.bin"
            src.write_bytes(b"x" * 1000)
            sd = Path(tmp) / "sd"
            sd.mkdir()
            dest = install(sd, {"FireRed3DS.3dsx": src, "firered3ds.pak": src})
            self.assertEqual(sorted(p.name for p in dest.iterdir()), ["FireRed3DS.3dsx", "firered3ds.pak"])
            self.assertEqual(dest, sd / "3ds" / "firered3ds")


class VtreeTests(unittest.TestCase):
    def test_structures_are_read_back_from_the_rom(self):
        rom = bytearray(0x1000)
        base = 0x08000000
        # Tileset structs at 0x100 and 0x120; a layout at 0x200.
        struct.pack_into("<iiIIII", rom, 0x200, 20, 30, 0, 0, base + 0x100, base + 0x120)
        # Map header at 0x400: layout 0x200, layout id 1, map type 3.
        struct.pack_into("<IIIIHH", rom, 0x400, base + 0x200, 0, 0, 0, 0, 1)
        rom[0x417] = 3
        meta = {
            "tilesets": {"gTileset_A": 0x100, "gTileset_B": 0x120},
            "layouts_table_label": "gMapLayouts",
            "layouts": [{"id": "LAYOUT_X", "name": "X_Layout", "blockdata_filepath": "data/layouts/X/map.bin",
                         "border_filepath": "data/layouts/X/border.bin", "rom": 0x200}, {}],
            "maps": [{"folder": "Here", "id": "MAP_HERE", "name": "Here", "rom": 0x400}],
            "map_types": {"3": "MAP_TYPE_ROUTE"},
            "script_layouts": {"Here": ["LAYOUT_X"]},
            "metatiles_h": [["gMetatiles_A", "data/tilesets/primary/a/metatiles.bin"],
                            ["gMetatileAttributes_A", "data/tilesets/primary/a/metatile_attributes.bin"]],
            "headers_h": [["gTileset_A", "gTilesetTiles_A", "gMetatiles_A", "gMetatileAttributes_A"]],
            "graphics_h": [["gTilesetTiles_A", "data/tilesets/primary/a/tiles.4bpp.lz"]],
            "behaviours": {"MB_CAVE_DOOR": 0x60},
        }
        payload = b""
        rom[0x600:0x602] = payload
        r = rcp.Recipe(engine_abi=0, rom_sha1="", release="t", vtree=meta,
                       inputs=[{"path": "data/layouts/X/map.bin", "size": 2,
                                "crc": zlib.crc32(payload) & 0xFFFFFFFF, "ops": [["C", 0x600, 2]]}])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vtree.build_tree(bytes(rom), r, root)
            layouts = json.loads((root / "data/layouts/layouts.json").read_text())["layouts"]
            self.assertEqual((layouts[0]["width"], layouts[0]["height"]), (20, 30))
            self.assertEqual((layouts[0]["primary_tileset"], layouts[0]["secondary_tileset"]),
                             ("gTileset_A", "gTileset_B"))
            self.assertEqual(layouts[1], {})
            m = json.loads((root / "data/maps/Here/map.json").read_text())
            self.assertEqual((m["layout"], m["map_type"]), ("LAYOUT_X", "MAP_TYPE_ROUTE"))
            self.assertIn("setmaplayoutindex LAYOUT_X", (root / "data/maps/Here/scripts.inc").read_text())
            self.assertEqual((root / "data/layouts/X/map.bin").read_bytes(), payload)
            self.assertIn('gMetatileAttributes_A[] = INCBIN_U32(',
                          (root / "src/data/tilesets/metatiles.h").read_text())
            self.assertIn(".tiles = gTilesetTiles_A", (root / "src/data/tilesets/headers.h").read_text())
            self.assertIn("tiles.4bpp.lz", (root / "src/data/tilesets/graphics.h").read_text())
            self.assertIn("#define MB_CAVE_DOOR 0x60",
                          (root / "include/constants/metatile_behaviors.h").read_text())


if __name__ == "__main__":
    unittest.main()
