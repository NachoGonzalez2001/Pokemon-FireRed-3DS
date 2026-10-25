#!/usr/bin/env python3
"""The pieces FireRed's rooms stand up as (src/voxel/voxel_room.c).

The GBA draws a room at 45 degrees: a thing H pixels tall standing on a row
of cells is drawn H pixels further north than it stands. So each object here
is a rectangle of its drawing and a height: the bottom H pixel rows of the
rectangle are its front, stood up at the rectangle's south edge, and the
rows above them its top, laid H pixels up. Seen from the GBA's angle it is
the drawing; from anywhere else, a box. A card is a box all front (a plant,
a chair); a wall is the room's top rows, all front, opaque.

Objects are listed by the tileset they are drawn from (ROOM_OBJECTS), each
the metatiles of its rectangle; wherever a room is drawn with them, they
stand. The cells under an object keep only the floor (the metatile's lower
layer) where the object is drawn on the upper one. Everything else in a room
lies flat - a guess from the collision stood rugs and tables up as tents.

Used by fr_gen_trees.py, which packs the art in the tree texture.
"""

import json
import os
import struct

import fr_art
import fr_map_render

# (cells, height in pixels). Cells row by row, north first; None matches
# anything (and is not part of the object).
X = {"xrep": 1}          # its middle column repeats: as long as it is drawn
Y0 = {"yrep": 0}         # its first row repeats

SILPH_CURB = {(123, 123, 123), (213, 213, 213), (255, 255, 255), (180, 180, 164)}
SILPH_POND = {(98, 139, 189), (123, 164, 189)}
ROOF_RAIL = {(57, 106, 82), (90, 205, 115), (41, 156, 98)}
# Pewter Gym's sand and earth round its rocks, the specks of grey in the sand
PEWTER_ROCK = {"drop": {(197, 189, 139), (164, 139, 115), (131, 106, 82)}, "speck": 4}

DECK_RAIL = {(82, 82, 106), (131, 131, 213), (98, 98, 172), (148, 148, 172)}
HARBOR_RAIL = {(82, 82, 106), (106, 205, 164), (57, 156, 115), (180, 189, 189), (148, 156, 156), (106, 115, 115)}

