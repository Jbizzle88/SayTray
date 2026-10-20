"""Persisted settings (%LOCALAPPDATA%\\SayTray\\settings.json)."""
import json, os, threading
from .logs import ROOT
from .voices import installed_ids, pretty_voice, resolve_saved_voice

DEFAULTS = {
    "speed": 1.0,
    "voice": "en_US-norman-medium",
    "speaker": 0,
    "sapi_voice": "",
    "read_hotkey": "alt+`",
    "dictate_hotkey": "ctrl+alt+space",
    "start_with_windows": True,
    "chime": True,
}
PATH = os.path.join(ROOT, "settings.json")


def installed_voices():
    return installed_ids()


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(PATH, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass
        voice = resolve_saved_voice(self.data.get("voice") or "")
        changed = voice != self.data.get("voice")
        self.data["voice"] = voice
        if "speaker" not in self.data:
            self.data["speaker"] = 0
        self.listeners = []
        if changed:
            try:
                self._write()
            except Exception:
                pass

    def __getitem__(self, k):
        return self.data[k]

    def _write(self):
        os.makedirs(ROOT, exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def set(self, **kw):
        with self._lock:
            self.data.update(kw)
            self._write()
        for cb in list(self.listeners):
            try:
                cb(kw)
            except Exception:
                pass
