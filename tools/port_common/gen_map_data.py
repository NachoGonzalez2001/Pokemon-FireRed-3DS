#!/usr/bin/env python3

"""Externalise map/border payloads and emit 12-byte descriptors in their place.

The layout table keeps one descriptor (payload offset, size, kind) per map or
border blob; the blobs themselves go to maps/layouts.bin, which the runtime
keeps resident (see 3ds_port/src/3ds_map_loader.c)."""

from pathlib import Path
import argparse
import re


ROOT = Path(__file__).resolve().parents[2]
PORT_DIR = ROOT / "3ds_port"
FS_DIR = PORT_DIR / "romfs"
OUT_DIR = FS_DIR / "maps"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build = PORT_DIR / "build"
    build.mkdir(parents=True, exist_ok=True)
    layouts = (ROOT / "data/layouts/layouts.inc").read_text()
    payload = bytearray()
    descriptors = []
    maxima = [0, 0]

    def externalize(match):
        symbol, path, kind = match.groups()
        data = (ROOT / path).read_bytes()
        if not data or len(data) % 2:
            raise ValueError(f"Invalid map payload: {path}")
        slot = int(kind == "border")
        maxima[slot] = max(maxima[slot], len(data))
        descriptors.extend([f"{symbol}::", f"\t.4byte {len(payload)}, {len(data)}, {slot}"])
        payload.extend(data)
        return ""

    layouts, count = re.subn(
        r'([A-Za-z_][A-Za-z_0-9]*)::\s*\.incbin "(data/layouts/[^"\n]+/(map|border)\.bin)"',
        externalize, layouts,
    )
    if not count or ".incbin" in layouts:
        raise ValueError("Unrecognized layout payload declarations")
    layouts += '\n\t.pushsection .rodata.port_map_assets, "a"\n\t.align 2\n'
    layouts += "gPortMapAssetsStart::\n" + "\n".join(descriptors)
    layouts += "\ngPortMapAssetsEnd::\ngPortMapAssetMaxSizes::\n"
    layouts += f"\t.4byte {maxima[0]}, {maxima[1]}\n\t.popsection\n"
    (build / "map_layouts.inc").write_text(layouts, encoding="ascii")
    include_rel = (build / "map_layouts.inc").relative_to(ROOT).as_posix()
    maps = (ROOT / "data/maps.s").read_text().replace(
        '"data/layouts/layouts.inc"', f'"{include_rel}"'
    )
    (build / "maps.s").write_text(maps, encoding="ascii")
    (OUT_DIR / "layouts.bin").write_bytes(payload)
    print(f"gen_map_data: {count} descriptors ({count * 12} bytes), "
          f"{len(payload)} payload bytes; cache maxima map={maxima[0]} border={maxima[1]}")


def configure(argv=None):
    global PORT_DIR, FS_DIR, OUT_DIR

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-dir", default=str(PORT_DIR))
    parser.add_argument("--fs-dir", default=None)
    args = parser.parse_args(argv)

    PORT_DIR = Path(args.port_dir).resolve()
    FS_DIR = Path(args.fs_dir).resolve() if args.fs_dir else PORT_DIR / "romfs"
    OUT_DIR = FS_DIR / "maps"


if __name__ == "__main__":
    configure()
    main()