ROOM_OBJECTS = {
    # rocks in the sea round the S.S. Anne (General's own, an indoor map)
    "gTileset_General": [
        ([[0x110, 0x111], [0x118, 0x119]], 32), ([[0x1CB, 0x1CC], [0x1D3, 0x1D4]], 32),
    ],
    # the Power Plant's rubble
    "gTileset_PowerPlant": [([[0x2B6]], 12), ([[0x2B5]], 12), ([[0x2E2]], 12)],
    "gTileset_Building": [
        # the GenericBuilding1 houses' tables and pots
        ([[0x0C8, 0x0C9], [0x0D0, 0x0D1]], 10), ([[0x0C6]], 14), ([[0x0C7]], 14),
        ([[0x0F6], [0x0FE]], 30), ([[0x0F5], [0x0FD]], 30),
        ([[0x155], [0x15D]], 30),
        ([[0x0DA, 0x0DB], [0x0E2, 0x0E3]], 12),
        # tables and their chairs
        ([[0x04C, 0x04D], [0x054, 0x055]], 10),
        ([[0x04B]], 14), ([[0x04E]], 14),
        ([[0x165, 0x166], [0x16D, 0x16E]], 10),
        ([[0x16F]], 14), ([[0x167]], 14),
        ([[0x128, 0x129], [0x130, 0x131]], 10), ([[0x126]], 14),
        # pot plants, top and pot
        ([[0x057], [0x05F]], 30), ([[0x047], [0x04F]], 30), ([[0x067], [0x05F]], 30),
        ([[0x09B], [0x093]], 30), ([[0x09C], [0x094]], 30),
        ([[0x156], [0x15E]], 30), ([[0x102], [0x103]], 30), ([[0x102], [0x136]], 30),
        ([[0x12E], [0x136]], 30),
        # against the back wall, standing out of it, the wall plain behind:
        # the bookshelf, the drawers, the glass cupboard - cabinets
        # (roof: the drawing's first rows are its top, not its front - as
        # tall as its front is drawn, no lid stood up over the books)
        ([[0x02B, 0x02C], [0x033, 0x034], [0x03B, 0x03C]], 0, {"model": (0, 12), "roof": 12}),
        ([[0x030], [0x038]], 0, {"model": (0, 10), "roof": 8}),
        ([[0x02E, 0x02F], [0x036, 0x037], [0x03E, 0x03F]], 0, {"model": (0, 12), "roof": 11}),
        # the kitchen counter, sink and stove: seen from above, its front low
        ([[0x031, 0x032], [0x039, 0x03A]], 12),
        # a television on its stand against the wall: its top, its front
        ([[0x02D], [0x035], [0x03D]], 17),
        # the desk's free end: its checked top, its front
        ([[0x086], [0x05A]], 10),
    ],
    "gTileset_GenericBuilding1": [
        ([[0x035], [0x281]], 16, {"rows": 1}),            # a television alone, a card
        ([[0x281]], 8),                                   # the console on its table
        # the bed: a column and a half wide, centred on the middle one
        ([[0x283, 0x284, 0x285], [0x28B, 0x28C, 0x28D], [0x293, 0x294, 0x295]], 10),
        # the television, seen from above like the rest: its top, its front
        # 17 high; the SNES on the rug in front of it, its own low piece
        ([[0x286], [0x035], [0x28E]], 17, {"split": (8, 3)}),
        # the PC on its desk against the wall: a box
        ([[0x287], [0x28F], [0x297]], 0, {"model": (24, 12)}),
    ],
    "gTileset_GenericBuilding2": [
        ([[0x2E9], [0x2F0]], 30),
        # gatehouse plants
        ([[0x2E9], [0x2F1]], 30), ([[0x2EA], [0x2F1]], 30), ([[0x2E8], [0x2F0]], 30),
        ([[0x2EF], [0x2F7]], 30),
        # the guards' counters, as long as they run, their top the row above
        ([[0x2EB, 0x2EC, 0x2ED], [0x2A4, 0x2A5, 0x2A6]], 16, X),
        ([[0x2FB, 0x2FC, 0x2FD], [0x303, 0x304, 0x305], [0x30B, 0x30C, 0x30D]], 14, X),
        ([[0x2EB, 0x29D, 0x28E], [0x2A4, 0x2A5, 0x296], [None, None, 0x28D], [None, None, 0x295]], 16, X),
        ([[0x2A4, 0x2A5, 0x2A6]], 8, X),
        # north-south dividers, and one turning into a counter
        ([[0x28D, None, None], [0x29C, 0x29F, 0x28E], [0x2A4, 0x2A5, 0x2A6]], 16, Y0),
        ([[0x28D], [0x295]], 16, Y0),
        # the underground path's L-shaped walls
        ([[0x294, 0x2A6], [0x28D, None], [0x29C, None], [0x2A4, 0x2A6]], 16),
        ([[0x2A4, 0x296], [None, 0x28D], [None, 0x29E], [0x2A4, 0x2A6]], 16),
        # tables, chairs, binoculars, statues
        ([[0x2D6, 0x2D7], [0x2DE, 0x2DF]], 12), ([[0x2E6]], 14), ([[0x2E7]], 14),
        ([[0x2C1], [0x2C9]], 30), ([[0x2C0], [0x2C8]], 30),
        ([[0x331], [0x32F]], 30), ([[0x32E], [0x32F]], 30),
    ],
    "gTileset_PokemonCenter": [
        # the corner plant: its leaves' tips on the wall's top row, its
        # leaves over the wall, its pot - the wall keyed out behind it
        ([[0x2D3], [0x28D], [0x294]], 30),
        # upstairs: the red counter's front row, its end
        ([[0x2E9, 0x2E9, 0x2F8]], 10), ([[0x2F9]], 10),
        # One Island: the glass booth of the cable club
        ([[0x350, 0x351, 0x355, 0x355, 0x352, 0x353], [0x34C, 0x34D, 0x356, 0x356, 0x34E, 0x34F],
          [0x354, 0x35C, 0x358, 0x359, 0x35E, 0x357], [0x341, 0x342, 0x346, 0x347, 0x343, 0x344]], 36),
        # upstairs: the trade and battle counters with their machines
        ([[0x302, 0x363, 0x365], [0x303, 0x2E9, 0x366]], 12),
        ([[0x302, 0x363, 0x365], [0x303, 0x2E9, 0x367]], 12),
        ([[0x2F6], [0x2F8]], 12), ([[0x326], [0x062]], 12), ([[0x376], [0x37E]], 12),
        ([[0x2E7], [0x2EF]], 30), ([[0x300], [0x301]], 30),
        ([[0x288], [0x2E9]], 30), ([[0x340], [0x301]], 30),
        # the Indigo Plateau's counter running down the west wall
        ([[0x338], [0x331], [0x2B5], [0x2BD]], 12),
        ([[0x362]], 30), ([[0x32F]], 30),
        # the counter, top and front, nurse's gap and all
        ([[0x2B1, 0x2B2, 0x2B3, 0x290, 0x363, 0x2B4, 0x2B5],
          [0x2B9, 0x2BC, 0x2BC, 0x298, 0x2BC, 0x2BC, 0x2BD]], 8),
        # on it, against the wall: the healing machine and the box - low
        # boxes standing on its top, seen from above like it (their drawn
        # top their top), the counter and the plain wall keyed out
        ([[0x2AA, 0x2AB], [0x2B2, 0x2B3]], 10, {"on": (8, [0x28C, 0x290])}),
        ([[0x2AC], [0x2B4]], 10, {"on": (8, [0x28C, 0x290])}),
        # beside it on the floor, the PC: a box, its screen the front
        ([[0x062], [0x295]], 0, {"model": (26, 12)}),
        # the green shelf against the west wall: a cabinet standing out of it
        ([[0x2C9, 0x2CA], [0x2CB, 0x2CC], [0x2CD, 0x2CE]], 0, {"model": (0, 12), "roof": 12}),
        ([[0x29C, 0x29D], [0x2A4, 0x2A5]], 12),           # the table
        ([[0x2F5]], 8), ([[0x2FD]], 8),                   # its stools
    ],
    "gTileset_Mart": [
        # the shelves: long and low, running back - seen from above, their
        # end the front, the goods on their top
        ([[0x296, 0x297], [0x29E, 0x29F], [0x2A6, 0x2A7], [0x2AE, 0x2AF]], 16),
        ([[0x296], [0x29E], [0x2A6], [0x2AE]], 16),
        # the counter's arm running back to the wall: the L's long side
        ([[0x295], [0x29D], [0x2A5], [0x2AD]], 16),
        # seen from above: low boxes, the glass their front
        # (solid: their glass is the floor's blue, the mask would take it)
        # the counters running across, drawn front on: stood up, cards
        ([[0x2A8, 0x2A9, 0x2AA], [0x2B0, 0x2B1, 0x2B2]], 32),
        ([[0x2B7, 0x2BC], [0x2C1, 0x2C2]], 32),
        ([[0x2B6]], 16),                                          # the plant
    ],
    "gTileset_SilphCo": [
        ([[0x356]], 16), ([[0x3EF], [0x062]], 30), ([[0x39D, 0x39E, 0x39F]], 10),
        ([[0x3AD, 0x3B6, 0x3AE, 0x3B6, 0x3AF], [0x3B5, 0x3B6, 0x3A8, 0x3B6, 0x3B7],
          [0x3BD, 0x3BE, 0x3BE, 0x3BE, 0x3BF]], 10),
        ([[0x302]], 16),
        # plants: in the wall's foot, and free standing
        ([[0x34F], [0x356]], 30), ([[0x355]], 16), ([[0x308]], 16), ([[0x309]], 16),
        # tables: the glass one, the conference one, the sofa, a crate
        ([[0x343, 0x344], [0x34B, 0x34C]], 10),
        ([[0x313, 0x314, 0x315], [0x31E, 0x31F, 0x31D], [0x323, 0x324, 0x325]], 10),
        ([[0x313, 0x314, 0x315], [0x31B, 0x316, 0x317], [0x323, 0x324, 0x325]], 10),
        ([[0x313, 0x314, 0x315], [0x323, 0x324, 0x325]], 10),
        ([[0x320, 0x321, 0x322]], 10), ([[0x099]], 12),
        ([[0x310, 0x311], [0x310, 0x311], [0x318, 0x319]], 14),
        ([[0x310, 0x311], [0x318, 0x319]], 14),
        # the small desks: their top, its edge, the drawers in front
        ([[0x36D, 0x36E, 0x36F], [0x323, 0x324, 0x325], [0x375, 0x376, 0x377]], 12, X),
        ([[0x36D, 0x36F], [0x323, 0x325], [0x375, 0x377]], 12),
        # with a computer on them
        ([[0x36D, 0x36E, 0x36F], [0x323, 0x388, 0x389], [0x375, 0x376, 0x377]], 12),
        ([[0x36D, 0x36E, 0x36F], [0x391, 0x31C, 0x31D], [0x323, 0x388, 0x389], [0x375, 0x376, 0x377]], 12),
        ([[0x36D, 0x36E, 0x36E, 0x36F], [0x391, 0x31C, 0x31C, 0x31D], [0x323, 0x324, 0x388, 0x389],
          [0x375, 0x376, 0x376, 0x377]], 12),
        # the lobby's ponds: the white curb round them, low; the fountain's
        # spray standing over the water
        ([[0x3DE], [0x3DF]], 24, {"drop": SILPH_POND}),
    ] + [([[m]], 4, {"keep": SILPH_CURB}) for m in (0x3CE, 0x3CC, 0x3CF, 0x3D2, 0x3D3, 0x3C7, 0x3C6, 0x3D0,
                                                     0x3D1, 0x3CA)] + [
        # desks with their computers
        ([[0x2BB, 0x2B9, 0x2C4], [0x2C3, 0x2B9, 0x2BA]], 12),
        ([[0x2BB, 0x2B9, 0x2BA], [0x2C3, 0x2B9, 0x2C4]], 12),
        ([[0x2B8, 0x2B9, 0x2C4]], 12), ([[0x2B8, 0x2B9, 0x2BA]], 12),
    ],
    "gTileset_SSAnne": [
        # the deck: its round tables, the barrels stacked by the cabin
        ([[0x377]], 14),
        ([[0x3AE], [0x396]], 16), ([[0x3B3], [0x38F], [0x396]], 16),
        ([[0x387], [0x397]], 16), ([[0x387], [0x38F], [0x397]], 16),
    ] + [
        # its railing, the rail and posts alone (the sea and the hull stay)
        ([[m]], 16, {"keep": DECK_RAIL}) for m in (0x35B, 0x35C, 0x3B0, 0x3B1, 0x3B2, 0x3B4, 0x376, 0x359,
                                                   0x35A, 0x360, 0x361, 0x369, 0x36A, 0x374, 0x373)
    ] + [
        ([[0x36C], [0x374]], 16, {"keep": DECK_RAIL}), ([[0x36B], [0x373]], 16, {"keep": DECK_RAIL}),
        ([[0x37F], [0x374]], 16, {"keep": DECK_RAIL}), ([[0x37E], [0x374]], 16, {"keep": DECK_RAIL}),
        ([[0x289]], 14), ([[0x28A]], 14), ([[0x333]], 16), ([[0x302]], 24, {"depth": 8}),
        ([[0x338, 0x339], [0x340, 0x341]], 10), ([[0x342, 0x343, 0x344], [0x34A, 0x34B, 0x34C]], 12),
        ([[0x329], [0x331]], 10), ([[0x309], [0x311]], 10),
    ],
    "gTileset_PokemonTower": [
        # the graves, one a cell, and the altar
        ([[0x2D8]], 14),
        ([[0x2D9]], 14),
        ([[0x293]], 14),
        ([[0x291]], 14),
        ([[0x289]], 14),
        ([[0x2DC]], 14),
        ([[0x2DD]], 14),
        ([[0x2A5]], 14),
        ([[0x2DA]], 14),
        ([[0x2B3]], 14),
        ([[0x2E3]], 14),
        ([[0x2E4]], 14),
        ([[0x2D6]], 14),
        ([[0x2BF]], 14),
        ([[0x2BE]], 14),
        ([[0x2A6]], 14),
        ([[0x2B1]], 14),
        ([[0x2B2]], 14),
        ([[0x2CF], [0x2D7]], 24),
    ],
    "gTileset_TrainerTower": [
        # the floors' white seats, boxes; the lobby's pot plants
        ([[0x389]], 0, {"model": (14, 12)}), ([[0x388]], 0, {"model": (14, 12)}),
        ([[0x380]], 0, {"model": (14, 12)}),
        ([[0x2D5], [0x2DD]], 30), ([[0x2D6], [0x2DE]], 30),
        # the roof: the raised block in three parts (the stairs' side, the
        # middle stepping forward, the elevator's side), their olive face
        # standing, their top flat on it; the lightning rods on that top
        ([[0x354, 0x35B, 0x35B, 0x35B]] * 4 + [[0x34A, 0x349, 0x349, 0x349], [0x360, 0x361, 0x362, 0x351]], 24),
        ([[0x35B] * 6] * 3 + [[0x368, 0x35B, 0x35B, 0x35B, 0x35B, 0x368], [0x369, 0x35B, 0x35B, 0x35B, 0x35B, 0x36A],
          [0x34A, 0x349, 0x349, 0x349, 0x349, 0x34B], [0x352, 0x351, 0x351, 0x351, 0x351, 0x353]], 24),
        ([[0x35B, 0x35B, 0x35B, 0x350]] * 4 + [[0x34D, 0x34E, 0x34F, 0x34B], [0x355, 0x356, 0x357, 0x353]], 24),
        ([[0x368], [0x369]], 0, {"model": (30, 2), "on": (24, [0x35B])}),
        ([[0x368], [0x36A]], 0, {"model": (30, 2), "on": (24, [0x35B])}),
    ],
    "gTileset_Lab": [
        ([[0x2AB, 0x2AC], [0x2B3, 0x2B4]], 24, {"depth": 8}),    # Oak's machine
        # Oak's table: its top, its front and legs - drawn over the row in
        # front of it, which is floor: stood back onto its own row
        ([[0x2A8, 0x2A9, 0x2AA], [0x2B0, 0x2B1, 0x2B2]], 8, {"back": "blocked"}),
        # Oak's bookshelves, the white top drawn on the floor north of them,
        # the books, the foot drawn on the floor south: low boxes on their
        # own row
        ([[0x2BA, 0x28B, 0x28C, 0x28B, 0x28C], [0x073, 0x073, 0x074, 0x073, 0x074],
          [0x287, 0x283, 0x284, 0x283, 0x284]], 19, {"back": "blocked"}),
        ([[0x28B, 0x28C, 0x28B, 0x28C, 0x28C], [0x073, 0x074, 0x073, 0x074, 0x074],
          [0x283, 0x284, 0x283, 0x284, 0x284]], 19, {"back": "blocked"}),
        # against the back wall: the bookshelves, and the desk under the
        # computers (they stay on the wall), out of it nearly to their foot -
        # the foot is drawn at the middle of the row in front, where Red walks
        ([[0x073, 0x074, 0x073, 0x074], [0x283, 0x284, 0x283, 0x284]], 0, {"model": (24, 10), "back": 3}),
        ([[0x285, 0x286, 0x285, 0x286]], 8, {"depth": 6, "back": 3}),
        # the two machines beside it, boxes out of the wall
        ([[0x2AD, 0x2A6], [0x2B5, 0x2B6]], 0, {"model": (24, 10), "back": 3}),
        # the corner plants
        ([[0x293], [0x29B]], 26), ([[0x294], [0x29C]], 26),
        ([[0x29F], [0x29F]], 10), ([[0x2A8, 0x2A9, 0x2AA]], 10),
        ([[0x2FB, 0x2FC], [0x073, 0x074]], 16, {"depth": 8}),
        ([[0x073]], 16, {"depth": 8}), ([[0x074]], 16, {"depth": 8}),   # bookshelves
        ([[0x2C7]], 30, {"crown": 1}), ([[0x094]], 30, {"crown": 1}),   # plants
        ([[0x2C8, 0x2C9], [0x2D0, 0x2D1]], 10),
        ([[0x2E0, 0x2E1, 0x2E2], [0x2E8, 0x2E9, 0x2EA], [0x2F0, 0x2F1, 0x2F2]], 10),
        ([[0x2E8, 0x311, 0x2EA], [0x2E8, 0x2E9, 0x312], [0x2F0, 0x2F1, 0x2F2]], 10),
        ([[0x30D, 0x30E, 0x30F]], 12), ([[0x099]], 12),
    ],
    "gTileset_DepartmentStore": [
        ([[0x2C6]], 30, {"crown": 1}), ([[0x2C7]], 30, {"crown": 1}),
        ([[0x320, 0x321], [0x328, 0x329], [0x330, 0x331]], 40, {"depth": 10}),
        ([[0x320, 0x321], [0x328, 0x329]], 28, {"depth": 10}),
        ([[0x300, 0x301, 0x302]], 12), ([[0x31F, 0x31F], [0x327, 0x327]], 24, {"depth": 8}),
        ([[0x34B, 0x34C], [0x353, 0x354]], 24, {"depth": 8}),
        # the roof: its drink machines, boxes
        ([[0x325], [0x32D]], 0, {"model": (28, 12)}),
        # the elevator's hut and the tower beside it, the roof light on top
        ([[0x32E, 0x32F, 0x32F], [0x336, 0x337, 0x337], [0x33D, 0x33C, 0x33E], [0x345, 0x344, 0x346]], 32),
        ([[0x32F, 0x34F], [0x337, 0x33F], [0x336, 0x33F], [0x336, 0x33F], [0x336, 0x33F], [0x336, 0x33F],
          [0x336, 0x33F], [0x33D, 0x347]], 16),
        # the green railing round it: front and back rails, the posts down
        # its sides (the green alone: the sky and the floor behind it stay)
        ([[0x339], [0x341]], 16, {"keep": ROOF_RAIL}), ([[0x33A], [0x341]], 16, {"keep": ROOF_RAIL}),
        ([[0x342], [0x341]], 16, {"keep": ROOF_RAIL}), ([[0x349], [0x341]], 16, {"keep": ROOF_RAIL}),
        ([[0x34A], [0x341]], 16, {"keep": ROOF_RAIL}),
        ([[0x338], [0x340]], 16, {"keep": ROOF_RAIL}), ([[0x35D], [0x351]], 16, {"keep": ROOF_RAIL}),
        ([[0x350], [0x358]], 16, {"keep": ROOF_RAIL}), ([[0x352], [0x35A]], 16, {"keep": ROOF_RAIL}),
    ],
    "gTileset_Museum": [
        # the tall glass case, and the fossil's table
        ([[0x293], [0x2A7], [0x2AF], [0x2B7]], 40),
        ([[0x2B8, 0x2B9], [0x2C0, 0x2C1], [0x2C8, 0x2C9]], 16),
        # pot plants, the leaves on the cell north of the pot
        ([[0x2AE], [0x2B6]], 30), ([[0x2CA], [0x2CB]], 30), ([[0x2AD], [0x2B5]], 30),
        ([[0x2F9, 0x2FA], [0x2FB, 0x2FC]], 10), ([[0x2CC], [0x2D4]], 24),
        ([[0x28B, 0x28C, 0x28D, 0x28E]], 14, {"crown": 1}),             # display cases
        ([[0x2D0, 0x2D1, 0x2D2, 0x2D3], [0x2E0, 0x2E1, 0x2E2, 0x2E3]], 24, {"crown": 1}),
        ([[0x2EA, 0x2EB]], 14, {"crown": 1}), ([[0x2F4, 0x2F5]], 14, {"crown": 1}),
        ([[0x290, 0x291, 0x292], [0x298, 0x299, 0x29A]], 14),         # the space shuttle
        ([[0x172, 0x166], [0x17A, 0x16E]], 10),
    ],
    "gTileset_FanClubDaycare": [
        ([[0x2B9], [0x30F]], 30), ([[0x2B8], [0x310]], 30),             # plants
        ([[0x29D, 0x29E, 0x29F], [0x2A5, 0x2A6, 0x2A7]], 10), ([[0x29D, 0x29F], [0x2A5, 0x2A7]], 10),
        ([[0x2B7, 0x2F9], [0x2A5, 0x2A7]], 10),
    ],
    "gTileset_SafariZoneBuilding": [
        ([[0x297], [0x29E]], 30), ([[0x297], [0x2A6]], 30), ([[0x29E]], 14), ([[0x2A6]], 14),
        ([[0x2A5, 0x2A5]], 10),
        ([[0x297], [0x2A3]], 30), ([[0x296]], 30, {"crown": 1}),
        ([[0x2BB]], 14), ([[0x2AF]], 14), ([[0x2BA]], 14), ([[0x29F]], 14), ([[0x2A7]], 14),
        ([[0x2B6]], 14), ([[0x2C4, 0x2C5]], 12), ([[0x2CC, 0x2CD], [0x2CE, 0x2CF]], 10),
        ([[0x2F1]], 24), ([[0x2ED, 0x2EE], [0x2F5, 0x2F6]], 10), ([[0x2EB, 0x2EC], [0x2F3, 0x2F4]], 10),
    ],
    "gTileset_PokemonLeague": [
        ([[0x349]], 16, {"solid": True}), ([[0x34B]], 16, {"solid": True}), ([[0x356]], 16, {"solid": True}), ([[0x372]], 16), ([[0x373]], 16), ([[0x249]], 14),
        # the Elite Four's statues
        ([[0x34A], [0x34D]], 32, {"solid": True}), ([[0x359], [0x35B]], 32, {"solid": True}), ([[0x354], [0x355]], 32, {"solid": True}),
        ([[0x370], [0x378]], 30), ([[0x371], [0x379]], 30),
    ],
    "gTileset_PokemonMansion": [
        # the rubble on the broken floor
        ([[0x2CB]], 12), ([[0x2CC]], 12),
        ([[0x313]], 24), ([[0x323]], 24), ([[0x361]], 24), ([[0x324]], 16), ([[0x31C]], 24), ([[0x32C]], 24),
    ],
    "gTileset_Condominiums": [
        # the roof: the stairs' hut, its white top flat, its face with the
        # door standing; the planters
        ([[0x31D, 0x31E, 0x31E, 0x31F], [0x325, 0x326, 0x326, 0x327], [0x325, 0x326, 0x326, 0x327],
          [0x325, 0x326, 0x326, 0x327], [0x325, 0x326, 0x326, 0x327], [0x330, 0x331, 0x332, 0x333],
          [0x338, 0x339, 0x33A, 0x33B]], 24),
        ([[0x340, 0x341], [0x348, 0x349]], 14),
        ([[0x2CA]], 16), ([[0x2D0]], 16), ([[0x2D1]], 16), ([[0x2CE]], 16),
    ],
    "gTileset_GameCorner": [
        ([[0x2D6]], 16), ([[0x2F0]], 16),
    ],
    "gTileset_PewterGym": [
        ([[0x2B2]], 16), ([[0x2DE]], 16),
        # the rocks: low, their tops seen from above (stood up whole, as
        # partitions, they were sheets of paper side on)
        # (cut out by colour: the floor's own grey is the rocks', and taken
        # for floor it hollowed them out)
        ([[0x2A3]], 8, PEWTER_ROCK), ([[0x2A4]], 8, PEWTER_ROCK),
        ([[0x2A2]], 8, PEWTER_ROCK), ([[0x29B]], 8, PEWTER_ROCK),
    ],
    "gTileset_CeladonGym": [
        ([[0x2B9]], 16),
    ],
    "gTileset_ViridianGym": [
        ([[0x2A9]], 16),
    ],
    "gTileset_BikeShop": [
        ([[0x282]], 16),
        ([[0x284]], 16),
        ([[0x28B]], 16),
        ([[0x290]], 16),
        ([[0x29C]], 16),
    ],
    "gTileset_VermilionGym": [
        ([[0x2B8]], 9),          # the bins: the rim their top, the can its front
        ([[0x2BA]], 16),
        ([[0x286]], 16),
    ],
    "gTileset_SaffronGym": [
        ([[0x29E]], 16),
    ],
    "gTileset_SeaCottage": [
        ([[0x28D]], 16),
        ([[0x2B0]], 16),
        ([[0x2B3]], 16),
    ],
    "gTileset_FuchsiaGym": [
        ([[0x297]], 16),
    ],
    "gTileset_CinnabarGym": [
        ([[0x2B7]], 16),
    ],
    "gTileset_CeruleanGym": [
        ([[0x2D2]], 16),
    ],
    "gTileset_BurgledHouse": [
        ([[0x29E]], 16),
    ],
    "gTileset_IslandHarbor": [
        # the railing along the quay (its posts and rail, not the quay)
        ([[0x28D]], 16, {"keep": HARBOR_RAIL}), ([[0x2A5]], 16, {"keep": HARBOR_RAIL}),
        ([[0x2AD]], 16),
    ],
}
# Partitions: walls drawn inside a room (Silph Co.'s offices, the Rocket
# Hideout's corridors), by tileset. Each run of them down a column stands
# as a wall PARTITION_H tall, its drawing above that its top; listed one
# metatile at a time, never guessed.
PARTITION_H = 12
PARTITIONS = {
    # Silph Co. and the Rocket Hideout: the white office walls, the teal
    # maze blocks, the reception counter
    "gTileset_SilphCo": {0x288, 0x289, 0x28A, 0x28B, 0x28C, 0x290, 0x291, 0x292, 0x293, 0x294,
                         0x298, 0x29C, 0x2DE, 0x2DF, 0x2E6, 0x2E7, 0x2FF, 0x305, 0x306, 0x307,
                         0x28D, 0x28E, 0x295, 0x296, 0x29D, 0x29E, 0x29F, 0x2A5, 0x2A7, 0x2AE,
                         0x2E5, 0x36C, 0x374, 0x373, 0x370, 0x371, 0x372,
                         # desks, crates, the tables, the Rockets' machine
                         0x2B8, 0x2B9, 0x2BA, 0x2BB, 0x2C3, 0x2C4, 0x397, 0x398, 0x326, 0x327,
                         0x32E, 0x32F, 0x310, 0x311, 0x318, 0x319, 0x392, 0x393, 0x394, 0x395,
                         0x36D, 0x36E, 0x36F, 0x391, 0x31C, 0x31D, 0x388, 0x389,
                         0x2AD, 0x2AF, 0x2B5, 0x2B6, 0x2B7, 0x2BD, 0x2BE,
                         0x3A2, 0x3A4, 0x3F0, 0x3F1, 0x3F8, 0x3F9, 0x3F4, 0x3F5, 0x3F6, 0x313, 0x315, 0x31B},
}
PARTITIONS.update({
    "gTileset_SSAnne": {0x286, 0x28E, 0x28D, 0x295, 0x287, 0x28F, 0x28B, 0x293, 0x283, 0x2AD,
                        0x284, 0x285, 0x2A7, 0x290, 0x2A6, 0x2D0, 0x2D1, 0x2D4, 0x2D2, 0x2D3,
                        0x2DA, 0x2DB, 0x2D8, 0x2D9, 0x2BF, 0x2EB, 0x2EA, 0x2F2, 0x305, 0x306,
                        0x307, 0x30D, 0x30E, 0x30F, 0x2F5, 0x2F6},
    "gTileset_PokemonTower": {0x28C, 0x288, 0x2A0, 0x28D, 0x290, 0x28A, 0x28B,
                              0x2D1, 0x2D2, 0x2D3, 0x2D4, 0x2C8},
    "gTileset_TrainerTower": {0x288, 0x290, 0x28A, 0x28C, 0x294, 0x28B, 0x291, 0x29D, 0x29E,
                              0x29F, 0x2B6, 0x2C1, 0x2B7, 0x2B4, 0x2C0, 0x295, 0x2C5, 0x2C6,
                              0x2C7, 0x377, 0x2AC, 0x28D, 0x2A1, 0x2A8, 0x2A9, 0x2BF, 0x2E8,
                              0x2F0, 0x2AD, 0x2CE, 0x2A2, 0x2AA, 0x2AB, 0x28E, 0x376, 0x2B9,
                              0x2CB, 0x062, 0x2F2, 0x2F1, 0x2EA, 0x2FB, 0x382, 0x2FD},
})
PARTITIONS.update({
    "gTileset_Lab": {0x2D4, 0x2D5, 0x2D3, 0x2CF, 0x2D6, 0x2D7, 0x06F, 0x08F, 0x077, 0x300, 0x07F,
                     0x308, 0x2DC, 0x2DD},
    "gTileset_DepartmentStore": {0x298, 0x2B0, 0x2A0, 0x2A8, 0x2AE, 0x2AF, 0x29F, 0x2B1, 0x2A7,
                                 0x2AD, 0x2EC, 0x2E1, 0x2CF, 0x2D3, 0x2D4, 0x2D5, 0x2DB, 0x2DD,
                                 0x2E3, 0x2F3, 0x2EB, 0x2D6, 0x2FB, 0x2EE, 0x2E6, 0x31C, 0x324,
                                 0x313, 0x314, 0x2E0, 0x306, 0x307, 0x30D, 0x30E, 0x30F, 0x2EF,
                                 0x2F7, 0x2D7, 0x2DF, 0x365},
})
PARTITIONS.update({
    "gTileset_Museum": {0x293, 0x29E, 0x2AC, 0x29C, 0x2A4, 0x294, 0x2B0, 0x29F, 0x2A7, 0x2AF,
                        0x2EF, 0x2F1, 0x2F0},
    "gTileset_FanClubDaycare": {0x30F, 0x310, 0x2E9, 0x2BD, 0x2BE, 0x2C4, 0x2C5, 0x2C6, 0x2CC,
                                0x2D0, 0x2B2, 0x2D8, 0x2B4, 0x2F6, 0x2F2, 0x2F5, 0x2E1, 0x304,
                                0x2FF, 0x2FC, 0x30E, 0x319, 0x320, 0x321},
    "gTileset_SafariZoneBuilding": {0x29C, 0x281, 0x289},
})
PARTITIONS.update({
    "gTileset_PokemonLeague": {0x383, 0x38B, 0x393, 0x390, 0x391, 0x3F0, 0x384, 0x38C, 0x3F1,
                               0x392, 0x394, 0x2D5, 0x2D4, 0x2DA, 0x2D9, 0x2F5, 0x2F4, 0x2FA},
})
# Walls drawn inside a room, the back wall of an office below a partition:
# each run down a column stands whole, as the room's own back wall does.
INNER_WALLS = {
    "gTileset_PokemonLeague": {0x283, 0x284, 0x285, 0x286, 0x287},
    "gTileset_SilphCo": {0x330, 0x338, 0x37F, 0x387, 0x35D, 0x365, 0x35E, 0x35F, 0x366, 0x367,
                         0x33E, 0x346, 0x33F, 0x347, 0x37B, 0x37C, 0x37D, 0x385, 0x38A, 0x38B,
                         0x38C, 0x38D, 0x352, 0x353, 0x35A, 0x35B, 0x272, 0x273, 0x27A, 0x27B,
                         0x276, 0x277, 0x27E, 0x27F,
                         0x358, 0x359, 0x360, 0x361},     # the elevator's door, set forward
}

