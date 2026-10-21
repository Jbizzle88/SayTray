"""Persisted settings (%LOCALAPPDATA%\\SayTray\\settings.json)."""
import json, os, threading, datetime
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

_MODS = {
    "ctrl", "control", "alt", "shift", "win", "windows", "cmd", "command", "option", "meta",
    "alt gr", "altgr", "left windows", "right windows",
}
_KEYS_WITH_SPACE = {
    "page up", "page down", "num lock", "scroll lock", "print screen", "caps lock",
    "left windows", "right windows", "left ctrl", "right ctrl", "left alt", "right alt",
    "left shift", "right shift", "alt gr",
}


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


def _hotkey_parts(value):
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or raw.lower() in ("press keys…", "press keys..."):
        return None
    return raw


def hotkey_structure_ok(value):
    """True when the shortcut is shaped like one SayTray can store."""
    raw = _hotkey_parts(value)
    if raw is None:
        return False
    parts = [p.strip() for p in raw.split("+")]
    if not parts or any(not p for p in parts) or len(parts) > 5:
        return False
    key = parts[-1]
    if any(ord(c) < 32 for c in key) or len(key) > 32:
        return False
    if any(ch.isspace() for ch in key) and key.lower() not in _KEYS_WITH_SPACE:
        return False
    for mod in parts[:-1]:
        if mod.lower() not in _MODS:
            return False
    return True


def hotkey_ok(value):
    """True when the shortcut should be kept in settings.

    A layout that cannot type the key today still keeps the saved shortcut.
    Registration skips it and tells the user, instead of replacing it.
    """
    if hotkey_structure_ok(value):
        return True
    raw = _hotkey_parts(value)
    if raw is None:
        return False
    try:
        import keyboard
        keyboard.parse_hotkey(raw)
        return True
    except Exception:
        return False


def hotkey_registerable(value):
    """False when the installed keyboard hook rejects this shortcut on the current layout."""
    raw = _hotkey_parts(value)
    if not raw:
        return False
    try:
        import keyboard
    except ImportError:
        return hotkey_structure_ok(value)
    try:
        keyboard.parse_hotkey(raw)
        return True
    except Exception:
        return False


def coerce_hotkey(value, default):
    if hotkey_ok(value):
        return value.strip()
    return default


def coerce_speaker(value, default=0):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 0:
        return default
    return n


def sanitize(data):
    """Fix known fields. Unknown keys are kept so a newer build's settings survive."""
    src = data if isinstance(data, dict) else {}
    out = dict(DEFAULTS)
    for key, value in src.items():
        if key not in DEFAULTS:
            out[key] = value
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


def write_atomic(path, data):
    """Replace `path` only after the new file is fully written."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup_unreadable(path):
    """Move a settings file that did not parse aside. Returns the backup path."""
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    dest = path + ".bad"
    if os.path.exists(dest):
        dest = path + ".bad." + stamp
    os.replace(path, dest)
    return dest


def installed_voices():
    return installed_ids()


def read_settings(path):
    """Return (data, should_write).

    A missing file is {}. JSON that does not parse, or JSON that is not an object,
    is moved to .bad and replaced with {}. A permission or sharing error leaves the
    file where it is and returns in-memory defaults without writing.
    """
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except FileNotFoundError:
        return {}, True
    except json.JSONDecodeError:
        try:
            backup_unreadable(path)
        except OSError:
            pass
        return {}, True
    except OSError:
        return {}, False
    if not isinstance(loaded, dict):
        try:
            backup_unreadable(path)
        except OSError:
            pass
        return {}, True
    return loaded, True


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        raw, should_write = read_settings(PATH)
        self.data = sanitize(raw or {})
        voice = resolve_saved_voice(self.data.get("voice") or "")
        if voice != self.data.get("voice"):
            self.data["voice"] = voice
        self.listeners = []
        if should_write:
            dirty = any(self.data.get(k) != (raw or {}).get(k) for k in self.data)
        else:
            dirty = False
        if dirty:
            try:
                self._write()
            except Exception:
                pass

    def __getitem__(self, k):
        return self.data[k]

    def _write(self):
        write_atomic(PATH, self.data)

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
