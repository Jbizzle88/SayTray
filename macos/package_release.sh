#!/bin/bash
# Build a shareable macOS zip under dist/ (app only — voices via Setup Piper Voices).
set -euo pipefail
cd "$(dirname "$0")"
VERSION="$(tr -d '[:space:]' < VERSION)"
./build.sh

STAGE="dist/stage-mac"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R build/SayTray.app "$STAGE/"
cp uninstall.sh "$STAGE/uninstall.sh"
chmod +x "$STAGE/uninstall.sh"
cp README.md "$STAGE/README.md"

# Double-clickable Piper setup. URLs stay in voices.json; this wrapper just runs setup_piper.sh.
cp support/setup_piper.sh "$STAGE/setup_piper.sh"
cp Sources/SayTray/voices.json "$STAGE/voices.json"
chmod +x "$STAGE/setup_piper.sh"
if [ -f ../THIRD_PARTY_NOTICES.md ]; then cp ../THIRD_PARTY_NOTICES.md "$STAGE/THIRD_PARTY_NOTICES.md"; fi
cat > "$STAGE/Setup Piper Voices.command" << 'CMD'
#!/bin/bash
cd "$(dirname "$0")"
bash ./setup_piper.sh
status=$?
echo
if [ "$status" -eq 0 ]; then
  echo "Done. Copy SayTray.app to ~/Applications (or /Applications), then open it."
  echo "First open: right-click → Open (self-signed; not notarized)."
fi
read -r -p "Press Return to close…" _
exit "$status"
CMD
chmod +x "$STAGE/Setup Piper Voices.command"

cat > "$STAGE/Uninstall SayTray.command" << 'CMD'
#!/bin/bash
cd "$(dirname "$0")"
bash ./uninstall.sh
read -r -p "Press Return to close…" _
CMD
chmod +x "$STAGE/Uninstall SayTray.command"

OUT="dist/SayTray-${VERSION}-macOS.zip"
rm -f "$OUT"
(
  cd "$STAGE"
  zip -r "../SayTray-${VERSION}-macOS.zip" \
    SayTray.app \
    "Setup Piper Voices.command" \
    setup_piper.sh \
    voices.json \
    "Uninstall SayTray.command" \
    uninstall.sh \
    README.md \
    THIRD_PARTY_NOTICES.md
)
rm -rf "$STAGE"
ls -lh "$OUT"
echo "Packaged $OUT"
