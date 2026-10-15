# Build a shareable Windows zip under dist\ (source + Install.cmd; voices downloaded on install).
$ErrorActionPreference = "Stop"
$Src = $PSScriptRoot
$Version = (Get-Content (Join-Path $Src "VERSION") | Select-Object -First 1).Trim()
$Dist = Join-Path $Src "dist"
$Stage = Join-Path $Dist "stage-win"
Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Stage | Out-Null

$include = @(
  "VERSION", "README.md", "RELEASING.md", "requirements.txt",
  "install.ps1", "uninstall.ps1", "Install.cmd", "run_saytray.pyw", "run_tests.ps1",
  "saytray", "tests", "assets"
)
foreach ($name in $include) {
  $p = Join-Path $Src $name
  if (Test-Path $p) {
    Copy-Item -Recurse $p (Join-Path $Stage $name)
  }
}
# Strip caches from staged package
Get-ChildItem $Stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem $Stage -Recurse -Filter "*.pyc" | Remove-Item -Force

$Out = Join-Path $Dist "SayTray-$Version-Windows.zip"
Remove-Item $Out -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Out -Force
Remove-Item -Recurse -Force $Stage
Get-Item $Out | Format-List FullName, Length
Write-Host "Packaged $Out"
