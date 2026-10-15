@echo off
REM One-click SayTray install for Windows. Double-click this file.
cd /d "%~dp0"
echo SayTray installer
echo.
where py >nul 2>&1
if errorlevel 1 (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python 3 was not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure "Add python.exe to PATH" is checked, then run Install.cmd again.
    pause
    exit /b 1
  )
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo Install failed.
  pause
  exit /b 1
)
echo.
echo Tip: set your real microphone as the Windows default input before dictating
echo (avoid Oculus/Steam Virtual Audio as the default).
pause

