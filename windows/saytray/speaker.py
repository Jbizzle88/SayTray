"""Speaker: TextPrep -> ReadSession (Piper + guard) -> Player, one read at a time. Port of macOS Speaker."""
import os, shutil, threading
from .textprep import chunks as prep_chunks
from .session import ReadSession
from .engine import PiperEngine
from .player import Player
from .voices import installed_ids, normalize_speaker, playback_voice
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

    def _prepare(self):
        """Point the engine at the saved voice, or Norman when that file is missing."""
        requested = self.settings["voice"]
        chosen = playback_voice(requested, installed_ids())
        if not chosen:
            return False
        if chosen != requested:
            logs.event(f"voice {requested} unavailable; using {chosen}")
            self.engine.speaker_id = None
        else:
            self.engine.speaker_id = normalize_speaker(chosen, self.settings.data.get("speaker"))
        return self.engine.ensure(chosen)

    def warm_up(self):
        self._prepare()

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
            d = logs.last_dir()
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "input.txt"), "w", encoding="utf-8") as f:
                f.write(
                    f"READ {self._read} VOICE {self.settings['voice']} SPEED {self.settings['speed']} "
                    f"CHARS {len(text)} CHUNKS {len(cs)}\n"
                )
            self.player.play_log = os.path.join(d, "play.log")
            self._gen = self.player.new_generation()
            use_piper = self._prepare()
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
