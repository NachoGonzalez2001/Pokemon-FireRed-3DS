param([string]$In, [string]$Out, [int]$X = 233, [int]$Y = 62, [int]$W = 557, [int]$H = 335, [int]$Scale = 2)

# The emulator draws the 400x240 top screen into a fixed rectangle of its
# window; cropping to it and scaling up is the only way to judge geometry from
# a desktop screenshot.
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Image]::FromFile($In)
$rect = New-Object System.Drawing.Rectangle $X, $Y, $W, $H
$cut = $src.Clone($rect, $src.PixelFormat)
$big = New-Object System.Drawing.Bitmap ($W * $Scale), ($H * $Scale)
$g = [System.Drawing.Graphics]::FromImage($big)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$g.DrawImage($cut, 0, 0, $big.Width, $big.Height)
$big.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $big.Dispose(); $cut.Dispose(); $src.Dispose()
Write-Output "cropped -> $Out"
