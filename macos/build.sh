#!/bin/bash
# Build SayTray, bundle it, sign it with the stable local identity, install helper + app.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(tr -d '[:space:]' < VERSION)"
# CFBundleVersion: numeric-ish build from semver (1.0.0 -> 100)
BUNDLE_VERSION="$(echo "$VERSION" | awk -F. '{printf "%d%02d%02d", $1, $2, $3}')"

swift build -c release --product SayTray
BIN="$(swift build -c release --show-bin-path)/SayTray"
APP="build/SayTray.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/SayTray"
cp support/saytray_piper.py "$APP/Contents/Resources/"
if [ -f assets/SayTray.icns ]; then
  cp assets/SayTray.icns "$APP/Contents/Resources/SayTray.icns"
fi

cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>SayTray</string>
<key>CFBundleDisplayName</key><string>SayTray</string>
<key>CFBundleIdentifier</key><string>com.jonbecherer.saytray</string>
<key>CFBundleExecutable</key><string>SayTray</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>${VERSION}</string>
<key>CFBundleVersion</key><string>${BUNDLE_VERSION}</string>
<key>CFBundleIconFile</key><string>SayTray</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSMicrophoneUsageDescription</key><string>SayTray uses the microphone to turn your speech into typed text.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>SayTray uses speech recognition to transcribe your dictation.</string>
</dict></plist>
PL

# Stable self-signed identity keeps privacy permissions across rebuilds; ad-hoc fallback.
SIGN_ID=$(security find-identity -p codesigning ~/Library/Keychains/login.keychain-db 2>/dev/null | awk '/"SpeakBar Local Signing"/{print $2; exit}')
if [ -n "$SIGN_ID" ] && codesign --force --deep -s "$SIGN_ID" "$APP" 2>/dev/null; then echo "Signed with SpeakBar Local Signing"
else codesign --force --deep -s - "$APP"; echo "WARNING: signed ad-hoc (permissions will reset)"; fi

# Install
pkill -x SayTray 2>/dev/null || true
pkill -f saytray_piper.py 2>/dev/null || true
sleep 1
PIPER="$HOME/Library/Application Support/SayTray/piper"
mkdir -p "$PIPER" && cp support/saytray_piper.py "$PIPER/saytray_piper.py"
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/SayTray.app"
cp -R "$APP" "$HOME/Applications/SayTray.app"
echo "Installed SayTray ${VERSION} to $HOME/Applications/SayTray.app"
