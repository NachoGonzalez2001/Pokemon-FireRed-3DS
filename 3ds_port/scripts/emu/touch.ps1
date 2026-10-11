param([int]$X = 160, [int]$Y = 120, [int]$Hold = 120)

# Taps the bottom screen at (X, Y) in 3DS pixels (0..319, 0..239).
#
# Like drive.ps1, input goes in as posted window messages: a left button
# press and release on Azahar's render widget, whose client area holds both
# screens. The bottom screen's rectangle is found from the layout Azahar uses
# at its default window size: both screens share one scale, the top screen
# (400x240) above the bottom one (320x240), centred horizontally.
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class T {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc e, IntPtr l);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  public struct R { public int L, T, Rr, B; }
  public static List<IntPtr> All(IntPtr parent) {
    List<IntPtr> f = new List<IntPtr>();
    EnumChildWindows(parent, delegate(IntPtr h, IntPtr l) { f.Add(h); return true; }, IntPtr.Zero);
    return f;
  }
  public static string Class(IntPtr h) { StringBuilder s = new StringBuilder(256); GetClassName(h, s, 256); return s.ToString(); }
}
"@

$p = Get-Process azahar -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output "no azahar"; exit 1 }
# The render surface is the OpenGL child (its own device context), not the
# largest window: Qt keeps a few full-size helper windows around.
$best = [IntPtr]::Zero; $area = 0; $rect = $null
foreach ($h in [T]::All($p.MainWindowHandle)) {
  if (-not ([T]::Class($h)).Contains("OwnDC")) { continue }
  $r = New-Object T+R
  [T]::GetClientRect($h, [ref]$r) | Out-Null
  $a = ($r.Rr - $r.L) * ($r.B - $r.T)
  if ($a -gt $area) { $area = $a; $best = $h; $rect = $r }
}
if ($best -eq [IntPtr]::Zero) { Write-Output "no render widget"; exit 1 }
$cw = $rect.Rr - $rect.L; $ch = $rect.B - $rect.T
# Two screens stacked: 400 wide, 480 tall at one scale.
$scale = [Math]::Min($cw / 400.0, $ch / 480.0)
$left = ($cw - 320 * $scale) / 2
$top = ($ch - 480 * $scale) / 2 + 240 * $scale
$cx = [int]($left + ($X + 0.5) * $scale)
$cy = [int]($top + ($Y + 0.5) * $scale)
$lp = [IntPtr](($cy -shl 16) -bor ($cx -band 0xFFFF))
[T]::PostMessage($best, 0x0200, [IntPtr]0, $lp) | Out-Null   # WM_MOUSEMOVE
[T]::PostMessage($best, 0x0201, [IntPtr]1, $lp) | Out-Null   # WM_LBUTTONDOWN
Start-Sleep -Milliseconds $Hold
[T]::PostMessage($best, 0x0202, [IntPtr]0, $lp) | Out-Null   # WM_LBUTTONUP
Write-Output "tap $X,$Y -> client $cx,$cy on $([T]::Class($best)) ${cw}x${ch}"
