# Run every suite. A failure is recorded and the rest still run.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$logDir = Join-Path ([System.IO.Path]::GetTempPath()) ("saytray-test-logs-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$env:SAYTRAY_LOG_DIR = $logDir

$python = $null
$prefix = @()
$venvPy = $null
if ($env:LOCALAPPDATA) {
    $venvPy = Join-Path $env:LOCALAPPDATA "SayTray\venv\Scripts\python.exe"
}
if ($venvPy -and (Test-Path -LiteralPath $venvPy)) {
    $python = $venvPy
    Write-Host "Python: $python"
} else {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $python = $py.Source
        $prefix = @("-3")
        Write-Host "Python: py -3 ($python)"
    } else {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) {
            $python = $cmd.Source
            Write-Host "Python: $python"
        }
    }
}
if (-not $python) {
    Write-Warning "Python was not found. Looked for the SayTray venv, then the py launcher, then python. Run windows\install.ps1 first."
    exit 1
}

$names = @()
$codes = @()
function Add-Suite {
    param([string]$Name, [string]$Script, [string[]]$Extra = @())
    Write-Host ""
    Write-Host "== $Name =="
    $code = 1
    try {
        & $python @prefix $Script @Extra
        if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE } else { $code = 0 }
    } catch {
        Write-Warning "$Name stopped: $_"
        $code = 1
    }
    $script:names += $Name
    $script:codes += $code
    if ($code -ne 0) {
        Write-Warning "$Name failed with exit $code. The remaining suites will still run."
    }
}

Add-Suite -Name "textprep" -Script (Join-Path $root "tests\test_textprep.py") -Extra @((Join-Path $root "tests\corpus"))
Add-Suite -Name "voice catalog" -Script (Join-Path $root "tests\test_voices.py")
Add-Suite -Name "chord" -Script (Join-Path $root "tests\test_chord.py")
Add-Suite -Name "venv setup" -Script (Join-Path $root "tests\test_setup_venv.py")
Add-Suite -Name "dictation flow" -Script (Join-Path $root "tests\test_dictation_flow.py")
Add-Suite -Name "dictation order" -Script (Join-Path $root "tests\test_dictation_order.py")
Add-Suite -Name "requirement wheels" -Script (Join-Path $root "tests\test_requirements_wheels.py")

$files = @()
$files += @(Get-ChildItem -Path (Join-Path $root "tests\corpus\*.txt") -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$files += @(Get-ChildItem -Path (Join-Path $root "tests\past\*.txt") -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
Add-Suite -Name "read pipeline" -Script (Join-Path $root "tests\pipeline_test.py") -Extra (@((Join-Path $root "tests\pipeline.json")) + $files)

Write-Host ""
Write-Host "SayTray Windows tests"
$failed = 0
for ($i = 0; $i -lt $names.Count; $i++) {
    if ($codes[$i] -eq 0) {
        Write-Host ("  {0}: passed" -f $names[$i])
    } else {
        Write-Host ("  {0}: FAILED (exit {1})" -f $names[$i], $codes[$i])
        $failed++
    }
}
Write-Host "Logs from this run: $env:SAYTRAY_LOG_DIR"
if ($failed -gt 0) { exit 1 }
exit 0
