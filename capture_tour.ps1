# capture_tour.ps1 - grab one still per scene from the LIVE site, at 4K.
#
# The layout is captured at 1920x1080 logical with a 2x device scale, so the
# terminal lays itself out exactly as a user sees it while every pixel is
# rendered at double density - a true 3840x2160 frame rather than an upscale.
#
# --virtual-time-budget is what makes this work headlessly: Chrome fast-forwards
# its clock until the page has finished fetching and drawing, so a panel that
# needs ten seconds of data loading is captured fully populated.

param(
  [string]$ScriptPath = "D:\mutxri-terminal\tour_script.json",
  [string]$OutDir = "C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour4k",
  [switch]$Force
)

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) { throw "Chrome not found at $chrome" }

$doc = Get-Content $ScriptPath -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$errLog = Join-Path $OutDir "chrome_stderr.txt"

foreach ($sc in $doc.scenes) {
  if (-not $sc.url) { continue }               # card scenes are rendered separately
  $out = Join-Path $OutDir ($sc.id + ".png")
  if ((Test-Path $out) -and -not $Force) {
    "{0,-14} reuse" -f $sc.id
    continue
  }
  if (Test-Path $out) { Remove-Item -LiteralPath $out -Force }

  $budget = [int]($sc.settle * 1000)
  $chromeArgs = @(
    "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    "--window-size=1920,1080", "--force-device-scale-factor=2",
    "--virtual-time-budget=$budget",
    "--screenshot=$out", $sc.url
  )
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs -NoNewWindow -Wait `
                -RedirectStandardError $errLog | Out-Null

  if (Test-Path $out) {
    $dim = & ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=p=0 $out
    "{0,-14} {1,-11} {2,9} bytes" -f $sc.id, $dim, (Get-Item $out).Length
  } else {
    "{0,-14} FAILED" -f $sc.id
  }
}
