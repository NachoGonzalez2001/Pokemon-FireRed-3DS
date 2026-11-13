"""The port's wild Pokémon: every non-legendary family of the 386, spread
over Kanto and the Sevii Islands by level and by habitat (3DS port).

usage: python wild_renewed.py [--tree C:/fr3ds/upstream] [--check]

Rewrites the species of FireRed's tables in src/data/wild_encounters.json
(the LeafGreen ones are left as they are). Each slot keeps its level range
and its rate; only who lives there changes:

* grass and caves (12 slots) take a pool of shares: the commonest species go
  to the 20% slots, the rarest to the 1% ones;
* surf, rock smash (5 slots) and each fishing rod take one species per slot;
* a species is the root of its family, and a slot whose lowest level is two
  past an evolution by level gets the evolved form, as in the games
  (Pidgey on Route 1, Pidgeotto on Route 13). "=NAME" keeps that exact
  species at any level (Magikarp in the super rod's slots).

--check only reports: families that live nowhere, legendaries, and the
species each map gets.
"""
import argparse
import json
import re
from pathlib import Path

MARGIN = 2

# ---------------------------------------------------------------------------
# Surf: [60, 30, 5, 4, 1]   Rock smash: [60, 30, 5, 4, 1]
# Fishing: old rod [70, 30], good rod [60, 20, 20], super rod [40, 40, 15, 4, 1]
# ---------------------------------------------------------------------------
W_SEA_A = ["TENTACOOL", "WINGULL", "WAILMER", "SLOWPOKE", "LAPRAS"]
W_SEA_B = ["TENTACOOL", "WINGULL", "WAILMER", "MANTINE", "LAPRAS"]
W_SEA_C = ["TENTACOOL", "WINGULL", "MANTINE", "CORSOLA", "LAPRAS"]
W_FRESH_A = ["PSYDUCK", "MARILL", "LOTAD", "SURSKIT", "SLOWPOKE"]
W_FRESH_B = ["PSYDUCK", "MARILL", "WOOPER", "SLOWPOKE", "LOTAD"]
W_FRESH_C = ["PSYDUCK", "WOOPER", "MARILL", "LOTAD", "SLOWPOKE"]
W_ICE = ["SEEL", "SPHEAL", "CLAMPERL", "LAPRAS", "HORSEA"]
W_ICE_BACK = ["TENTACOOL", "SPHEAL", "LAPRAS", "MANTINE", "CLAMPERL"]
W_POLLUTED = ["PSYDUCK", "GRIMER", "KOFFING", "GULPIN", "LOTAD"]
W_VALLEY = ["WOOPER", "MARILL", "PSYDUCK", "LOTAD", "SURSKIT"]

F_SEA_A = ["=MAGIKARP", "TENTACOOL", "KRABBY", "HORSEA", "=MAGIKARP",
           "STARYU", "KRABBY", "SHELLDER", "CHINCHOU", "GYARADOS"]
F_SEA_B = ["=MAGIKARP", "TENTACOOL", "HORSEA", "KRABBY", "LUVDISC",
           "SHELLDER", "STARYU", "CARVANHA", "REMORAID", "GYARADOS"]
F_SEA_C = ["=MAGIKARP", "TENTACOOL", "REMORAID", "QWILFISH", "HORSEA",
           "WAILMER", "CHINCHOU", "CORSOLA", "RELICANTH", "GYARADOS"]
F_SEA_D = ["=MAGIKARP", "TENTACOOL", "QWILFISH", "REMORAID", "LUVDISC",
           "WAILMER", "CARVANHA", "CLAMPERL", "RELICANTH", "GYARADOS"]
F_FRESH_A = ["=MAGIKARP", "GOLDEEN", "POLIWAG", "GOLDEEN", "BARBOACH",
             "POLIWAG", "BARBOACH", "GOLDEEN", "CORPHISH", "=FEEBAS"]
F_FRESH_B = ["=MAGIKARP", "GOLDEEN", "POLIWAG", "BARBOACH", "CORPHISH",
             "GOLDEEN", "POLIWAG", "CORPHISH", "DRATINI", "=FEEBAS"]
F_FRESH_C = ["=MAGIKARP", "GOLDEEN", "POLIWAG", "BARBOACH", "GOLDEEN",
             "POLIWAG", "CORPHISH", "BARBOACH", "=FEEBAS", "GYARADOS"]
F_FRESH_D = ["=MAGIKARP", "GOLDEEN", "POLIWAG", "BARBOACH", "GOLDEEN",
             "POLIWAG", "GOLDEEN", "BARBOACH", "DRATINI", "GYARADOS"]
F_SAFARI = ["=MAGIKARP", "GOLDEEN", "POLIWAG", "GOLDEEN", "BARBOACH",
            "GOLDEEN", "=DRATINI", "DRAGONAIR", "=FEEBAS", "GYARADOS"]
F_ICE = ["=MAGIKARP", "HORSEA", "HORSEA", "SHELLDER", "KRABBY",
         "SHELLDER", "HORSEA", "CLAMPERL", "SEADRA", "GYARADOS"]