WALL_ROWS = 2
WALL_GAP_MAX = 6        # the longest gap the collision leaves in a back wall
# rooms whose back wall is drawn taller
WALL_ROWS_BY = {"gTileset_PokemonLeague": 3}           # a room's back wall, from its top
# the wall goes on past its rows while it is drawn with these (the elevators'
# third row, their buttons)
WALL_MORE = {"gTileset_SilphCo": {0x2F8, 0x2FB, 0x2FC},
             # the Trainer Tower's timer gate, its steps
             "gTileset_TrainerTower": {0x382, 0x2FB, 0x2FD}}
VOID_SHARE = 0.85
INDOOR = ("MAP_TYPE_INDOOR",)

PARTITIONS.setdefault("gTileset_PokemonMansion", set()).update({0x2A0, 0x2A1, 0x2A2, 0x2A3, 0x2A4, 0x2A5, 0x2A8, 0x2A9, 0x2AA, 0x2AB, 0x2AC, 0x2AD, 0x2B1, 0x2B2, 0x2B3, 0x2B4, 0x2BD, 0x2BF, 0x2C5, 0x2C7, 0x2CD, 0x2ED, 0x2EE, 0x2EF, 0x2F3, 0x2F4, 0x2F5, 0x2F6, 0x2F7, 0x2F8, 0x2F9, 0x2FA, 0x2FB, 0x2FC, 0x300, 0x301, 0x302, 0x303, 0x304, 0x30C, 0x310, 0x311, 0x312, 0x317, 0x318, 0x319, 0x31A, 0x31D, 0x31E, 0x31F, 0x328, 0x32D, 0x32E, 0x330, 0x331, 0x332, 0x335, 0x336, 0x339, 0x33A, 0x340, 0x350, 0x354, 0x355, 0x356, 0x358, 0x360, 0x362, 0x367, 0x368, 0x36A, 0x370, 0x372, 0x374, 0x375, 0x376, 0x377, 0x380, 0x381})

