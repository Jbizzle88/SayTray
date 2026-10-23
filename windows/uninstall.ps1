# Uninstall SayTray (Windows). Stops the app and removes program files, shortcuts,
# and the startup Run key. settings.json and downloaded voices are kept.
param(
  [switch]$KeepSettings,
  [switch]$Quiet
)
$ErrorActionPreference = "Stop"
$R = Join-Path $env:LOCALAPPDATA "SayTray"

function Say($m) { if (-not $Quiet) { Write-Host $m } }

Say "Quitting SayTray…"
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*run_saytray.pyw*" -or $_.CommandLine -like "*SayTray*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

$shortcuts = @(
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SayTray.lnk",
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SayTray.lnk"
)
foreach ($s in $shortcuts) {
  if (Test-Path $s) { Remove-Item $s -Force; Say "Removed $s" }
}

Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "SayTray" -ErrorAction SilentlyContinue
Say "Removed startup Run key"

# Remove Add/Remove Programs entry
$arp = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SayTray"
if (Test-Path $arp) { Remove-Item $arp -Recurse -Force; Say "Removed Add/Remove Programs entry" }

# -KeepSettings is accepted so an older shortcut still works. Settings and voices stay either way.
if (Test-Path $R) {
  foreach ($name in @("app", "venv", "debug")) {
    $p = Join-Path $R $name
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue; Say "Removed $p" }
  }
  Say "Kept settings and voices under $R"
} else {
  Say "Install folder not found (already removed?)"
}

Say "SayTray uninstalled."
if (-not $Quiet) {
  Write-Host "Done. You can close this window."
  try { Start-Sleep -Seconds 2 } catch {}
}
