"""Commercial Piper voice catalog. The only place Windows voice URLs live.

`voices.json` next to this file is the catalog. install.ps1 reads the same file.
"""
import hashlib, json, os, threading, urllib.request
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


def size_matches(got, expected):
    """A catalog file is installed only at its exact size. Unknown sizes still reject empty files."""
    try:
        got = int(got)
        expected = int(expected or 0)
    except (TypeError, ValueError):
        return False
    if expected > 0:
        return got == expected
    return got > 0


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def marker_path(path):
    return path + ".sha256"


def write_hash_marker(path, sha):
    expect = (sha or "").strip().lower()
    if not expect:
        return
    try:
        with open(marker_path(path), "w", encoding="utf-8") as f:
            f.write(expect + "\n")
    except OSError:
        pass


# (path, size, mtime, expected hash) -> trusted. A same-size corrupt file is hashed once.
_trust_cache = {}


def file_trusted(path, expected_size, sha):
    """Size match, then the catalog hash. A matching .sha256 marker skips re-reading the file."""
    try:
        st = os.stat(path) if os.path.isfile(path) else None
    except OSError:
        return False
    if st is None:
        return False
    got = st.st_size
    if not size_matches(got, expected_size):
        return False
    expect = (sha or "").strip().lower()
    if not expect:
        return True
    mark = marker_path(path)
    try:
        if os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip().lower() == expect:
            return True
    except OSError:
        pass
    key = (os.path.abspath(path), got, getattr(st, "st_mtime_ns", st.st_mtime), expect)
    cached = _trust_cache.get(key)
    if cached is not None:
        return cached
    try:
        digest = sha256_file(path)
    except OSError:
        return False
    if digest != expect:
        try:
            os.remove(mark)
        except OSError:
            pass
        _trust_cache[key] = False
        return False
    write_hash_marker(path, digest)
    _trust_cache[key] = True
    return True


def is_installed(v, directory=None):
    directory = directory or VOICES
    files = v.get("files") or []
    if not files:
        return False
    for f in files:
        path = os.path.join(directory, f["filename"])
        if not file_trusted(path, f.get("sizeBytes") or 0, f.get("sha256") or ""):
            return False
    return True


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
    if voice_id == default_voice():
        raise ValueError("Norman is the default voice and cannot be deleted.")
    st = downloads.status(voice_id)
    if st.get("state") == "downloading":
        raise RuntimeError("Wait for the download to finish before deleting this voice.")
    for fn in list(_before_delete):
        fn(voice_id)
    directory = directory or VOICES
    os.makedirs(directory, exist_ok=True)
    for f in v["files"]:
        for path in (
            os.path.join(directory, f["filename"]),
            os.path.join(directory, f["filename"] + ".partial"),
            marker_path(os.path.join(directory, f["filename"])),
        ):
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
        self._stop = False
        self._cancel = set()
        self._again = set()

    def shutdown(self):
        """Drop queued downloads. An in-progress file stays a .partial and is not installed."""
        with self._mu:
            self._stop = True
            self._queue.clear()

    def cancel(self, voice_id):
        """Stop one download. A queued voice is dropped. Only the active download is flagged."""
        with self._mu:
            queued = voice_id in self._queue
            current = self._current == voice_id
            self._queue = [v for v in self._queue if v != voice_id]
            self._again.discard(voice_id)
            if current:
                self._cancel.add(voice_id)
            if queued or current:
                self._status[voice_id] = {"state": "idle", "fraction": 0.0, "message": ""}
        if queued or current:
            self._emit(voice_id)

    def _cancelled(self, voice_id):
        with self._mu:
            return self._stop or voice_id in self._cancel

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
        if self._stop or not by_id(voice_id):
            return False
        with self._mu:
            self._cancel.discard(voice_id)
            if voice_id in self._queue:
                return True
            if self._current == voice_id:
                # The worker may be cancelling. Ask it to start again when it exits.
                self._again.add(voice_id)
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
        written = []
        try:
            files = v["files"]
            total = voice_size(v) or 1
            done = 0
            os.makedirs(VOICES, exist_ok=True)
            for f in files:
                if self._cancelled(voice_id):
                    raise RuntimeError("download cancelled")
                dest = os.path.join(VOICES, f["filename"])
                self._download(
                    f["url"], dest, done, total, int(f.get("sizeBytes") or 0), voice_id,
                    sha=f.get("sha256") or "",
                )
                written.append(dest)
                done += int(f.get("sizeBytes") or 0)
            if not is_installed(v):
                raise RuntimeError("download finished but voice files are missing")
            self._set(voice_id, state="done", fraction=1.0, message="Downloaded")
            with self._mu:
                self._again.discard(voice_id)
        except Exception as e:
            for path in written:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if "cancelled" in str(e).lower():
                self._set(voice_id, state="idle", fraction=0.0, message="")
            else:
                self._set(voice_id, state="error", message=f"Download failed: {e}")
        finally:
            with self._mu:
                self._cancel.discard(voice_id)
                again = voice_id in self._again and not self._stop
                self._again.discard(voice_id)
                if self._current == voice_id:
                    self._current = None
                if again:
                    self._queue.append(voice_id)
                    self._status[voice_id] = {"state": "downloading", "fraction": 0.0, "message": "Waiting…"}
            if again:
                self._emit(voice_id)
            self._pump()

    def _download(self, url, dest, done, total, file_size, voice_id, sha=""):
        tmp = dest + ".partial"
        req = urllib.request.Request(url, headers={"User-Agent": "SayTray"})
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                got = 0
                with open(tmp, "wb") as out:
                    while True:
                        if self._cancelled(voice_id):
                            raise RuntimeError("download cancelled")
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        digest.update(chunk)
                        got += len(chunk)
                        counted = min(got, file_size) if file_size else got
                        frac = min(0.99, (done + counted) / float(total or 1))
                        self._set(voice_id, state="downloading", fraction=frac, message=f"Downloading… {int(frac * 100)}%")
            if self._cancelled(voice_id):
                raise RuntimeError("download cancelled")
            if not size_matches(got, file_size):
                raise RuntimeError(f"incomplete download ({got} of {file_size} bytes)")
            expect = (sha or "").strip().lower()
            if expect and digest.hexdigest() != expect:
                raise RuntimeError(f"checksum mismatch for {os.path.basename(dest)}")
            os.replace(tmp, dest)
            write_hash_marker(dest, expect or digest.hexdigest())
        except Exception:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise


downloads = Downloads()
