#!/usr/bin/env python3
"""Write tools/locales/french.json.gz, the BPRF localization manifest.

The manifest pairs each source literal of the port's decompilation with the
symbol of the same name in the French retail ROM. Nothing is copied out of the
ROM: files hold source spans, the SHA-256 of the file they apply to, ROM
offsets and sizes, and graphics hold one path per differing asset.

    python tools/locale_research/make_french_manifest.py \
        --elf pokefirered.elf --english-rom baserom.gba \
        --french-elf pokerougefeu.elf --french-rom rougefeu.gba \
        --tree build/upstream

--elf is the US retail link (pinned upstream, agbcc, --emit-relocs) and
--french-elf the French decompilation's own link (qigast/pokerougefeu, which
rebuilds BPRF byte for byte): their shared symbol names give the French offset
of every English symbol. --tree is a bootstrapped tree after `make generated`,
whose sources supply the spans and the fingerprints. Needs pyelftools
(tools/requirements-research.txt).

A candidate is kept only when its source literal, re-encoded with the decomp's
charmap, reproduces the English ROM bytes of that symbol exactly: that single
gate disambiguates duplicate definitions (firered and leafgreen share names),
charmap macro arguments and the EOS, and it is why a span cannot drift silently.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROM_LO, ROM_HI = 0x08000000, 0x0A000000
TREE = Path("build/upstream")
CHARMAP = TREE / "charmap.txt"
EN_ROM = FR_ROM = EN_ELF = FR_ELF = Path()

GRAPHICS_SKIPPED = {
    "data/tilesets/secondary/department_store/metatiles.bin":
        "the French ROM stores a different metatile count, and the port "
        "generates metatiles from the layouts",
}
FONT_FILES = (
    ("sFontNormalLatinGlyphs", "graphics/fonts/latin_normal.fwlatfont"),
    ("sFontMaleLatinGlyphs", "graphics/fonts/latin_male.fwlatfont"),
    ("sFontFemaleLatinGlyphs", "graphics/fonts/latin_female.fwlatfont"),
    ("sFontSmallLatinGlyphs", "graphics/fonts/latin_small.hwlatfont"),
)
C_EXTS = {".c", ".h", ".inc"}
ASM_EXTS = {".s", ".inc"}
INCBIN = re.compile(r"(\w+)\[\]\s*=\s*INCBIN_\w+\(\"([^\"]+)\"\)")
WIDTH_ARRAY = re.compile(r"static const u8 (sFont\w*LatinGlyphWidths)\[\]\s*=")


def elf_symbols(path: Path) -> dict:
    """Address, size, type and section of every named symbol."""
    symbols = {}
    with open(path, "rb") as handle:
        elf = ELFFile(handle)
        for symbol in elf.get_section_by_name(".symtab").iter_symbols():
            if symbol["st_info"]["type"] in ("STT_FILE", "STT_SECTION") or not symbol.name:
                continue
            index = symbol["st_shndx"]
            section = ""
            if isinstance(index, int) and 0 < index < elf.num_sections():
                section = elf.get_section(index).name
            symbols[symbol.name] = {"addr": symbol["st_value"], "size": symbol["st_size"],
                                    "type": symbol["st_info"]["type"], "section": section}
    return symbols


def french_offsets(english: dict, french: dict) -> dict:
    """Offset, size and category of every symbol the two links share."""
    pairs = {}
    for name in english.keys() & french.keys():
        symbol = french[name]
        if not ROM_LO <= symbol["addr"] < ROM_HI:
            continue
        if symbol["type"] == "STT_FUNC":
            kind = "fonction"
        elif re.search(r"(Text|String|_text)", name):
            kind = "texte"
        elif symbol["section"] in (".rodata", "rodata"):
            kind = "donnee rodata"
        else:
            kind = "autre donnee ROM"
        pairs[name] = [symbol["addr"] - ROM_LO, symbol["size"], kind]
    return pairs


def load_charmap():
    """charmap.txt : 'X' = NN, '\\n' = FE, '\\'' = B4, MACRO = FD 01."""
    chars, macros = {}, {}
    entry = re.compile(r"^\s*'(?P<tok>(?:\\.|[^'])*)'\s*=\s*(?P<val>[0-9A-Fa-f ]+?)\s*(?:@.*)?$")
    macro = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>[0-9A-Fa-f ]+?)\s*(?:@.*)?$")
    for raw in CHARMAP.read_text(encoding="utf-8").splitlines():
        m = entry.match(raw)
        if m:
            value = bytes.fromhex(m.group("val").replace(" ", ""))
            tok = m.group("tok")
            chars[tok] = value
            if tok.startswith("\\") and len(tok) == 2:
                chars.setdefault(tok[1], value)     # \' -> l'apostrophe nue
            continue
        m = macro.match(raw)
        if m:
            macros[m.group("name")] = bytes.fromhex(m.group("val").replace(" ", ""))
    return chars, macros


