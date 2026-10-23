# SayTray for Windows: install/update script.
# Creates %LOCALAPPDATA%\SayTray (venv, app, voices, logs), Start Menu + Startup shortcuts,
# registers Add/Remove Programs (per-user), then launches.
param([switch]$NoLaunch, [switch]$SkipDeps, [switch]$SkipVoices)
$ErrorActionPreference = "Stop"
$Src = $PSScriptRoot
$R = Join-Path $env:LOCALAPPDATA "SayTray"
$Version = (Get-Content (Join-Path $Src "VERSION") -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
if (-not $Version) { $Version = "1.1.0" }

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

# 1. Python venv + dependencies. A moved venv (SpeakBar → SayTray) can leave python.exe
# or pip.exe pointing at the old path; recreate it instead of continuing.
function Test-VenvHealthy([string]$Root) {
  $python = Join-Path $Root "Scripts\python.exe"
  $pip = Join-Path $Root "Scripts\pip.exe"
  if (!(Test-Path $python)) { return $false }
  try {
    & $python -c "import sys" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    if (Test-Path $pip) {
      & $pip --version 1>$null 2>$null
      if ($LASTEXITCODE -ne 0) { return $false }
    }
    & $python -m pip --version 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    & $python -c "import piper, onnxruntime" 1>$null 2>$null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Test-FileSha([string]$Path, [string]$Expect) {
  if ([string]::IsNullOrWhiteSpace($Expect)) { return $true }
  $got = (Get-FileHash -Algorithm SHA256 -Path $Path).Hash
  return $got.ToLower() -eq $Expect.ToLower()
}

function Write-VoiceMarker([string]$Path, [string]$Hash) {
  if ([string]::IsNullOrWhiteSpace($Hash)) { return }
  [System.IO.File]::WriteAllText("$Path.sha256", $Hash.ToLower() + "`n")
}

$py = (Get-Command py -ErrorAction SilentlyContinue)
$venv = Join-Path $R "venv"
if ((Test-Path $venv) -and -not (Test-VenvHealthy $venv)) {
  Write-Host "Piper venv is broken (python, pip, or Piper is not runnable). Recreating it…"
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*SayTray*" -or $_.CommandLine -like "*SpeakBar*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 500
  Remove-Item -Recurse -Force $venv
}
if (!(Test-Path "$venv\Scripts\python.exe")) {
  Write-Host "Creating venv…"
  if ($py) { & py -3 -m venv $venv } else { & python -m venv $venv }
  if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& "$venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required." }
if (!$SkipDeps) {
  Write-Host "Installing Python packages (piper-tts, faster-whisper, …)…"
  & "$venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
  & "$venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "$Src\requirements.txt"
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  Write-Host "Downloading the dictation model (first time only)…"
  & "$venv\Scripts\python.exe" -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "The dictation model did not download. SayTray will try again when you dictate."
  }
}

# 2. Default Piper voices from saytray\voices.json (Norman + LJSpeech). Optional voices download in the app.
if (!$SkipVoices) {
  $catalogPath = Join-Path $Src "saytray\voices.json"
  if (!(Test-Path $catalogPath)) { throw "Missing voice catalog: $catalogPath" }
  $catalog = [System.IO.File]::ReadAllText($catalogPath) | ConvertFrom-Json
  $defaults = @($catalog.voices | Where-Object { $_.installByDefault })
  $bytes = 0
  foreach ($v in $defaults) { foreach ($file in @($v.files)) { $bytes += [int64]$file.sizeBytes } }
  $mb = [int][math]::Round($bytes / 1MB)
  Write-Host "Ensuring Piper voices (about $mb MB the first time)…"
  foreach ($id in @($catalog.removed)) {
    foreach ($ext in @(".onnx", ".onnx.json")) {
      $old = Join-Path "$R\voices" ($id + $ext)
      if (Test-Path $old) {
        Write-Host "  removing retired voice $id$ext"
        Remove-Item $old -Force
      }
    }
  }
  foreach ($v in $defaults) {
    foreach ($file in @($v.files)) {
      $o = Join-Path "$R\voices" $file.filename
      $expect = [int64]$file.sizeBytes
      $hash = [string]$file.sha256
      $got = -1
      if (Test-Path $o) { $got = (Get-Item $o).Length }
      $ok = ($expect -gt 0 -and $got -eq $expect) -or ($expect -le 0 -and $got -gt 0)
      if ($ok -and $hash -and -not (Test-FileSha $o $hash)) {
        Write-Host "  checksum mismatch $($file.filename); downloading again"
        $ok = $false
      }
      if (-not $ok) {
        if ($got -ge 0) {
          Write-Host "  replacing incomplete $($file.filename) ($got of $expect bytes)"
        } else {
          Write-Host "  downloading $($file.filename) …"
        }
        $tmp = "$o.partial"
        curl.exe -fL --retry 3 --progress-bar -o $tmp $file.url
        if ($LASTEXITCODE -ne 0) {
          Remove-Item $tmp -Force -ErrorAction SilentlyContinue
          throw "download failed: $($file.filename)"
        }
        Move-Item -Force $tmp $o
        $final = (Get-Item $o).Length
        if (($expect -gt 0 -and $final -ne $expect) -or $final -le 0) {
          Remove-Item $o -Force -ErrorAction SilentlyContinue
          throw "incomplete download: $($file.filename) ($final of $expect bytes)"
        }
        if ($hash -and -not (Test-FileSha $o $hash)) {
          Remove-Item $o -Force -ErrorAction SilentlyContinue
          throw "checksum mismatch: $($file.filename)"
        }
        Write-VoiceMarker $o $hash
      } else {
        Write-VoiceMarker $o $hash
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
$notice = Join-Path $Src "THIRD_PARTY_NOTICES.md"
if (!(Test-Path $notice)) { $notice = Join-Path $Src "..\THIRD_PARTY_NOTICES.md" }
if (Test-Path $notice) { Copy-Item $notice "$R\app\THIRD_PARTY_NOTICES.md" -Force }
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

# 4. Shortcuts: Start Menu + Startup. Check that each file exists afterwards.
# Antivirus behavior shields (Avast, AVG) have quarantined these .lnk files.
$ws = New-Object -ComObject WScript.Shell
$targets = @(
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SayTray.lnk",
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SayTray.lnk"
)
$blocked = @()
foreach ($lnk in $targets) {
  $dir = Split-Path -Parent $lnk
  if ($dir -and !(Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
  try {
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = "$R\venv\Scripts\pythonw.exe"
    $s.Arguments = "`"$R\app\run_saytray.pyw`""
    $s.WorkingDirectory = "$R\app"
    $s.IconLocation = "$IcoDst"
    $s.Description = "SayTray $Version — read selected text aloud, push-to-talk dictation"
    $s.Save()
  } catch {
    Write-Warning "Could not write $lnk : $_"
  }
  if (!(Test-Path -LiteralPath $lnk)) { $blocked += $lnk }
}
$startupLnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SayTray.lnk"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runCmd = "`"$R\venv\Scripts\pythonw.exe`" `"$R\app\run_saytray.pyw`""
if (!(Test-Path -LiteralPath $startupLnk)) {
  try {
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name "SayTray" -Value $runCmd
  } catch {
    Write-Warning "Could not set the startup Run key: $_"
  }
  $saved = $null
  try { $saved = (Get-ItemProperty -Path $runKey -Name "SayTray" -ErrorAction SilentlyContinue).SayTray } catch {}
  if ($saved) {
    Write-Output "Launch at startup was saved in the registry because the Startup shortcut was blocked."
  } else {
    Write-Warning "SayTray could not turn on launch at startup."
  }
} else {
  Remove-ItemProperty -Path $runKey -Name "SayTray" -ErrorAction SilentlyContinue
}
if ($blocked.Count -gt 0) {
  Write-Warning @"
SayTray could not create these shortcuts:
$($blocked -join [Environment]::NewLine)

Your antivirus (often Avast or AVG) or a folder permission blocked them.
1. Open Avast or AVG, choose Menu, then Quarantine.
2. Restore install.ps1, uninstall.ps1, and SayTray.lnk if they are listed.
3. Add an exception for this folder: $R
4. In Windows Security, open Virus & threat protection, Manage settings, Exclusions, and add the same folder.
5. Run this installer again.

Until the Startup shortcut or the registry Run key is in place, SayTray will not start when Windows starts.
"@
}

# 5. Add/Remove Programs (per-user / HKCU)
# A blocked copy must not stop the install. Avast denies uninstall.ps1 on some PCs.
$uninstScript = Join-Path $R "app\uninstall.ps1"
$haveUninstall = $false
if (Test-Path (Join-Path $Src "uninstall.ps1")) {
  try {
    Copy-Item (Join-Path $Src "uninstall.ps1") $uninstScript -Force -ErrorAction Stop
    $haveUninstall = Test-Path -LiteralPath $uninstScript
  } catch {
    Write-Warning "Could not copy uninstall.ps1 ($($_.Exception.Message)). The rest of the install will continue. Antivirus may have blocked the script."
    $haveUninstall = $false
  }
}
if (-not $haveUninstall) {
  Write-Warning @"
uninstall.ps1 is missing from $R\app. Antivirus may have quarantined it.
Restore it from Avast or AVG Quarantine and allow $R, then run this installer again.
Apps & Features will use a built-in uninstall command until that script is in place.
That command quits SayTray and removes the program files. Settings and voices are kept.
"@
}
$arp = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SayTray"
New-Item -Path $arp -Force | Out-Null
Set-ItemProperty $arp -Name "DisplayName" -Value "SayTray"
Set-ItemProperty $arp -Name "DisplayVersion" -Value $Version
Set-ItemProperty $arp -Name "Publisher" -Value "Jon Becherer"
Set-ItemProperty $arp -Name "InstallLocation" -Value $R
Set-ItemProperty $arp -Name "DisplayIcon" -Value $IcoDst
# RemoteSigned runs a local script without the Bypass flag antivirus products flag.
if ($haveUninstall) {
  $uninstallCmd = "powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File `"$uninstScript`""
  $quietUninstallCmd = "$uninstallCmd -Quiet"
} else {
  # Do not point Apps & Features at a script that is not on disk, and do not
  # hide the command in a base64 blob. Quit SayTray first. Remove the program
  # files only. settings.json and voices stay.
  $uninstallCmd = @'
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | Where-Object { $_.CommandLine -like '*run_saytray.pyw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 800; Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name SayTray -ErrorAction SilentlyContinue; Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\SayTray.lnk'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\SayTray.lnk'); foreach ($dir in @('app','venv','debug')) { $p = Join-Path (Join-Path $env:LOCALAPPDATA 'SayTray') $dir; if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue } }; Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SayTray' -Recurse -Force -ErrorAction SilentlyContinue"
'@
  $quietUninstallCmd = $uninstallCmd.Trim()
  $uninstallCmd = $quietUninstallCmd
}
Set-ItemProperty $arp -Name "UninstallString" -Value $uninstallCmd
Set-ItemProperty $arp -Name "QuietUninstallString" -Value $quietUninstallCmd
Set-ItemProperty $arp -Name "NoModify" -Value 1 -Type DWord
Set-ItemProperty $arp -Name "NoRepair" -Value 1 -Type DWord
Set-ItemProperty $arp -Name "EstimatedSize" -Value 520000 -Type DWord

Write-Output "Installed SayTray $Version to $R"

# 6. Launch
if (!$NoLaunch) {
  Start-Process "$R\venv\Scripts\pythonw.exe" -ArgumentList "`"$R\app\run_saytray.pyw`"" -WorkingDirectory "$R\app"
  Write-Output "Launched"
}
