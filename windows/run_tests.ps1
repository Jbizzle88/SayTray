# TextPrep unit/corpus tests + full Piper pipeline over the corpus (and Jon's past texts in tests\past).
$R = Join-Path $env:LOCALAPPDATA "SayTray"
$py = "$R\venv\Scripts\python.exe"
& $py "$PSScriptRoot\tests\test_textprep.py" "$PSScriptRoot\tests\corpus"
$u = $LASTEXITCODE
$files = @(Get-ChildItem "$PSScriptRoot\tests\corpus\*.txt") + @(Get-ChildItem "$PSScriptRoot\tests\past\*.txt" -ErrorAction SilentlyContinue) | ForEach-Object { $_.FullName }
& $py "$PSScriptRoot\tests\pipeline_test.py" "$PSScriptRoot\tests\pipeline.json" @files
exit ($u -bor $LASTEXITCODE)
