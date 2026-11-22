Pokémon FireRed 3DS
===================

A native Nintendo 3DS port of Pokémon FireRed that uses both screens.

This download does NOT contain the game. You need your own dump of your own
Pokémon FireRed cartridge. The builder reads that ROM on this computer and
generates the game's data pack from it, in your cartridge's language. The ROM is not uploaded,
copied or modified, and no Internet connection is needed.

What you need
-------------
- A Nintendo 3DS / 2DS family console with custom firmware (Luma3DS) and the
  Homebrew Launcher.
- A clean ROM of Pokémon FireRed, one of:
    USA (Rev 1)  dd5945db9b930750cb39d00c84da8571feebf417  English
    Spain        ab8f6bfe0ccdaf41188cd015c8c74c314d02296a  Spanish
    France       fc663907256f06a3a09e2d6b967bc9af4919f111  French
    Germany      18a3758ceeef2c77b315144be2c3910d6f1f69fe  German
    Italy        66a9d415205321376b4318534c0dce5f69d28362  Italian
  (SHA-1 and the language the game comes out in.)
- The console's SD card in this computer (or any folder, to copy by hand).

Install
-------
1. Extract this whole ZIP to a folder.
2. Run FireRed3DS-Builder.exe.
3. Choose your ROM. The builder checks it and picks its language's build.
4. Choose your SD card (it is detected when it has a "Nintendo 3DS" folder)
   or any folder.
5. Press Install. It writes:
       /3ds/firered3ds/FireRed3DS.3dsx
       /3ds/firered3ds/FireRed3DS.smdh
       /3ds/firered3ds/firered3ds.pak
6. Put the card back in the console and start Pokémon FireRed 3DS from the
   Homebrew Launcher.

Saves are kept in /3ds/firered3ds/firered3ds.sav. Reinstalling or updating
never touches it.

Command line
------------
    firered3ds-builder-cli.exe build   --rom "Pokemon FireRed.gba" --output out
    firered3ds-builder-cli.exe install --rom "Pokemon FireRed.gba" --sd E:\
    firered3ds-builder-cli.exe verify  --pak E:\3ds\firered3ds\firered3ds.pak

Updating
--------
Each release comes with its own builder. Run the new builder again with the
same ROM: a data pack only works with the release that generated it, and the
game tells you when they do not match.

Legal
-----
Pokémon FireRed 3DS is an unofficial fan project, not affiliated with or endorsed by
Nintendo, Game Freak, Creatures or The Pokémon Company. Pokémon and Pokémon
FireRed are trademarks of their respective owners. See LICENSES/.
