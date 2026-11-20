"""The website guide's wild Pokémon data, from the port's own tables.

usage: python tools/build_wild_guide.py [--tree C:/fr3ds/upstream]
                                        [--out site/data/wild.json]

Reads the bootstrapped tree (FireRed's tables in src/data/wild_encounters.json
as tools/dev/wild_renewed.py left them, the map headers, the region map's
place names, the species' names, types and National Pokédex numbers) and
writes one JSON file for site/guide.html. It holds names, levels and rates
only: no graphics. Run it again whenever the wild tables change.
"""
import argparse
import json
import re
from pathlib import Path

METHODS = [
    ("land_mons", "land"),
    ("water_mons", "surf"),
    ("rock_smash_mons", "rock"),
]
RODS = ["old_rod", "good_rod", "super_rod"]
ISLANDS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN"]
TYPES = ["NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BUG", "GHOST",
         "STEEL", "MYSTERY", "FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE",
         "DRAGON", "DARK"]
# Words the game writes in capitals that are not plain title case.
WORDS = {"MT.": "Mt.", "S.S.": "S.S.", "POKEMON": "Pokémon", "POKéMON": "Pokémon"}
# Map names whose last words don't say where in the place they are.
SUBS = {
    "MAP_SSANNE_EXTERIOR": "",
    "MAP_SEVEN_ISLAND_SEVAULT_CANYON_ENTRANCE": "Entrance",
    "MAP_SIX_ISLAND_ALTERING_CAVE": "",
    "MAP_MT_EMBER_EXTERIOR": "",
}


def title(text):
    out = []
    for word in text.split():
        if word in WORDS:
            out.append(WORDS[word])
        elif re.fullmatch(r"B?\d+F", word):
            out.append(word)
        else:
            out.append("-".join(p[:1] + p[1:].lower() for p in word.split("-")))
    return " ".join(out)


def species_name(raw):
    raw = raw.replace("{FEMALE}", "♀").replace("{MALE}", "♂")
    if raw == "FARFETCH'D":
        return "Farfetch'd"
    return title(raw)


def read_species(tree):
    names = {}
    for m in re.finditer(r'\[(SPECIES_\w+)\]\s*=\s*_\("([^"]*)"\)',
                         (tree / "src/data/text/species_names.h").read_text(encoding="utf-8")):
        names[m.group(1)] = species_name(m.group(2))
    dex = {}
    body = (tree / "include/constants/pokedex.h").read_text(encoding="utf-8")
    enum = body[body.index("NATIONAL_DEX_NONE"):]
    for n, m in enumerate(re.finditer(r"NATIONAL_DEX_(\w+)", enum)):
        dex.setdefault("SPECIES_" + m.group(1), n)
    types = {}
    info = (tree / "src/data/pokemon/species_info.h").read_text(encoding="utf-8")
    for m in re.finditer(r"\[(SPECIES_\w+)\]\s*=\s*\{.*?\.types\s*=\s*\{\s*TYPE_(\w+)\s*,\s*TYPE_(\w+)\s*\}",
                         info, re.S):
        a, b = m.group(2), m.group(3)
        types[m.group(1)] = [a.lower()] if a == b else [a.lower(), b.lower()]
    return names, dex, types


def read_places(tree):
    strings = {}
    for m in re.finditer(r'(sMapsecName_\w+)\[\]\s*=\s*_\("([^"]*)"\)',
                         (tree / "src/data/region_map/region_map_entry_strings.h").read_text(encoding="utf-8")):
        strings[m.group(1)] = m.group(2)
    mapsec = {}
    for m in re.finditer(r"\[(MAPSEC_\w+)\s*-\s*KANTO_MAPSEC_START\]\s*=\s*(sMapsecName_\w+)",
                         (tree / "src/data/region_map/region_map_entries.h").read_text(encoding="utf-8")):
        mapsec[m.group(1)] = strings[m.group(2)]
    maps = {}
    for path in (tree / "data/maps").glob("*/map.json"):
        header = json.loads(path.read_text(encoding="utf-8"))
        maps[header["id"]] = (header["name"], header.get("region_map_section"))
    return mapsec, maps


def letters(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper().replace("É", "E"))