CHARS, MACROS = {}, {}


def load_characters() -> None:
    """Fill the charmap globals once the tree is known."""
    global CHARS, MACROS
    CHARS, MACROS = load_charmap()


NUM = re.compile(r"0[xX][0-9A-Fa-f]+|\d+")


def match_arg(arg: str, target: bytes, i: int):
    """Un argument de macro : la largeur et la base qui collent à la ROM."""
    if arg in MACROS:
        b = MACROS[arg]
        return i + len(b) if target[i:i + len(b)] == b else None
    if not NUM.fullmatch(arg):
        return None
    if arg.lower().startswith("0x"):
        values = [int(arg, 16)]
    else:
        values = sorted({int(arg, 10), int(arg, 16)})
    for value in values:
        for width in (1, 2):
            if value < 1 << (8 * width):
                b = value.to_bytes(width, "little")
                if target[i:i + len(b)] == b:
                    return i + len(b)
    return None


def match_literal(literal: str, target: bytes, i: int = 0):
    """Consomme un littéral en exigeant que ses octets soient ceux de la ROM.

    L'ancrage sur la ROM lève les ambiguïtés du charmap : `{CLEAR 11}` est
    décimal ou hexa, un ou deux octets, et seule la comparaison tranche.
    """
    j = 0
    while j < len(literal):
        c = literal[j]
        if c == "\\":
            b = CHARS.get(literal[j:j + 2])
            if not b or target[i:i + len(b)] != b:
                return None
            i += len(b)
            j += 2
        elif c == "{":
            end = literal.find("}", j)
            if end < 0:
                return None
            parts = literal[j + 1:end].split()
            if not parts or parts[0] not in MACROS:
                return None
            base = MACROS[parts[0]]
            if target[i:i + len(base)] != base:
                return None
            i += len(base)
            for arg in parts[1:]:
                nxt = match_arg(arg, target, i)
                if nxt is None:
                    return None
                i = nxt
            j = end + 1
        else:
            b = CHARS.get(c)
            if not b or target[i:i + len(b)] != b:
                return None
            i += len(b)
            j += 1
    return i


def sequence_matches(parts: list[str], target: bytes) -> bool:
    """Les littéraux d'un texte, bout à bout, doivent être exactement la ROM."""
    i = 0
    for part in parts:
        i = match_literal(part, target, i)
        if i is None:
            return False
    # EOS : soit le '$' du littéral (dernier octet produit), soit celui que
    # preproc ajoute après coup ; le reste n'est que remplissage d'alignement.
    if i == 0:
        return False
    rest = target[i:]
    if rest[:1] == b"\xff" and set(rest[1:]) <= {0x00}:
        return True
    return target[i - 1] == 0xFF and set(rest) <= {0x00}


STRING = re.compile(r'"((?:[^"\\]|\\.)*)"', re.S)
COND = re.compile(r"#\s*(if|ifdef|ifndef|else|elif|endif)\b(.*)")


def cond_value(kind: str, expr: str) -> bool:
    """Évalue les `#if` minuscules du dépôt, avec REVISION=1 (cible du port)."""
    expr = expr.strip()
    if kind == "ifdef":
        return True
    if kind == "ifndef":
        return False
    env = {"REVISION": 1, "FIRERED": 1, "LEAFGREEN": 0, "GERMAN": 0, "FRENCH": 1,
           "JAPANESE": 0, "ENGLISH": 0, "defined": lambda x: 1}
    expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", r"defined(\1)", expr)
    try:
        return bool(eval(expr, {"__builtins__": {}}, env))  # noqa: S307 - expressions du dépôt
    except Exception:
        return True


