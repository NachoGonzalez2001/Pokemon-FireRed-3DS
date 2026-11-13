# Pokémon Rouge Feu en français

FireRed 3DS fonctionne avec la ROM française propre de **Pokémon Version Rouge
Feu (France, BPRF)**, avec ses textes et ses graphiques. La traduction n'est pas
distribuée : elle vient de ta propre ROM, sur ton ordinateur.

## Installer

Le builder reconnaît les deux ROMs prises en charge et choisit la variante tout
seul : la ROM américaine (BPRE) ou la française (BPRF).

| Langue | Code | SHA-1 de la ROM propre |
|---|---|---|
| Français | BPRF | `fc663907256f06a3a09e2d6b967bc9af4919f111` |
| Anglais | BPRE | `dd5945db9b930750cb39d00c84da8571feebf417` |

## Compiler la version française depuis le code

```sh
python tools/bootstrap.py --make --french-rom "/chemin/Pokemon Version Rouge Feu.gba" -j8
```

Le bootstrap applique les patchs, compile les outils et les includes générés,
exécute `tools/localize_french.py` avec ta ROM, puis compile le 3DSX dans
`build/upstream/3ds_port/firered3ds.3dsx`. Relancer sans `--french-rom`
réinitialise l'arbre, efface les objets compilés et les ressources localisées,
pour ne pas réutiliser les données d'une autre langue.

## Comment on obtient la version française

`tools/localize_french.py` vérifie le SHA-1 de la ROM et les empreintes SHA-256
des fichiers source avant d'écrire dans l'arbre généré. Le manifeste de
`tools/locales/french.json.gz` contient des positions dans le code, des décalages
et des tailles dans la ROM, des noms de symboles et des adresses. Il ne contient
aucun texte, graphique, son ni section de la ROM.

Le processus remplace les textes par ceux de ta ROM : 6 489 édits dans 328
fichiers (dialogues, menus, noms, descriptions du Pokédex, écrans d'aide,
script de terrain et de combat), soit 99,6 % des 6 517 chaînes dont les octets
diffèrent entre les deux ROMs. Il extrait aussi les quatre polices latines avec
leurs fichiers du port (`latin_normal`, `latin_male`, `latin_female`,
`latin_small`) et la table de largeur de la petite police, puis les 61
graphismes dont les pixels diffèrent : écran titre (logo et bandeau
« appuyez sur start »), tilesets général et Department Store, cartes de
dresseur, Pokédex, Easy Chat, écran de résumé, machine à sous, Teachy TV,
crédits, Party menu, écran de nommage, boîte à objets et à CT.

Une seule ressource reste en anglais : `department_store/metatiles.bin`, dont le
nombre de métatiles diffère dans la ROM française alors que le port construit
ses métatiles depuis les layouts. Le manifeste la liste avec sa raison, pour que
ce soit une décision et non un oubli.

## Ce qui n'est pas vérifié

Les textes, les polices et les graphismes sont comparés octet pour octet à la
ROM française au moment de la génération du manifeste, et la compilation
française a été lancée dans Azahar : écran titre, écrans d'aide, introduction.
Le reste de l'aventure n'a pas été parcouru en entier, et rien n'a été testé sur
une console physique avec cette branche de contribution. Les retours de jeu réel
sont les bienvenus.

## Régénérer le manifeste

```sh
python tools/locale_research/make_french_manifest.py \
    --elf baserom.elf --english-rom "FireRed (USA, Rev 1).gba" \
    --french-elf pokerougefeu.elf --french-rom "Rouge Feu (France).gba" \
    --tree build/upstream
```

`--elf` est la ROM américaine compilée depuis l'amont épinglé (agbcc,
`--emit-relocs`), `--french-elf` la décompilation française
(`qigast/pokerougefeu`, qui reconstruit BPRF à l'octet près) : les noms de
symboles communs donnent l'offset français de chaque symbole anglais. Le
manifeste est produit à partir de la décomp française de référence
(`qigast/pokerougefeu`, qui reconstruit BPRF à l'octet près), de l'ELF de la
décomp épinglée et des deux ROMs propres. Chaque littéral source est ré-encodé
et comparé aux octets de la ROM américaine avant d'être retenu : un texte qui
ne se ré-encode pas exactement à l'identique est écarté plutôt que deviné.
