"""Commercial Piper voice catalog. The only place Windows voice URLs live.

`voices.json` next to this file is the catalog. install.ps1 reads the same file.
"""
import json, os, threading, urllib.request
from .logs import VOICES

_PATH = os.path.join(os.path.dirname(__file__), "voices.json")
_catalog = None
_lock = threading.Lock()


def catalog():
    global _catalog
    if _catalog is None:
        with open(_PATH, encoding="utf-8") as f:
            _catalog = json.load(f)
    return _catalog


def voices():
    return catalog()["voices"]


def by_id(voice_id):
    for v in voices():
        if v["id"] == voice_id:
            return v
    return None


def default_voice():
    return catalog().get("defaultVoice") or "en_US-norman-medium"


def voice_size(v):
    return sum(int(f.get("sizeBytes") or 0) for f in v.get("files") or [])


def format_size(n):
    """Whole mebibytes, matching the macOS catalog label."""
    return f"{int(n / (1024 * 1024) + 0.5)} MB"


def pretty_voice(voice_id):
    v = by_id(voice_id)
    if v:
        return v["label"]
    return voice_id or ""


def resolve_saved_voice(saved):
    """Unknown or removed voices fall back to Norman. Catalog ids are kept even if not downloaded."""
    if saved and by_id(saved):
        return saved
    return default_voice()


def normalize_speaker(voice_id, saved):
    """Speaker id for a multi-speaker voice, or None for single-speaker voices."""
    v = by_id(voice_id)
    speakers = (v or {}).get("speakers") or []
    if not speakers:
        return None
    ids = [int(s["id"]) for s in speakers]
    try:
        n = int(saved)
    except (TypeError, ValueError):
        n = None
    if n in ids:
        return n
    return ids[0]


def playback_voice(requested, installed):
    """Voice id to load, or None when nothing usable is on disk."""
    installed = set(installed)
    if requested in installed:
        return requested
    fallback = default_voice()
    if fallback in installed:
        return fallback
    return None


def _nonempty(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def is_installed(v, directory=None):
    directory = directory or VOICES
    files = v.get("files") or []
    return bool(files) and all(_nonempty(os.path.join(directory, f["filename"])) for f in files)


def installed_ids(directory=None):
    return [v["id"] for v in voices() if is_installed(v, directory)]


def remove_retired_voices(directory=None):
    """Delete voices that are not licensed for a commercial build, if a previous install left them."""
    directory = directory or VOICES
    removed = []
    if not directory or not os.path.isdir(directory):
        return removed
    for voice_id in catalog().get("removed") or []:
        for ext in (".onnx", ".onnx.json", ".onnx.partial"):
            path = os.path.join(directory, voice_id + ext)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    removed.append(path)
                except OSError:
                    pass
    return removed


_before_delete = []
_after_delete = []


def on_before_delete(fn):
    _before_delete.append(fn)


def on_after_delete(fn):
    _after_delete.append(fn)


def delete_voice(voice_id, directory=None):
    v = by_id(voice_id)
    if not v:
        raise ValueError("unknown voice")
    st = downloads.status(voice_id)
    if st.get("state") == "downloading":
        raise RuntimeError("Wait for the download to finish before deleting this voice.")
    for fn in list(_before_delete):
        fn(voice_id)
    directory = directory or VOICES
    os.makedirs(directory, exist_ok=True)
    for f in v["files"]:
        for path in (os.path.join(directory, f["filename"]), os.path.join(directory, f["filename"] + ".partial")):
            if os.path.isfile(path):
                os.remove(path)
    for fn in list(_after_delete):
        fn(voice_id)


class Downloads:
    """One-at-a-time downloader. Status is polled by the tray menu and the settings window."""

    def __init__(self):
        self._mu = threading.Lock()
        self._status = {}
        self._queue = []
        self._current = None
        self._listeners = []

    def add_listener(self, fn):
        with self._mu:
            self._listeners.append(fn)

    def status(self, voice_id):
        with self._mu:
            return dict(self._status.get(voice_id) or {"state": "idle", "fraction": 0.0, "message": ""})

    def active(self):
        with self._mu:
            return [(vid, dict(st)) for vid, st in self._status.items() if st.get("state") == "downloading"]

    def start(self, voice_id):
        if not by_id(voice_id):
            return False
        with self._mu:
            st = self._status.get(voice_id) or {}
            if st.get("state") == "downloading" or voice_id in self._queue or self._current == voice_id:
                return True
            self._queue.append(voice_id)
            self._status[voice_id] = {"state": "downloading", "fraction": 0.0, "message": "Waiting…"}
        self._emit(voice_id)
        self._pump()
        return True

    def _emit(self, voice_id):
        st = self.status(voice_id)
        with self._mu:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(voice_id, st)
            except Exception:
                pass

    def _set(self, voice_id, **kw):
        with self._mu:
            st = dict(self._status.get(voice_id) or {})
            st.update(kw)
            prev = self._status.get(voice_id) or {}
            # Avoid waking the UI on every socket block.
            pct = int(float(st.get("fraction") or 0) * 100)
            prev_pct = int(float(prev.get("fraction") or 0) * 100)
            self._status[voice_id] = st
            changed = pct != prev_pct or st.get("state") != prev.get("state") or st.get("message") != prev.get("message")
        if changed:
            self._emit(voice_id)

    def _pump(self):
        with self._mu:
            if self._current or not self._queue:
                return
            voice_id = self._queue.pop(0)
            self._current = voice_id
        threading.Thread(target=self._run, args=(voice_id,), daemon=True, name="voice-download").start()

    def _run(self, voice_id):
        v = by_id(voice_id)
        try:
            files = v["files"]
            total = voice_size(v) or 1
            done = 0
            os.makedirs(VOICES, exist_ok=True)
            for f in files:
                dest = os.path.join(VOICES, f["filename"])
                self._download(f["url"], dest, done, total, int(f.get("sizeBytes") or 0), voice_id)
                done += int(f.get("sizeBytes") or 0)
            if not is_installed(v):
                raise RuntimeError("download finished but voice files are missing")
            self._set(voice_id, state="done", fraction=1.0, message="Downloaded")
        except Exception as e:
            self._set(voice_id, state="error", message=f"Download failed: {e}")
        finally:
            with self._mu:
                if self._current == voice_id:
                    self._current = None
            self._pump()

    def _download(self, url, dest, done, total, file_size, voice_id):
        tmp = dest + ".partial"
        req = urllib.request.Request(url, headers={"User-Agent": "SayTray"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                got = 0
                with open(tmp, "wb") as out:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                        counted = min(got, file_size) if file_size else got
                        frac = min(0.99, (done + counted) / float(total or 1))
                        self._set(voice_id, state="downloading", fraction=frac, message=f"Downloading… {int(frac * 100)}%")
            if not _nonempty(tmp):
                raise RuntimeError("empty download")
            os.replace(tmp, dest)
        except Exception:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise


downloads = Downloads()
