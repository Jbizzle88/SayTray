#!/bin/bash
# Uninstall SayTray from this Mac.
set -euo pipefail

APP="$HOME/Applications/SayTray.app"
SUPPORT="$HOME/Library/Application Support/SayTray"
LOGS="$HOME/Library/Logs/SayTray"
KEEP_DATA=0

usage() {
  echo "Usage: $0 [--keep-data]"
  echo "  Quits SayTray, removes the login item, and deletes $APP."
  echo "  Without --keep-data, also removes Support + Logs (voices, venv, settings logs)."
  echo "  Preferences in UserDefaults (hotkeys, speed, etc.) are left alone; remove with:"
  echo "    defaults delete com.jonbecherer.saytray"
}

for arg in "$@"; do
  case "$arg" in
    --keep-data) KEEP_DATA=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg"; usage; exit 1 ;;
  esac
done

echo "Quitting SayTray…"
pkill -x SayTray 2>/dev/null || true
pkill -f saytray_piper.py 2>/dev/null || true
sleep 1

# Unregister launch-at-login if the app is still present
if [ -d "$APP" ]; then
  "$APP/Contents/MacOS/SayTray" --unregister-login 2>/dev/null || true
  # SMAppService unregister via sfltool / open is unreliable; try defaults + launchctl cleanup
  osascript -e 'tell application "System Events" to delete (every login item whose name is "SayTray")' 2>/dev/null || true
fi

if [ -d "$APP" ]; then
  echo "Removing $APP"
  rm -rf "$APP"
else
  echo "App not found at $APP (already removed?)"
fi

if [ "$KEEP_DATA" -eq 0 ]; then
  if [ -d "$SUPPORT" ]; then
    echo "Removing $SUPPORT"
    rm -rf "$SUPPORT"
  fi
  if [ -d "$LOGS" ]; then
    echo "Removing $LOGS"
    rm -rf "$LOGS"
  fi
else
  echo "Keeping Support/Logs (--keep-data)."
fi

echo "SayTray uninstalled."
echo "Optional: defaults delete com.jonbecherer.saytray"
