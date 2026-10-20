#!/bin/bash
# Create the Piper venv and download the default commercial voices (Norman + LJSpeech).
# Voice URLs live only in Sources/SayTray/voices.json (also copied next to this script in the zip).
set -euo pipefail

PIPER="$HOME/Library/Application Support/SayTray/piper"
VOICES="$PIPER/voices"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

HELPER=""
if [ -f "$SCRIPT_DIR/saytray_piper.py" ]; then
  HELPER="$SCRIPT_DIR/saytray_piper.py"
elif [ -f "$SCRIPT_DIR/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
  HELPER="$SCRIPT_DIR/SayTray.app/Contents/Resources/saytray_piper.py"
elif [ -f "$HOME/Applications/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
  HELPER="$HOME/Applications/SayTray.app/Contents/Resources/saytray_piper.py"
elif [ -f "/Applications/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
  HELPER="/Applications/SayTray.app/Contents/Resources/saytray_piper.py"
fi

if [ -f "$SCRIPT_DIR/voices.json" ]; then
  CATALOG="$SCRIPT_DIR/voices.json"
elif [ -f "$SCRIPT_DIR/../Sources/SayTray/voices.json" ]; then
  CATALOG="$SCRIPT_DIR/../Sources/SayTray/voices.json"
else
  echo "voices.json not found next to setup_piper.sh or in Sources/SayTray."
  exit 1
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

download() {
  local name="$1" url="$2"
  local out="$VOICES/$name"
  if [ -f "$out" ] && [ -s "$out" ]; then
    echo "  already have $name"
    return 0
  fi
  echo "  downloading $name …"
  curl -fL --retry 3 --progress-bar -o "$out.partial" "$url"
  mv "$out.partial" "$out"
}

# Catalog fields are tab-separated: kind, name, url-or-bytes.
LIST="$("$PYTHON3" - "$CATALOG" << 'PY'
import json, sys
cat = json.load(open(sys.argv[1], encoding="utf-8"))
defaults = [v for v in cat["voices"] if v.get("installByDefault")]
total = sum(int(f.get("sizeBytes") or 0) for v in defaults for f in v["files"])
print(f"total\t{total}\t")
for voice_id in cat.get("removed") or []:
    print(f"remove\t{voice_id}\t")
for v in defaults:
    for f in v["files"]:
        print(f"file\t{f['filename']}\t{f['url']}")
PY
)"

TOTAL_MB="$(printf '%s\n' "$LIST" | awk -F'\t' '$1=="total" { printf "%d", ($2/1048576)+0.5 }')"
echo "Downloading default voices (about ${TOTAL_MB} MB)…"
printf '%s\n' "$LIST" | while IFS="$(printf '\t')" read -r kind name url; do
  case "$kind" in
    remove)
      rm -f "$VOICES/$name.onnx" "$VOICES/$name.onnx.json" "$VOICES/$name.onnx.partial"
      ;;
    file)
      download "$name" "$url"
      ;;
  esac
done

echo "Piper setup complete. Voices in: $VOICES"
echo "Norman (medium) is the default. LJSpeech (high) is included."
echo "More voices (Kristin, John, Cori, LibriTTS, Bryce, Jenny (Dioco)) download from Settings."