F_POLLUTED = ["=MAGIKARP", "GRIMER", "GRIMER", "BARBOACH", "=MAGIKARP",
              "GRIMER", "BARBOACH", "CORPHISH", "MUK", "=FEEBAS"]

R_TUNNEL = ["GEODUDE", "NOSEPASS", "ONIX", "SHUCKLE", "ARON"]
R_EMBER = ["GEODUDE", "SLUGMA", "NOSEPASS", "TORKOAL", "SHUCKLE"]
R_EMBER_DEEP = ["SLUGMA", "GEODUDE", "TORKOAL", "NUMEL", "MAGCARGO"]
R_KINDLE = ["GEODUDE", "NOSEPASS", "SHUCKLE", "ANORITH", "LILEEP"]
R_SEVAULT = ["GEODUDE", "NOSEPASS", "AERODACTYL", "LILEEP", "ANORITH"]
R_CERULEAN = ["GEODUDE", "NOSEPASS", "OMANYTE", "KABUTO", "AERODACTYL"]


def pool(text):
    """'RATTATA 25, PIDGEY 25' -> [('RATTATA', 25), ('PIDGEY', 25)]"""
    out = []
    for part in text.split(","):
        name, share = part.split()
        out.append((name, int(share)))
    assert sum(s for _, s in out) == 100, (text, sum(s for _, s in out))
    return out


TOWER_LOW = "GASTLY 45, SHUPPET 15, DUSKULL 15, CUBONE 15, MISDREAVUS 10"
LOST_CAVE = "GASTLY 25, ZUBAT 15, MURKROW 10, MISDREAVUS 10, SHUPPET 10, DUSKULL 10, SABLEYE 10, HAUNTER 5, ABSOL 5"
MANSION_B = "KOFFING 15, GRIMER 15, DITTO 15, RATTATA 10, GROWLITHE 10, VULPIX 10, MAGMAR 10, PORYGON 10, SLUGMA 5"
VICTORY_1 = ("ZUBAT 15, GEODUDE 15, MACHOP 15, ONIX 10, ARON 10, CUBONE 5, MAKUHITA 10, NOSEPASS 5, "
             "SABLEYE 5, MAWILE 5, HITMONLEE 3, HITMONCHAN 2")
EMBER_DEEP = "GEODUDE 35, SLUGMA 35, NUMEL 15, TORKOAL 10, MAGMAR 5"
ICEFALL_IN = "SWINUB 25, ZUBAT 15, SEEL 15, DELIBIRD 10, SNORUNT 15, SNEASEL 10, JYNX 5, SPHEAL 5"
ICEFALL_OUT = "SEEL 20, ZUBAT 15, SPHEAL 15, SNEASEL 15, SNORUNT 10, JYNX 10, DELIBIRD 10, SWINUB 5"
SAFARI_W = W_FRESH_B

