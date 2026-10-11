param([string]$Out = "shot.png")

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after,
      int x, int y, int cx, int cy, uint f);
  public struct R { public int L, T, Rr, B; }
}
"@

$p = Get-Process azahar -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output "no azahar window"; exit 1 }
$h = $p.MainWindowHandle
# The shot is a copy of the screen under the window's rectangle, so anything
# on top of Azahar ends up in it - and something usually is, because a chat
# window that pops up while the build is running lands straight in the frame.
#
# SetForegroundWindow is not enough: Windows refuses it to a process that does
# not own the foreground, and even when it works the next notification takes
# the foreground straight back. Making the window topmost for the duration of
# the capture is the only thing that holds, because topmost beats activation.
# 0x0001|0x0002|0x0010 = keep the size, keep the position, do not activate.
[W]::ShowWindow($h, 9) | Out-Null
[W]::SetWindowPos($h, [IntPtr](-1), 0, 0, 0, 0, 0x0013) | Out-Null
[W]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 700

$r = New-Object W+R
[W]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Rr - $r.L
$ht = $r.B - $r.T
if ($w -le 0 -or $ht -le 0) { Write-Output "bad rect"; exit 1 }

$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
# Back to an ordinary window: leaving the emulator pinned over everything else
# is the sort of thing a test script has no business doing to a desktop.
[W]::SetWindowPos($h, [IntPtr](-2), 0, 0, 0, 0, 0x0013) | Out-Null
Write-Output "saved $Out  ${w}x${ht}"
