param(
  [Parameter(Mandatory = $true)][string]$App,
  [string]$Out = "shot.png",
  [int]$Wait = 8,
  [string]$Keys = "",
  [switch]$Keep
)

# Starts Azahar on a .3dsx, waits, optionally drives keys (drive.ps1 syntax),
# captures the window of THIS process (grab.ps1 -Id) and closes it unless
# -Keep. An Azahar the user already has open is left alone; since Azahar may
# hand the file to it instead of starting, the script refuses to run then.

$azahar = "C:\Program Files\Azahar\azahar.exe"
if (-not (Test-Path $azahar)) { Write-Output "Azahar not found at $azahar"; exit 1 }
if (Get-Process azahar -ErrorAction SilentlyContinue) {
  Write-Output "another Azahar is running: close it first"; exit 2
}
$App = (Resolve-Path $App).Path
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$p = Start-Process -FilePath $azahar -ArgumentList "`"$App`"" -PassThru
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
  $p.Refresh()
  if ($p.HasExited) { Write-Output "azahar exited (code $($p.ExitCode))"; exit 1 }
  if ($p.MainWindowHandle -ne 0) { break }
  Start-Sleep -Milliseconds 250
}
Start-Sleep -Seconds $Wait
if ($Keys) { & (Join-Path $here "drive.ps1") -Seq $Keys -Id $p.Id }
& (Join-Path $here "grab.ps1") -Out $Out -Id $p.Id
if (-not $Keep) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