# map -> {"land": shares, "water": 5, "rock": 5, "fish": 10}
DESIGN = {
    # ---- Pallet to Pewter: levels 2-12 ----
    "ROUTE1": {"land": "RATTATA 25, PIDGEY 25, SENTRET 15, ZIGZAGOON 15, HOOTHOOT 10, POOCHYENA 10"},
    "ROUTE22": {"land": "RATTATA 20, SPEAROW 20, MANKEY 15, POOCHYENA 15, NIDORAN_M 10, NIDORAN_F 10, ZIGZAGOON 10",
                "water": W_FRESH_A, "fish": F_FRESH_A},
    "ROUTE2": {"land": "RATTATA 20, PIDGEY 20, CATERPIE 15, WEEDLE 15, LEDYBA 10, WURMPLE 10, TAILLOW 10"},
    "VIRIDIAN_FOREST": {"land": "CATERPIE 20, WEEDLE 20, WURMPLE 15, SPINARAK 10, LEDYBA 10, NINCADA 10, PIKACHU 5, "
                                "SHROOMISH 5, SEEDOT 5"},
    "ROUTE3": {"land": "SPEAROW 20, TAILLOW 15, JIGGLYPUFF 10, NIDORAN_F 10, NIDORAN_M 10, MANKEY 10, WHISMUR 10, "
                       "SKITTY 10, SANDSHREW 5"},
    "MT_MOON_1F": {"land": "ZUBAT 35, GEODUDE 25, PARAS 10, CLEFAIRY 10, ARON 10, SABLEYE 5, NOSEPASS 5"},
    "MT_MOON_B1F": {"land": "PARAS 50, SHROOMISH 30, ZUBAT 20"},
    "MT_MOON_B2F": {"land": "ZUBAT 30, GEODUDE 20, CLEFAIRY 15, PARAS 10, ARON 10, LUNATONE 5, SOLROCK 5, SABLEYE 5"},
    "ROUTE4": {"land": "SPEAROW 20, EKANS 15, SANDSHREW 15, RATTATA 10, MANKEY 10, TRAPINCH 10, CACNEA 10, WHISMUR 10",
               "water": W_SEA_A, "fish": F_SEA_A},
    # ---- Cerulean, Vermilion: 7-17 ----
    "ROUTE24": {"land": "ODDISH 15, BELLSPROUT 15, PIDGEY 10, ABRA 10, HOPPIP 10, SUNKERN 10, LOTAD 10, SEEDOT 10, "
                        "MAREEP 10",
                "water": W_FRESH_A, "fish": F_FRESH_A},
    "ROUTE25": {"land": "MAREEP 15, PIDGEY 15, ODDISH 10, BELLSPROUT 10, ABRA 10, NATU 10, RALTS 10, "
                        "MEDITITE 5, VOLBEAT 5, ILLUMISE 5, SURSKIT 5",
                "water": W_FRESH_A, "fish": F_FRESH_A},
    "ROUTE5": {"land": "MEOWTH 15, PIDGEY 15, ODDISH 10, BELLSPROUT 10, SNUBBULL 10, SKITTY 10, ELECTRIKE 10, "
                       "JIGGLYPUFF 10, ABRA 10"},
    "ROUTE6": {"land": "MEOWTH 15, PIDGEY 15, ODDISH 10, BELLSPROUT 10, PLUSLE 10, MINUN 10, VENONAT 10, SURSKIT 10, "
                       "PSYDUCK 10",
               "water": W_FRESH_A, "fish": F_FRESH_A},
    "ROUTE11": {"land": "EKANS 15, SPEAROW 15, DROWZEE 15, SPOINK 10, MAKUHITA 10, WINGULL 10, SANDSHREW 10, "
                        "ZIGZAGOON 10, MR_MIME 5",
                "water": W_SEA_A, "fish": F_SEA_A},
    "DIGLETTS_CAVE_B1F": {"land": "DIGLETT 70, TRAPINCH 15, SANDSHREW 10, PHANPY 5"},
    "ROUTE9": {"land": "SPEAROW 15, RATTATA 15, EKANS 15, SANDSHREW 10, GLIGAR 10, CACNEA 10, TRAPINCH 10, "
                       "MANKEY 10, SUDOWOODO 5"},
    "ROUTE10": {"land": "VOLTORB 20, MAGNEMITE 15, ELECTRIKE 15, SPEAROW 10, MAREEP 10, EKANS 10, MAKUHITA 10, "
                        "PLUSLE 5, MINUN 5",
                "water": W_SEA_A, "fish": F_SEA_A},
    "ROCK_TUNNEL_1F": {"land": "ZUBAT 25, GEODUDE 20, MACHOP 15, ONIX 10, WHISMUR 10, MAKUHITA 10, ARON 10"},
    "ROCK_TUNNEL_B1F": {"land": "ZUBAT 25, GEODUDE 20, MACHOP 10, ONIX 10, MANKEY 10, NOSEPASS 10, MAWILE 10, "
                                "SABLEYE 5",
                        "rock": R_TUNNEL},
    # ---- Lavender, Celadon, Saffron: 13-25 ----
    "ROUTE8": {"land": "GROWLITHE 15, VULPIX 15, PIDGEY 10, MEOWTH 10, EKANS 10, HOUNDOUR 10, SNUBBULL 10, ABRA 10, "
                       "KECLEON 5, SPINDA 5"},
    "ROUTE7": {"land": "PIDGEY 10, MEOWTH 10, ODDISH 10, BELLSPROUT 10, GROWLITHE 10, VULPIX 10, AIPOM 10, "
                       "MURKROW 10, SPINDA 10, SNUBBULL 10"},
    "POKEMON_TOWER_3F": {"land": "GASTLY 55, SHUPPET 15, DUSKULL 15, CUBONE 15"},
    "POKEMON_TOWER_4F": {"land": TOWER_LOW},
    "POKEMON_TOWER_5F": {"land": TOWER_LOW},
    "POKEMON_TOWER_6F": {"land": "GASTLY 40, SHUPPET 15, DUSKULL 15, CUBONE 10, MISDREAVUS 10, HAUNTER 5, CHIMECHO 5"},
    "POKEMON_TOWER_7F": {"land": "GASTLY 35, SHUPPET 15, DUSKULL 15, MISDREAVUS 10, CUBONE 10, HAUNTER 10, CHIMECHO 5"},
    "ROUTE16": {"land": "SPEAROW 15, DODUO 15, RATTATA 15, ZIGZAGOON 10, SLAKOTH 10, TAILLOW 10, GIRAFARIG 10, "
                        "TEDDIURSA 10, LICKITUNG 5"},
    "ROUTE17": {"land": "SPEAROW 15, DODUO 15, PONYTA 15, RATTATA 10, GRIMER 10, ZANGOOSE 10, SEVIPER 10, "
                        "POOCHYENA 10, LICKITUNG 5"},
    "ROUTE18": {"land": "SPEAROW 15, DODUO 15, SWABLU 15, RATTATA 10, PONYTA 10, TAILLOW 10, FARFETCHD 10, "
                        "ZANGOOSE 5, SEVIPER 5, LICKITUNG 5"},
    # ---- Fuchsia and the south: 17-35 ----
    "ROUTE12": {"land": "ODDISH 15, BELLSPROUT 15, VENONAT 15, PIDGEY 10, FARFETCHD 10, LOTAD 10, SEEDOT 10, "
                        "ROSELIA 10, TROPIUS 5",
                "water": W_SEA_B, "fish": F_SEA_B},
    "ROUTE13": {"land": "VENONAT 15, ODDISH 10, BELLSPROUT 10, PIDGEY 10, SUNKERN 10, YANMA 10, ROSELIA 10, "
                        "FARFETCHD 10, DITTO 5, VOLBEAT 5, ILLUMISE 5",
                "water": W_SEA_B, "fish": F_SEA_B},
    "ROUTE14": {"land": "VENONAT 15, ODDISH 10, BELLSPROUT 10, PIDGEY 10, HOPPIP 10, YANMA 10, SHROOMISH 10, "
                        "GULPIN 10, NATU 10, DITTO 5"},
    "ROUTE15": {"land": "VENONAT 15, ODDISH 10, BELLSPROUT 10, PIDGEY 10, GULPIN 10, SEEDOT 10, CACNEA 10, "
                        "SPINDA 10, MILTANK 10, DITTO 5"},
    "SAFARI_ZONE_CENTER": {"land": "RHYHORN 15, EXEGGCUTE 15, NIDORAN_M 10, NIDORAN_F 10, VENONAT 10, GIRAFARIG 10, "
                                   "STANTLER 10, TROPIUS 6, SCYTHER 5, PINSIR 5, CHANSEY 4",
                           "water": SAFARI_W, "fish": F_SAFARI},
    "SAFARI_ZONE_EAST": {"land": "DODUO 15, NIDORAN_M 10, NIDORAN_F 10, EXEGGCUTE 10, PARAS 10, MILTANK 10, "
                                 "TANGELA 10, KANGASKHAN 5, SCYTHER 5, HERACROSS 5, LICKITUNG 5, TAUROS 5",
                         "water": SAFARI_W, "fish": F_SAFARI},
    "SAFARI_ZONE_NORTH": {"land": "RHYHORN 15, NIDORAN_M 10, NIDORAN_F 10, EXEGGCUTE 10, PARAS 10, PHANPY 10, "
                                  "TEDDIURSA 10, GLIGAR 10, CHANSEY 5, TAUROS 5, KECLEON 5",
                          "water": SAFARI_W, "fish": F_SAFARI},
    "SAFARI_ZONE_WEST": {"land": "DODUO 15, NIDORAN_M 10, NIDORAN_F 10, EXEGGCUTE 10, VENONAT 10, GIRAFARIG 10, "
                                 "SWABLU 10, TAUROS 5, KANGASKHAN 5, PINSIR 5, ABSOL 5, SPINDA 5",
                         "water": SAFARI_W, "fish": F_SAFARI},
    "POWER_PLANT": {"land": "VOLTORB 25, MAGNEMITE 25, ELECTRIKE 15, PIKACHU 10, MAREEP 10, ELECTABUZZ 5, PLUSLE 5, "
                            "MINUN 5"},
    "ROUTE21_NORTH": {"land": "TANGELA 25, LOTAD 15, WINGULL 15, ROSELIA 15, SHROOMISH 15, EXEGGCUTE 10, TROPIUS 5",
                      "water": W_SEA_B, "fish": F_SEA_B},
    "ROUTE21_SOUTH": {"land": "TANGELA 25, LOTAD 15, WINGULL 15, SEEDOT 15, HOPPIP 15, SUNKERN 10, CASTFORM 5",
                      "water": W_SEA_B, "fish": F_SEA_B},
    "ROUTE19": {"water": W_SEA_B, "fish": F_SEA_B},
    "ROUTE20": {"water": W_SEA_B, "fish": F_SEA_B},
    "SEAFOAM_ISLANDS_1F": {"land": "ZUBAT 35, PSYDUCK 20, SEEL 15, SPHEAL 15, SNORUNT 10, SWINUB 5"},
    "SEAFOAM_ISLANDS_B1F": {"land": "ZUBAT 30, SEEL 15, PSYDUCK 15, SPHEAL 15, SNORUNT 10, SWINUB 10, JYNX 5"},
    "SEAFOAM_ISLANDS_B2F": {"land": "ZUBAT 25, SEEL 15, SPHEAL 15, PSYDUCK 10, SNORUNT 10, SWINUB 10, SNEASEL 10, "
                                    "JYNX 5"},
    "SEAFOAM_ISLANDS_B3F": {"land": "ZUBAT 20, SEEL 20, SPHEAL 15, SWINUB 10, JYNX 10, SNEASEL 10, DELIBIRD 10, "
                                    "SNORUNT 5",
                            "water": W_ICE, "fish": F_ICE},
    "SEAFOAM_ISLANDS_B4F": {"land": "SEEL 25, SPHEAL 20, JYNX 15, ZUBAT 15, SNEASEL 10, DELIBIRD 10, SNORUNT 5",
                            "water": W_ICE, "fish": F_ICE},
    "POKEMON_MANSION_1F": {"land": "KOFFING 20, GRIMER 15, RATTATA 15, GROWLITHE 10, VULPIX 10, HOUNDOUR 10, "
                                   "TORKOAL 10, MAGMAR 5, PORYGON 5"},
    "POKEMON_MANSION_2F": {"land": "KOFFING 20, GRIMER 15, RATTATA 15, GROWLITHE 10, VULPIX 10, PONYTA 10, NUMEL 10, "
                                   "MAGMAR 5, SLUGMA 5"},
    "POKEMON_MANSION_3F": {"land": "KOFFING 20, GRIMER 15, RATTATA 15, HOUNDOUR 10, PONYTA 10, NUMEL 10, TORKOAL 10, "
                                   "MAGMAR 5, PORYGON 5"},
    "POKEMON_MANSION_B1F": {"land": MANSION_B},
    # ---- The League: 32-48 ----
    "ROUTE23": {"land": "MANKEY 15, SPEAROW 15, EKANS 10, SANDSHREW 10, GLIGAR 10, MAKUHITA 10, MEDITITE 10, "
                        "ABSOL 5, ZANGOOSE 5, SEVIPER 5, SKARMORY 5",
                "water": W_FRESH_B, "fish": F_FRESH_B},
    "VICTORY_ROAD_1F": {"land": VICTORY_1},
    "VICTORY_ROAD_2F": {"land": "ZUBAT 15, GEODUDE 15, MACHOP 10, ONIX 10, ARON 10, MANKEY 10, MEDITITE 10, "
                                "SABLEYE 5, MAWILE 5, SOLROCK 5, HITMONTOP 3, BAGON 2"},
    "VICTORY_ROAD_3F": {"land": "ZUBAT 15, GEODUDE 15, MACHOP 15, ONIX 10, ARON 10, MEDITITE 10, LUNATONE 5, "
                                "CUBONE 5, NOSEPASS 5, MAKUHITA 5, BAGON 3, BELDUM 2"},
    # ---- Towns ----
    "PALLET_TOWN": {"water": W_SEA_A, "fish": F_SEA_A},
    "VIRIDIAN_CITY": {"water": W_FRESH_A, "fish": F_FRESH_A},
    "CERULEAN_CITY": {"water": W_FRESH_A, "fish": F_FRESH_A},
    "VERMILION_CITY": {"water": W_SEA_A, "fish": F_SEA_A},
    "SSANNE_EXTERIOR": {"water": W_SEA_A, "fish": F_SEA_A},
    "CELADON_CITY": {"water": W_POLLUTED, "fish": F_POLLUTED},
    "FUCHSIA_CITY": {"water": W_FRESH_B, "fish": F_FRESH_B},
    "CINNABAR_ISLAND": {"water": W_SEA_B, "fish": F_SEA_B},
    # ---- Mt. Ember and the Sevii Islands: 29-55 ----
    "ONE_ISLAND": {"water": W_SEA_C, "fish": F_SEA_C},
    "ONE_ISLAND_KINDLE_ROAD": {"land": "SPEAROW 15, PONYTA 15, VULPIX 12, GEODUDE 10, MEOWTH 10, NUMEL 10, TORKOAL 10, "
                                       "SLUGMA 10, MAGMAR 5, =CHARMELEON 1, =COMBUSKEN 1, =QUILAVA 1",
                               "water": W_SEA_C, "rock": R_KINDLE, "fish": F_SEA_C},
    "ONE_ISLAND_TREASURE_BEACH": {"land": "WINGULL 20, SPEAROW 15, TANGELA 10, MEOWTH 10, PSYDUCK 10, CORPHISH 10, "
                                          "SLOWPOKE 10, MARILL 7, CASTFORM 5, =WARTORTLE 1, =CROCONAW 1, "
                                          "=MARSHTOMP 1",
                                  "water": W_SEA_C, "fish": F_SEA_C},
    "MT_EMBER_EXTERIOR": {"land": "PONYTA 20, SPEAROW 15, MACHOP 10, GEODUDE 10, NUMEL 10, TORKOAL 10, VULPIX 10, "
                                  "MAGMAR 5, HOUNDOUR 5, SLUGMA 4, =QUILAVA 1",
                          "rock": R_EMBER},
    "MT_EMBER_SUMMIT_PATH_1F": {"land": "GEODUDE 35, MACHOP 30, ARON 10, MAKUHITA 10, NUMEL 10, TORKOAL 5"},
    "MT_EMBER_SUMMIT_PATH_2F": {"land": "GEODUDE 30, MACHOP 30, ARON 10, MAKUHITA 10, SLUGMA 10, TORKOAL 10",
                                "rock": R_EMBER},
    "MT_EMBER_SUMMIT_PATH_3F": {"land": "GEODUDE 35, MACHOP 30, ARON 10, MAKUHITA 10, NUMEL 10, TORKOAL 5"},
    "MT_EMBER_RUBY_PATH_1F": {"land": "GEODUDE 30, MACHOP 25, SLUGMA 15, NUMEL 15, TORKOAL 10, MAGMAR 5",
                              "rock": R_EMBER},
    "MT_EMBER_RUBY_PATH_B1F": {"land": EMBER_DEEP, "rock": R_EMBER},
    "MT_EMBER_RUBY_PATH_B2F": {"land": EMBER_DEEP, "rock": R_EMBER},
    "MT_EMBER_RUBY_PATH_B1F_STAIRS": {"land": EMBER_DEEP, "rock": R_EMBER},
    "MT_EMBER_RUBY_PATH_B2F_STAIRS": {"land": EMBER_DEEP, "rock": R_EMBER},
    "MT_EMBER_RUBY_PATH_B3F": {"land": "SLUGMA 60, NUMEL 20, TORKOAL 15, MAGMAR 5", "rock": R_EMBER_DEEP},
    "TWO_ISLAND_CAPE_BRINK": {"land": "SPEAROW 10, ODDISH 10, MEOWTH 10, PSYDUCK 10, SUNKERN 15, HOPPIP 15, "
                                      "ROSELIA 10, GIRAFARIG 10, TROPIUS 7, =IVYSAUR 1, =BAYLEEF 1, "
                                      "=GROVYLE 1",
                              "water": W_FRESH_C, "fish": F_FRESH_C},
    "THREE_ISLAND_BOND_BRIDGE": {"land": "PIDGEY 15, SWABLU 15, ODDISH 10, MEOWTH 10, VENONAT 10, PSYDUCK 10, "
                                         "SLAKOTH 10, NATU 10, SKITTY 5, CHIMECHO 5",
                                 "water": W_SEA_C, "fish": F_SEA_C},
    "THREE_ISLAND_BERRY_FOREST": {"land": "PIDGEY 15, ODDISH 15, VENONAT 10, DROWZEE 10, EXEGGCUTE 10, HOOTHOOT 10, "
                                          "SHROOMISH 10, HERACROSS 5, PINECO 5, AIPOM 5, TROPIUS 3, "
                                          "SNORLAX 2",
                                  "water": W_FRESH_C, "fish": F_FRESH_C},
    "THREE_ISLAND_PORT": {"land": "DUNSPARCE 100"},
    "FOUR_ISLAND": {"water": W_FRESH_C, "fish": F_FRESH_C},
    "FOUR_ISLAND_ICEFALL_CAVE_ENTRANCE": {"land": "SEEL 25, ZUBAT 20, SPHEAL 15, PSYDUCK 10, SNORUNT 10, SNEASEL 10, "
                                                  "JYNX 10",
                                          "water": W_ICE, "fish": F_ICE},
    "FOUR_ISLAND_ICEFALL_CAVE_1F": {"land": ICEFALL_IN},
    "FOUR_ISLAND_ICEFALL_CAVE_B1F": {"land": ICEFALL_IN},
    "FOUR_ISLAND_ICEFALL_CAVE_BACK": {"land": ICEFALL_OUT, "water": W_ICE_BACK, "fish": F_ICE},
    "FIVE_ISLAND": {"water": W_SEA_C, "fish": F_SEA_D},
    "FIVE_ISLAND_MEADOW": {"land": "HOPPIP 20, PIDGEY 10, SENTRET 10, MEOWTH 10, PSYDUCK 10, MAREEP 10, "
                                   "PLUSLE 5, MINUN 5, SMEARGLE 5, MILTANK 5, STANTLER 5, EEVEE 5",
                           "water": W_SEA_C, "fish": F_SEA_D},
    "FIVE_ISLAND_MEMORIAL_PILLAR": {"land": "HOPPIP 35, SWABLU 20, NATU 20, TAILLOW 15, CHIMECHO 5, TOGETIC 5",
                                    "water": W_SEA_C, "fish": F_SEA_D},
    "FIVE_ISLAND_RESORT_GORGEOUS": {"water": W_SEA_C, "fish": F_SEA_D},
    "FIVE_ISLAND_WATER_LABYRINTH": {"water": W_SEA_C, "fish": F_SEA_D},
    "SIX_ISLAND_PATTERN_BUSH": {"land": "CATERPIE 15, WEEDLE 15, SPINARAK 10, LEDYBA 10, HERACROSS 10, WURMPLE 10, "
                                        "NINCADA 10, PINSIR 5, VOLBEAT 5, ILLUMISE 5, SCYTHER 3, SHUCKLE 2"},
    "SIX_ISLAND_OUTCAST_ISLAND": {"water": W_SEA_C, "fish": F_SEA_D},
    "SIX_ISLAND_GREEN_PATH": {"water": W_SEA_C, "fish": F_SEA_D},
    "SIX_ISLAND_WATER_PATH": {"land": "SPEAROW 10, SENTRET 10, ODDISH 10, MEOWTH 10, PSYDUCK 10, LOTAD 10, MARILL 10, "
                                      "SURSKIT 10, SEEDOT 10, KECLEON 5, CASTFORM 5",
                              "water": W_SEA_C, "fish": F_SEA_D},
    "SIX_ISLAND_RUIN_VALLEY": {"land": "NATU 15, SPEAROW 10, YANMA 10, WOOPER 10, MEOWTH 10, WOBBUFFET 10, BALTOY 10, "
                                       "CACNEA 10, SMEARGLE 5, ABSOL 5, TRAPINCH 5",
                               "water": W_VALLEY, "fish": F_FRESH_C},
    "SIX_ISLAND_ALTERING_CAVE": {"land": "ZUBAT 30, AIPOM 10, TEDDIURSA 10, SHUCKLE 10, STANTLER 10, SMEARGLE 10, "
                                         "HOUNDOUR 10, PINECO 10"},
    "SEVEN_ISLAND_TRAINER_TOWER": {"water": W_SEA_C, "fish": F_SEA_D},
    "SEVEN_ISLAND_SEVAULT_CANYON_ENTRANCE": {"land": "PHANPY 15, SPEAROW 10, SENTRET 10, MEOWTH 10, GLIGAR 10, "
                                                     "TEDDIURSA 10, SANDSHREW 10, PSYDUCK 5, SKARMORY 5, ZANGOOSE 5, "
                                                     "SEVIPER 5, TRAPINCH 5"},
    "SEVEN_ISLAND_SEVAULT_CANYON": {"land": "GEODUDE 15, PHANPY 10, CUBONE 10, SPEAROW 10, ONIX 10, SKARMORY 10, "
                                            "ARON 10, GLIGAR 7, LARVITAR 5, BAGON 5, RHYHORN 5, =METANG 3",
                                    "rock": R_SEVAULT},
    "SEVEN_ISLAND_TANOBY_RUINS": {"water": W_SEA_C, "fish": F_SEA_D},
    "FIVE_ISLAND_LOST_CAVE": {"land": LOST_CAVE},  # every ROOMn
    # ---- Cerulean Cave: 46-67 ----
    "CERULEAN_CAVE_1F": {"land": "ZUBAT 15, MAGNEMITE 10, PARAS 10, MACHOP 10, MANKEY 10, DITTO 10, WOBBUFFET 10, "
                                 "VOLTORB 5, ABRA 5, SABLEYE 5, MAWILE 5, CHANSEY 5",
                         "water": W_FRESH_B, "rock": R_CERULEAN, "fish": F_FRESH_D},
    "CERULEAN_CAVE_2F": {"land": "ZUBAT 15, MACHOP 10, MAGNEMITE 10, PARAS 10, ABRA 10, DITTO 10, WOBBUFFET 10, "
                                 "VOLTORB 5, ABSOL 5, =SHELGON 5, =PUPITAR 5, RHYHORN 5",
                         "rock": R_CERULEAN},
    "CERULEAN_CAVE_B1F": {"land": "ABRA 15, DITTO 15, MAGNEMITE 10, PARAS 10, ZUBAT 10, MACHOP 10, WOBBUFFET 10, "
                                  "VOLTORB 5, =METANG 5, CHANSEY 5, PORYGON 5",
                          "water": W_FRESH_B, "rock": R_CERULEAN, "fish": F_FRESH_D},
}