def c_literal_span(text: str, eq: int, target: bytes):
    """Après `<sym>[] = ` : renvoie (start, end, variantes) du contenu de _("...").

    Les blocs `#if REVISION == 0 / #else / #endif` à l'intérieur du littéral
    sont tranchés pour la révision 1, celle que le port accepte.
    """
    m = re.compile(r"\s*(__?)\(").match(text, eq + 1)
    if not m:
        return None
    # la plage couvre `_(...)` en entier : la sortie est `= {0x..};`, du C pur
    start = m.start(1)
    parts = []
    pos = start
    active = True
    stack = []
    end = None
    while pos < len(text):
        line_end = text.find("\n", pos)
        if line_end < 0:
            line_end = len(text)
        line = text[pos:line_end]
        stripped = line.strip()
        cond = COND.match(stripped)
        if cond:
            kind, expr = cond.group(1), cond.group(2)
            if kind in ("if", "ifdef", "ifndef"):
                stack.append(active)
                active = active and cond_value(kind, expr)
            elif kind == "else":
                if stack:
                    active = stack[-1] and not active
            elif kind == "endif":
                if stack:
                    active = stack.pop()
        elif active:
            for lit in STRING.finditer(line):
                parts.append(lit.group(1))
            if re.search(r"\)\s*;", line):
                end = pos + line.rindex(")") + 1   # la parenthèse fermante comprise
                break
        pos = line_end + 1
    if not parts or end is None:
        return None
    return (start, end) if sequence_matches(parts, target) else None


def asm_literal_span(text: str, label_pos: int, target: bytes):
    """Après un label `Nom::` : les lignes .string consécutives -> octets."""
    pos = text.find("\n", label_pos)
    if pos < 0:
        return None
    start = end = None
    parts = []
    while True:
        pos += 1
        m = re.match(r"[ \t]*\.string[ \t]+(.*)", text[pos:])
        if not m:
            break
        line = m.group(1)
        literals = STRING.findall(line)
        if not literals:
            break
        parts.extend(literals)
        if start is None:
            start = pos
        end = pos + len(m.group(0))
        pos = text.find("\n", pos)
        if pos < 0:
            break
    if not parts:
        return None
    return (start, end) if sequence_matches(parts, target) else None


BRAILLE_LINE = re.compile(r"[ \t]*\.braille[ \t]+(.*)")


def braille_span(text: str, label_pos: int):
    """Les lignes .braille d'un label : (start, end, ascii concaténé)."""
    pos = text.find("\n", label_pos)
    if pos < 0:
        return None
    start = end = None
    parts = []
    while True:
        pos += 1
        m = BRAILLE_LINE.match(text[pos:])
        if not m:
            break
        literals = STRING.findall(m.group(1))
        if not literals:
            break
        parts.extend(literals)
        if start is None:
            start = pos
        end = pos + len(m.group(0))
        pos = text.find("\n", pos)
        if pos < 0:
            break
    if not parts:
        return None
    return start, end, "".join(parts).encode("ascii", "replace")


def braille_matches(ascii_text: bytes, rom: bytes) -> bool:
    """Un caractère braille = un octet, terminé par EOS (le '$' du source)."""
    for candidate in (ascii_text + b"\xff", ascii_text):
        if rom[:len(candidate)] == candidate and set(rom[len(candidate):]) <= {0x00}:
            return True
    # le motif braille n'est pas l'ASCII : on vérifie seulement la structure
    body = ascii_text[:-1] if ascii_text.endswith(b"$") else ascii_text
    return rom[-1:] == b"\xff" and len(rom) == len(body) + 1


def with_eos(data: bytes) -> bytes:
    """preproc termine un `_(\"...\")` par EOS (0xFF), puis agbcc aligne sur 4."""
    d = data + b"\xff"
    if len(d) % 4:
        d += b"\x00" * (4 - len(d) % 4)
    return d


def matches(encoded, rom: bytes) -> bool:
    if not encoded:
        return False
    if isinstance(encoded, bytes):
        encoded = [encoded]
    for variant in encoded:
        # C : preproc ajoute EOS. asm : le '$' du .string est déjà EOS.
        for candidate in (variant + b"\xff", variant):
            if rom[:len(candidate)] == candidate and set(rom[len(candidate):]) <= {0x00}:
                return True
    return False


