#!/bin/bash
# Run a command inside devkitPro's MSYS2 with the host toolchain on PATH:
#   C:\devkitPro\msys2\usr\bin\bash.exe -l tools/dkp.sh <dir> <command...>
# devkitPro's MSYS2 has make and git but no host gcc; the decomp's tools
# (gbagfx, preproc, mapjson...) are built with MSYS2 UCRT64's gcc/g++ and
# libpng, and Python is the Windows one.
set -e
UCRT=${UCRT:-/c/msys64/ucrt64}
export PATH="$DEVKITARM/bin:$DEVKITPRO/tools/bin:$UCRT/bin:$PATH"
if ! command -v python >/dev/null 2>&1; then
  for p in /c/Users/*/AppData/Local/Programs/Python/Python3*/ /c/Python3*/ \
           /c/Users/*/AppData/Local/Microsoft/WindowsApps/; do
    [ -x "$p/python.exe" ] && export PATH="$p:$PATH" && break
  done
fi
cd "$1"; shift
exec "$@"
