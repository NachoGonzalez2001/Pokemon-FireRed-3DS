#!/usr/bin/env python3
"""Move sections with unaligned pointers out of the 3DSX and into RomFS.

3dsxtool builds its own relocation table and rejects any relocation that is not
word aligned ("Unaligned relocation!"). Two kinds of GBA data are built that
way on purpose: script bytecode, which carries 32-bit pointers inside a byte
stream, and MP2K song data, whose PATT commands do the same. Neither can stay
in the executable, and neither should need a resolution hook on every
pointer.

The answer here is the same for both, and needs no hook anywhere in the game.
The data keeps its exact layout; the executable reserves a zero-initialised
region of exactly that size with every symbol defined at its real offset inside
it, so EventScript_X and mus_littleroot are already the correct addresses. A
loader reads the payload into that region and applies two relocation lists.

The bundle is position independent: pointers into the payload are stored as
payload-relative offsets, and pointers into the executable as link-time
addresses plus a reference symbol, so a 3DSX loaded at another base still
resolves correctly.
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
from pathlib import Path

# magic, version, payload bytes, reference symbol link address, internal count,
# external count; little endian, as on the console.
HEADER = struct.Struct("<4sIIIII")
VERSION = 1
REFERENCE_SYMBOL = "AgbMain"


def tool(name: str) -> str:
    devkitarm = os.environ.get("DEVKITARM", "/opt/devkitpro/devkitARM")
    for candidate in (Path(devkitarm) / "bin" / name, Path(devkitarm) / "bin" / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return name


def defined_symbols(obj: Path) -> dict[str, int]:
    out = subprocess.check_output([tool("arm-none-eabi-nm"), "--defined-only", str(obj)],
                                  text=True, errors="ignore")
    result: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        # Globals only. Local labels repeat across objects (the AI script macros
        # reuse names, and every song calls its first track _1) and are reached
        # through section-relative relocations, so they neither need nor can
        # have a unique entry here.
        if len(parts) < 3 or parts[1] not in {"T", "D", "R", "B"}:
            continue
        name = parts[2]
        if name.startswith("$") or "." in name:
            continue
        result[name] = int(parts[0], 16)
    return result


def elf_symbols(elf: Path) -> dict[str, int]:
    out = subprocess.check_output([tool("arm-none-eabi-readelf"), "--wide", "--symbols", str(elf)],
                                  text=True, errors="ignore")
    result: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].endswith(":"):
            continue
        if parts[4] not in {"GLOBAL", "WEAK"} or parts[6] == "UND":
            continue
        result[parts[7]] = int(parts[1], 16)
    return result


def relocations(obj: Path, section: str) -> list[tuple[int, str]]:
    out = subprocess.check_output([tool("arm-none-eabi-objdump"), "-r", str(obj)],
                                  text=True, errors="ignore")
    pattern = re.compile(r"^([0-9a-fA-F]+)\s+R_ARM_ABS32\s+(\S+)$")
    found: list[tuple[int, str]] = []
    inside = False
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("RELOCATION RECORDS FOR ["):
            inside = line.startswith("RELOCATION RECORDS FOR [%s]" % section)
            continue
        if not inside or not line or line.startswith("OFFSET"):
            continue
        match = pattern.match(line)
        if match:
            found.append((int(match.group(1), 16), match.group(2)))
    return found


def dump_section(obj: Path, section: str, tmp: Path) -> bytearray:
    subprocess.check_call([tool("arm-none-eabi-objcopy"),
                           "--dump-section", "%s=%s" % (section, tmp), str(obj)])
    return bytearray(tmp.read_bytes())


class Bundle:
    """One externalised region: its objects, its section and its names."""

    def __init__(self, tag: str, magic: bytes, section: str, blob_symbol: str,
                 payload_name: str, reloc_name: str):
        self.tag = tag
        self.magic = magic
        self.section = section
        self.blob_symbol = blob_symbol
        self.payload_name = payload_name
        self.reloc_name = reloc_name

    def load(self, objects: list[Path], tmp: Path):
        """Lay the sections out once and record where every symbol lands."""
        missing = [str(o) for o in objects if not o.exists()]
        if missing:
            raise SystemExit("%s: missing objects:\n  %s" % (self.tag, "\n  ".join(missing)))

        sections = []
        offsets: dict[str, int] = {}
        total = 0
        for obj in objects:
            data = dump_section(obj, self.section, tmp)
            # Keep the next object word aligned so its own tables stay aligned.
            while len(data) % 4:
                data.append(0)
            for name, value in defined_symbols(obj).items():
                if name in offsets:
                    raise SystemExit("%s: %s is defined by two objects" % (self.tag, name))
                offsets[name] = total + value
            sections.append((obj, total, data))
            total += len(data)
        if tmp.exists():
            tmp.unlink()
        return sections, offsets, total

    def write_blob_asm(self, offsets: dict[str, int], size: int, out_asm: Path) -> None:
        by_offset: dict[int, list[str]] = {}
        for name, offset in offsets.items():
            by_offset.setdefault(offset, []).append(name)

        out_asm.parent.mkdir(parents=True, exist_ok=True)
        with out_asm.open("w", encoding="ascii", newline="\n") as f:
            f.write("/* Generated by scripts/%s.py --blob. Do not edit.\n"
                    " * Reserves the region and defines every symbol at its real offset\n"
                    " * inside it, so the existing references need no resolution hook.\n"
                    " * The bundle loader fills it from RomFS. */\n" % self.tag)
            f.write('\t.section .bss.%s, "aw", %%nobits\n\t.align 4\n'
                    % self.blob_symbol.lstrip("_"))
            f.write("\t.global %s\n%s:\n" % (self.blob_symbol, self.blob_symbol))
            cursor = 0
            for offset in sorted(by_offset):
                if offset > cursor:
                    f.write("\t.space %d\n" % (offset - cursor))
                    cursor = offset
                for name in sorted(by_offset[offset]):
                    f.write("\t.global %s\n%s:\n" % (name, name))
            if size > cursor:
                f.write("\t.space %d\n" % (size - cursor))
            f.write("\t.global %s_end\n%s_end:\n" % (self.blob_symbol, self.blob_symbol))
        print("%s: %d symbols over %d bytes -> %s" % (self.tag, len(offsets), size, out_asm))

    def write_keep_asm(self, sections, offsets: dict[str, int], out_asm: Path,
                       keep_symbol: str) -> None:
        """Reference everything the payload calls, so --gc-sections keeps it.

        Nothing inside the executable refers to those handlers any more: the
        only references are inside the payload, which is no longer part of the
        link. The linker would drop them and the bundle could not be resolved
        against the ELF.
        """
        wanted: set[str] = set()
        for obj, _, _ in sections:
            for _, symbol in relocations(obj, self.section):
                if symbol != self.section and symbol not in offsets:
                    wanted.add(symbol)

        out_asm.parent.mkdir(parents=True, exist_ok=True)
        lines = ["/* Generated by scripts/%s.py --blob. Do not edit." % self.tag,
                 " * One word per handler the externalised payload calls. */",
                 '\t.section .rodata.%s, "a", %%progbits' % keep_symbol.lstrip("_"),
                 "\t.align 2",
                 "\t.global %s" % keep_symbol,
                 "%s:" % keep_symbol]
        lines += ["\t.4byte %s" % name for name in sorted(wanted)]
        lines += ["\t.global %s_end" % keep_symbol, "%s_end:" % keep_symbol, ""]
        out_asm.write_text("\n".join(lines), encoding="ascii", newline="\n")
        print("%s: %d handlers kept -> %s" % (self.tag, len(wanted), out_asm))

    def write_bundle(self, sections, offsets, size, elf: Path, out_dir: Path) -> None:
        symbols = elf_symbols(elf)
        if REFERENCE_SYMBOL not in symbols:
            raise SystemExit("%s: %s not found in %s" % (self.tag, REFERENCE_SYMBOL, elf))
        blob_start = symbols.get(self.blob_symbol)
        if blob_start is None:
            raise SystemExit("%s: the executable does not reserve %s"
                             % (self.tag, self.blob_symbol))

        internal: list[int] = []
        external: list[int] = []
        unresolved: set[str] = set()

        for obj, base, data in sections:
            for site, symbol in relocations(obj, self.section):
                if site + 4 > len(data):
                    continue
                addend = struct.unpack_from("<I", data, site)[0]
                if symbol == self.section:
                    # The addend is the target's offset inside THIS object.
                    struct.pack_into("<I", data, site, base + addend)
                    internal.append(base + site)
                elif symbol in offsets:
                    # Something in another bundled object.
                    struct.pack_into("<I", data, site, (offsets[symbol] + addend) & 0xFFFFFFFF)
                    internal.append(base + site)
                elif symbol in symbols:
                    struct.pack_into("<I", data, site, (symbols[symbol] + addend) & 0xFFFFFFFF)
                    external.append(base + site)
                else:
                    unresolved.add(symbol)

        payload = bytearray()
        for _, _, data in sections:
            payload.extend(data)
        if len(payload) != size:
            raise SystemExit("%s: payload size changed between passes" % self.tag)

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / self.payload_name).write_bytes(payload)
        with (out_dir / self.reloc_name).open("wb") as f:
            f.write(HEADER.pack(self.magic, VERSION, len(payload),
                                symbols[REFERENCE_SYMBOL], len(internal), len(external)))
            f.write(b"".join(struct.pack("<I", x) for x in internal))
            f.write(b"".join(struct.pack("<I", x) for x in external))

        print("%s: payload=%d bytes, internal=%d, external=%d, region at %08X"
              % (self.tag, len(payload), len(internal), len(external), blob_start))
        if unresolved:
            print("%s: %d unresolved symbol(s)" % (self.tag, len(unresolved)), file=sys.stderr)
            for name in sorted(unresolved)[:20]:
                print("  - %s" % name, file=sys.stderr)
            raise SystemExit(1)
