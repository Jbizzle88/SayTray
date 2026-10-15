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

# Double-clickable Piper setup (downloads ~360 MB voices + creates venv)
cat > "$STAGE/Setup Piper Voices.command" << 'CMD'
#!/bin/bash
cd "$(dirname "$0")"
set -euo pipefail
PIPER="$HOME/Library/Application Support/SayTray/piper"
APP_HELPER="SayTray.app/Contents/Resources/saytray_piper.py"
mkdir -p "$PIPER/voices"
if [ -f "$APP_HELPER" ]; then cp "$APP_HELPER" "$PIPER/saytray_piper.py"; fi
PYTHON3="$(command -v python3 || true)"
if [ -z "$PYTHON3" ]; then
  echo "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/ then re-run."
  read -r -p "Press Return to close…" _
  exit 1
fi
if [ ! -x "$PIPER/venv/bin/python" ]; then
  echo "Creating Piper venv…"
  "$PYTHON3" -m venv "$PIPER/venv"
  "$PIPER/venv/bin/pip" install --upgrade pip
  "$PIPER/venv/bin/pip" install 'piper-tts==1.8.0'
else
  echo "Piper venv already present; ensuring piper-tts…"
  "$PIPER/venv/bin/pip" install -q 'piper-tts==1.8.0' || true
fi
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US"
download() {
  local name="$1" url="$2"
  local out="$PIPER/voices/$name"
  if [ -f "$out" ] && [ -s "$out" ]; then echo "  already have $name"; return 0; fi
  echo "  downloading $name …"
  curl -fL --progress-bar -o "$out.partial" "$url"
  mv "$out.partial" "$out"
}
echo "Downloading voices (≈360 MB)…"
download "en_US-ryan-high.onnx" "$BASE/ryan/high/en_US-ryan-high.onnx?download=true"
download "en_US-ryan-high.onnx.json" "$BASE/ryan/high/en_US-ryan-high.onnx.json?download=true"
download "en_US-lessac-high.onnx" "$BASE/lessac/high/en_US-lessac-high.onnx?download=true"
download "en_US-lessac-high.onnx.json" "$BASE/lessac/high/en_US-lessac-high.onnx.json?download=true"
download "en_US-amy-medium.onnx" "$BASE/amy/medium/en_US-amy-medium.onnx?download=true"
download "en_US-amy-medium.onnx.json" "$BASE/amy/medium/en_US-amy-medium.onnx.json?download=true"
download "en_US-libritts_r-medium.onnx" "$BASE/libritts_r/medium/en_US-libritts_r-medium.onnx?download=true"
download "en_US-libritts_r-medium.onnx.json" "$BASE/libritts_r/medium/en_US-libritts_r-medium.onnx.json?download=true"
echo
echo "Done. Copy SayTray.app to ~/Applications (or /Applications), then open it."
echo "First open: right-click → Open (self-signed; not notarized)."
read -r -p "Press Return to close…" _
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
    "Uninstall SayTray.command" \
    uninstall.sh \
    README.md
)
rm -rf "$STAGE"
ls -lh "$OUT"
echo "Packaged $OUT"
