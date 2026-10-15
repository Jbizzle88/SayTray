#!/usr/bin/env python3
"""SayTray persistent Piper helper.

Loads one voice once, then serves line-delimited JSON on stdin/stdout.
  request: {"name": str, "read": int, "text": str, "dir": str, "noise_scale": f, "noise_w": f, "priority": bool}
  cancel:  {"cmd": "cancel", "read": int}      -> drops queued requests of that read
  reply:   {"name": str, "path": str, "seconds": f, "phonemes": int}  or  {"name": str, "error": str}
Each WAV is written to <dir>/<name>.wav.part, closed, then atomically renamed before the reply.
"""
import sys, os, io, json, wave, threading, dataclasses
from piper import PiperVoice, SynthesisConfig

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
voice = PiperVoice.load(sys.argv[1])
FIELDS = {f.name for f in dataclasses.fields(SynthesisConfig)}

def config(ns, nw):
    want = {"length_scale": 1.0, "noise_scale": ns, "noise_w_scale": nw, "noise_w": nw}
    return SynthesisConfig(**{k: v for k, v in want.items() if k in FIELDS})

# count real phones only: skip spaces, punctuation, stress and length marks
PUNCT = set(" ,.;:!?'\"-()\u02c8\u02cc\u02d0\u02d1")
def phoneme_count(text):
    try:
        return sum(1 for sent in voice.phonemize(text) for ph in sent if ph not in PUNCT)
    except Exception:
        return 0

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()

# warm-up so the first real chunk doesn't pay one-time costs
try:
    with wave.open(io.BytesIO(), "wb") as wf:
        voice.synthesize_wav("Ready.", wf, syn_config=config(0.5, 0.6))
except Exception as e:
    print("warmup failed:", e, file=sys.stderr)
emit({"ready": True})

queue, cv = [], threading.Condition()

def reader():
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except Exception:
            continue
        with cv:
            if m.get("cmd") == "cancel":
                queue[:] = [q for q in queue if q.get("read") != m.get("read")]
            elif m.get("priority"):
                queue.insert(0, m)
            else:
                queue.append(m)
            cv.notify()
    with cv:
        queue.append(None); cv.notify()

threading.Thread(target=reader, daemon=True).start()
while True:
    with cv:
        while not queue:
            cv.wait()
        m = queue.pop(0)
    if m is None:
        break
    name = m.get("name", "chunk")
    path = os.path.join(m["dir"], name + ".wav")
    tmp = path + ".part"
    try:
        with wave.open(tmp, "wb") as wf:
            voice.synthesize_wav(m["text"], wf, syn_config=config(float(m.get("noise_scale", 0.5)), float(m.get("noise_w", 0.6))))
        with wave.open(tmp, "rb") as r:
            secs = r.getnframes() / float(r.getframerate())
        os.replace(tmp, path)
        emit({"name": name, "path": path, "seconds": secs, "phonemes": phoneme_count(m["text"])})
    except Exception as e:
        print("synth error:", repr(e), file=sys.stderr)
        emit({"name": name, "error": str(e)})
