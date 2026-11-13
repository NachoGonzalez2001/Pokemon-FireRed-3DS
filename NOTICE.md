# Attribution

## Pokémon Emerald 3Ds Dual Screen

`3ds_port/scripts/voxel_building.py` is copied from
[ZallaxDev/pokeemerald-3Ds-dualscreen](https://github.com/ZallaxDev/pokeemerald-3Ds-dualscreen)
(`3ds_port/scripts/voxel_building.py`), with two changes for FireRed: it reads
tileset art through `fr_art.py` instead of `dump_region_art.py`, and splits
primary and secondary metatiles at 640 instead of 512 (plus tolerating the
empty placeholders in FireRed's `layouts.json`). `fr_art.py`,
`fr_building_specs.py` and `fr_gen_buildings.py` follow the interfaces and
method of that project's `dump_region_art.py`, `voxel_building_specs.py` and
`gen_voxel_buildings.py`. `3ds_port/scripts/emu/grab.ps1`, `drive.ps1` and
`touch.ps1` are copied from that project's `3ds_port/scripts/emu/`, changed
to target one emulator process (`-Id`) and Azahar's default START/SELECT keys.

The 3DS backend in `3ds_port/` (`src/`, `include/`, `compat/`, `scripts/`,
`tests/`, `forwarder/`, `Makefile`, `full.mk`, `firered3ds.ld.in`) and
`tools/port_common/` start as copies of that project's files of the same
names and are being adapted to FireRed; `tools/bootstrap.py` and
`patches/pokefirered/0004-platform-layer.patch` are adapted from its
bootstrap and its `0004-platform-layer.patch`. Files in
`3ds_port/src/voxel/` additionally carry the attribution of their own
`NOTICE.md` (pokeemerald-multiplatform, MIT).

The visible wild Pokémon (OPTIONS, ENHANCEMENTS, VISIBLE WILD; the
`VisibleWild_*` section of `src/wild_encounter.c` in
`patches/pokefirered/0028-wild-renewed-and-visible.patch`) are adapted from
that project's `patches/pokeemerald/0014-visible-wild.patch` as of its
commit d724c5d, under the MIT License below: FireRed's encounter tiles,
Unown letters, the SHINY ODDS setting and the Pokémon Tower's ghosts.

Its port code is distributed under the MIT License:

    MIT License

    Copyright (c) 2026 ZallaxDev and Pokémon Emerald 3Ds Dual Screen contributors

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

## pret/pokefirered

The game data the generators read comes from a checkout of
[pret/pokefirered](https://github.com/pret/pokefirered) at the commit pinned in
`upstream.lock`. Nothing derived from it is committed here; generated previews
stay under the ignored `build/` directory.

Pokémon FireRed is a trademark of Nintendo, Game Freak, Creatures and The
Pokémon Company. This is an unofficial fan project.

## Mega Evolution sprites

The Mega Evolution battle sprites (`3ds_port/src/fr_mega_art.c`, made by
`tools/dev/mega_sprites.py`) come from the
[Gen VI: DS-Style 64x64 Pokémon Sprite Resource](https://www.pokecommunity.com/threads/gen-vi-ds-style-64x64-pokemon-sprite-resource.314422/)
on PokéCommunity, which allows their use in fan projects with credit to that
thread. The resource continues Chaos Rush's DS-Style 64x64 Pokémon Sprite
Resource. As its credits list them, for the forms used here:

- MrDollSteak: every sprite not listed below
- Spherical Ice: Mega Beedrill front
- leparagon: Mega Alakazam, Mega Mewtwo X, Mega Mewtwo Y
- Wobblebuns: Mega Kangaskhan's baby
- BlackWhiteRobin: Mega Blastoise back
- The Cynical Poet: Mega Slowbro front
- Criminon: quality check on Mega Blastoise
- Chaos Rush: the original resource, continued with their permission
- Layell: permission to use sprites from the Smogon XY Sprite Project

Mega Dragonite comes from the
[DS-style Gen VII and Beyond Pokémon Sprite Repository in 64x64](https://www.pokecommunity.com/threads/ds-style-gen-vii-and-beyond-pok%C3%A9mon-sprite-repository-in-64x64.368703/)
on PokéCommunity, free to use with credit to its contributors:
Axel_CodeInfinity (front), Lykeron (back), leParagon (quality check).

The sprites are reduced to 16 colours for the GBA's battle screen. The MEGA
key's Key Stone, the bag icons of the MEGA STONE, MEGA STONE Y and MEGA RING
(tools/dev/mega_item_icons.py) and the Mega Evolution effect's orbs, sphere
and shards (tools/dev/mega_fx.py) are the port's own, drawn by those scripts.
