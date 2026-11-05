# Declare the battle text capacity reserved for Brock's defeat message

Related: issue #3 and commit b6d1553. This hardens the existing workaround;
it does not claim that the current release still fails to award the badge.

The linker reserves 256 bytes after `gDisplayedStringBattle[300]` to absorb
Brock's long expanded defeat speech. Those bytes protect adjacent state but
are outside the C array's bounds. Native builds now declare the same total
capacity (556 bytes) in both declaration and definition, and the special
linker placement/padding is removed. Stock GBA builds retain 300 bytes.

Validation:

- Actual array declaration and `StringCopy` with encoded Brock dialogue,
  names of length 0..7 and battle pause/terminator: ASan/UBSan PASS.
- The same test against the previous source produces an ASan global buffer
  overflow. No copyrighted dialogue/ROM is committed in the test.
- Full native ARM11 build succeeded; ELF symbol size is 0x22c (556), hard-float
  ARM32 and no strong undefined symbols.
- Builder host tests: 14 tests, one skipped, otherwise PASS.
- Full gym victory / badge persistence was not replayed in this contribution.

Run after bootstrap:

```
python3 3ds_port/tests/battle_string_capacity_test.py --tree build/upstream --sanitize
```

The repository's existing `verify_build.py` also needs a separate update:
its video check rejects the current software presenter's DrawFrame symbols,
and its full-game symbol check still requires InitKeys. It was not reported
as passing for this change.
