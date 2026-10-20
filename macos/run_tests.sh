#!/bin/bash
# 1) TextPrep unit + corpus tests  2) full pipeline (real Piper + guard) over corpus and past problem texts.
set -uo pipefail
cd "$(dirname "$0")"
python3 ../windows/tests/test_voices.py
VOICES=$?
swift build -c release --product TextPrepTests >/dev/null && "$(swift build -c release --show-bin-path)/TextPrepTests" Tests/corpus "$@"
UNIT=$?
mkdir -p build/past
i=0
for f in "$HOME/Library/Logs/SayTray/last/input.txt" Tests/past/*.txt; do
  [ -f "$f" ] || continue; i=$((i+1))
  if grep -q -- "--- RAW ---" "$f"; then python3 -c 'import sys;s=open(sys.argv[1]).read();print(s.split("--- RAW ---\n",1)[1].split("\n--- SCALARS ---",1)[0],end="")' "$f" > build/past/past$i.txt
  else cp "$f" build/past/past$i.txt; fi
done
"$HOME/Applications/SayTray.app/Contents/MacOS/SayTray" --pipeline-test build/pipeline.json Tests/corpus/*.txt build/past/*.txt
python3 Tests/summarize.py build/pipeline.json
PIPE=$?
exit $(( UNIT || PIPE || VOICES ))