PARTITIONS.setdefault("gTileset_Condominiums", set()).update({0x099, 0x289, 0x28B, 0x28C, 0x290, 0x291, 0x293, 0x294, 0x29C, 0x29D, 0x29E, 0x29F, 0x2A8, 0x2AA, 0x2AB, 0x2B0, 0x2B5, 0x2B8, 0x2B9, 0x2BA, 0x2BB, 0x2C0, 0x2C1, 0x2C2, 0x2C3, 0x2CD, 0x2CF, 0x2D5, 0x2D6, 0x2D7, 0x2DD, 0x2DE, 0x2DF, 0x2E5, 0x2E6, 0x2E7, 0x2ED, 0x2EE, 0x2F4, 0x2F5, 0x2F6, 0x2FA, 0x2FB, 0x2FC, 0x31B, 0x337, 0x33C, 0x33D, 0x33E, 0x33F, 0x348, 0x349, 0x34A, 0x34B, 0x330, 0x331, 0x332, 0x333, 0x338, 0x33A, 0x33B})

PARTITIONS.setdefault("gTileset_GameCorner", set()).update({0x28F, 0x297, 0x29B, 0x2A0, 0x2A1, 0x2A2, 0x2A3, 0x2A4, 0x2A5, 0x2A6, 0x2A7, 0x2AD, 0x2AE, 0x2AF, 0x2BC, 0x2BD, 0x2BE, 0x2CF, 0x2D7, 0x2EC, 0x2F4, 0x2F5, 0x2F6, 0x2F9, 0x2FA, 0x300, 0x301, 0x302, 0x30D, 0x30E, 0x315, 0x316, 0x2CC, 0x2CD, 0x2B8, 0x2B9, 0x2C0, 0x2C1})

PARTITIONS.setdefault("gTileset_CableClub", set()).update({0x294, 0x295, 0x2A8, 0x2B1, 0x2B2, 0x2B9, 0x2BA, 0x2C1, 0x2C2, 0x2C4, 0x2C5, 0x2C6, 0x2C7, 0x2C8, 0x2CB, 0x2D0, 0x2D3, 0x2E9, 0x2EF, 0x2F1, 0x2F7, 0x2F9, 0x2FA, 0x2FB, 0x2FC, 0x2FD, 0x2FE, 0x2FF, 0x300, 0x307, 0x30C, 0x30D, 0x310, 0x313, 0x318, 0x31B, 0x320, 0x323, 0x328, 0x32B, 0x338, 0x339, 0x33A, 0x33B, 0x33C, 0x33D, 0x33E, 0x33F, 0x340, 0x341, 0x342, 0x343, 0x348, 0x349, 0x34A, 0x34B})

PARTITIONS.setdefault("gTileset_UndergroundPath", set()).update({0x293, 0x297, 0x29B, 0x29F})

PARTITIONS.setdefault("gTileset_School", set()).update({0x299, 0x29A, 0x2A3, 0x2A4, 0x2AC})

PARTITIONS.setdefault("gTileset_PewterGym", set()).update({0x288, 0x28F, 0x290, 0x291, 0x292, 0x296, 0x297, 0x298, 0x29F, 0x29B, 0x2A2, 0x2A3, 0x2A4, 0x2CD, 0x2D5, 0x2DD})

PARTITIONS.setdefault("gTileset_RestaurantHotel", set()).update({0x28C, 0x292, 0x293, 0x294, 0x29A, 0x29B, 0x29C, 0x2AA, 0x2AB, 0x2AC, 0x2B9, 0x2BA, 0x2BB, 0x2C1, 0x2C2, 0x2C3, 0x2C6, 0x2C7, 0x2D2, 0x2D3, 0x2D9, 0x2E0, 0x2E1, 0x2E2, 0x2E3, 0x2E4, 0x2E7})

PARTITIONS.setdefault("gTileset_CeladonGym", set()).update({0x28D, 0x295, 0x2BE, 0x2BF, 0x28B, 0x2A0, 0x2A3})

PARTITIONS.setdefault("gTileset_ViridianGym", set()).update({0x29A, 0x29B, 0x29C, 0x29D, 0x29F, 0x2A0, 0x2A2, 0x2A3, 0x2A4, 0x2A5, 0x2A6, 0x2A8, 0x2AD, 0x2AE, 0x2B0, 0x2B1, 0x2B8, 0x2B9, 0x2CC, 0x2D1})

PARTITIONS.setdefault("gTileset_BikeShop", set()).update({0x288, 0x293, 0x298, 0x299, 0x29A, 0x2A8, 0x2A9})

PARTITIONS.setdefault("gTileset_VermilionGym", set()).update({0x285, 0x28D, 0x290, 0x297, 0x298, 0x29F, 0x2A8, 0x2AA, 0x2AB, 0x2B1, 0x2B2, 0x2B3, 0x2C0, 0x2C1, 0x2C2, 0x2C8, 0x2C9, 0x2A9, 0x2AC, 0x2B4})

PARTITIONS.setdefault("gTileset_SaffronGym", set()).update({0x283, 0x284, 0x28B, 0x28C, 0x294, 0x295, 0x297, 0x29F})

PARTITIONS.setdefault("gTileset_SeaCottage", set()).update({0x099, 0x28C, 0x28E, 0x28F, 0x291, 0x292, 0x293, 0x295, 0x296, 0x297, 0x29C, 0x2A4, 0x2A5, 0x2A6, 0x2B2, 0x2B4})

# Blocked cells drawn as plain floor: they stay flat (Fuchsia Gym's
# invisible walls, in the room and along its west edge).
FLOOR_BLOCKS = {"gTileset_FuchsiaGym": {0x282, 0x28A}}

