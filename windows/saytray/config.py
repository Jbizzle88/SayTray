"""Persisted settings (%LOCALAPPDATA%\\SayTray\\settings.json)."""
import json, os, threading
from .logs import ROOT, VOICES

DEFAULTS = {
    "speed": 1.0,
    "voice": "en_US-ryan-high",
    "sapi_voice": "",
    "read_hotkey": "alt+`",
    "dictate_hotkey": "ctrl+alt+space",
    "start_with_windows": True,
    "chime": True,
}
PATH = os.path.join(ROOT, "settings.json")


def installed_voices():
    try:
        return sorted(f[:-5] for f in os.listdir(VOICES) if f.endswith(".onnx"))
    except OSError:
        return []


def pretty_voice(v):
    p = v.split("-")
    return f"{p[1].replace('_', ' ').title()} ({p[2]})" if len(p) >= 3 else v


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(PATH, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass
        vs = installed_voices()
        if vs and self.data["voice"] not in vs:
            self.data["voice"] = next((v for v in vs if "ryan-high" in v), vs[0])
        self.listeners = []

    def __getitem__(self, k):
        return self.data[k]

    def set(self, **kw):
        with self._lock:
            self.data.update(kw)
            os.makedirs(ROOT, exist_ok=True)
            with open(PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        for cb in list(self.listeners):
            try:
                cb(kw)
            except Exception:
                pass
