# Pokémon FireRed 3DS Builder

Turns the player's own Pokémon FireRed (USA, Rev 1) ROM into `firered3ds.pak`
and installs the game on an SD card.

Release users get a standalone Windows executable (no Python needed). From
source (any OS, Python 3.11+ and Pillow):

```
python -m firered3ds_builder                          # window
python -m firered3ds_builder --payload DIR build --rom ROM --output OUT
python -m firered3ds_builder --payload DIR install --rom ROM --sd /media/me/3DS
python -m firered3ds_builder --payload DIR verify --pak FILE
python -m firered3ds_builder detect
```

`DIR` is a release's `payload/` folder (executable, `firered3ds.recipe`,
`voxelgen/`); by default the builder looks next to itself.

| Module | Role |
|---|---|
| `rom.py` | recognises the supported ROM |
| `recipe.py` | recipe format; rebuilds one file from the ROM and checks it |
| `vtree.py` | rebuilds the voxel generators' inputs from the ROM |
| `voxel.py` | runs the bundled generators (in child processes, or in-process for the web) |
| `pak.py` | writes and reads the data pack |
| `build.py` | ROM → data pack |
| `install.py` | SD card detection and installation |
| `cli.py`, `gui.py` | the two desktop front ends |
| `web.py` | entry point of the web builder (Pyodide in the browser) |
| `webmanifest.py` | `web-manifest.json`, the contract between a release and the website |

Privacy: the ROM is read into memory and never copied, uploaded or modified;
temporary files are removed even when a step fails.

## Web builder

The website (`site/`, published on GitHub Pages by `.github/workflows/site.yml`)
runs this same package in the browser (Pyodide, in a Web Worker) from
`FireRed3DS-WebPayload.zip`, through
`web.run_web_build(rom, payload, out_pak, progress, manifest)`. The only
difference with the desktop build is that the voxel generators run in-process
(`voxel.run_step_inprocess`): each script gets fresh sibling modules, argv,
working directory and import path, exactly as a new process would. Outputs are
checked against the same CRCs and ABI, so the pack is byte for byte the
desktop one.

Python in the browser has no network and no threads: the page downloads the
follower sprites itself (`web.follower_downloads()` lists them) into the
in-memory file system, laid out as the desktop cache, and
`web.run_web_followers()` packs them with the same code. `web.make_sd_zip()`
gives the player one ZIP with `3ds/firered3ds/`.

`tools/build_web_payload.py` makes the ZIP and `web-manifest.json` from a
release's `payload/` folder; `tools/build_site.py` assembles the whole site from
a release's Windows ZIP (the workflow does it on every release), and
`tools/build_web_payload.py --synthetic DIR` writes a synthetic payload and
"ROM" to exercise it without game data.

Tests: `python -m unittest discover -s builder/tests` (synthetic data only).
