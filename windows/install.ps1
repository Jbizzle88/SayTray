# SayTray for Windows: install/update script.
# Creates %LOCALAPPDATA%\SayTray (venv, app, voices, logs), Start Menu + Startup shortcuts,
# registers Add/Remove Programs (per-user), then launches.
param([switch]$NoLaunch, [switch]$SkipDeps, [switch]$SkipVoices)
$ErrorActionPreference = "Stop"
$Src = $PSScriptRoot
$R = Join-Path $env:LOCALAPPDATA "SayTray"
$Version = (Get-Content (Join-Path $Src "VERSION") -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
if (-not $Version) { $Version = "1.0.0" }

# Migrate from SpeakBar (old name) if present
$OldR = Join-Path $env:LOCALAPPDATA "SpeakBar"
if ((Test-Path $OldR) -and ($OldR -ne $R)) {
  Write-Host "Migrating from SpeakBar…"
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*run_speakbar*" -or $_.CommandLine -like "*SpeakBar*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 500
  if (!(Test-Path $R)) {
    Move-Item $OldR $R
  } else {
    foreach ($sub in @("voices", "venv")) {
      if ((Test-Path "$OldR\$sub") -and !(Test-Path "$R\$sub")) { Move-Item "$OldR\$sub" "$R\$sub" }
    }
    if ((Test-Path "$OldR\settings.json") -and !(Test-Path "$R\settings.json")) {
      Copy-Item "$OldR\settings.json" "$R\settings.json"
    }
    Remove-Item $OldR -Recurse -Force -ErrorAction SilentlyContinue
  }
  foreach ($s in @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SpeakBar.lnk",
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SpeakBar.lnk"
  )) { if (Test-Path $s) { Remove-Item $s -Force } }
  if (Test-Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeakBar") {
    Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeakBar" -Recurse -Force
  }
}

New-Item -ItemType Directory -Force "$R\voices", "$R\Logs", "$R\app", "$R\debug" | Out-Null

# 1. Python venv + dependencies
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (!(Test-Path "$R\venv\Scripts\python.exe")) {
  Write-Host "Creating venv…"
  if ($py) { & py -3 -m venv "$R\venv" } else { & python -m venv "$R\venv" }
}
if (!$SkipDeps) {
  Write-Host "Installing Python packages (piper-tts, faster-whisper, …)…"
  & "$R\venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
  & "$R\venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "$Src\requirements.txt"
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

# 2. Piper voices (same four as the Mac version) — skip with -SkipVoices for a smaller/faster reinstall
if (!$SkipVoices) {
  $B = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US"
  Write-Host "Ensuring Piper voices (≈360 MB first time)…"
  foreach ($v in "lessac/high/en_US-lessac-high", "amy/medium/en_US-amy-medium", "ryan/high/en_US-ryan-high", "libritts_r/medium/en_US-libritts_r-medium") {
    $n = Split-Path $v -Leaf
    foreach ($e in "onnx", "onnx.json") {
      $o = "$R\voices\$n.$e"
      if (!(Test-Path $o) -or (Get-Item $o).Length -eq 0) {
        Write-Host "  downloading $n.$e …"
        curl.exe -fL --progress-bar -o $o "$B/$v.$e"
        if ($LASTEXITCODE -ne 0) { throw "download failed: $n.$e" }
      }
    }
  }
}

# 3. Stop a running copy, install app files
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*run_saytray.pyw*" -or $_.CommandLine -like "*SayTray*run_saytray*" -or $_.CommandLine -like "*run_speakbar*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
Remove-Item -Recurse -Force "$R\app\saytray" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$R\app\speakbar" -ErrorAction SilentlyContinue
Copy-Item -Recurse "$Src\saytray" "$R\app\saytray"
Copy-Item "$Src\run_saytray.pyw" "$R\app\"
Copy-Item "$Src\VERSION" "$R\app\VERSION" -ErrorAction SilentlyContinue
@"
"""Auto-written by install.ps1 from the repo VERSION file. Do not edit by hand."""
__version__ = "$Version"
"@ | Set-Content -Path "$R\app\saytray\_version.py" -Encoding utf8

# Branded icon for shortcuts
$IcoSrc = Join-Path $Src "assets\SayTray.ico"
$IcoDst = "$R\app\saytray.ico"
if (Test-Path $IcoSrc) {
  Copy-Item $IcoSrc $IcoDst -Force
} else {
  & "$R\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'$R\app'); from saytray.app import _icon; _icon('idle').save(r'$IcoDst', sizes=[(16,16),(32,32),(48,48),(64,64)])"
}

# 4. Shortcuts: Start Menu + Startup
$ws = New-Object -ComObject WScript.Shell
$targets = @(
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SayTray.lnk",
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SayTray.lnk"
)
foreach ($lnk in $targets) {
  $s = $ws.CreateShortcut($lnk)
  $s.TargetPath = "$R\venv\Scripts\pythonw.exe"
  $s.Arguments = "`"$R\app\run_saytray.pyw`""
  $s.WorkingDirectory = "$R\app"
  $s.IconLocation = "$IcoDst"
  $s.Description = "SayTray $Version — read selected text aloud, push-to-talk dictation"
  $s.Save()
}

# 5. Add/Remove Programs (per-user / HKCU)
if (Test-Path (Join-Path $Src "uninstall.ps1")) {
  Copy-Item (Join-Path $Src "uninstall.ps1") "$R\app\uninstall.ps1" -Force
}
$arp = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SayTray"
New-Item -Path $arp -Force | Out-Null
Set-ItemProperty $arp -Name "DisplayName" -Value "SayTray"
Set-ItemProperty $arp -Name "DisplayVersion" -Value $Version
Set-ItemProperty $arp -Name "Publisher" -Value "Jon Becherer"
Set-ItemProperty $arp -Name "InstallLocation" -Value $R
Set-ItemProperty $arp -Name "DisplayIcon" -Value $IcoDst
Set-ItemProperty $arp -Name "UninstallString" -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$R\app\uninstall.ps1`""
Set-ItemProperty $arp -Name "QuietUninstallString" -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$R\app\uninstall.ps1`" -Quiet"
Set-ItemProperty $arp -Name "NoModify" -Value 1 -Type DWord
Set-ItemProperty $arp -Name "NoRepair" -Value 1 -Type DWord
Set-ItemProperty $arp -Name "EstimatedSize" -Value 520000 -Type DWord

Write-Output "Installed SayTray $Version to $R"

# 6. Launch
if (!$NoLaunch) {
  Start-Process "$R\venv\Scripts\pythonw.exe" -ArgumentList "`"$R\app\run_saytray.pyw`"" -WorkingDirectory "$R\app"
  Write-Output "Launched"
}
