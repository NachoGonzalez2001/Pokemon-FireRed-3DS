# Development helpers

| Script | Use |
|---|---|
| `mk.sh <log> <make args>` | make in `C:\fr3ds\upstream\3ds_port`, log to `C:\fr3ds\<log>.log`, summarize errors |
| `cycle.ps1 [-Wait s] [-Shot name] [-Keys seq]` | bootstrap overlay, build the 3dsx, run it in Azahar, capture `build/<name>.png`, print port.log and emulator errors |
| `a2l.sh <addr>...` | addr2line on `firered3ds.elf` |
| `raw2png.py <frame.raw> <out.png>` | convert a `CTR_FRAME_DUMP` frame (BGR555 240x160 + regs + palette) |
| `merge3.py <em_ref> <emerald patch> <tree> <file>...` | 3-way merge an Emerald-port patch's hunks into FireRed files |
| `take_ours.py <file>...` | resolve merge conflicts keeping the port side |
| `sizeof_scan.py` | count `sizeof()` uses on INCBIN arrays (stubs in this build) |

Run the bash ones through devkitPro's MSYS2: `$env:MSYSTEM='MSYS'; & C:\devkitPro\msys2\usr\bin\bash.exe -l tools/dkp.sh /c/fr3ds bash tools/dev/mk.sh ...`
