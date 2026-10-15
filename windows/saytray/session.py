"""ReadSession: chunks -> Piper WAVs (with babble guard) -> ordered play items. Port of macOS ReadSession.

Guard policy: 1st failure -> split in two (lower noise); unsplittable -> one lower-noise retry;
still bad -> Windows SAPI voice for that piece. Every trigger is logged."""
import os, threading
from .textprep import BabbleGuard, split_in_half, word_count
from .engine import Noise
from . import logs


class Slot:
    def __init__(self, text, key, parent=None):
        self.text, self.key, self.parent = text, key, parent
        self.items = None          # list of ("file", path) / ("system", text)
        self.subs = []
        self.attempts = []         # (seconds, verdict)
        self.events = []
        self.phonemes = 0


class ReadSession:
    def __init__(self, read_id, chunks, out_dir, engine):
        self.id, self.dir, self.engine = read_id, out_dir, engine
        self.slots = [Slot(c, f"{i + 1:03d}") for i, c in enumerate(chunks)]
        self.cancelled = False
        self.on_update = None
        self._lock = threading.RLock()

    @property
    def complete(self):
        return all(s.items is not None for s in self.slots)

    def start(self):
        if self.engine is None:
            for s in self.slots:
                s.items = [("system", s.text)]
            self._notify()
            return
        for s in self.slots:
            self._submit(s, 0)

    def _submit(self, s, attempt):
        is_sub = s.parent is not None
        noise = Noise.NORMAL if (attempt == 0 and not is_sub) else Noise.STRICT
        name = f"r{self.id}-{s.key}-a{attempt}"
        self.engine.synthesize(self.id, name, s.text, self.dir, noise, attempt > 0 or is_sub,
                               lambda res, err: self._done(s, attempt, res, err))

    def _done(self, s, attempt, res, err):
        if self.cancelled:
            return
        with self._lock:
            is_sub = s.parent is not None
            if err or res is None:
                self._trigger(s, f"engine failure ({err}); using system voice")
                return self._resolve(s, [("system", s.text)])
            path, secs, ph = res
            ok, spp, spw, reason = BabbleGuard.check(s.text, secs, ph)
            s.attempts.append((secs, "ok" if ok else reason))
            s.phonemes = ph
            if ok:
                return self._resolve(s, [("file", path)])
            detail = f"{secs:.2f}s, {ph} phonemes, {spp:.3f} s/phoneme, {spw:.3f} s/word"
            halves = split_in_half(s.text) if (not is_sub and attempt == 0) else None
            if halves:
                self._trigger(s, f"{reason} ({detail}); splitting into 2 parts with lower noise")
                s.subs = [Slot(t, f"{s.key}s{i}", s) for i, t in enumerate(halves)]
                for sub in s.subs:
                    self._submit(sub, 0)
            elif attempt == 0:
                self._trigger(s, f"{reason} ({detail}); re-synthesizing with lower noise")
                self._submit(s, 1)
            else:
                self._trigger(s, f"{reason} again ({detail}); using system voice")
                self._resolve(s, [("system", s.text)])

    def _trigger(self, s, msg):
        s.events.append(msg)
        logs.guard(f"read {self.id} chunk {s.key}: {msg} | {s.text}")
        logs.append(f"GUARD chunk {s.key}: {msg}", os.path.join(self.dir, "play.log"))

    def _resolve(self, s, items):
        s.items = items
        p = s.parent
        if p is not None and all(x.items is not None for x in p.subs):
            p.items = [it for x in p.subs for it in x.items]
        self._notify()

    def _notify(self):
        if self.on_update and not self.cancelled:
            self.on_update(self)