# Not wild in the port: legendaries, mythicals, the babies (their families
# live here as the grown-ups), Unown (Tanoby's chambers keep theirs).
EXCLUDED = {
    "ARTICUNO", "ZAPDOS", "MOLTRES", "MEWTWO", "MEW", "RAIKOU", "ENTEI", "SUICUNE", "LUGIA", "HO_OH",
    "CELEBI", "REGIROCK", "REGICE", "REGISTEEL", "LATIAS", "LATIOS", "KYOGRE", "GROUDON", "RAYQUAZA",
    "JIRACHI", "DEOXYS",
}
BABIES = {"PICHU", "CLEFFA", "IGGLYBUFF", "TOGEPI", "TYROGUE", "SMOOCHUM", "ELEKID", "MAGBY", "AZURILL", "WYNAUT"}
KEPT = ("SEVEN_ISLAND_TANOBY_RUINS_", )  # the Unown chambers
LEVEL_METHODS = ("EVO_LEVEL", "EVO_LEVEL_ATK_GT_DEF", "EVO_LEVEL_ATK_EQ_DEF", "EVO_LEVEL_ATK_LT_DEF",
                 "EVO_LEVEL_SILCOON", "EVO_LEVEL_CASCOON", "EVO_LEVEL_NINJASK")


def read_evolutions(tree):
    """{species: [(method, param, target)]} from src/data/pokemon/evolution.h."""
    text = (tree / "src/data/pokemon/evolution.h").read_text(encoding="utf-8")
    evos = {}
    for m in re.finditer(r"\[SPECIES_(\w+)\]\s*=\s*\{(.*?\})\},", text, re.S):
        for e in re.finditer(r"\{(EVO_\w+),\s*(\w+),\s*SPECIES_(\w+)\}", m.group(2)):
            evos.setdefault(m.group(1), []).append((e.group(1), e.group(2), e.group(3)))
    return evos