def place(map_id, maps, mapsec):
    name, sec = maps[map_id]
    place_name = mapsec.get(sec, name)
    parts = name.split("_")
    if map_id == "MAP_SEVEN_ISLAND_SEVAULT_CANYON_ENTRANCE":
        place_name = "SEVAULT CANYON"  # its own section is "Canyon Entrance"
    chamber = re.fullmatch(r"MAP_SEVEN_ISLAND_TANOBY_RUINS_(\w+_CHAMBER)", map_id)
    if chamber:
        place_name, sub = "TANOBY RUINS", title(chamber.group(1).replace("_", " "))
    elif map_id in SUBS:
        sub = SUBS[map_id]
    else:
        # Drop the island and the words that repeat the place's own name.
        own = letters(place_name)
        rest = [p for p in parts if not re.fullmatch(r"(One|Two|Three|Four|Five|Six|Seven)Island", p)]
        while rest and own.startswith(letters(rest[0])):
            own = own[len(letters(rest[0])):]
            rest = rest[1:]
        sub = " ".join(re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z][a-z])", " ", p) for p in rest)
        sub = re.sub(r"\bRoom(\d)", r"Room \1", sub)
        if sub and letters(sub) in letters(place_name):
            sub = ""  # "Three Isle Port" / "Port"
    island = next((i for i, w in enumerate(ISLANDS) if map_id.startswith("MAP_%s_ISLAND" % w)), None)
    return title(place_name), sub.strip(), island


def group_of(map_id, island):
    if island is not None:
        return "sevii"
    if re.fullmatch(r"MAP_ROUTE\d+(_\w+)?", map_id):
        return "routes"
    if map_id.endswith(("_TOWN", "_CITY")) or map_id == "MAP_CINNABAR_ISLAND":
        return "towns"
    return "dungeons"


def slots(table, rates, names):
    """Same species in one method: rates added up, levels joined."""
    merged = {}
    for mon, rate in zip(table, rates):
        sp = mon["species"]
        if sp not in names:
            raise SystemExit("unknown species %s" % sp)
        lo, hi = mon["min_level"], mon["max_level"]
        if sp in merged:
            e = merged[sp]
            e["rate"] += rate
            e["min"] = min(e["min"], lo)
            e["max"] = max(e["max"], hi)
        else:
            merged[sp] = {"s": sp[8:], "min": lo, "max": hi, "rate": rate}
    return sorted(merged.values(), key=lambda e: (-e["rate"], e["min"]))


def build(tree):
    names, dex, types = read_species(tree)
    mapsec, maps = read_places(tree)
    data = json.loads((tree / "src/data/wild_encounters.json").read_text(encoding="utf-8"))
    group = data["wild_encounter_groups"][0]
    fields = {f["type"]: f for f in group["fields"]}
    areas, used, seen = [], set(), set()
    for enc in group["encounters"]:
        label = enc["base_label"]
        if not label.endswith("_FireRed") or enc["map"] in seen:
            continue  # LeafGreen, and Altering Cave's Mystery Gift variants
        seen.add(enc["map"])
        name, sub, island = place(enc["map"], maps, mapsec)
        methods = {}
        for key, short in METHODS:
            if key in enc:
                methods[short] = slots(enc[key]["mons"], fields[key]["encounter_rates"], names)
        if "fishing_mons" in enc:
            mons = enc["fishing_mons"]["mons"]
            rates = fields["fishing_mons"]["encounter_rates"]
            for rod in RODS:
                idx = fields["fishing_mons"]["groups"][rod]
                methods[rod.replace("_rod", "")] = slots([mons[i] for i in idx], [rates[i] for i in idx], names)
        for found in methods.values():
            used.update("SPECIES_" + e["s"] for e in found)
        areas.append({
            "id": enc["map"][4:].lower(),
            "name": name,
            "sub": sub,
            "group": group_of(enc["map"], island),
            "island": None if island is None else island + 1,
            "methods": methods,
        })

    def order(area):
        route = re.fullmatch(r"route(\d+)(_\w+)?", area["id"])
        return ({"routes": 0, "towns": 1, "dungeons": 2, "sevii": 3}[area["group"]],
                area["island"] or 0,
                int(route.group(1)) if route else 0,
                area["name"],
                [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", area["sub"])])

    areas.sort(key=order)
    species = {
        sp[8:]: {"name": names[sp], "dex": dex[sp], "types": types[sp]}
        for sp in sorted(used, key=lambda s: dex[s])
    }
    return {"schema": 1, "areas": areas, "species": species}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", default="C:/fr3ds/upstream", type=Path)
    ap.add_argument("--out", default=Path(__file__).resolve().parent.parent / "site/data/wild.json", type=Path)
    args = ap.parse_args()
    data = build(args.tree)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")
    print("%d places, %d species -> %s" % (len(data["areas"]), len(data["species"]), args.out))


if __name__ == "__main__":
    main()
