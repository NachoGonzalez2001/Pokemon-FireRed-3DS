param([int]$Wait = 15, [string]$Shot = "boot", [string]$Keys = "")
# Build the 3dsx, run it in Azahar, capture, close, and print the port log
# tail plus the emulator's distinct errors.
$P = 'C:\Users\ignac\OneDrive\Escritorio\pokemon voxel mod\pokefirered-3ds'
$scratch = ($PSScriptRoot -replace '\\','/')
python "$P\tools\bootstrap.py" --dir C:\fr3ds\upstream 2>&1 | Select-Object -Last 1
$env:MSYSTEM = 'MSYS'
& C:\devkitPro\msys2\usr\bin\bash.exe -l "$P\tools\dkp.sh" /c/fr3ds bash "$scratch/mk.sh" all all -j4
if (-not (Test-Path C:\fr3ds\upstream\3ds_port\firered3ds.3dsx)) { "no 3dsx"; exit 1 }
$sd = "$env:APPDATA\Azahar\sdmc\3ds\emerald3ds"
Remove-Item "$sd\port.log" -ErrorAction SilentlyContinue
& "$P\3ds_port\scripts\emu\run.ps1" -App C:\fr3ds\upstream\3ds_port\firered3ds.3dsx -Out "$P\build\$Shot.png" -Wait $Wait -Keys $Keys -Keep
Get-Process azahar -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }
Start-Sleep -Milliseconds 2500
Get-Process azahar -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
"---- port.log"
if (Test-Path "$sd\port.log") { Get-Content "$sd\port.log" -Tail 40 }
"---- emulator errors"
$f = "$env:APPDATA\Azahar\log\azahar_log.txt"
Select-String -Path $f -Pattern '<Error>|<Critical>' | Where-Object { $_.Line -notmatch 'update_checker|ClCertA|title id|ConfigureNew3DSCPU|port-prev|Rename|Delay generator' } |
  ForEach-Object { ($_.Line -replace '^\[\s*[\d.]+\]\s*','') -replace '@ 0x[0-9A-F]+','@ ...' } |
  Group-Object | Sort-Object Count -Descending | Select-Object -First 15 | ForEach-Object { "{0,6}x {1}" -f $_.Count, $_.Name.Substring(0, [Math]::Min(170, $_.Name.Length)) }
