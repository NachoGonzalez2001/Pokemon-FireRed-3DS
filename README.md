# Pokémon Rojo Fuego 3DS (voxel)

Port de Pokémon Rojo Fuego a Nintendo 3DS con mundo voxel, tomando como base
técnica [Pokémon Emerald 3Ds Dual Screen](https://github.com/ZallaxDev/pokeemerald-3Ds-dualscreen)
y la decompilación [pret/pokefirered](https://github.com/pret/pokefirered).

**Estado:** prueba piloto de modelado. Todavía no hay port a 3DS; por ahora
solo existen los generadores de modelos 3D a partir del arte del juego.

## Generadores de modelos (piloto)

Los edificios se reconstruyen en 3D a partir de su propio dibujo, con el mismo
método que el port de Esmeralda: el arte de GBA es una proyección oblicua fija
(`u = X`, `v = Z − Y`), así que cada modelo se comprueba renderizándolo a 45° y
comparándolo píxel a píxel con el dibujo original.

Requisitos: Python 3.11+, Pillow y una copia de `pokefirered` en el commit de
`upstream.lock`, junto a este proyecto (`../pokefirered`) o en `$POKEFIRERED`.

```sh
# mapa en plano, con cuadrícula y datos de cada celda
python 3ds_port/scripts/fr_map_render.py LAYOUT_PALLET_TOWN build/pallet.png --grid --info

# arte de un edificio con regla de píxeles, para leerlo fila a fila
python 3ds_port/scripts/fr_art_ruler.py LAYOUT_PALLET_TOWN 5 3 5 5 build/house.png --ground 0x011,0x296

# construir y verificar los modelos, con vistas previas y el pueblo entero
python 3ds_port/scripts/fr_gen_buildings.py --preview build/pilot --town LAYOUT_PALLET_TOWN
```

| Script | Función |
|---|---|
| `fr_art.py` | Lee tiles (PNG indexado), paletas JASC, metatiles y atributos de 32 bits de Rojo Fuego |
| `voxel_building.py` | Núcleo de geometría del port de Esmeralda (MIT), adaptado al corte de 640 metatiles |
| `fr_building_specs.py` | Lectura de cada edificio: piezas, tejados y zonas que deben coincidir con el dibujo |
| `fr_gen_buildings.py` | Construye, verifica (píxeles y densidad de texels) y renderiza vistas |

Modelados: casas de Pueblo Paleta (las dos usan el mismo modelo) y el
Laboratorio del Prof. Oak.

## Diferencias de Rojo Fuego frente a Esmeralda

- 640 tiles y metatiles primarios (Esmeralda: 512) y 7 paletas primarias (6).
- Atributos de metatile de 32 bits (Esmeralda: 16).
- Los faldones laterales de los tejados están dibujados como franjas
  verticales; el generador los traspone en vez de repetir el faldón frontal.

Ver [NOTICE.md](NOTICE.md) para créditos y licencias.