PARTITIONS.setdefault("gTileset_CinnabarGym", set()).update({0x285, 0x286, 0x287, 0x28B, 0x28C, 0x28D, 0x28E, 0x28F, 0x290, 0x294, 0x296, 0x297, 0x298, 0x299, 0x29A, 0x29B, 0x29C, 0x29F, 0x2A0, 0x2A1, 0x2A2, 0x2A3, 0x2A5, 0x2A6, 0x2A8, 0x2B0, 0x2BD, 0x2BE, 0x2CC, 0x2D3, 0x2D4, 0x2D5, 0x2D6, 0x2D7, 0x2DC, 0x2DD, 0x2DE, 0x2DF})

PARTITIONS.setdefault("gTileset_CeruleanGym", set()).update({0x295, 0x296, 0x297, 0x2AE, 0x2AF})

PARTITIONS.setdefault("gTileset_BurgledHouse", set()).update({0x128, 0x129, 0x131, 0x295, 0x296, 0x2B0})

PARTITIONS.setdefault("gTileset_IslandHarbor", set()).update({0x28C, 0x28D, 0x28E, 0x28F, 0x294, 0x295, 0x296, 0x297, 0x298, 0x299, 0x29A, 0x29D, 0x2AC, 0x2C4, 0x2C6, 0x2C8, 0x2CA})

PARTITIONS.setdefault("gTileset_SeafoamIslands", set()).update({0x181})

PARTITIONS.setdefault("gTileset_PowerPlant", set()).update({0x289, 0x28A, 0x28D, 0x291, 0x292, 0x293, 0x294, 0x295, 0x296, 0x297, 0x298, 0x299, 0x29A, 0x29C, 0x29E, 0x2A0, 0x2A1, 0x2A2, 0x2A3, 0x2A4, 0x2A6, 0x2A7, 0x2A8, 0x2B0, 0x2B1, 0x2B8, 0x2B9, 0x2BA, 0x2BF, 0x2C0, 0x2C7, 0x2CF, 0x2D2, 0x2D3, 0x2D4, 0x2D5, 0x2D8, 0x2D9, 0x2DA, 0x2DB, 0x2DC, 0x2DD, 0x2DE, 0x2DF, 0x2E0, 0x2E8, 0x2E9, 0x2EA, 0x2EB, 0x2EC, 0x2ED, 0x2EE, 0x2EF, 0x2F0, 0x2F1, 0x2F2, 0x2F3, 0x2F4, 0x2F5, 0x2F8, 0x2F9, 0x2FA, 0x2FB, 0x2FC, 0x2FD, 0x308, 0x310})


def layer(ts, entries, which):
    out = [[None] * 16 for _ in range(16)]
    for q in range(4):
        entry = entries[which * 4 + q]
        data = ts.subtile(entry & 0x3FF, (entry >> 12) & 0xF)
        fx, fy = bool(entry & 0x400), bool(entry & 0x800)
        for y in range(8):
            for x in range(8):
                out[(q >> 1) * 8 + y][(q & 1) * 8 + x] = data[(7 - y if fy else y) * 8 + (7 - x if fx else x)]
    return out


def indoor_layouts(root):
    layouts = json.load(open(os.path.join(root, "data", "layouts", "layouts.json"),
                             encoding="utf-8"))["layouts"]
    wanted = set()
    maps = os.path.join(root, "data", "maps")
    for name in os.listdir(maps):
        path = os.path.join(maps, name, "map.json")
        if os.path.exists(path):
            m = json.load(open(path, encoding="utf-8"))
            if m.get("map_type") in INDOOR:
                wanted.add(m.get("layout"))
    for index, entry in enumerate(layouts, start=1):
        if entry.get("id") in wanted:
            yield index, entry["id"]


class Room:
    def __init__(self, layout_id):
        self.L = fr_map_render.FrLayout(layout_id)
        self.w, self.h = self.L.w, self.L.h
        self._void = {}
        self.wall_art = {}      # (x, y) -> metatile drawn on the wall there instead
        # the doormat's half in the bottom edge row, and whatever is beside
        # the black under the room: floor, never furniture
        self.flat = {(x, y) for y in range(self.h) for x in range(self.w)
                     if y + 1 >= self.h or self.void(x, y + 1)}
        # blocked cells the game draws as floor (Fuchsia Gym's invisible
        # walls): they lie flat, the maze as hidden as on the GBA
        hidden = FLOOR_BLOCKS.get(self.L.primary, set()) | FLOOR_BLOCKS.get(self.L.secondary, set())
        self.flat |= {(x, y) for y in range(self.h) for x in range(self.w) if self.m(x, y) in hidden}
        self._reach = None

    def reachable(self, x, y):
        """Whether the player can stand on the cell: walking from the map's
        warps over unblocked cells. A cell of the back wall the collision
        leaves open is wall all the same, out of reach behind the blocked
        row below it (it left a gap in the wall). Without warps, every
        unblocked cell counts."""
        if self._reach is None:
            starts = set()
            maps = os.path.join(fr_art.ROOT, "data", "maps")
            for name in os.listdir(maps):
                path = os.path.join(maps, name, "map.json")
                if os.path.exists(path):
                    m = json.load(open(path, encoding="utf-8"))
                    if m.get("layout") == self.L.id:
                        starts |= {(w["x"], w["y"]) for w in m.get("warp_events", ())}
            starts = {(sx, sy) for sx, sy in starts if 0 <= sx < self.w and 0 <= sy < self.h}
            if not starts:
                self._reach = {(cx, cy) for cy in range(self.h) for cx in range(self.w)
                               if not self.L.collision(cx, cy)}
            else:
                seen, todo = set(starts), list(starts)
                while todo:
                    cx, cy = todo.pop()
                    for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                        if 0 <= nx < self.w and 0 <= ny < self.h and (nx, ny) not in seen                                 and not self.L.collision(nx, ny) and not self.void(nx, ny):
                            seen.add((nx, ny))
                            todo.append((nx, ny))
                self._reach = seen
        return (x, y) in self._reach

    def wall_gap(self, x, y):
        """An open cell out of reach in a short run of open cells with
        blocked cells at both ends of it, along its row: a gap in a wall
        (Pewter Gym's back wall), not a stretch of floor running to the edge
        or the sea round the S.S. Anne."""
        if self.L.collision(x, y) or self.reachable(x, y):
            return False
        ends = []
        for step in (-1, 1):
            cx = x + step
            while 0 <= cx < self.w and not self.L.collision(cx, y) and not self.void(cx, y):
                cx += step
            if not (0 <= cx < self.w) or self.void(cx, y):
                return False
            ends.append(cx)
        return ends[1] - ends[0] - 1 <= WALL_GAP_MAX

    def m(self, x, y):
        return self.L.metatile(x, y)

    def tileset_of(self, m):
        return self.L.primary if m < 0x280 else self.L.secondary

    def entries(self, m):
        return self.L.entries(m)

    def part_black(self, x, y):
        """A bevelled corner: a good part of it the black round the room."""
        m = self.m(x, y)
        px = self.L.metatile_image(m).convert("RGB").load()
        black = sum(1 for j in range(16) for i in range(16) if px[i, j] == (0, 0, 0))
        return 40 <= black < VOID_SHARE * 256

    def void(self, x, y):
        m = self.m(x, y)
        if m not in self._void:
            px = self.L.metatile_image(m).convert("RGB").load()
            black = sum(1 for j in range(16) for i in range(16) if px[i, j] == (0, 0, 0))
            self._void[m] = black >= VOID_SHARE * 256
        return self._void[m]


def drop_specks(art, size):
    """Clears the specks of an art: groups of fewer than `size` drawn pixels
    (the floor's grey dots, in a rock's own grey)."""
    seen = set()
    for j in range(16):
        for i in range(16):
            if art[j][i] is None or (i, j) in seen:
                continue
            group, todo = [], [(i, j)]
            seen.add((i, j))
            while todo:
                ci, cj = todo.pop()
                group.append((ci, cj))
                for ni, nj in ((ci - 1, cj), (ci + 1, cj), (ci, cj - 1), (ci, cj + 1)):
                    if 0 <= ni < 16 and 0 <= nj < 16 and (ni, nj) not in seen and art[nj][ni] is not None:
                        seen.add((ni, nj))
                        todo.append((ni, nj))
            if len(group) < size:
                for ci, cj in group:
                    art[cj][ci] = None


def expand(cells, xrep, yrep, n):
    """The pattern with its column xrep (or row yrep) repeated n times."""
    if xrep is not None:
        return [row[:xrep] + [row[xrep]] * n + row[xrep + 1:] for row in cells]
    if yrep is not None:
        return cells[:yrep] + [cells[yrep]] * n + cells[yrep + 1:]
    return cells


def match_objects(room):
    """[(cells {(x, y)}, x0, x1, ybot, h)] for each listed object found.

    An entry is (cells, h) or (cells, h, {"xrep": i} / {"yrep": j}): the
    column (row) named repeats as often as the room draws it - a counter
    or a divider as long as it runs."""
    found, taken = [], set()
    specs = []
    for ts in (room.L.primary, room.L.secondary):
        for spec in ROOM_OBJECTS.get(ts, ()):
            cells, h = spec[0], spec[1]
            opt = spec[2] if len(spec) > 2 else {}
            specs.append((cells, h, opt.get("xrep"), opt.get("yrep"), opt.get("depth", 0),
                          opt.get("rows"), opt.get("crown", 0), opt.get("solid", False),
                          opt.get("model"), opt))
    specs.sort(key=lambda s: -sum(1 for row in s[0] for c in row if c is not None))
    for base, h, xrep, yrep, depth, only, crown, solid, model, opt in specs:
        seated = "on" in opt
        reps = range(max(room.w, room.h), 0, -1) if (xrep is not None or yrep is not None) else (1,)
        for y in range(room.h):
            for x in range(room.w):
                for n in reps:
                    cells = expand(base, xrep, yrep, n)
                    rows, cols = len(cells), len(cells[0])
                    if x + cols > room.w or y + rows > room.h:
                        continue
                    part = only or rows       # the rows that are the object
                    here = {(x + i, y + j) for j in range(part) for i in range(cols)
                            if cells[j][i] is not None}
                    if here & taken and not seated:
                        continue
                    if all(room.m(x + i, y + j) == cells[j][i] for j in range(rows) for i in range(cols)
                           if cells[j][i] is not None):
                        # crown: the leaves drawn over the cell north of it
                        top = {(cx, cy - crown) for (cx, cy) in here if cy == y} if crown else set()
                        top = {c for c in top if c[1] >= 0 and c not in taken and not room.void(*c)}
                        here = here | top
                        # nearly as tall as drawn: a card, exactly
                        drawn = (y + part - min(c[1] for c in here)) * 16
                        hh = drawn if drawn - 4 <= h < drawn and not model else h
                        found.append((here, x, x + cols, y + part, hh, here, depth, solid, model, opt))
                        if not seated:
                            taken |= here
                        break
    return found, taken