def read_species(tree):
    """National-dex species names, in order (Gen 1-3, no SPECIES_OLD_UNOWN_*)."""
    text = (tree / "include/constants/species.h").read_text(encoding="utf-8")
    names = re.findall(r"#define SPECIES_(\w+)\s+\d+", text)
    return [n for n in names if n not in ("NONE", "EGG") and not n.startswith("OLD_UNOWN")
            and not n.startswith("UNOWN_") and n not in ("NUM_SPECIES",)]


def stage(name, level, evos):
    """The form a wild Pokémon of this family has at this level."""
    if name.startswith("="):
        return name[1:]
    while True:
        nxt = [t for meth, p, t in evos.get(name, []) if meth in LEVEL_METHODS and level >= int(p) + MARGIN]
        if not nxt:
            return name
        name = nxt[0]


def assign(shares, rates):
    """Slots for a pool of shares. Every species first gets one slot, the
    rarest the smallest (a 1% species takes a 1% slot); the slots left go,
    biggest first, to the species furthest below its share."""
    assert len(shares) <= len(rates), "%d species for %d slots" % (len(shares), len(rates))
    got = {n: 0 for n, _ in shares}
    out = [None] * len(rates)
    small = sorted(range(len(rates)), key=lambda i: (rates[i], -i))
    for (n, _), i in zip(sorted(shares, key=lambda s: s[1]), small):
        out[i] = n
        got[n] += rates[i]
    for i in sorted((i for i in range(len(rates)) if out[i] is None), key=lambda i: (-rates[i], i)):
        n = max(shares, key=lambda s: (s[1] - got[s[0]], s[1]))[0]
        out[i] = n
        got[n] += rates[i]
    return out