# --------------------------------------------------------------------------- sources
def source_files():
    for pattern in ("*.c", "*.h", "*.inc", "*.s"):
        for p in TREE.rglob(pattern):
            rel = p.relative_to(TREE).as_posix()
            if rel.startswith(("build/", "tools/", "3ds_port/", "builder/")):
                continue
            if p.suffix in ASM_EXTS or p.suffix in C_EXTS:
                yield p, rel


C_DEF = re.compile(r"(?m)^[^\n=;{}]*?\b([A-Za-z_][A-Za-z0-9_]*)\[\s*\]\s*=")
ASM_DEF = re.compile(r"(?m)^([A-Za-z_][A-Za-z0-9_]*):(?::)?")   # `Nom:` ou `Nom::`


def rom_string(rom: bytes, addr: int, size: int) -> bytes:
    """Les octets d'un texte dans la ROM : jusqu'à EOS, ou la taille connue."""
    start = addr - 0x08000000
    if size:
        return rom[start:start + size]
    end = rom.find(b"\xff", start)
    return rom[start:end + 1] if end >= 0 else rom[start:start + 256]

def stage_texts(pairs: dict) -> dict:
    """Source spans for every text whose bytes differ between the two ROMs."""
    english = {name: (symbol["addr"], symbol["size"])
               for name, symbol in elf_symbols(EN_ELF).items()}
    enrom = EN_ROM.read_bytes()
    frrom = FR_ROM.read_bytes()

    wanted = {}
    not_text = 0
    for name, (offset, size, kind) in pairs.items():
        if kind != "texte" or name not in english:
            continue
        address, esize = english[name]
        if not ROM_LO <= address < ROM_HI:
            continue
        english_bytes = rom_string(enrom, address, esize)
        if not english_bytes.endswith(b"\xff"):
            # A label whose name suggests text but that holds a script, a
            # pointer table or battle data.
            not_text += 1
            continue
        french_bytes = rom_string(frrom, offset + ROM_LO, size)
        if english_bytes != french_bytes:
            wanted[name] = (offset, len(french_bytes), english_bytes)
    print("labelled as text but not text (script/table): %d" % not_text)
    print("texts whose bytes differ between the two ROMs: %d" % len(wanted))

    found = {}
    for path, relative in source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "::" in text:
            for match in ASM_DEF.finditer(text):
                name = match.group(1)
                if name in wanted and name not in found:
                    target = wanted[name][2]
                    span = asm_literal_span(text, match.end(), target)
                    if span:
                        found[name] = (relative, span[0], span[1], "asm")
                        continue
                    braille = braille_span(text, match.end())
                    if braille and braille_matches(braille[2], target):
                        found[name] = (relative, braille[0], braille[1], "asm")
        if "[]" in text or "[] " in text:
            for match in C_DEF.finditer(text):
                name = match.group(1)
                if name in wanted and name not in found:
                    span = c_literal_span(text, match.end() - 1, wanted[name][2])
                    if span:
                        found[name] = (relative, span[0], span[1], "c")

    print("spans whose re-encoded literal equals the English bytes: %d / %d"
          % (len(found), len(wanted)))
    missing = sorted(set(wanted) - set(found))
    print("unresolved: %d" % len(missing))

    files = {}
    for name, (relative, start, end, kind) in found.items():
        offset, size, _ = wanted[name]
        files.setdefault(relative, {"edits": []})["edits"].append([start, end, offset, size, kind])
    for relative, entry in files.items():
        entry["edits"].sort()
        entry["sha256"] = hashlib.sha256(
            (TREE / relative).read_text(encoding="utf-8").encode()).hexdigest()

    return {
        "version": "0.1-fr",
        "rom_sha1": hashlib.sha1(frrom).hexdigest(),
        "status": "experimental",
        "files": files,
        "graphics": [],
        "graphics_skipped": [],
        "credits": 0,
        "credits_entries": 0,
        "floors": [],
        "unmapped_source_texts": [{"file": "", "start": 0, "kind": "c", "reason": name}
                                  for name in missing],
        "checks": {"symboles_texte": len(wanted), "resolus": len(found)},
    }