# The plain back wall, row by row from its top, per tileset: drawn where an
# object standing against the wall covers it (the healing machine), and to
# square off the bevelled corners of a room.
PLAIN_WALL = {
    "gTileset_Building": [0x020, 0x028],
    "gTileset_PokemonCenter": [0x284, 0x28C],
    "gTileset_Mart": [0x287, 0x28F],
    # the labs' (in Building's own metatiles: without it, the houses')
    "gTileset_Lab": [0x069, 0x071],
}


def plain_wall(room):
    return PLAIN_WALL.get(room.L.secondary) or PLAIN_WALL.get(room.L.primary)


def walls(room, taken):
    """The room's back wall: each column's first WALL_ROWS cells that are not
    the black round the room, stood up at the last one's south edge; above an
    object standing in it (a plant against the wall), what is left of it."""
    out = []
    for x in range(room.w):
        y0 = next((y for y in range(room.h) if not room.void(x, y)), None)
        if y0 is None:
            continue
        cells = []
        rows = max(WALL_ROWS_BY.get(room.L.primary, WALL_ROWS), WALL_ROWS_BY.get(room.L.secondary, WALL_ROWS))
        for y in range(y0, min(room.h, y0 + rows)):
            # (a bevelled corner, half black, beside the black round the room)
            corner = room.part_black(x, y) and ((x > 0 and room.void(x - 1, y))
                                                or (x + 1 < room.w and room.void(x + 1, y)))
            plain = plain_wall(room)
            if plain and ((x, y) in taken or corner) and y - y0 < len(plain):
                room.wall_art[(x, y)] = plain[y - y0]
            elif (x, y) in taken or (not room.L.collision(x, y) and not room.wall_gap(x, y)) or corner:
                break
            cells.append((x, y))
        more = WALL_MORE.get(room.L.secondary, set()) | WALL_MORE.get(room.L.primary, set())
        while cells and len(cells) == rows and more:
            y = cells[-1][1] + 1
            if y >= room.h or (x, y) in taken or room.m(x, y) not in more or not room.L.collision(x, y):
                break
            cells.append((x, y))
            rows += 1
        if cells:
            out.append((set(cells), x, x + 1, y0 + len(cells), len(cells) * 16))
    return out


AUTO_BOX = 12          # an unlisted piece of furniture's front
AUTO_CARD = 14         # an unlisted single thing standing


def has_upper(room, m):
    return any(v & 0x3FF for v in room.entries(m)[4:])


def partitions(room, taken, table=None):
    """The listed partition cells, a run down each column at a time."""
    ids = set()
    for ts in (room.L.primary, room.L.secondary):
        ids |= (table or PARTITIONS).get(ts, set())
    cells = {(x, y) for y in range(room.h) for x in range(room.w)
             if (x, y) not in taken and room.m(x, y) in ids}
    out = []
    for cx in sorted({c[0] for c in cells}):
        col = sorted(cy for (px, cy) in cells if px == cx)
        start = col[0]
        for a, b in zip(col, col[1:] + [None]):
            if b != a + 1:
                run = {(cx, yy) for yy in range(start, a + 1)}
                h = PARTITION_H if table is None else 16 * len(run)
                # a wall stands only facing floor: with the black (or the
                # map's edge) south of it it is the room's south wall, and
                # stood up it hid the room from the camera
                south_open = a + 1 < room.h and not room.void(cx, a + 1)
                if table is None or south_open:
                    out.append((run, cx, cx + 1, a + 1, h, cells))
                start = b
    return out


