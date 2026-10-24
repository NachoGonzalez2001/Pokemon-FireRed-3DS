# Pokémon FireRed 3DS (voxel)

A port of Pokémon FireRed to the Nintendo 3DS with a voxel world, built on the
technical groundwork of [Pokémon Emerald 3Ds Dual Screen](https://github.com/ZallaxDev/pokeemerald-3Ds-dualscreen)
and the [pret/pokefirered](https://github.com/pret/pokefirered) decompilation.

**Status:** modelling pilot. There is no 3DS port yet; for now only the
generators that build 3D models from the game's art exist.

## Model generators (pilot)

Buildings are rebuilt in 3D from their own drawing, with the same method as
the Emerald port: GBA art is a fixed oblique projection (`u = X`, `v = Z − Y`),
so each model is checked by rendering it at 45° and comparing it pixel by pixel
with the original drawing.

Requirements: Python 3.11+, Pillow and a copy of `pokefirered` at the commit in
`upstream.lock`, next to this project (`../pokefirered`) or in `$POKEFIRERED`.

```sh
# top-down map, with a grid and each cell's data
python 3ds_port/scripts/fr_map_render.py LAYOUT_PALLET_TOWN build/pallet.png --grid --info

# a building's art with a pixel ruler, to read it row by row
python 3ds_port/scripts/fr_art_ruler.py LAYOUT_PALLET_TOWN 5 3 5 5 build/house.png --ground 0x011,0x296

# build and verify the models, with previews and the whole town
python 3ds_port/scripts/fr_gen_buildings.py --preview build/pilot --town LAYOUT_PALLET_TOWN
```

| Script | Purpose |
|---|---|
| `fr_art.py` | Reads FireRed's tiles (indexed PNG), JASC palettes, metatiles and 32-bit attributes |
| `voxel_building.py` | The Emerald port's geometry core (MIT), adapted to the 640-metatile split |
| `fr_building_specs.py` | How each building reads: parts, roofs and areas that must match the drawing |
| `fr_gen_buildings.py` | Builds, verifies (pixels and texel density) and renders views |

Modelled: the Pallet Town houses (both use the same model) and Prof. Oak's
Lab.

## How FireRed differs from Emerald

- 640 primary tiles and metatiles (Emerald: 512) and 7 primary palettes (6).
- 32-bit metatile attributes (Emerald: 16).
- The side slopes of roofs are drawn as vertical strips; the generator
  transposes them instead of repeating the front slope.

See [NOTICE.md](NOTICE.md) for credits and licences.
