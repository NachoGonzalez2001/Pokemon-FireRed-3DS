#!/usr/bin/env python3
"""Build Pokémon FireRed 3DS in another language.

    python tools/lang/build_lang.py --tree C:/fr3ds/upstream --overlay C:/fr3ds/lang/es/overlay \
        --work C:/fr3ds/lang/es/tree [--no-clean] [--prepare-only] [-- <make targets>]

The English tree (bootstrapped and built: lang_overlay.py reads its build) is
mirrored into --work, and the copy is turned into the language's:

* the language overlay (lang_overlay.py, made from that language's ROM on
  this machine): the scripts' text is written into the event script sources,
  the tree files (graphics, tilesets, fonts, layouts) are replaced, and the C
  units' text is given to their objects before the link
  (3ds_port/scripts/lang_patch_objects.py, LANG_OVERLAY);
* the port's own text in that language (3ds_port/lang/<lang>.json, part of
  the repository): the Mega Evolution text and the bottom screen's labels;
* GAME_LANGUAGE, so the Pokémon caught there carry the language's mark.

Then make runs in the copy (default targets: all release). Its staging is the
language's (the recipe is cut from it with that language's ROM, like the
English one) and its dist/ holds the language's executable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lang_overlay  # noqa: E402

LANGUAGE_CONSTANTS = {"ja": "LANGUAGE_JAPANESE", "en": "LANGUAGE_ENGLISH", "fr": "LANGUAGE_FRENCH",
                      "it": "LANGUAGE_ITALIAN", "de": "LANGUAGE_GERMAN", "es": "LANGUAGE_SPANISH"}
# Never mirrored: the English build's outputs. The copy builds its own.
SKIP_DIRS = {".git", "3ds_port/build", "3ds_port/dist"}
GENERATED_ROMFS = ["assets", "data", "generated", "graphics", "maps", "scripts", "sound",
                   "gamedata", "engine", "voxel", "data.embedded"]


def log(msg: str) -> None:
    print("build_lang: " + msg, flush=True)


def mirror(src: Path, dst: Path) -> None:
    """dst becomes a copy of src (changed files only), the build outputs aside."""
    if sys.platform == "win32":
        xd = [str(src / d) for d in SKIP_DIRS] + [str(dst / d) for d in SKIP_DIRS]
        cmd = ["robocopy", str(src), str(dst), "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS",
               "/NP", "/XD"] + xd
        code = subprocess.call(cmd)
        if code >= 8:
            raise SystemExit("build_lang: robocopy failed (%d)" % code)
        return
    subprocess.check_call(["rsync", "-a", "--delete"] + ["--exclude=/%s" % d for d in SKIP_DIRS]
                          + [str(src) + "/", str(dst) + "/"])


def encode(tree: Path, texts: dict[str, str]) -> dict[str, bytes]:
    """Text in the game's notation ({PLAYER}, \\n, POKéMON...) to the game's bytes,
    through the tree's own preproc and charmap.txt, with the end of string."""
    if not texts:
        return {}
    preproc = tree / "tools" / "preproc" / ("preproc" + (".exe" if sys.platform == "win32" else ""))
    names = sorted(texts)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "text.s"
        with src.open("w", encoding="utf-8", newline="\n") as f:
            for i, name in enumerate(names):
                body = texts[name].replace('"', '\\"')   # \n, \p, \l as in the game's sources
                f.write("T%d:\n\t.string \"%s$\"\n" % (i, body))
        env = dict(os.environ)
        ucrt = os.environ.get("UCRT", "C:/msys64/ucrt64") + "/bin"
        if Path(ucrt).is_dir():   # the decomp's tools are built with MSYS2 UCRT64 (tools/dkp.sh)
            env["PATH"] = str(Path(ucrt)) + os.pathsep + env.get("PATH", "")
        out = subprocess.check_output([str(preproc), str(src), str(tree / "charmap.txt")],
                                      cwd=tree, text=True, encoding="utf-8", env=env)
    result, cur, buf = {}, None, bytearray()
    for line in out.splitlines():
        m = re.match(r"^T(\d+):", line)
        if m:
            if cur is not None:
                result[names[cur]] = bytes(buf)
            cur, buf = int(m.group(1)), bytearray()
            continue
        m = re.match(r"^\s*\.byte\s+(.*)$", line)
        if m and cur is not None:
            buf.extend(int(v.strip(), 0) for v in m.group(1).split(",") if v.strip())
    if cur is not None:
        result[names[cur]] = bytes(buf)
    for name, data in result.items():
        if not data or data[-1] != 0xFF or 0xFF in data[:-1]:
            raise SystemExit("build_lang: %s did not encode to one string" % name)
    return result


