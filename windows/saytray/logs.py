"""Logging: %LOCALAPPDATA%\\SayTray\\Logs\\events.log, guard.log, and the per-read Logs\\last folder."""
import os, threading, datetime

ROOT = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SayTray")
LOGS = os.path.join(ROOT, "Logs")
LAST = os.path.join(LOGS, "last")
VOICES = os.path.join(ROOT, "voices")
_lock = threading.Lock()


def append(line, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{ts} {line}\n")


def event(s):
    append(s, os.path.join(LOGS, "events.log"))


def guard(s):
    event("GUARD " + s)
    append(s, os.path.join(LOGS, "guard.log"))
