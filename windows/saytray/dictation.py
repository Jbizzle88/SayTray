"""Push-to-talk dictation: record while the hotkey is held, transcribe locally with faster-whisper
(base.en, CPU int8), type the result at the cursor.

start() and stop() return immediately. The microphone opens on a worker after the start chime,
and a generation counter drops that open if the key is released during the chime or if a new
hold begins while the previous transcript is still running.
"""
import threading, time
import numpy as np
from . import logs
from .selection import type_text

SR = 16000
_CHIME_LEAD = 0.16  # start tone is ~120 ms; wait so the mic does not cut it off or transcribe it


class Dictation:
    def __init__(self, player=None, settings=None):
        self._model = None
        self._stream = None
        self._frames = []
        self._capturing = False
        self.recording = False
        self.on_state = None
        self.player = player
        self.settings = settings
        self._lock = threading.Lock()
        self._transcribe_lock = threading.Lock()
        self._gen = 0
        self._phase = "idle"  # idle, arming, recording, finalizing
        self._mic_closed = threading.Event()
        self._mic_closed.set()
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
        if not self._capturing:
            return
        chunk = indata[:, 0].copy()
        with self._lock:
            if self._capturing:
                self._frames.append(chunk)

    def start(self):
        with self._lock:
            if self._phase in ("arming", "recording"):
                logs.event(f"dictation: start ignored, already {self._phase}")
                return
            if self._phase == "finalizing":
                logs.event("dictation: previous session still finalizing; starting a new one")
            self._gen += 1
            gen = self._gen
            self._phase = "arming"
            self.recording = True
            self._capturing = False
            self._frames = []
        self._state()
        logs.event(f"dictation: arming gen {gen}")
        threading.Thread(target=self._arm, args=(gen,), daemon=True, name="dictation-arm").start()

    def _arm(self, gen):
        played = self._chime("start")
        if played:
            time.sleep(_CHIME_LEAD)
        with self._lock:
            if gen != self._gen or self._phase != "arming":
                logs.event(f"dictation: arm cancelled gen {gen}")
                return
        self._open_mic(gen)

    def _open_mic(self, gen):
        import sounddevice as sd
        if not self._wait_mic(gen):
            return
        try:
            stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=self._cb)
            stream.start()
        except Exception as e:
            logs.event(f"dictation: microphone open failed: {e!r}")
            with self._lock:
                if gen == self._gen and self._phase == "arming":
                    self._phase = "idle"
                    self.recording = False
                    self._capturing = False
            self._state()
            return
        with self._lock:
            if gen != self._gen or self._phase != "arming":
                leftover = stream
            else:
                self._stream = stream
                self._mic_closed.clear()
                self._capturing = True
                self._phase = "recording"
                leftover = None
        if leftover is not None:
            self._close_stream(leftover)
            logs.event(f"dictation: discarded microphone opened after cancel gen {gen}")
            return
        logs.event(f"dictation: started gen {gen}")
        self._state()

    def _wait_mic(self, gen):
        deadline = time.time() + 1.0
        while not self._mic_closed.is_set():
            with self._lock:
                if gen != self._gen or self._phase != "arming":
                    logs.event(f"dictation: openMic skipped gen {gen}")
                    return False
            if time.time() > deadline:
                logs.event("dictation: previous microphone did not close in time")
                return True
            self._mic_closed.wait(0.05)
        return True

    def stop(self):
        with self._lock:
            if self._phase == "arming":
                self._gen += 1
                self._phase = "idle"
                self.recording = False
                self._capturing = False
                kind = "arm"
            elif self._phase == "recording":
                gen = self._gen
                self._phase = "finalizing"
                self.recording = False
                self._capturing = False
                stream, self._stream = self._stream, None
                frames, self._frames = self._frames, []
                kind = "record"
            else:
                return
        self._state()
        self._chime("stop")
        if kind == "arm":
            logs.event("dictation: cancelled before microphone opened")
            return
        threading.Thread(target=self._finish, args=(stream, frames, gen), daemon=True, name="dictation-stop").start()

    def _finish(self, stream, frames, gen):
        self._close_stream(stream)
        audio = np.concatenate(frames) if frames else np.zeros(0, np.float32)
        logs.event(f"dictation: stopped gen {gen}, {len(audio) / SR:.1f}s of audio")
        try:
            self._transcribe(audio)
        finally:
            with self._lock:
                if self._gen == gen and self._phase == "finalizing":
                    self._phase = "idle"

    def _close_stream(self, stream):
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass
        self._mic_closed.set()

    def _chime(self, kind):
        chime_on = True if self.settings is None else bool(self.settings["chime"])
        if not chime_on or self.player is None:
            return False
        try:
            ok = self.player.play_chime(kind)
        except Exception as e:
            logs.event(f"dictation: {kind} chime failed: {e!r}")
            return False
        if ok is False:
            logs.event(f"dictation: {kind} chime FAILED")
            return False
        logs.event(f"dictation: {kind} chime started")
        return True

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
        # One model call at a time. A new hold may already be recording while this audio
        # is still transcribing; the next transcript waits instead of using Whisper concurrently.
        with self._transcribe_lock:
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
