# PyInstaller spec: one folder, windowed, no UPX (fewer antivirus false positives).
# Built by tools/build_release.py; run from the builder/ directory.
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["emerald3ds-builder.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    # The voxel generators are plain scripts run through --run-script; every
    # module they import is listed in build/hidden-imports.txt by
    # tools/build_release.py so that it is bundled.
    hiddenimports=["PIL.Image", "PIL.ImageDraw", "runpy"] + [
        line.strip() for line in open("build/hidden-imports.txt", encoding="utf-8") if line.strip()],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# The window, and a console twin for the command line and for running the
# bundled generator scripts (a windowed executable has no stdout).
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Emerald3DS-Builder",
          debug=False, strip=False, upx=False, console=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="emerald3ds-builder-cli",
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="Emerald3DS-Builder")
