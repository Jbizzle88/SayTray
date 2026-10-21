"""Logging: %LOCALAPPDATA%\\SayTray\\Logs\\events.log, guard.log, and the per-read Logs\\last folder."""
import os, threading, datetime

ROOT = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SayTray")
LOGS = os.path.join(ROOT, "Logs")
LAST = os.path.join(LOGS, "last")
VOICES = os.path.join(ROOT, "voices")
_lock = threading.Lock()
_MAX_BYTES = 512 * 1024


def rotate_if_big(path, limit=_MAX_BYTES):
    """Keep one older copy. The live file starts empty after the rename."""
    try:
        if os.path.isfile(path) and os.path.getsize(path) >= limit:
            os.replace(path, path + ".1")
            return True
    except OSError:
        pass
    return False


def append(line, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with _lock:
        rotate_if_big(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{ts} {line}\n")


def event(s):
    append(s, os.path.join(LOGS, "events.log"))


def guard(s):
    event("GUARD " + s)
    append(s, os.path.join(LOGS, "guard.log"))


def purge_legacy_text_logs(root=None, version="1.1.0"):
    """Once per version, drop logs and WAVs that older builds filled with the user's text."""
    root = root or LOGS
    os.makedirs(root, exist_ok=True)
    marker = os.path.join(root, f".purged-{version}")
    if os.path.exists(marker):
        return False
    for name in ("events.log", "events.log.1", "guard.log", "guard.log.1"):
        try:
            os.remove(os.path.join(root, name))
        except OSError:
            pass
    last = os.path.join(root, "last")
    if os.path.isdir(last):
        for name in os.listdir(last):
            lower = name.lower()
            if lower.endswith(".wav") or lower.endswith(".wav.part") or lower in ("input.txt", "play.log"):
                try:
                    os.remove(os.path.join(last, name))
                except OSError:
                    pass
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(version + "\n")
    except OSError:
        return False
    return True
