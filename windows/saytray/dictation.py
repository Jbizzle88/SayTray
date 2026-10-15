"""Push-to-talk dictation: record while the hotkey is held, transcribe locally with faster-whisper
(base.en, CPU int8), type the result at the cursor."""
import threading, time
import numpy as np
from . import logs
from .selection import type_text

SR = 16000


class Dictation:
    def __init__(self, player=None, settings=None):
        self._model = None
        self._stream = None
        self._frames = []
        self._capturing = False   # True only after the start chime finishes (chime never transcribed)
        self.recording = False
        self.on_state = None
        self.player = player
        self.settings = settings
        self._lock = threading.Lock()
        threading.Thread(target=self._load_model, daemon=True, name="whisper-load").start()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            t0 = time.time()
            self._model = WhisperModel("base.en", device="cpu", compute_type="int8")
            logs.event(f"dictation: whisper base.en loaded in {time.time() - t0:.1f}s")
        except Exception as e:
            logs.event(f"dictation: model load failed: {e!r}")

    def _cb(self, indata, frames, t, status):
        if self._capturing:
            self._frames.append(indata[:, 0].copy())

    def start(self):
        import sounddevice as sd
        with self._lock:
            if self.recording:
                return
            self._frames = []
            self._capturing = False
            try:
                self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=self._cb)
                self._stream.start()
            except Exception as e:
                logs.event(f"dictation: microphone open failed: {e!r}")
                self._stream = None
                return
            self.recording = True
        # Chime once the mic is open, then start capturing so the chime is never transcribed.
        chime_on = True if self.settings is None else bool(self.settings["chime"])
        if chime_on and self.player is not None:
            try:
                self.player.play_chime("start")
            except Exception as e:
                logs.event(f"dictation: start chime failed: {e!r}")
            time.sleep(0.20)  # chime (~120 ms) + pad finishes before we keep audio
        self._capturing = True
        logs.event("dictation: started")
        self._state()

    def stop(self):
        with self._lock:
            if not self.recording:
                return
            self.recording = False
            self._capturing = False
            st, self._stream = self._stream, None
        try:
            st.stop(); st.close()
        except Exception:
            pass
        self._state()
        chime_on = True if self.settings is None else bool(self.settings["chime"])
        if chime_on and self.player is not None:
            try:
                self.player.play_chime("stop")
            except Exception as e:
                logs.event(f"dictation: stop chime failed: {e!r}")
        audio = np.concatenate(self._frames) if self._frames else np.zeros(0, np.float32)
        logs.event(f"dictation: stopped, {len(audio) / SR:.1f}s of audio")
        threading.Thread(target=self._transcribe, args=(audio,), daemon=True).start()

    def _transcribe(self, audio):
        if len(audio) < SR * 0.3:
            logs.event("dictation: too short, ignored")
            return
        for _ in range(100):
            if self._model is not None:
                break
            time.sleep(0.1)
        if self._model is None:
            logs.event("dictation: no model")
            return
        t0 = time.time()
        try:
            segs, _ = self._model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
            text = " ".join(s.text.strip() for s in segs).strip()
        except Exception as e:
            logs.event(f"dictation: transcribe failed: {e!r}")
            return
        logs.event(f"dictation: transcribed {len(text)} chars in {time.time() - t0:.1f}s")
        if text:
            type_text(text)

    def _state(self):
        if self.on_state:
            try:
                self.on_state()
            except Exception:
                pass
