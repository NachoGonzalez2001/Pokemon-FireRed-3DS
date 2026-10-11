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
