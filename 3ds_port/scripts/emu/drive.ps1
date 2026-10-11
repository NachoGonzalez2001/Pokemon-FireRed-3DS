param([string]$Seq = "", [int]$Hold = 130, [int]$Gap = 180)

# Azahar ignores SendInput here even with the window in the foreground, so keys
# go in as posted window messages instead. Qt reads them from its event queue,
# which does not care about focus at all.
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class D {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc e, IntPtr l);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint c, uint t);
  public static List<IntPtr> All(IntPtr parent) {
    List<IntPtr> f = new List<IntPtr>();
    f.Add(parent);
    EnumChildWindows(parent, delegate(IntPtr h, IntPtr l) { f.Add(h); return true; }, IntPtr.Zero);
    return f;
  }
  public static void Post(List<IntPtr> ws, ushort vk, bool up) {
    uint sc = MapVirtualKey(vk, 0);
    IntPtr lp = (IntPtr)(1 | (int)(sc << 16) | (up ? (1 << 30) | (1 << 31) : 0));
    foreach (IntPtr h in ws) PostMessage(h, up ? 0x0101u : 0x0100u, (IntPtr)vk, lp);
  }
}
"@

# The emulator's own mapping, read out of qt-config.ini.
$VK = @{
  "a" = 0x41; "b" = 0x53; "start" = 0x0D; "select" = 0x08
  "up" = 0x54; "down" = 0x47; "left" = 0x46; "right" = 0x48
}

$p = Get-Process azahar -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output "no azahar"; exit 1 }
$ws = [D]::All($p.MainWindowHandle)

foreach ($tok in $Seq.Split(",")) {
  $t = $tok.Trim().ToLower()
  if ($t -eq "") { continue }
  if ($t -match "^wait(\d+)$") { Start-Sleep -Milliseconds ([int]$Matches[1]); continue }
  $rep = 1
  $hold = $Hold
  if ($t -match "^(\w+)\*(\d+)$") { $t = $Matches[1]; $rep = [int]$Matches[2] }
  if ($t -match "^(\w+)\+(\d+)$") { $t = $Matches[1]; $hold = [int]$Matches[2] }
  if (-not $VK.ContainsKey($t)) { Write-Output "unknown '$t'"; continue }
  for ($i = 0; $i -lt $rep; $i++) {
    [D]::Post($ws, [uint16]$VK[$t], $false)
    Start-Sleep -Milliseconds $hold
    [D]::Post($ws, [uint16]$VK[$t], $true)
    Start-Sleep -Milliseconds $Gap
  }
}
Write-Output "ok: $Seq"
