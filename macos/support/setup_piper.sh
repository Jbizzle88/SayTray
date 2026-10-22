#!/bin/bash
# Create the Piper venv and download the default commercial voices (Norman + LJSpeech).
# Voice URLs live only in Sources/SayTray/voices.json (also copied next to this script in the zip).
set -euo pipefail

# Recreate the venv when python or the pip script cannot run. A venv moved from
# another path (SpeakBar → SayTray) keeps a pip shebang pointing at the old
# interpreter; installing with that script fails, and `|| true` used to hide it.
ensure_piper_venv() {
  local piper="$1"
  local python3="$2"
  local venv="$piper/venv"
  if [ -d "$venv" ]; then
    if ! "$venv/bin/python" -c 'import sys' >/dev/null 2>&1 \
        || ! "$venv/bin/pip" --version >/dev/null 2>&1 \
        || ! "$venv/bin/python" -c 'import piper, onnxruntime' >/dev/null 2>&1; then
      echo "Piper venv is broken (python, pip, or Piper is not runnable). Recreating it…"
      rm -rf "$venv"
    fi
  fi
  if [ ! -x "$venv/bin/python" ]; then
    echo "Creating Piper venv at $venv …"
    "$python3" -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip
    "$venv/bin/python" -m pip install 'piper-tts==1.8.0'
  else
    echo "Piper venv already present."
    "$venv/bin/python" -m pip install -q --upgrade pip
    "$venv/bin/python" -m pip install -q 'piper-tts==1.8.0'
  fi
}

main() {
  local PIPER="$HOME/Library/Application Support/SayTray/piper"
  local VOICES="$PIPER/voices"
  local SCRIPT_DIR
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

  local HELPER=""
  if [ -f "$SCRIPT_DIR/saytray_piper.py" ]; then
    HELPER="$SCRIPT_DIR/saytray_piper.py"
  elif [ -f "$SCRIPT_DIR/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
    HELPER="$SCRIPT_DIR/SayTray.app/Contents/Resources/saytray_piper.py"
  elif [ -f "$HOME/Applications/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
    HELPER="$HOME/Applications/SayTray.app/Contents/Resources/saytray_piper.py"
  elif [ -f "/Applications/SayTray.app/Contents/Resources/saytray_piper.py" ]; then
    HELPER="/Applications/SayTray.app/Contents/Resources/saytray_piper.py"
  fi

  local CATALOG=""
  if [ -f "$SCRIPT_DIR/voices.json" ]; then
    CATALOG="$SCRIPT_DIR/voices.json"
  elif [ -f "$SCRIPT_DIR/../Sources/SayTray/voices.json" ]; then
    CATALOG="$SCRIPT_DIR/../Sources/SayTray/voices.json"
  else
    echo "voices.json not found next to setup_piper.sh or in Sources/SayTray."
    exit 1
  fi

  local PYTHON3
  PYTHON3="$(command -v python3 || true)"
  if [ -z "$PYTHON3" ]; then
    echo "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/ then re-run."
    exit 1
  fi
  if ! "$PYTHON3" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 or newer is required."
    exit 1
  fi

  mkdir -p "$VOICES"
  ensure_piper_venv "$PIPER" "$PYTHON3"

  if [ -n "$HELPER" ]; then
    cp "$HELPER" "$PIPER/saytray_piper.py"
    echo "Installed saytray_piper.py"
  fi

  sha_of() {
    local path="$1"
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 "$path" | awk '{print $1}'
    else
      sha256sum "$path" | awk '{print $1}'
    fi
  }

  download() {
    local name="$1" url="$2" expect="${3:-0}" sha="${4:-}"
    local out="$VOICES/$name" got
    if [ -f "$out" ]; then
      got=$(wc -c < "$out" | tr -d '[:space:]')
      local size_ok=0
      if { [ "$expect" -gt 0 ] && [ "$got" -eq "$expect" ]; } || { [ "$expect" -le 0 ] && [ "$got" -gt 0 ]; }; then
        size_ok=1
      fi
      if [ "$size_ok" -eq 1 ] && { [ -z "$sha" ] || [ "$(sha_of "$out")" = "$sha" ]; }; then
        echo "  already have $name"
        if [ -n "$sha" ]; then
          printf '%s\n' "$sha" > "$out.sha256"
        fi
        return 0
      fi
      echo "  replacing incomplete $name ($got of $expect bytes)"
      rm -f "$out"
    fi
    echo "  downloading $name …"
    curl -fL --retry 3 --progress-bar -o "$out.partial" "$url"
    got=$(wc -c < "$out.partial" | tr -d '[:space:]')
    if [ "$expect" -gt 0 ] && [ "$got" -ne "$expect" ]; then
      rm -f "$out.partial"
      echo "  incomplete download: $name ($got of $expect bytes)" >&2
      exit 1
    fi
    if [ "${got:-0}" -le 0 ]; then
      rm -f "$out.partial"
      echo "  incomplete download: $name (empty)" >&2
      exit 1
    fi
    if [ -n "$sha" ] && [ "$(sha_of "$out.partial")" != "$sha" ]; then
      rm -f "$out.partial"
      echo "  checksum mismatch: $name" >&2
      exit 1
    fi
    mv "$out.partial" "$out"
    if [ -n "$sha" ]; then
      printf '%s\n' "$sha" > "$out.sha256"
    fi
  }

  # Catalog fields are tab-separated: kind, name, url-or-bytes.
  local LIST
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
        print(f"file\t{f['filename']}\t{f['url']}\t{int(f.get('sizeBytes') or 0)}\t{f.get('sha256') or ''}")
PY
)"

  local TOTAL_MB
  TOTAL_MB="$(printf '%s\n' "$LIST" | awk -F'\t' '$1=="total" { printf "%d", ($2/1048576)+0.5 }')"
  echo "Downloading default voices (about ${TOTAL_MB} MB)…"
  printf '%s\n' "$LIST" | while IFS="$(printf '\t')" read -r kind name url size sha; do
    case "$kind" in
      remove)
        rm -f "$VOICES/$name.onnx" "$VOICES/$name.onnx.json" "$VOICES/$name.onnx.partial"
        ;;
      file)
        download "$name" "$url" "${size:-0}" "${sha:-}"
        ;;
    esac
  done

  echo "Piper setup complete. Voices in: $VOICES"
  echo "Norman (medium) is the default. LJSpeech (high) is included."
  echo "More voices (Kristin, John, Cori, LibriTTS, Bryce, Jenny (Dioco)) download from Settings."
}

# `bash setup_piper.sh` leaves $0 as bash, so compare against an explicit opt-out
# instead of $0. Tests source the file with SAYTRAY_SETUP_LIBRARY=1.
if [ "${SAYTRAY_SETUP_LIBRARY:-}" != 1 ]; then
  main "$@"
fi
