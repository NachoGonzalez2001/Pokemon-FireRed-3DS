"""Put the game on an SD card (or any folder laid out like one)."""

from __future__ import annotations

import os
import shutil
import string
import sys
from pathlib import Path

from .errors import BuilderError

APP_DIR = Path("3ds") / "emerald3ds"


def find_sd_cards() -> list[Path]:
    """Mounted volumes that look like a 3DS SD card (they hold 'Nintendo 3DS').

    Only a suggestion: the builder never installs anywhere without the
    player choosing the destination."""
    candidates: list[Path] = []
    if os.name == "nt":
        roots = [Path("%s:\\" % letter) for letter in string.ascii_uppercase]
    elif sys.platform == "darwin":
        roots = list(Path("/Volumes").glob("*"))
    else:
        roots = [p for base in ("/media", "/run/media") for p in Path(base).glob("*/*")]
    for root in roots:
        try:
            if (root / "Nintendo 3DS").is_dir():
                candidates.append(root)
        except OSError:
            continue
    return candidates


def install(sd_root: Path, files: dict[str, Path], progress=None) -> Path:
    """Copy `files` ({name: source}) into <sd_root>/3ds/emerald3ds/.

    Each file is written under a temporary name first and renamed into place,
    so a card pulled out mid-copy never holds a half-written pack."""
    sd_root = Path(sd_root)
    if not sd_root.is_dir():
        raise BuilderError("The destination folder does not exist:\n%s" % sd_root)
    dest = sd_root / APP_DIR
    need = sum(src.stat().st_size for src in files.values())
    try:
        free = shutil.disk_usage(sd_root).free
    except OSError:
        free = need
    if free < need + (4 << 20):
        raise BuilderError("There is not enough free space on the destination (%d MiB needed)."
                           % ((need >> 20) + 4))
    dest.mkdir(parents=True, exist_ok=True)
    done = 0
    for name, src in files.items():
        tmp = dest / (name + ".partial")
        with src.open("rb") as fin, tmp.open("wb") as fout:
            while True:
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                fout.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done / max(need, 1))
            fout.flush()
            os.fsync(fout.fileno())
        os.replace(tmp, dest / name)
    return dest
