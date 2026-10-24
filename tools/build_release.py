#!/usr/bin/env python3
"""Assemble a Pokémon FireRed 3DS release.

    python tools/build_release.py --version 0.1.0 --rom baserom.gba [--tree C:/fr3ds/upstream]

Before it, in the build tree (tools/bootstrap.py, then devkitPro's make in
<tree>/3ds_port): `make all` (the staging the recipe is cut from) and
`make release` (dist/FireRed3DS.3dsx and .smdh, engine files only).

Steps (each can be skipped when its output is already there):

1. the recipe (tools/gen_recipe.py) from the build's staging and the ROM;
2. the payload: executable, recipe and the voxel generator scripts;
3. the standalone builder (PyInstaller, one folder, no UPX), or with
   --python-builder the builder as Python sources (needs Python 3.11+ and
   Pillow on the player's computer);
4. dist/FireRed3DS-v<version>-Windows.zip with the builder, the payload,
   README.txt and LICENSES/;
5. the standalone dist/FireRed3DS.3dsx and .smdh (a quick update of the
   executable when the data ABI did not change), and the HOME Menu forwarder
   dist/FireRed3DS-Forwarder.cia when 3ds_port/forwarder/dist has one;
6. tools/release_audit.py over the ZIP (and a scan for any run of the ROM's
   bytes), then SHA256SUMS.txt over every release asset.

The ROM is read to write the recipe and to audit; it is never copied into the
release. The release never contains a data pack.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = "FireRed3DS"
CIA_NAME = APP + "-Forwarder.cia"
GENERATORS = ["fr_gen_relief.py", "fr_gen_trees.py", "fr_export_buildings.py"]
VOXELGEN_FILES = ["src/voxel/voxel_props_table.h"]


def run(cmd, cwd=None):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def local_closure(scripts_dir: Path, names: list[str]) -> tuple[list[str], set[str]]:
    """The generator scripts plus every sibling module they import, and the
    external modules they need bundled."""
    todo = [n for n in names if (scripts_dir / n).exists()]
    seen, external = set(), set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((scripts_dir / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            for mod in mods:
                top = mod.split(".")[0]
                if (scripts_dir / (top + ".py")).exists():
                    todo.append(top + ".py")
                else:
                    external.add(mod)
    return sorted(seen), external


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--rom", type=Path, required=True)
    ap.add_argument("--tree", type=Path, default=Path("C:/fr3ds/upstream"), help="the build tree")
    ap.add_argument("--nm", default="C:/devkitPro/devkitARM/bin/arm-none-eabi-nm.exe")
    ap.add_argument("--skip-recipe", action="store_true")
    ap.add_argument("--python-builder", action="store_true",
                    help="ship the builder as Python sources instead of a PyInstaller executable")
    args = ap.parse_args()

    port = args.tree / "3ds_port"
    tag = "v" + args.version
    release = DIST / ("%s-%s-Windows" % (APP, tag))
    payload = release / "payload"
    for name in (APP + ".3dsx", APP + ".smdh"):
        if not (port / "dist" / name).exists():
            sys.exit("%s is missing: run make release in %s first" % (port / "dist" / name, port))

    DIST.mkdir(parents=True, exist_ok=True)
    recipe = DIST / "firered3ds.recipe"
    if not args.skip_recipe:
        run([sys.executable, ROOT / "tools/gen_recipe.py", "--romfs", port / "romfs", "--rom", args.rom,
             "--decomp", args.tree, "--out", recipe, "--release", tag,
             "--elf", port / "build/gamedata_image.elf", "--nm", args.nm,
             "--report", DIST / "recipe-literal-report.txt"])

    if release.exists():
        shutil.rmtree(release)
    payload.mkdir(parents=True)
    for name in (APP + ".3dsx", APP + ".smdh"):
        shutil.copy2(port / "dist" / name, payload / name)
    shutil.copy2(recipe, payload / "firered3ds.recipe")
    scripts, external = local_closure(port / "scripts", GENERATORS)
    (payload / "voxelgen" / "scripts").mkdir(parents=True)
    for name in scripts:
        shutil.copy2(port / "scripts" / name, payload / "voxelgen" / "scripts" / name)
    for rel in VOXELGEN_FILES:
        dst = payload / "voxelgen" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(port / rel, dst)

    if args.python_builder:
        shutil.copytree(ROOT / "builder" / "firered3ds_builder", release / "firered3ds_builder",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "builder" / "firered3ds-builder.py", release / "firered3ds-builder.py")
    else:
        build = ROOT / "builder" / "build"
        build.mkdir(parents=True, exist_ok=True)
        (build / "hidden-imports.txt").write_text("\n".join(sorted(external)) + "\n", encoding="utf-8")
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", build / "dist", "--workpath", build / "pyi", "firered3ds-builder.spec"],
            cwd=ROOT / "builder")
        shutil.copytree(build / "dist" / (APP + "-Builder"), release, dirs_exist_ok=True)

    shutil.copy2(ROOT / "builder" / "README-release.txt", release / "README.txt")
    licenses = release / "LICENSES"
    licenses.mkdir()
    shutil.copy2(ROOT / "NOTICE.md", licenses / "NOTICE.md")
    shutil.copy2(ROOT / "3ds_port/src/voxel/NOTICE.md", licenses / "voxel-NOTICE.md")

    archive = DIST / ("%s-%s-Windows.zip" % (APP, tag))
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(release.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(DIST).as_posix())

    standalone = []
    for name in (APP + ".3dsx", APP + ".smdh"):
        shutil.copy2(payload / name, DIST / name)
        standalone.append(DIST / name)
    cia = port / "forwarder" / "dist" / CIA_NAME
    if cia.exists():
        shutil.copy2(cia, DIST / CIA_NAME)
        standalone.append(DIST / CIA_NAME)

    run([sys.executable, ROOT / "tools/release_audit.py", "--zip", archive, "--strict", "--rom", args.rom])
    sums = DIST / "SHA256SUMS.txt"
    assets = [archive] + standalone
    lines = ["%s  %s" % (sha256(path), path.name) for path in assets]
    for path in sorted(payload.glob("*")):
        if path.is_file():
            lines.append("%s  payload/%s" % (sha256(path), path.relative_to(payload).as_posix()))
    sums.write_text("\n".join(lines) + "\n", encoding="ascii")
    for path in assets:
        print("release asset: %s (%.1f MiB)" % (path, path.stat().st_size / 1048576))
    print("release asset: %s" % sums)


if __name__ == "__main__":
    main()