def stage_graphics(manifest: dict, pairs: dict) -> None:
    """Every asset whose bytes differ, plus the fonts the port loads."""
    english = elf_symbols(EN_ELF)
    enrom = EN_ROM.read_bytes()
    frrom = FR_ROM.read_bytes()
    sources = {}
    for root in ("src", "data", "include"):
        for path in (TREE / root).rglob("*"):
            if path.suffix not in (".c", ".inc", ".h", ".s"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in INCBIN.finditer(text):
                sources.setdefault(match.group(1), match.group(2))

    graphics, skipped = [], []
    for symbol, relative in sorted(sources.items()):
        if symbol not in pairs or symbol not in english:
            continue
        offset, size, _ = pairs[symbol]
        french = frrom[offset:offset + size]
        top = english[symbol]["addr"] - ROM_LO
        if enrom[top:top + english[symbol]["size"]] == french \
                and english[symbol]["size"] == size:
            continue
        if relative in GRAPHICS_SKIPPED:
            skipped.append([relative, GRAPHICS_SKIPPED[relative]])
            continue
        graphics.append([relative, offset, size])
    have = {item[0] for item in graphics}
    for symbol, relative in FONT_FILES:
        if symbol in pairs and relative not in have:
            graphics.append([relative, pairs[symbol][0], pairs[symbol][1]])
    manifest["graphics"] = sorted(graphics)
    manifest["graphics_skipped"] = skipped
    print("graphics differing between the two ROMs: %d, kept English: %d"
          % (len(graphics), len(skipped)))


def stage_widths(manifest: dict, pairs: dict) -> None:
    """The font width tables are literals in src/text.c, not assets."""
    english = elf_symbols(EN_ELF)
    text = (TREE / "src/text.c").read_text(encoding="utf-8")
    enrom = EN_ROM.read_bytes()
    frrom = FR_ROM.read_bytes()
    edits = []
    for name in WIDTH_ARRAY.findall(text):
        if name not in pairs or name not in english:
            continue
        offset, size, _ = pairs[name]
        top = english[name]["addr"] - ROM_LO
        if enrom[top:top + english[name]["size"]] == frrom[offset:offset + size]:
            continue
        match = re.search(r"static const u8 " + name + r"\[\]\s*=\s*\{", text)
        start = text.index("{", match.start())
        depth, index = 0, start
        while True:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        edits.append([start, index + 1, offset, size, "u8array"])
    if not edits:
        return
    entry = manifest["files"].setdefault("src/text.c", {"edits": []})
    entry["edits"] = sorted(entry["edits"] + edits)
    entry["sha256"] = hashlib.sha256((TREE / "src/text.c").read_bytes()).hexdigest()
    manifest["checks"]["largeurs"] = len(edits)
    print("width tables differing: %d" % len(edits))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, default=TREE,
                        help="bootstrapped tree, after make generated")
    parser.add_argument("--elf", type=Path, required=True, help="US retail link")
    parser.add_argument("--english-rom", type=Path, required=True)
    parser.add_argument("--french-elf", type=Path, required=True, help="French decomp link")
    parser.add_argument("--french-rom", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="defaults to tools/locales/french.json.gz")
    args = parser.parse_args()

    tree = args.tree.resolve()
    globals().update(TREE=tree, CHARMAP=tree / "charmap.txt",
                     EN_ROM=args.english_rom.resolve(), FR_ROM=args.french_rom.resolve(),
                     EN_ELF=args.elf.resolve(), FR_ELF=args.french_elf.resolve())
    load_characters()
    out = args.out or Path(__file__).resolve().parents[2] / "tools/locales/french.json.gz"

    pairs = french_offsets(elf_symbols(EN_ELF), elf_symbols(FR_ELF))
    print("symbols shared by the two links: %d" % len(pairs))
    manifest = stage_texts(pairs)
    stage_graphics(manifest, pairs)
    stage_widths(manifest, pairs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(json.dumps(manifest, ensure_ascii=False).encode(), 9))
    print("wrote %s: %d files, %d edits, %d graphics"
          % (out, len(manifest["files"]),
             sum(len(f["edits"]) for f in manifest["files"].values()),
             len(manifest["graphics"])))


if __name__ == "__main__":
    main()
