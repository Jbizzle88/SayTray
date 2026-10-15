#!/bin/bash
# Create the Piper venv and download default English voices into Application Support.
# SpeaksBar ships without the ~360 MB voice models; run this once after install.
set -euo pipefail

PIPER="$HOME/Library/Application Support/SayTray/piper"
VOICES="$PIPER/voices"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Prefer the helper bundled next to this script (repo) or from the installed app.
HELPER=""
if [ -f "$SCRIPT_DIR/saytray_piper.py" ]; then
  HELPER="$SCRIPT_DIR/saytray_piper.py"
elif [ -f "$HOME/Applications/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
  HELPER="$HOME/Applications/SayTray.app/Contents/Resources/saytray_piper.py"
fi

PYTHON3="$(command -v python3 || true)"
if [ -z "$PYTHON3" ]; then
  echo "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/ then re-run."
  exit 1
fi

mkdir -p "$VOICES"
if [ ! -x "$PIPER/venv/bin/python" ]; then
  echo "Creating Piper venv at $PIPER/venv …"
  "$PYTHON3" -m venv "$PIPER/venv"
  "$PIPER/venv/bin/pip" install --upgrade pip
  "$PIPER/venv/bin/pip" install 'piper-tts==1.8.0'
else
  echo "Piper venv already present."
  "$PIPER/venv/bin/pip" install -q 'piper-tts==1.8.0' || true
fi

if [ -n "$HELPER" ]; then
  cp "$HELPER" "$PIPER/saytray_piper.py"
  echo "Installed saytray_piper.py"
fi

# Hugging Face rhasspy/piper-voices (public)
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US"
download() {
  local name="$1" url="$2"
  local out="$VOICES/$name"
  if [ -f "$out" ] && [ -s "$out" ]; then
    echo "  already have $name"
    return 0
  fi
  echo "  downloading $name …"
  curl -fL --progress-bar -o "$out.partial" "$url"
  mv "$out.partial" "$out"
}

echo "Downloading voices (≈360 MB total)…"
download "en_US-ryan-high.onnx"      "$BASE/ryan/high/en_US-ryan-high.onnx?download=true"
download "en_US-ryan-high.onnx.json" "$BASE/ryan/high/en_US-ryan-high.onnx.json?download=true"
download "en_US-lessac-high.onnx"    "$BASE/lessac/high/en_US-lessac-high.onnx?download=true"
download "en_US-lessac-high.onnx.json" "$BASE/lessac/high/en_US-lessac-high.onnx.json?download=true"
download "en_US-amy-medium.onnx"     "$BASE/amy/medium/en_US-amy-medium.onnx?download=true"
download "en_US-amy-medium.onnx.json" "$BASE/amy/medium/en_US-amy-medium.onnx.json?download=true"
download "en_US-libritts_r-medium.onnx" "$BASE/libritts_r/medium/en_US-libritts_r-medium.onnx?download=true"
download "en_US-libritts_r-medium.onnx.json" "$BASE/libritts_r/medium/en_US-libritts_r-medium.onnx.json?download=true"

echo "Piper setup complete. Voices in: $VOICES"
echo "Launch SayTray and pick a Piper voice in Settings if needed (Ryan high is the default)."
