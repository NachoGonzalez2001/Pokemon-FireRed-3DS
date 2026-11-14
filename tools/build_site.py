#!/usr/bin/env python3
"""Assemble the website (site/) with a release's web builder files.

    python tools/build_site.py --windows-zip dist/FireRed3DS-v0.5.1-Windows.zip \
        --tag v0.5.1 [--published-at 2026-11-14T19:14:30Z] [--notes dist/RELEASE_NOTES.md] \
        [--cia] [--out build/site]

The output is a static site, ready for GitHub Pages (.github/workflows/site.yml
runs this on every release):

* the pages and scripts of site/;
* img/: the project's icon, logo and screenshots (docs/screenshots);
* payload/: FireRed3DS-WebPayload.zip and web-manifest.json, made by
  tools/build_web_payload.py from the payload/ folder of the release's Windows
  ZIP, and release.json (the version, its date, highlights and notes, links).

The web payload is the release's own payload: the same executable, recipe and
generators as the Windows builder, with the builder package of this checkout.
It never holds a ROM or anything taken from the game (the manifest's checks
and tools/release_audit.py --web-payload say so).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_web_payload  # noqa: E402

REPO = "NachoGonzalez2001/Pokemon-FireRed-3DS"
APP = "FireRed3DS"


def inline(text: str) -> str:
    """The Markdown the release notes use inside a line: **bold**, `code`, [links](url)."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                 lambda m: '<a href="%s" rel="noopener">%s</a>' % (html.escape(m.group(2)), m.group(1)), out)
    return out


def markdown(text: str) -> str:
    """Headings, paragraphs and (nested) lists: what RELEASE_NOTES.md holds."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []          # (indent, "ul"/"ol") of the open lists
    para: list[str] = []

    def close_para():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            para.clear()

    def close_lists(indent: int = -1):
        while stack and stack[-1][0] > indent:
            out.append("</li></%s>" % stack.pop()[1])

    for raw in text.splitlines():
        line = raw.rstrip()
        item = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if not line.strip():
            close_para()
            continue
        if line.startswith("#"):
            close_para()
            close_lists()
            level = min(len(line) - len(line.lstrip("#")) + 1, 4)
            out.append("<h%d>%s</h%d>" % (level, inline(line.lstrip("#").strip()), level))
        elif item:
            close_para()
            indent, kind = len(item.group(1)), ("ol" if item.group(2)[0].isdigit() else "ul")
            if stack and stack[-1][0] > indent:
                close_lists(indent)
            if not stack or stack[-1][0] < indent:
                out.append("<%s><li>%s" % (kind, inline(item.group(3))))
                stack.append((indent, kind))
            else:
                out.append("</li><li>%s" % inline(item.group(3)))
        elif stack and raw.startswith(" "):
            out[-1] += " " + inline(line.strip())
        else:
            close_lists()
            para.append(line.strip())
    close_para()
    close_lists()
    return "\n".join(out)


def highlights(notes: str) -> list[str]:
    """The bold lead of each item under "### New in ...": the release's news in a line each."""
    out, inside = [], False
    for line in notes.splitlines():
        if line.startswith("### "):
            inside = line.lower().startswith("### new in")
            continue
        m = re.match(r"^- \*\*(.+?)\*\*", line)
        if inside and m:
            out.append(m.group(1).rstrip(".:"))
    return out


def images(out: Path) -> None:
    img = out / "img"
    (img / "screenshots").mkdir(parents=True, exist_ok=True)
    for path in sorted((ROOT / "docs" / "screenshots").glob("*.png")):
        shutil.copy2(path, img / "screenshots" / path.name)
    art = ROOT / "3ds_port" / "assets" / "artwork"
    Image.open(art / "icon_large.png").convert("RGBA").resize((128, 128), Image.LANCZOS).save(img / "icon.png", optimize=True)
    logo = Image.open(art / "FireRed 3DS.png").convert("RGBA")
    logo = logo.resize((1200, round(1200 * logo.height / logo.width)), Image.LANCZOS)
    logo.save(img / "logo.webp", quality=88, method=6)
    og = Image.new("RGBA", (1200, 630), (255, 248, 241, 255))
    og.alpha_composite(logo, (0, (630 - logo.height) // 2))
    og.convert("RGB").save(img / "og.png", optimize=True)


def payload_from_zip(windows_zip: Path, work: Path) -> Path:
    with zipfile.ZipFile(windows_zip) as zf:
        names = [n for n in zf.namelist() if "/payload/" in n and not n.endswith("/")]
        if not names:
            raise SystemExit("%s has no payload/ folder" % windows_zip)
        for name in names:
            rel = name.split("/payload/", 1)[1]
            dst = work / "payload" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(zf.read(name))
    return work / "payload"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--windows-zip", type=Path, help="the release's FireRed3DS-v<version>-Windows.zip")
    src.add_argument("--payload", type=Path, help="a release's payload/ folder")
    ap.add_argument("--tag", required=True, help="the release's tag, e.g. v0.5.1")
    ap.add_argument("--published-at", default="", help="the release's date (ISO 8601)")
    ap.add_argument("--notes", type=Path, help="the release notes (Markdown)")
    ap.add_argument("--cia", action="store_true", help="the release has %s-Forwarder.cia" % APP)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "site")
    args = ap.parse_args()

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    images(out)

    version = args.tag.lstrip("v")
    cia_name = APP + "-Forwarder.cia" if args.cia else None
    with tempfile.TemporaryDirectory() as tmp:
        payload = args.payload or payload_from_zip(args.windows_zip, Path(tmp))
        build_web_payload.build(payload, version, out / "payload", cia_name)

    download = "https://github.com/%s/releases/download/%s/" % (args.repo, args.tag)
    notes = args.notes.read_text(encoding="utf-8") if args.notes else ""
    info = {
        "tag": args.tag,
        "version": version,
        "publishedAt": args.published_at or None,
        "highlights": highlights(notes),
        "notesHtml": markdown(notes) if notes else "",
        "assets": {
            "windowsZip": download + "%s-%s-Windows.zip" % (APP, args.tag),
            "cia": download + cia_name if cia_name else None,
        },
    }
    (out / "payload" / "release.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print("site: %s (%.1f MiB)" % (out, size / 1048576))


if __name__ == "__main__":
    main()