def design_for(mapname):
    if mapname in DESIGN:
        return DESIGN[mapname]
    if mapname.startswith("FIVE_ISLAND_LOST_CAVE_ROOM"):
        return DESIGN["FIVE_ISLAND_LOST_CAVE"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default="C:/fr3ds/upstream")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    tree = Path(a.tree)
    path = tree / "src/data/wild_encounters.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    group = data["wild_encounter_groups"][0]
    rates = {f["type"]: f["encounter_rates"] for f in group["fields"]}
    evos = read_evolutions(tree)
    known = set(read_species(tree))
    parent = {t: s for s, lst in evos.items() for _, _, t in lst}

    def root(n):
        """The family's first stage that lives in the wild (a baby's family
        starts at the grown-up: Pikachu, not Pichu)."""
        while n in parent and parent[n] not in BABIES:
            n = parent[n]
        return n

    placed, seen_altering, report = set(), False, []
    for enc in group["encounters"]:
        if not enc["base_label"].endswith("FireRed"):
            continue
        mapname = enc["map"][4:]
        if mapname.startswith(KEPT):
            continue
        if mapname == "SIX_ISLAND_ALTERING_CAVE":
            if seen_altering:  # the other eight are Mystery Gift tables, never active
                continue
            seen_altering = True
        des = design_for(mapname)
        assert des, "no design for " + mapname
        line = [mapname]
        for kind, key in (("land", "land_mons"), ("water", "water_mons"), ("rock", "rock_smash_mons"),
                          ("fish", "fishing_mons")):
            if key not in enc:
                assert kind not in des, (mapname, kind)
                continue
            assert kind in des, (mapname, "has %s in the game" % kind)
            mons = enc[key]["mons"]
            spec = des[kind]
            names = assign(pool(spec), rates[key]) if isinstance(spec, str) else list(spec)
            assert len(names) == len(mons), (mapname, kind)
            got = []
            for m, n in zip(mons, names):
                s = stage(n, m["min_level"], evos)
                assert s in known, (mapname, s)
                assert s not in EXCLUDED and s not in BABIES, (mapname, s)
                m["species"] = "SPECIES_" + s
                placed.add(root(s))
                got.append("%s %d-%d" % (s, m["min_level"], m["max_level"]))
            line.append("  %s: %s" % (kind, ", ".join(got)))
        report.append("\n".join(line))
    for name in DESIGN:
        if name not in ("FIVE_ISLAND_LOST_CAVE",):
            assert any(e["map"] == "MAP_" + name for e in group["encounters"]), "unknown map " + name

    families = {root(n) for n in known if n not in BABIES} - EXCLUDED - {"UNOWN"}
    missing = sorted(families - placed)
    print("families placed: %d, nowhere: %s" % (len(placed), ", ".join(missing) or "none"))
    if a.check:
        print("\n".join(report))
        return
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
