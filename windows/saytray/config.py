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

_MODS = {"ctrl", "control", "alt", "shift", "win", "windows", "cmd", "command", "option", "meta"}


def clamp_speed(value, default=1.0):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if n != n or n == float("inf") or n == float("-inf"):
        return default
    if n < 0.5:
        return 0.5
    if n > 2.0:
        return 2.0
    return n


def coerce_bool(value, default):
    """Real booleans only. The string "false" must not become True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 0 or value == 0.0:
            return False
        if value == 1 or value == 1.0:
            return True
        return default
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    return default


def coerce_hotkey(value, default):
    if not isinstance(value, str):
        return default
    raw = value.strip()
    parts = [p.strip() for p in raw.split("+")]
    if not parts or any(not p for p in parts) or len(parts) > 4:
        return default
    if any(any(ch.isspace() for ch in p) for p in parts):
        return default
    key = parts[-1]
    if len(key) > 24 or any(ord(c) < 32 or ord(c) > 126 for c in key):
        return default
    for mod in parts[:-1]:
        if mod.lower() not in _MODS:
            return default
    return raw


def coerce_speaker(value, default=0):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 0 or n > 64:
        return default
    return n


def sanitize(data):
    """Keep only known settings, with speed, hotkeys, and chime in range."""
    src = data if isinstance(data, dict) else {}
    out = dict(DEFAULTS)
    out["speed"] = clamp_speed(src.get("speed", DEFAULTS["speed"]))
    voice = src.get("voice", DEFAULTS["voice"])
    out["voice"] = voice.strip() if isinstance(voice, str) and voice.strip() else DEFAULTS["voice"]
    out["speaker"] = coerce_speaker(src.get("speaker", DEFAULTS["speaker"]))
    sapi = src.get("sapi_voice", "")
    out["sapi_voice"] = sapi if isinstance(sapi, str) else ""
    out["read_hotkey"] = coerce_hotkey(src.get("read_hotkey"), DEFAULTS["read_hotkey"])
    out["dictate_hotkey"] = coerce_hotkey(src.get("dictate_hotkey"), DEFAULTS["dictate_hotkey"])
    out["start_with_windows"] = coerce_bool(src.get("start_with_windows"), DEFAULTS["start_with_windows"])
    out["chime"] = coerce_bool(src.get("chime"), DEFAULTS["chime"])
    return out


def installed_voices():
    return installed_ids()


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        raw = {}
        try:
            with open(PATH, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            pass
        self.data = sanitize(raw)
        voice = resolve_saved_voice(self.data.get("voice") or "")
        if voice != self.data.get("voice"):
            self.data["voice"] = voice
        self.listeners = []
        dirty = any(self.data.get(k) != raw.get(k) for k in DEFAULTS) or any(k not in DEFAULTS for k in raw)
        if dirty:
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
            merged = dict(self.data)
            merged.update(kw)
            self.data = sanitize(merged)
            self._write()
        for cb in list(self.listeners):
            try:
                cb(kw)
            except Exception:
                pass
