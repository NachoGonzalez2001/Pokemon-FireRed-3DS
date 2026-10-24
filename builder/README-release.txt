Pokémon FireRed 3DS
===================

A native Nintendo 3DS port of Pokémon FireRed that uses both screens.

This download does NOT contain the game. You need your own dump of your own
Pokémon FireRed (USA) cartridge, revision 1. The builder reads that ROM on this
computer and generates the game's data pack from it. The ROM is not uploaded,
copied or modified, and no Internet connection is needed.

What you need
-------------
- A Nintendo 3DS / 2DS family console with custom firmware (Luma3DS) and the
  Homebrew Launcher.
- A clean ROM of Pokémon FireRed (USA, Rev 1),
  SHA-1 dd5945db9b930750cb39d00c84da8571feebf417.
- The console's SD card in this computer (or any folder, to copy by hand).

Install
-------
1. Extract this whole ZIP to a folder.
2. Run FireRed3DS-Builder.exe.
3. Choose your ROM. The builder checks that it is the supported one.
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