def auto_objects(room, taken):
    """Furniture no list names: each group of blocked cells left (not wall,
    not the black round the room) stands as a box AUTO_BOX tall, a column at
    a time so an L stands as drawn, its sides where the group ends. A group
    with leaves or a top drawn over the cells north of it (a pot plant, a
    lamp) is a card instead, the whole drawing standing."""
    out, seen = [], set(taken)
    for y in range(room.h):
        for x in range(room.w):
            if (x, y) in seen or room.void(x, y) or not room.L.collision(x, y) \
                    or (x, y) in room.flat:
                continue
            group, todo = set(), [(x, y)]
            seen.add((x, y))
            while todo:
                cx, cy = todo.pop()
                group.add((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < room.w and 0 <= ny < room.h and (nx, ny) not in seen \
                            and not room.void(nx, ny) and room.L.collision(nx, ny) \
                            and (nx, ny) not in room.flat:
                        seen.add((nx, ny))
                        todo.append((nx, ny))
            # against the room's side or round its edge: the room's own
            # strip of wall or stairs, which lie as drawn
            if any(cx in (0, room.w - 1) or (cx > 0 and room.void(cx - 1, cy))
                   or (cx < room.w - 1 and room.void(cx + 1, cy)) for cx, cy in group):
                continue
            # what is drawn over the cells just north of it is part of it
            crown = set()
            for (cx, cy) in group:
                n = (cx, cy - 1)
                if n not in group and n not in seen and cy > 0 and not room.void(*n) \
                        and not room.L.collision(*n) and has_upper(room, room.m(*n)):
                    crown.add(n)
            # a card is a small thing (a plant, a lamp, a chair); a long run
            # of wall with things drawn on its top is a box, never a slab
            small = len(group) <= 2 and len({cx for cx, _ in group}) == 1
            card = small and (bool(crown) or len(group) == 1)
            if not card:
                crown = set()
            cells = group | crown
            seen |= crown
            for cx in sorted({c[0] for c in cells}):
                col = sorted(cy for (px, cy) in cells if px == cx)
                runs, start = [], col[0]
                for a, b in zip(col, col[1:] + [None]):
                    if b != a + 1:
                        runs.append((start, a))
                        start = b
                for y0, y1 in runs:
                    run = {(cx, yy) for yy in range(y0, y1 + 1)}
                    rows = y1 - y0 + 1
                    h = min(rows * 16 - 2, 30) if card else AUTO_BOX
                    if card and rows == 1:
                        h = AUTO_CARD
                    out.append((run, cx, cx + 1, y1 + 1, h, cells))
    return out


def object_mask(room, cells, all_cells):
    """{(x, y): 16x16 rgba or None} - the object's drawing over its cells,
    the floor showing round it removed: from the edge of its cells inward,
    every pixel drawn on the lower layer alone in a colour of the floor
    beside it is floor. (Only from the edge: a shelf's glass the floor's
    blue stays.)"""
    img = {}
    near = set()
    # the room's floor drawings, pixel by pixel: a pixel is floor where some
    # floor tile of the room draws that very colour at that very place
    if not hasattr(room, "floor_px"):
        room.floor_px = [set() for _ in range(256)]
        fms = {room.m(x, y) for y in range(room.h) for x in range(room.w)
               if not room.L.collision(x, y) and not room.void(x, y)
               and not any(v & 0x3FF for v in room.entries(room.m(x, y))[4:])}
        for fm in fms:
            fl = room.L.metatile_image(fm).convert("RGB").load()
            for j in range(16):
                for i in range(16):
                    room.floor_px[j * 16 + i].add(fl[i, j])
    if not cells:
        return {}
    xs = [c[0] for c in cells]; ys = [c[1] for c in cells]
    x0, y0 = min(xs), min(ys)
    for (cx, cy) in cells:
        m = room.m(cx, cy)
        full = room.L.metatile_image(m).convert("RGB").load()
        top = layer(room.ts, room.entries(m), 1)
        for j in range(16):
            for i in range(16):
                img[((cx - x0) * 16 + i, (cy - y0) * 16 + j)] = (full[i, j], bool(top[j][i][1]))
        fl = room.L.metatile_image(floor_near(room, cx, cy, all_cells)).convert("RGB").load()
        near |= {fl[i, j] for j in range(16) for i in range(16)}
    # also the colours of the floor beside it the object itself never draws
    own = {rgb for rgb, up in img.values() if up}
    loose = near - own
    # where it stands in the wall (a plant in the corner), the plain wall:
    # what it draws at that very place, and its colours the object's cells
    # below the wall never draw
    below = {img[((cx - x0) * 16 + i, (cy - y0) * 16 + j)][0] for (cx, cy) in cells
             if (cx, cy) not in room.wall_art for j in range(16) for i in range(16)}
    wall_px = {}
    for c in cells:
        if c in room.wall_art:
            wim = room.L.metatile_image(room.wall_art[c]).convert("RGB").load()
            pxs = [wim[i, j] for j in range(16) for i in range(16)]
            wall_px[c] = (pxs, set(pxs) - own - below)
    gone = set()
    todo = [p for p in img if (p[0] % 16 == 0 and (x0 + p[0] // 16 - 1, y0 + p[1] // 16) not in cells)
            or (p[0] % 16 == 15 and (x0 + p[0] // 16 + 1, y0 + p[1] // 16) not in cells)
            or (p[1] % 16 == 0 and (x0 + p[0] // 16, y0 + p[1] // 16 - 1) not in cells)
            or (p[1] % 16 == 15 and (x0 + p[0] // 16, y0 + p[1] // 16 + 1) not in cells)]
    # a cell whose lower layer is floor alone: all of that is floor
    for (cx, cy) in cells:
        if low_is_floor(room, cx, cy, all_cells):
            for j in range(16):
                for i in range(16):
                    q = ((cx - x0) * 16 + i, (cy - y0) * 16 + j)
                    if not img[q][1]:
                        gone.add(q)
    while todo:
        q = todo.pop()
        if q in gone or q not in img:
            continue
        rgb, upper = img[q]
        pos = (q[1] % 16) * 16 + q[0] % 16
        w = wall_px.get((x0 + q[0] // 16, y0 + q[1] // 16))
        if w and (rgb == w[0][pos] or rgb in w[1]):
            pass
        elif upper or (rgb not in room.floor_px[pos] and rgb not in loose):
            continue
        gone.add(q)
        todo += [(q[0] + 1, q[1]), (q[0] - 1, q[1]), (q[0], q[1] + 1), (q[0], q[1] - 1)]
    out = {}
    for (cx, cy) in cells:
        out[(cx, cy)] = [[None if ((cx - x0) * 16 + i, (cy - y0) * 16 + j) in gone
                          else img[((cx - x0) * 16 + i, (cy - y0) * 16 + j)][0] + (255,)
                          for i in range(16)] for j in range(16)]
    return out


def floor_near(room, x, y, skip):
    """The floor under a piece: among the plain floor cells near it, the
    one the room is most made of (a rug's edge beside a bed is not the floor
    under the bed)."""
    if not hasattr(room, "floor_count"):
        import collections
        room.floor_count = collections.Counter(
            room.m(i, j) for j in range(room.h) for i in range(room.w)
            if not room.L.collision(i, j) and not room.void(i, j)
            and not any(v & 0x3FF for v in room.entries(room.m(i, j))[4:]))
    best = None
    for d in range(1, 4):
        for dy in range(-d, d + 1):
            for dx in range(-d, d + 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < room.w and 0 <= ny < room.h and (nx, ny) not in skip \
                        and not room.void(nx, ny) and not room.L.collision(nx, ny):
                    m = room.m(nx, ny)
                    score = room.floor_count.get(m, 0)
                    if best is None or score > best[0]:
                        best = (score, m)
        if best is not None and best[0] > 0:
            return best[1]
    if room.floor_count:
        return room.floor_count.most_common(1)[0][0]
    return room.m(x, y)


def lower_is_floor(room, m):
    """True when the cell's lower layer is the floor itself (a chair drawn
    on the upper layer over the rug): it lies flat under the piece."""
    low = layer(room.ts, room.entries(m), 0)
    hit = sum(1 for j in range(16) for i in range(16)
              if low[j][i][0] in room.floor_px[j * 16 + i])
    return hit >= 0.75 * 256


def side_art(art_cells):
    """A box's side, 16x16: the colour its front is mostly painted in near
    its edge, outlined in its darkest colour along the top and the front."""
    import collections
    cols = collections.Counter()
    for art in art_cells:
        for j in range(16):
            for i in range(16):
                if art[j][i]:
                    cols[art[j][i][:3]] += 1
    if not cols:
        return None
    dark = min(cols, key=lambda c: sum(c))
    # its body, not its outline: the commonest colour that is not dark
    light = [(n, c) for c, n in cols.items() if sum(c) > 300]
    body = max(light)[1] if light else cols.most_common(1)[0][0]
    out = [[body + (255,) for _ in range(16)] for _ in range(16)]
    for k in range(16):
        out[0][k] = dark + (255,)
        out[k][15] = dark + (255,)
    return out


# ROOM_OVERLAYS: small things standing on a piece, the piece not theirs - the
# flowers on the Pokemon Center's counter. (cells, lift, base metatiles): the
# art is what the cells draw in colours the base metatiles never use.
FLOWER_POT = {(82, 148, 197), (255, 255, 255), (106, 197, 106), (213, 197, 106), (172, 148, 65)}
ROOM_OVERLAYS = {
    "gTileset_PokemonCenter": [
        # (a set of colours instead of bases: the thing is drawn in those
        # alone - the counter's red shows through the petals, its white is
        # theirs too)
        ([[0x2B1], [0x2B9]], 8, FLOWER_POT),
        ([[0x2B5], [0x2BD]], 8, FLOWER_POT),
    ],
}


def overlays(room, place_art):
    rows = []
    for ts in (room.L.primary, room.L.secondary):
        for cells, lift, bases in ROOM_OVERLAYS.get(ts, ()):
            base_cols = set()
            keep = bases if isinstance(bases, set) else None
            for b in ([] if keep else bases):
                im = room.L.metatile_image(b).convert("RGB").load()
                base_cols |= {im[i, j] for j in range(16) for i in range(16)}
            R, C = len(cells), len(cells[0])
            for y in range(room.h - R + 1):
                for x in range(room.w - C + 1):
                    if not all(room.m(x + i, y + j) == cells[j][i] for j in range(R) for i in range(C)):
                        continue
                    arts = {}
                    for j in range(R):
                        for i in range(C):
                            im = room.L.metatile_image(cells[j][i]).convert("RGB").load()
                            arts[(x + i, y + j)] = [[None if (im[a, b] not in keep if keep else im[a, b] in base_cols)
                                                     else im[a, b] + (255,)
                                                     for a in range(16)] for b in range(16)]
                    opaque = [cy * 16 + b for (cx, cy), art in arts.items()
                              for b in range(16) if any(art[b])]
                    if not opaque:
                        continue
                    top, ybot = min(opaque), max(opaque) + 1
                    for (cx, cy), art in sorted(arts.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                        if not any(any(r) for r in art):
                            continue
                        sx, sy = place_art(art)
                        rows.append(row(y=cy, x=cx, h=ybot - top, flags=FLAG_OVERLAY, lift=lift,
                                        ybot=ybot, top=top, sx=sx, sy=sy))
    return rows


FLAG_WEST, FLAG_EAST, FLAG_NO_GROUND, FLAG_BARE, FLAG_ATLAS = 1, 2, 4, 8, 16
FLAG_MODEL, FLAG_FLAT, FLAG_OVERLAY = 32, 64, 128

ROW_FIELDS = ("y", "x", "h", "flags", "depth", "lift", "cap", "inw", "ine", "ybot", "top",
              "tw", "te", "sx", "sy", "ground", "ssx", "ssy", "tsx", "tsy", "back")


def row(**kw):
    return tuple(kw.get(f, 0) for f in ROW_FIELDS)


def pixels(room, m):
    """The metatile's 256 pixels, row by row, cached."""
    cache = room.__dict__.setdefault("_px", {})
    if m not in cache:
        im = room.L.metatile_image(m).convert("RGB").load()
        cache[m] = [im[i, j] for j in range(16) for i in range(16)]
    return cache[m]


def low_is_floor(room, x, y, skip):
    """True when the cell's lower layer is floor alone - a plain pattern of
    a few colours, all of them drawn by one walkable floor cell round it (a
    chair drawn on the upper layer over a rug's middle): the thing is its
    upper layer, that floor lies under it."""
    cache = room.__dict__.setdefault("_lowfloor", {})
    if (x, y) not in cache:
        lo = layer(room.ts, room.entries(room.m(x, y)), 0)
        own = {lo[j][i][0] for j in range(16) for i in range(16)}
        hit = False
        if len(own) <= 4:
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    nx, ny = x + dx, y + dy
                    if (dx, dy) == (0, 0) or not (0 <= nx < room.w and 0 <= ny < room.h)                             or (nx, ny) in skip or room.void(nx, ny) or room.L.collision(nx, ny):
                        continue
                    nl = layer(room.ts, room.entries(room.m(nx, ny)), 0)
                    if own <= {nl[j][i][0] for j in range(16) for i in range(16)}:
                        hit = True
        cache[(x, y)] = hit
    return cache[(x, y)]


def ground_for(room, x, y, skip, art=None):
    """The floor under a piece's cell (art: its drawing there, None where the
    floor shows): its own lower layer when that is floor; else of the cells
    round it, the one the floor showing in it matches best; drawn over
    whole, the one beside it on its own row (a television on a rug's edge).
    Returns (metatile, bare, sure): not sure, drawn over whole - the piece's
    other cells on that row know better (the wood round a bed's middle)."""
    if low_is_floor(room, x, y, skip):
        return room.m(x, y), True, True
    import collections
    freq = room.__dict__.get("_freq")
    if freq is None:
        freq = room._freq = collections.Counter(room.m(i, j) for j in range(room.h) for i in range(room.w))
    full = pixels(room, room.m(x, y))
    shown = [k for k in range(256) if art is None or art[k // 16][k % 16] is None]
    best = None
    row_best = None
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            nx, ny = x + dx, y + dy
            if (dx, dy) == (0, 0) or not (0 <= nx < room.w and 0 <= ny < room.h)                     or (nx, ny) in skip or room.void(nx, ny):
                continue
            c = room.m(nx, ny)
            # a cell with something drawn over it (a phone, a plant) is not
            # the floor, whatever it shows round it
            if has_upper(room, c) and room.L.collision(nx, ny):
                continue
            d = max(abs(dx), abs(dy))
            if dy == 0 and (row_best is None or d < row_best[0]):
                row_best = (d, c)
            cp = pixels(room, c)
            seen = sum(1 for k in shown if full[k] == cp[k])
            # matching alike (the wood showing by a bed matches a rug's edge
            # drawn on wood too): the floor the room is most made of
            score = (seen, freq[c], dy == 0, -d)
            if best is None or score > best[0]:
                best = (score, c, seen)
    if best and best[2] >= 16:
        return best[1], False, True
    if row_best:
        return row_best[1], False, False
    return floor_near(room, x, y, skip), False, False


def seated_mask(room, cells, first, bases):
    """A thing standing on another piece: its drawing less what is drawn
    there without it, pixel for pixel - bases, one metatile a row (the
    plain wall behind, the counter's top under it)."""
    out = {}
    for (cx, cy) in cells:
        own = pixels(room, room.m(cx, cy))
        base = pixels(room, bases[min(cy - first, len(bases) - 1)])
        out[(cx, cy)] = [[None if own[j * 16 + i] == base[j * 16 + i] else own[j * 16 + i] + (255,)
                          for i in range(16)] for j in range(16)]
    return out


def top_art(masks, cells, cx, top_px, ybot_px, roof=0):
    """A box's top over column cx: each pixel column's first rows of the
    drawing, stretched back - opaque wherever the column is drawn at all;
    with a roof, those roof rows themselves (its drawn top)."""
    def px(i, r):
        art = masks.get((cx, r // 16))
        return art[r % 16][i] if art else None
    art = [[None] * 16 for _ in range(16)]
    for i in range(16):
        t = next((r for r in range(top_px, ybot_px) if px(i, r)), None)
        if t is None:
            continue
        for k in range(16):
            if roof:
                art[k][i] = px(i, top_px + k * roof // 16) or px(i, t)
            else:
                art[k][i] = px(i, t + min(2, k * 3 // 16)) or px(i, t)
    return art if any(any(r) for r in art) else None


def build(root, place_art):
    """place_art(rgba16x16) -> (sx, sy). Returns [(layout index, [cell rows])]."""
    out = []
    for index, lid in indoor_layouts(root):
        try:
            room = Room(lid)
        except Exception:
            continue
        room.ts = fr_art.Tilesets(room.L.primary, room.L.secondary)
        object_mask(room, set(), set())         # builds room.floor_px
        plain = plain_wall(room)
        if plain:
            for pm in plain:                    # the wall behind an object is keyed too
                im = room.L.metatile_image(pm).convert("RGB").load()
                for j in range(16):
                    for i in range(16):
                        room.floor_px[j * 16 + i].add(im[i, j])
        objects, taken = match_objects(room)
        seated = set().union(*[o[0] for o in objects if "on" in o[9]]) if objects else set()
        wall = walls(room, taken | seated)
        for w in wall:
            taken |= w[0]
        pieces = [(o, "object") for o in objects] + [(w, "wall") for w in wall]
        for pt in partitions(room, taken, INNER_WALLS):
            taken |= pt[0]
            pieces.append((pt, "inner"))
        for pt in partitions(room, taken):
            taken |= pt[0]
            pieces.append((pt, "auto"))
        all_cells = set().union(*[p[0][0] for p in pieces]) if pieces else set()
        rows = []
        # the bevelled corners left below the wall, squared off: floor
        if plain:
            for y in range(room.h):
                for x in range(room.w):
                    if (x, y) in all_cells or not room.part_black(x, y):
                        continue
                    if y + 1 >= room.h or room.void(x, y + 1):
                        continue                # the exit under the mat, not a corner
                    if x in (0, room.w - 1) or (x > 0 and room.void(x - 1, y)) \
                            or (x + 1 < room.w and room.void(x + 1, y)):
                        rows.append(row(y=y, x=x, flags=FLAG_FLAT, ground=floor_near(room, x, y, all_cells)))
        for piece, kind in pieces:
            # an inner wall stands as the back wall does, but on the floor
            # (seen past its edge, the room's floor and not the black)
            inner = kind == "inner"
            wall = kind in ("wall", "inner")
            cells, x0, x1, ybot, h = piece[:5]
            group = piece[5] if len(piece) > 5 else cells
            depth = piece[6] if len(piece) > 6 else 0
            solid = len(piece) > 7 and piece[7]
            model = piece[8] if len(piece) > 8 else None
            opt = piece[9] if len(piece) > 9 else {}
            on = opt.get("on")
            first = min(cy for _, cy in cells)
            masks = {}
            if kind == "object":
                if solid:
                    for (x, y) in cells:
                        im = room.L.metatile_image(room.m(x, y)).convert("RGB").load()
                        masks[(x, y)] = [[im[i, j] + (255,) for i in range(16)] for j in range(16)]
                elif on:
                    masks = seated_mask(room, cells, first, on[1])
                elif opt.get("keep") or opt.get("drop"):
                    # drawn in these colours alone (a curb round a pond), or
                    # without these (a fountain's spray over its water)
                    keep, drop = opt.get("keep"), opt.get("drop")
                    for (x, y) in cells:
                        im = room.L.metatile_image(room.m(x, y)).convert("RGB").load()
                        masks[(x, y)] = [[im[i, j] + (255,) if (keep is None or im[i, j] in keep)
                                          and (drop is None or im[i, j] not in drop) else None
                                          for i in range(16)] for j in range(16)]
                        if opt.get("speck"):
                            drop_specks(masks[(x, y)], opt["speck"])
                else:
                    masks = object_mask(room, cells, all_cells)
            # split: the last row's pixels from `cut` down are a thing of
            # their own in front of it (the SNES before the television)
            whole = dict(masks)
            under = {}
            if opt.get("split") and masks:
                cut = opt["split"][0]
                last = max(cy for _, cy in cells)
                for c in [c for c in cells if c[1] == last]:
                    art = masks[c]
                    under[c] = [r if j >= cut else [None] * 16 for j, r in enumerate(art)]
                    masks[c] = [r if j < cut else [None] * 16 for j, r in enumerate(art)]
            # it stands where its drawing ends, not at its cells' foot
            top_px, ybot_px = 0, ybot * 16
            if masks:
                opaque = [cy * 16 + j for (cx, cy), art in masks.items() for j in range(16) if any(art[j])]
                if opaque:
                    top_px, ybot_px = min(opaque), max(opaque) + 1
                else:
                    top_px = first * 16
            # back: stood this many pixels north of where its drawing ends -
            # "blocked", onto the south edge of its blocked cells, the floor
            # its drawing spills over left free to walk in front of it
            back = opt.get("back", 0)
            if back == "blocked":
                edge = 16 * (max((cy for (cx, cy) in cells if room.L.collision(cx, cy)), default=ybot - 1) + 1)
                back = max(0, ybot_px - edge)
            roof = opt.get("roof", 0)
            card = not model and h >= ybot_px - top_px - 4
            ss = (0, 0)
            if kind == "object" and not card:
                side = side_art(list(masks.values()))
                if side:
                    ss = place_art(side)
            mh, mdepth = (model if model else (h, depth))
            tops = {}
            if model and masks:
                for cx in sorted({c[0] for c in cells}):
                    art = top_art(masks, cells, cx, top_px, ybot_px, roof)
                    if art:
                        tops[cx] = place_art(art)
            if model and roof:
                # its front from below its drawn top, a pixel a pixel high
                top_px += roof
                mh = ybot_px - top_px
            # one plane per side: the piece's outermost drawn column on each
            # edge, not each cell's own (stepped, a bed's sides came apart)
            edge_w, edge_e = {}, {}
            if kind == "object":
                for (cx, cy), art in masks.items():
                    used = [i for i in range(16) if any(art[j][i] for j in range(16))]
                    if not used:
                        continue
                    if (cx - 1, cy) not in group:
                        edge_w[cx] = min(edge_w.get(cx, 16), used[0])
                    if (cx + 1, cy) not in group:
                        edge_e[cx] = min(edge_e.get(cx, 16), 15 - used[-1])
            unsure, known = [], {}
            for (x, y) in sorted(cells, key=lambda c: (c[1], c[0])):
                m = room.m(x, y)
                e = room.entries(m)
                upper = any(v & 0x3FF for v in e[4:]) and not wall
                flags = 0
                cap = 0
                inw = ine = 0
                if kind == "object":
                    art = masks[(x, y)]
                    if not any(any(r) for r in art):
                        continue                # nothing of it drawn here
                    sx, sy = place_art(art)
                    cap = next((j for j in range(16) if any(art[j][i] for i in range(16))), 0)
                    # its sides where its drawing ends, not at the cell's edge:
                    # cut out, a box's side stood apart from it
                    cols = [i for i in range(16) if any(art[j][i] for j in range(16))]
                    if cols:
                        inw, ine = cols[0], 15 - cols[-1]
                    inw, ine = edge_w.get(x, inw), edge_e.get(x, ine)
                else:
                    flags |= FLAG_ATLAS
                    sx, sy = room.wall_art.get((x, y), m), 0
                # a model's side reaches only as high as its drawing does at
                # that edge: taller, its inside showed over a rounded top
                tw = te = 0
                if kind == "object" and masks:
                    colcells = sorted(c for c in cells if c[0] == x)

                    def edge_top(cols):
                        # the edge's few columns: an outline a pixel in from
                        # the one before it does not end the side short
                        for (cx, cy) in colcells:
                            for j in range(16):
                                if any(masks[(cx, cy)][j][i] for i in cols):
                                    return cy * 16 + j
                        return top_px
                    tw = edge_top(range(inw, min(16, inw + 4)))
                    te = edge_top(range(max(0, 12 - ine), 16 - ine))
                if (x - 1, y) not in group:
                    flags |= FLAG_WEST
                if (x + 1, y) not in group:
                    flags |= FLAG_EAST
                if model:
                    flags |= FLAG_MODEL
                if on:
                    flags |= FLAG_OVERLAY
                    ground = 0
                elif inner:
                    ground = floor_near(room, x, y, all_cells)
                elif wall:
                    flags |= FLAG_NO_GROUND
                    ground = 0
                elif kind == "object":
                    ground, bare, sure = ground_for(room, x, y, all_cells,
                                                    whole.get((x, y)) if not solid else None)
                    if bare:
                        flags |= FLAG_BARE
                    if not sure:
                        unsure.append((len(rows), y))
                    elif not bare:
                        known.setdefault(y, []).append(ground)
                elif upper and low_is_floor(room, x, y, all_cells):
                    flags |= FLAG_BARE
                    ground = m
                else:
                    ground = floor_near(room, x, y, all_cells)
                ts = tops.get(x, (0, 0))
                rows.append(row(y=y, x=x, h=mh if model else h, flags=flags,
                                depth=mdepth if (model or y == first) else 0,
                                lift=on[0] if on else 0, cap=cap, inw=inw, ine=ine,
                                ybot=ybot_px, top=top_px, tw=tw, te=te, sx=sx, sy=sy,
                                ground=ground, ssx=ss[0], ssy=ss[1], tsx=ts[0], tsy=ts[1], back=back))
            # a cell drawn over whole: the floor its row's other cells found
            for k, y in unsure:
                if known.get(y):
                    g = max(set(known[y]), key=known[y].count)
                    rows[k] = rows[k][:15] + (g,) + rows[k][16:]
            # the thing split off in front: a low piece of its own, on the
            # cells' own floor
            if under:
                opaque = [cy * 16 + j for (cx, cy), art in under.items() for j in range(16) if any(art[j])]
                if opaque:
                    utop, ubot = min(opaque), max(opaque) + 1
                    for (x, y), art in sorted(under.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                        if any(any(r) for r in art):
                            sx, sy = place_art(art)
                            rows.append(row(y=y, x=x, h=opt["split"][1], flags=FLAG_OVERLAY,
                                            ybot=ubot, top=utop, sx=sx, sy=sy))
        rows += overlays(room, place_art)
        if rows:
            # a cell's own piece first, its wall before what stands in it
            rows.sort(key=lambda r: (r[0], r[1], 1 if r[3] & FLAG_OVERLAY else 0,
                                     0 if r[3] & FLAG_ATLAS else 1))
            out.append((index, lid, rows))
    return out


def write_table(rooms, path):
    lines = ["/* Generated by scripts/fr_gen_trees.py (fr_gen_rooms.py): each room's",
             " * standing pieces, cell by cell, row by row (voxel_room.c). */",
             "#ifndef CTR_VOXEL_ROOM_TABLE_H", "#define CTR_VOXEL_ROOM_TABLE_H", "",
             "#define ROOM_WEST 1", "#define ROOM_EAST 2", "#define ROOM_NO_GROUND 4",
             "#define ROOM_BARE 8",
             "#define ROOM_ATLAS 16    /* its art is metatile `sx` in the map's atlas */",
             "#define ROOM_MODEL 32    /* a box h tall, depth deep, its front the drawing */",
             "#define ROOM_FLAT 64     /* nothing stands: `ground` lies there */",
             "#define ROOM_OVERLAY 128 /* stands on the cell's piece, not its owner */", "",
             "static const struct { unsigned short layout, first, count; } sRoomLayouts[] = {"]
    first = 0
    for index, lid, rows in rooms:
        lines.append("    { %d, %d, %d }, /* %s */" % (index, first, len(rows), lid))
        first += len(rows)
    lines += ["};", "",
              "static const struct",
              "{",
              "    unsigned char y, x, h, flags, depth, lift, cap;",
              "    unsigned char inw, ine;     /* its sides this far in from the cell's edges */",
              "    unsigned short ybot, top;   /* pixels from the room's top */",
              "    unsigned short tw, te;      /* its drawing's first row at each edge */",
              "    unsigned short sx, sy, ground, ssx, ssy;   /* ss: its sides' art, 0 none */",
              "    unsigned short tsx, tsy;    /* a model's top art, 0 none */",
              "    unsigned char back;         /* stood this many pixels north of its drawing */",
              "} sRoomCells[] = {"]
    for index, lid, rows in rooms:
        for r in rows:
            lines.append("    { %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, 0x%03X, %d, %d, %d, %d, %d }," % r)
    lines += ["};", "", "#endif", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