def rewrite_scripts(tree: Path, texts: dict[str, bytes]) -> set[str]:
    """Write each label's text, as bytes, over its .string lines."""
    done: set[str] = set()
    for path in sorted(list((tree / "data").rglob("*.inc")) + list((tree / "data").rglob("*.s"))):
        lines = path.read_text(encoding="utf-8").split("\n")
        out, i, changed = [], 0, False
        while i < len(lines):
            m = re.match(r"^(\w+)::?\s*(@.*)?$", lines[i])
            if m and m.group(1) in texts:
                j = i + 1
                while j < len(lines) and re.match(r"^\s*\.string\s", lines[j]):
                    j += 1
                if j > i + 1:
                    data = texts[m.group(1)]
                    out.append(lines[i])
                    for k in range(0, len(data), 16):
                        out.append("\t.byte " + ", ".join("0x%02x" % b for b in data[k:k + 16]))
                    done.add(m.group(1))
                    changed = True
                    i = j
                    continue
            out.append(lines[i])
            i += 1
        if changed:
            path.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return done


def ui_header(tree: Path, ui: dict[str, str], out: Path) -> None:
    """The bottom screen's labels in the language: English key -> the game's bytes."""
    enc = encode(tree, {"u%d" % i: text for i, text in enumerate(ui.values())})
    rows = []
    for i, key in enumerate(ui):
        if not key.isascii() or '"' in key or "\\" in key:
            raise SystemExit("build_lang: UI key %r must be plain ASCII" % key)
        data = enc["u%d" % i]
        rows.append((key.encode("ascii"), key, data))
    rows.sort()
    text = ["/* Generated by tools/lang/build_lang.py. Do not edit. */",
            "#define PORT_LANG_UI_COUNT %d" % len(rows),
            "static const struct PortLangText sPortLangUi[] = {"]
    for _, key, data in rows:
        text.append('    {"%s", (const u8[]){%s}},' % (key, ", ".join("0x%02x" % b for b in data)))
    text.append("};")
    out.write_text("\n".join(text) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", type=Path, required=True, help="the English tree, built")
    ap.add_argument("--overlay", type=Path, required=True, help="lang_overlay.py's output")
    ap.add_argument("--work", type=Path, required=True, help="where the language's tree goes")
    ap.add_argument("--no-clean", action="store_true", help="keep the copy's previous build")
    ap.add_argument("--prepare-only", action="store_true", help="make the tree, do not build")
    ap.add_argument("--make", default="make")
    ap.add_argument("--jobs", default="4")
    ap.add_argument("targets", nargs="*", default=["all", "release"])
    args = ap.parse_args()

    overlay_path = (args.overlay / "overlay.json").resolve()
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    lang = overlay["lang"]
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    log("%s: mirroring %s" % (lang, args.tree))
    mirror(args.tree.resolve(), work)
    port = work / "3ds_port"
    if not args.no_clean:
        shutil.rmtree(port / "build", ignore_errors=True)
        for name in GENERATED_ROMFS:
            p = port / "romfs" / name
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()

    # The language ROM's tree files.
    for rel in overlay["files"]:
        dst = work / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.overlay / "files" / rel, dst)
    log("%d tree files from the language's ROM" % len(overlay["files"]))

    # The port's own text in the language.
    own_path = ROOT / "3ds_port" / "lang" / ("%s.json" % lang)
    own = json.loads(own_path.read_text(encoding="utf-8")) if own_path.is_file() else {}
    game = own.get("game", {})
    encoded = encode(work, game)
    script_names = {s.name for s in lang_overlay.script_symbols(args.tree / "3ds_port")}
    gamedata = {}
    for s in lang_overlay.gamedata_symbols(args.tree / "3ds_port"):
        gamedata.setdefault(s.name, []).append(s)
    c_overlay = dict(overlay["c"])
    asm_texts = {k: bytes.fromhex(v) for k, v in overlay["asm"].items()}
    for name, data in encoded.items():
        obj = None
        if "|" in name:   # "<object stem>|<symbol>" for a name two units define
            obj, sym = name.split("|", 1)
        else:
            sym = name
        if obj is None and sym in script_names:
            asm_texts[sym] = data
            continue
        found = [s for s in gamedata.get(sym, []) if s.key and (obj is None or obj in s.key.split("|")[0])]
        if len(found) != 1:
            raise SystemExit("build_lang: %s: %s names %d symbols" % (own_path.name, name, len(found)))
        old = found[0].data
        pad = len(old) - len(old.rstrip(b"\0"))
        c_overlay[found[0].key] = (data + b"\0" * pad).hex()
    log("%d texts of the port's own (%s)" % (len(encoded), own_path.name if own else "none"))

    done = rewrite_scripts(work, asm_texts)
    missing = sorted(set(asm_texts) - done)
    log("%d script texts written, %d labels not found%s" % (len(done), len(missing),
        (": " + ", ".join(missing[:8])) if missing else ""))

    patched = port / "lang_overlay.json"
    patched.write_text(json.dumps({"c": c_overlay}, sort_keys=True), encoding="utf-8")
    log("%d C symbols for the link" % len(c_overlay))

    ui_header(work, own.get("ui", {}), port / "src" / "port_lang_table.h")
    # The data pack this executable takes: one made from the language's ROM.
    sha = bytes.fromhex(overlay["rom_sha1"])
    names = {"BPRS": "Pokemon FireRed (Spain)", "BPRF": "Pokemon FireRed (France)",
             "BPRD": "Pokemon FireRed (Germany)", "BPRI": "Pokemon FireRed (Italy)",
             "BPRJ": "Pokemon FireRed (Japan)"}
    (port / "src" / "port_rom.h").write_text(
        "/* Generated by tools/lang/build_lang.py. Do not edit. */\n"
        "#define PORT_ROM_SHA1 %s\n#define PORT_ROM_NAME \"%s\"\n"
        % (", ".join("0x%02x" % b for b in sha), names.get(overlay["code"], overlay["code"])),
        encoding="utf-8", newline="\n")

    glob_h = work / "include" / "constants" / "global.h"
    text = glob_h.read_text(encoding="utf-8")
    text = re.sub(r"#define GAME_LANGUAGE \(LANGUAGE_\w+\)",
                  "#define GAME_LANGUAGE (%s)" % LANGUAGE_CONSTANTS[lang], text)
    glob_h.write_text(text, encoding="utf-8", newline="\n")

    (port / "local.mk").write_text(
        "# Written by tools/lang/build_lang.py: the %s build.\n"
        "LANG_OVERLAY := lang_overlay.json\n" % lang,
        encoding="utf-8", newline="\n")
    if args.prepare_only:
        log("prepared %s" % work)
        return
    for target in args.targets:
        cmd = [args.make, "-j" + args.jobs, target] if target != "release" else [args.make, target]
        log("make %s" % " ".join(cmd[1:]))
        subprocess.check_call(cmd, cwd=port)
    log("built %s" % work)


if __name__ == "__main__":
    main()
