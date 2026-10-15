"""Speaker: TextPrep -> ReadSession (Piper + guard) -> Player, one read at a time. Port of macOS Speaker."""
import os, shutil, threading
from .textprep import chunks as prep_chunks
from .session import ReadSession
from .engine import PiperEngine
from .player import Player
from . import logs


class Speaker:
    def __init__(self, settings):
        self.settings = settings
        self.engine = PiperEngine()
        self.player = Player(settings)
        self.player.on_idle = self._pump_safe
        self._session = None
        self._next = 0
        self._gen = 0
        self._read = 0
        self._lock = threading.RLock()
        self.on_state = None

    def warm_up(self):
        self.engine.ensure(self.settings["voice"])

    @property
    def speaking(self):
        return self._session is not None or not self.player.idle

    def speak(self, text):
        self.stop()
        cs = prep_chunks(text)
        if not cs:
            logs.event("read: nothing speakable in selection")
            return False
        with self._lock:
            self._read += 1
            d = logs.LAST
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
            scal = "".join(c if 32 <= ord(c) < 127 else f"<U+{ord(c):04X}>" for c in text)
            with open(os.path.join(d, "input.txt"), "w", encoding="utf-8") as f:
                f.write(f"READ {self._read} VOICE {self.settings['voice']} SPEED {self.settings['speed']}\n--- RAW ---\n{text}\n"
                        f"--- SCALARS ---\n{scal}\n--- CHUNKS ---\n" + "\n".join(f"{i + 1:03d}: {c}" for i, c in enumerate(cs)) + "\n")
            self.player.play_log = os.path.join(d, "play.log")
            self._gen = self.player.new_generation()
            use_piper = self.engine.ensure(self.settings["voice"])
            s = ReadSession(self._read, cs, d, self.engine if use_piper else None)
            s.on_update = self._on_update
            self._session, self._next = s, 0
        self._state()
        s.start()
        return True

    def _on_update(self, s):
        with self._lock:
            if s is self._session:
                self._pump()

    def _pump_safe(self):
        with self._lock:
            self._pump()

    def _pump(self):
        s = self._session
        if s is None:
            return
        while self._next < len(s.slots) and s.slots[self._next].items is not None:
            self.player.enqueue(s.slots[self._next].items, self._gen)
            self._next += 1
        if self._next == len(s.slots) and self.player.idle:
            self._session = None
            self._state()

    def stop(self):
        with self._lock:
            if self._session:
                self._session.cancelled = True
                self.engine.cancel(self._session.id)
            self._session = None
            self.player.stop()
        self._state()

    def _state(self):
        if self.on_state:
            try:
                self.on_state()
            except Exception:
                pass
