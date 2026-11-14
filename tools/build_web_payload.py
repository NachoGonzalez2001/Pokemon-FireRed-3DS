#!/usr/bin/env python3
"""Make the web builder's payload: FireRed3DS-WebPayload.zip and web-manifest.json.

    python tools/build_web_payload.py --payload dist/FireRed3DS-v0.5.1-Windows/payload \
        --version 0.5.1 [--cia FireRed3DS-Forwarder.cia] [--out dist]
    python tools/build_web_payload.py --synthetic DIR

The website (site/) runs the builder's own Python package under Pyodide in the
browser, on the files of this ZIP; builder/firered3ds_builder/webmanifest.py
describes its layout and the manifest. The ZIP holds the release's payload
(executable, recipe, voxel generators), the builder package without its
desktop window, and the licences: never a ROM, a data pack or anything taken
from the game. tools/build_release.py calls this after assembling the payload.

--synthetic writes a payload made from a synthetic "ROM" (no game data), the
ZIP and the manifest, for the tests and for trying the website without a ROM.
The ZIP is deterministic: the same inputs give the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))

from firered3ds_builder import __version__ as BUILDER_VERSION  # noqa: E402
from firered3ds_builder import pak, webmanifest  # noqa: E402
from firered3ds_builder.recipe import Recipe  # noqa: E402
from firered3ds_builder.rom import KNOWN_CODES, ROM_PROFILES  # noqa: E402

APP = "FireRed3DS"
PACKAGE = ROOT / "builder" / "firered3ds_builder"
# The desktop front ends are of no use in a browser (tkinter, the SD card).
DESKTOP_ONLY = {"gui.py", "install.py", "cli.py", "__main__.py"}
LICENSES = [(ROOT / "NOTICE.md", "licenses/NOTICE.md"),
            (ROOT / "3ds_port" / "src" / "voxel" / "NOTICE.md", "licenses/voxel-NOTICE.md")]
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
LANG_NAMES = {"BPRS": "es", "BPRF": "fr", "BPRI": "it", "BPRD": "de", "BPRJ": "ja"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect(payload: Path, licenses=None) -> dict[str, bytes]:
    """Every file of the web payload: {zip path: bytes}."""
    files: dict[str, bytes] = {}
    for path in sorted(Path(payload).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files["payload/" + path.relative_to(payload).as_posix()] = path.read_bytes()
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name not in DESKTOP_ONLY:
            files["python/firered3ds_builder/" + path.name] = path.read_bytes()
    for src, dst in (LICENSES if licenses is None else licenses):
        files[dst] = Path(src).read_bytes()
    for name in files:
        if name.lower().endswith(webmanifest.FORBIDDEN_SUFFIXES):
            raise SystemExit("refusing to put %s into the web payload" % name)
    return files


def _ref(files: dict[str, bytes], path: str, release_asset: str | None = None) -> dict:
    ref = {"path": path, "sha256": sha256(files[path]), "size": len(files[path])}
    if release_asset is not None:
        ref["releaseAsset"] = release_asset
    return ref


def _rom_info(sha1: str, folder: str) -> dict:
    code = next((c for c, s in ROM_PROFILES.items() if s == sha1), None)
    if code is None:
        code = next((c for c, lang in LANG_NAMES.items() if lang == folder), "BPRE")
    return {"sha1": sha1, "code": code, "name": KNOWN_CODES.get(code, "Pokemon FireRed").replace("Pokemon", "Pokémon")}


def make_manifest(files: dict[str, bytes], version: str, tag: str, cia_name: str | None = None) -> dict:
    recipe = Recipe.from_bytes(files["payload/firered3ds.recipe"])
    assets = {
        "threeDsx": _ref(files, "payload/%s.3dsx" % APP, "%s.3dsx" % APP),
        "smdh": _ref(files, "payload/%s.smdh" % APP, "%s.smdh" % APP),
        "recipe": _ref(files, "payload/firered3ds.recipe", None),
        "ciaForwarder": None if not cia_name else {
            "releaseAsset": cia_name, "target": "sdmc:/%s/%s.3dsx" % (webmanifest.INSTALL_DIR, APP)},
    }
    variants = []
    folders = sorted({p.split("/")[1] for p in files
                      if p.startswith("payload/") and p.count("/") == 2 and p.endswith("/firered3ds.recipe")})
    for folder in folders:
        sub = Recipe.from_bytes(files["payload/%s/firered3ds.recipe" % folder])
        variants.append({
            "rom": _rom_info(sub.rom_sha1, folder),
            "dataAbi": "%08x" % sub.engine_abi,
            "recipeRelease": sub.release,
            "assets": {
                "threeDsx": _ref(files, "payload/%s/%s.3dsx" % (folder, APP), "%s-%s.3dsx" % (APP, folder)),
                "smdh": _ref(files, "payload/%s/%s.smdh" % (folder, APP), "%s-%s.smdh" % (APP, folder)),
                "recipe": _ref(files, "payload/%s/firered3ds.recipe" % folder, None),
            },
        })
    manifest = {
        "schemaVersion": webmanifest.SCHEMA_VERSION,
        "kind": webmanifest.KIND,
        "releaseVersion": version,
        "releaseTag": tag,
        "builderVersion": BUILDER_VERSION,
        "dataAbi": "%08x" % recipe.engine_abi,
        "packSchema": pak.SCHEMA,
        "supportedRoms": [_rom_info(recipe.rom_sha1, "")],
        "entrypoint": dict(webmanifest.ENTRYPOINT),
        "install": {"dir": webmanifest.INSTALL_DIR, "files": list(webmanifest.INSTALL_FILES)},
        "assets": assets,
        "files": [_ref(files, path) for path in sorted(files)],
    }
    if variants:
        manifest["variants"] = variants
    return webmanifest.validate(manifest)


def write_zip(path: Path, files: dict[str, bytes], manifest: dict) -> None:
    entries = dict(files)
    entries[webmanifest.MANIFEST_NAME] = manifest_bytes(manifest)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in [webmanifest.MANIFEST_NAME] + sorted(files):
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, entries[name])


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build(payload: Path, version: str, out: Path, cia_name: str | None = None, licenses=None) -> dict:
    """Write <out>/FireRed3DS-WebPayload.zip and <out>/web-manifest.json."""
    files = collect(payload, licenses)
    manifest = make_manifest(files, version, "v" + version.lstrip("v"), cia_name)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / webmanifest.PAYLOAD_NAME
    write_zip(zip_path, files, manifest)
    manifest_path = out / webmanifest.MANIFEST_NAME
    manifest_path.write_bytes(manifest_bytes(manifest))
    print("web payload: %s (%.1f MiB), %s" % (zip_path, zip_path.stat().st_size / 1048576, manifest_path))
    return {"zip": zip_path, "manifest": manifest_path}


# --- synthetic payload (tests, trying the website without a ROM) -------------

SYN_GEN_RELIEF = '''import argparse, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    data = open(os.path.join(ROOT, "data", "in.bin"), "rb").read()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    open(args.output, "wb").write(bytes(b ^ 0x5A for b in data))
if __name__ == "__main__":
    main()
'''
SYN_GEN_TREES = '''import argparse, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    data = open(os.path.join(ROOT, "data", "in.bin"), "rb").read()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    open(args.output, "wb").write(data[::-1])
if __name__ == "__main__":
    main()
'''


def _synthetic_rom(code: bytes, seed: int) -> bytes:
    data = bytearray(0x10000)
    state = seed
    for i in range(0, len(data), 4):          # xorshift: deterministic noise
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        struct.pack_into("<I", data, i, state)
    data[0xA0:0xB0] = b"SYNTHETIC\0\0\0" + code
    return bytes(data)


def _crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _synthetic_variant(folder: Path, rom: bytes, release: str) -> None:
    """An executable, smdh and recipe for one synthetic ROM: two files copied
    from it, one filled, and two made by the generators from a third."""
    from firered3ds_builder.rom import ROM_SIZE
    full = rom + b"\xff" * (ROM_SIZE - len(rom))
    a, b = full[0x1000:0x1400], b"\x07" * 300
    tree_input = full[0x2000:0x2100]
    relief = bytes(x ^ 0x5A for x in tree_input)
    trees = tree_input[::-1]
    entries = [{"path": "data/a.bin", "size": len(a), "crc": _crc(a), "ops": [["C", 0x1000, len(a)]]},
               {"path": "data/b.bin", "size": len(b), "crc": _crc(b), "ops": [["F", 7, len(b)]]}]
    generated = [{"path": "voxel/relief.bin", "size": len(relief), "crc": _crc(relief), "generator": "fr_gen_relief.py"},
                 {"path": "voxel/trees.rgba5551", "size": len(trees), "crc": _crc(trees), "generator": "fr_gen_trees.py"}]
    items = [(e["path"], e["size"], e["crc"]) for e in entries + generated]
    vtree = {"tilesets": {}, "layouts": [], "layouts_table_label": "gMapLayouts", "maps": [],
             "script_layouts": {}, "map_types": {}, "metatiles_h": [], "headers_h": [], "graphics_h": [],
             "behaviours": {}}
    inputs = [{"path": "data/in.bin", "size": len(tree_input), "crc": _crc(tree_input),
               "ops": [["C", 0x2000, len(tree_input)]]}]
    import hashlib as _h
    recipe = Recipe(engine_abi=pak.engine_abi(items), rom_sha1=_h.sha1(full).hexdigest(), release=release,
                    entries=entries, generated=generated, inputs=inputs, vtree=vtree)
    folder.mkdir(parents=True, exist_ok=True)
    recipe.save(folder / "firered3ds.recipe")
    (folder / ("%s.3dsx" % APP)).write_bytes(b"3DSX" + bytes([len(folder.name)]) * 60)
    (folder / ("%s.smdh" % APP)).write_bytes(b"SMDH" + bytes([len(folder.name)]) * 60)


def make_synthetic(root: Path) -> dict:
    """A synthetic release: payload/ (English variant and an es/ one), the two
    ROMs, the ZIP and the manifest."""
    root = Path(root)
    payload = root / "payload"
    rom_en, rom_es = _synthetic_rom(b"BPRE", 0x1234567), _synthetic_rom(b"BPRS", 0x7654321)
    _synthetic_variant(payload, rom_en, "v0.0.0-synthetic")
    _synthetic_variant(payload / "es", rom_es, "v0.0.0-synthetic")
    scripts = payload / "voxelgen" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "fr_gen_relief.py").write_text(SYN_GEN_RELIEF, encoding="utf-8", newline="\n")
    (scripts / "fr_gen_trees.py").write_text(SYN_GEN_TREES, encoding="utf-8", newline="\n")
    (root / "rom.gba").write_bytes(rom_en)
    (root / "rom-es.gba").write_bytes(rom_es)
    out = build(payload, "0.0.0", root / "release")
    return {"zip": out["zip"], "manifest": out["manifest"], "payload": payload,
            "rom": root / "rom.gba", "rom_es": root / "rom-es.gba"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payload", type=Path, help="a release's payload/ folder")
    ap.add_argument("--version", help="the release's version, e.g. 0.5.1")
    ap.add_argument("--cia", help="the release asset name of the HOME Menu forwarder, if there is one")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    ap.add_argument("--synthetic", type=Path, metavar="DIR", help="write a synthetic payload into DIR")
    args = ap.parse_args()
    if args.synthetic:
        out = make_synthetic(args.synthetic)
        print("synthetic ROMs: %s, %s" % (out["rom"], out["rom_es"]))
        return
    if not args.payload or not args.version:
        ap.error("--payload and --version are needed (or --synthetic DIR)")
    build(args.payload, args.version, args.out, args.cia)


if __name__ == "__main__":
    main()
