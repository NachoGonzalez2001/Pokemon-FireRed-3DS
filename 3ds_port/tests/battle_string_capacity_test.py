"""Brock's real expanded defeat text must fit the declared native array.

Reads a bootstrapped source tree; no ROM or copyrighted text is embedded in
this test. Exercises the actual declaration and StringCopy under ASan when
requested. This tests storage capacity, not the complete post-battle script.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature + '\n{')
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def brock_text(tree, name_length):
    charmap = {}
    for line in (tree / 'charmap.txt').read_text().splitlines():
        m = re.match(r"\s*(.+?)\s*=\s*((?:[0-9A-F]{2}(?:\s+|$))+)", line)
        if m:
            key = m[1].strip()
            if key.startswith("'") and key.endswith("'"):
                key = key[1:-1]
            charmap[key] = bytes.fromhex(m[2])
    text = (tree / 'data/maps/PewterCity_Gym/text.inc').read_text()
    block = text.split('PewterCity_Gym_Text_BrockDefeat::', 1)[1].split('\n\n', 1)[0]
    raw = ''.join(re.findall(r'\.string "(.*)"', block))
    out = bytearray()
    pos = 0
    while pos < len(raw):
        if raw[pos] == '{':
            end = raw.index('}', pos)
            token = raw[pos + 1:end]
            if token == 'PLAYER':
                out.extend(charmap['A'] * name_length)
            else:
                parts = token.split()
                out.extend(charmap[parts[0]])
                out.extend(int(p, 0) for p in parts[1:])
            pos = end + 1
        else:
            token = raw[pos:pos + 2] if raw[pos] == '\\' else raw[pos]
            out.extend(charmap[token])
            pos += len(token)
    assert out[-1] == 0xFF
    # BattleStringExpandPlaceholders appends a pause after trainer lose text,
    # then terminates its output. Include both in the required capacity.
    return out[:-1] + charmap['PAUSE_UNTIL_PRESS'] + b'\xff'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, default=ROOT / 'build/upstream')
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    tree = args.tree
    header = (tree / 'include/battle_message.h').read_text()
    definition = re.search(r'^EWRAM_DATA u8 gDisplayedStringBattle\[[^\]]+\] = \{0\};',
                           (tree / 'src/battle_main.c').read_text(), re.M).group()
    declaration = re.search(r'^extern u8 gDisplayedStringBattle\[[^\]]+\];', header, re.M).group()
    macro = re.search(r'#ifdef PORTABLE\n#define BATTLE_DISPLAYED_STRING_SIZE.*?\n#endif', header, re.S)
    config = macro.group() if macro else ''  # also exercise the pre-fix tree
    copy = function((tree / 'src/string_util.c').read_text(), 'u8 *StringCopy(u8 *dest, const u8 *src)')
    texts = [brock_text(tree, n) for n in range(8)]
    assert min(map(len, texts)) > 300, 'fixture no longer exercises original overflow'
    with tempfile.TemporaryDirectory(prefix='fr-battle-string-') as temp:
        path = Path(temp)
        for portable in (False, True):
            code = '#include <assert.h>\n#include <string.h>\n#include <stdio.h>\ntypedef unsigned char u8;\n#define EWRAM_DATA\n#define EOS 255\n'
            if portable:
                code += '#define PORTABLE 1\n'
            code += config + '\n' + declaration + '\n' + definition + '\n' + copy + '\n'
            code += 'int main(void) {\n'
            if not portable:
                code += 'assert(sizeof(gDisplayedStringBattle)==300);\n'
            else:
                for i, text in enumerate(texts):
                    code += 'const u8 text%d[]={%s};\n' % (i, ','.join(map(str, text)))
                    # The write intentionally precedes assertions: an old
                    # 300-byte definition must fail under ASan even if an
                    # unrelated linker script places padding after it.
                    code += 'StringCopy(gDisplayedStringBattle,text%d);\n' % i
                    code += 'assert(sizeof(text%d)<=sizeof(gDisplayedStringBattle));\n' % i
                    code += 'assert(!memcmp(gDisplayedStringBattle,text%d,sizeof(text%d)));\n' % (i, i)
            code += 'return 0; }\n'
            (path / 'test.c').write_text(code)
            cmd = [args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-g']
            if args.sanitize:
                cmd += ['-fsanitize=address,undefined']
            subprocess.run(cmd + [str(path / 'test.c'), '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True)
    print('PASS: Brock defeat text (player names 0..7), native capacity, GBA 300-byte layout')
    print('Longest expanded text including battle pause/EOS: %d bytes' % max(map(len, texts)))


if __name__ == '__main__':
    main()
