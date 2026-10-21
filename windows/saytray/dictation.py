"""Push-to-talk dictation: record while the hotkey is held, transcribe locally with faster-whisper
(base.en, CPU int8), type the result at the cursor.

The input stream stays open and keeps ~450 ms of audio. The session itself is every
sample from key-down to key-up, with no duration cap. Long clips are transcribed in
30 s pieces (under one Whisper window). A piece whose transcript does not cover it
is halved and transcribed again, then the pieces are concatenated in order.
"""
import threading, time
import numpy as np
from . import logs
from .preroll import Ring
from .segments import SEGMENT_S, stitch_audio
from .config import coerce_bool
from .selection import insert_dictation

SR = 16000
_PRE_ROLL_S = 0.45
_MIN_LIVE_S = 0.15
_GRACE_S = 0.25          # keep capturing briefly after key-up so the last word is not lost
_IDLE_MIC_S = 20.0       # release the input after this so a headset is not stuck in hands-free mode


def keep_whisper_segment(text, no_speech_prob, avg_logprob):
    """Drop silence hallucinations such as a lone "you" on a quiet slice."""
    if not (text or "").strip():
        return False
    try:
        nsp = float(0 if no_speech_prob is None else no_speech_prob)
    except (TypeError, ValueError):
        nsp = 0.0
    try:
        lp = float(0 if avg_logprob is None else avg_logprob)
    except (TypeError, ValueError):
        lp = 0.0
    if nsp >= 0.6 and lp < -0.5:
        return False
    if nsp >= 0.85:
        return False
    return True


def slice_is_silent(samples, sample_rate):
    """Near-digital silence. Real speech sits well above this."""
    if samples is None or len(samples) == 0:
        return True
    rms = float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=np.float32)))))
    return rms < 0.003


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
        self._open_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()
        self._gen = 0
        self._phase = "idle"  # idle, recording, finalizing
        self._ring = Ring(int(SR * _PRE_ROLL_S))
        self._pre_samples = 0
        self._pressed_at = None
        self._first_live_at = None
        self._closed = False
        self._grace_gen = None
        self._idle_token = None
        self.on_notice = None
        self._model_error = None
        threading.Thread(target=self._load_model, daemon=True, name="whisper-load").start()
        threading.Thread(target=self._open_warm, daemon=True, name="dictation-warm").start()

    def _load_model(self):
        delay = 2.0
        while not self._closed:
            try:
                from faster_whisper import WhisperModel
                t0 = time.time()
                self._model = WhisperModel("base.en", device="cpu", compute_type="int8")
                self._model_error = None
                logs.event(f"dictation: whisper base.en loaded in {time.time() - t0:.1f}s")
                return
            except Exception as e:
                self._model_error = str(e)
                logs.event(f"dictation: model load failed: {e!r}; retrying in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 2, 60.0)

    def _cb(self, indata, frames, t, status):
        samples = indata[:, 0].copy()
        with self._lock:
            self._ring.push(samples)
            if self._capturing:
                if self._first_live_at is None:
                    self._first_live_at = time.monotonic()
                self._frames.append(samples)

    def _stream_ok(self):
        try:
            return self._stream is not None and bool(self._stream.active)
        except Exception:
            return False

    def _open_warm(self):
        with self._open_lock:
            with self._lock:
                if self._closed or self._stream_ok():
                    return False
            import sounddevice as sd
            try:
                stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=self._cb)
                stream.start()
            except Exception as e:
                logs.event(f"dictation: microphone open failed: {e!r}")
                return False
            with self._lock:
                if self._closed:
                    try:
                        stream.stop(); stream.close()
                    except Exception:
                        pass
                    return False
                old, self._stream = self._stream, stream
            if old is not None:
                try:
                    old.stop(); old.close()
                except Exception:
                    pass
            logs.event("dictation: pre-roll microphone running")
            return True

    def start(self):
        pressed = time.monotonic()
        with self._lock:
            if self._closed:
                logs.event("dictation: start ignored, shutting down")
                return
            if self._phase == "recording":
                logs.event("dictation: start ignored, already recording")
                return
            pending = self._grace_gen if self._phase == "grace" else None
        if pending is not None:
            self._end_grace(pending)
        with self._lock:
            if self._closed or self._phase == "recording":
                return
            if self._phase == "finalizing":
                logs.event("dictation: previous session still finalizing; starting a new one")
            self._idle_token = None
            self._gen += 1
            gen = self._gen
            self._phase = "recording"
            self.recording = True
            need_open = not self._stream_ok()
        self._state()
        just_opened = False
        if need_open:
            just_opened = self._open_warm()
        with self._lock:
            if gen != self._gen or self._phase != "recording":
                logs.event(f"dictation: start cancelled gen {gen}")
                return
            if not self._stream_ok():
                self._phase = "idle"
                self.recording = False
                self._capturing = False
                failed = True
            else:
                pre = self._ring.snapshot()
                self._frames = [pre] if pre.size else []
                self._pre_samples = int(pre.size)
                self._pressed_at = pressed
                self._first_live_at = None
                self._capturing = True
                failed = False
                pre_s = pre.size / SR
        if failed:
            logs.event("dictation: microphone not running")
            self._state()
            return
        # Chime after the stream is already up, and without waiting to record.
        # A cold open happened before this call returns to the chime, so the device
        # change and the tone are not in the same moment on a warm microphone.
        chime_ok = self._chime("start")
        if just_opened:
            logs.event("dictation: microphone was just opened before the chime")
        label = {True: "played", False: "FAILED"}.get(chime_ok, "off")
        logs.event(f"dictation: capture gen {gen} chime={label} pre-roll {pre_s * 1000:.0f}ms")
        self._state()

    def stop(self):
        with self._lock:
            if self._phase != "recording":
                return
            gen = self._gen
            self._phase = "grace"
            self._grace_gen = gen
            self.recording = False
        self._state()
        self._chime("stop")
        timer = threading.Timer(_GRACE_S, self._end_grace, args=(gen,))
        timer.daemon = True
        timer.start()

    def _end_grace(self, gen):
        """Finish the hold, including a short tail, and drop that tail from the next pre-roll."""
        with self._lock:
            if self._phase != "grace" or self._grace_gen != gen:
                return
            self._capturing = False
            self._phase = "finalizing"
            frames = self._frames
            self._frames = []
            pre = self._pre_samples
            pressed = self._pressed_at
            first = self._first_live_at
            self._ring.clear()
        self._state()
        audio = np.concatenate(frames) if frames else np.zeros(0, np.float32)
        live = max(0, len(audio) - pre)
        lat = ((first - pressed) * 1000.0) if first is not None and pressed is not None else -1.0
        logs.event(
            f"dictation: stopped gen {gen} audio {len(audio) / SR:.2f}s "
            f"frames {len(frames)} (no duration cap) "
            f"pre-roll {pre / SR * 1000:.0f}ms live {live / SR:.2f}s first-buffer {lat:.0f}ms"
        )
        if live < int(SR * _MIN_LIVE_S):
            logs.event("dictation: too short, ignored")
            with self._lock:
                if self._gen == gen and self._phase == "finalizing":
                    self._phase = "idle"
            self._state()
            self._arm_mic_idle()
            return
        threading.Thread(target=self._finish, args=(audio, gen), daemon=True, name="dictation-stop").start()

    def _arm_mic_idle(self):
        token = time.monotonic()
        self._idle_token = token
        timer = threading.Timer(_IDLE_MIC_S, self._close_if_idle, args=(token,))
        timer.daemon = True
        timer.start()

    def _close_if_idle(self, token):
        with self._lock:
            if self._closed or token != self._idle_token or self._phase != "idle":
                return
            stream = self._stream
            self._stream = None
            self._ring.clear()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            logs.event("dictation: microphone released after idle")

    def _notify(self, message):
        logs.event("dictation: " + message)
        if self.on_notice:
            try:
                self.on_notice(message)
            except Exception:
                pass

    def shutdown(self):
        """Close the microphone and drop the capture. Do not transcribe or type."""
        with self._lock:
            self._closed = True
            self._gen += 1
            self._capturing = False
            self._phase = "idle"
            self.recording = False
            self._frames = []
            stream = self._stream
            self._stream = None
            self._ring.clear()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        logs.event("dictation: shutdown")
        self._state()

    def _finish(self, audio, gen):
        try:
            self._transcribe(audio, gen)
        except Exception as e:
            logs.event(f"dictation: transcribe failed: {e!r}")
        finally:
            with self._lock:
                if self._gen == gen and self._phase == "finalizing":
                    self._phase = "idle"
            self._arm_mic_idle()

    def _chime(self, kind):
        chime_on = True if self.settings is None else coerce_bool(self.settings["chime"], True)
        if not chime_on or self.player is None:
            logs.event(f"dictation: {kind} chime skipped")
            return None
        try:
            ok = self.player.play_chime(kind)
        except Exception as e:
            logs.event(f"dictation: {kind} chime FAILED {e!r}")
            return False
        if ok is False:
            logs.event(f"dictation: {kind} chime FAILED")
            return False
        return True

    def _transcribe(self, audio, gen):
        dur = len(audio) / SR
        if dur < _MIN_LIVE_S:
            logs.event("dictation: too short, ignored")
            return
        for _ in range(100):
            if self._model is not None:
                break
            time.sleep(0.1)
        if self._model is None:
            logs.event("dictation: no model")
            self._notify("Dictation isn't available yet. The speech model is still downloading, or the download failed. SayTray will keep trying.")
            return
        n_slices = max(1, int((dur + SEGMENT_S - 1e-9) // SEGMENT_S))
        logs.event(f"dictation: kept {dur:.2f}s with no duration cap; {n_slices} slices of <={SEGMENT_S:.0f}s")
        t0 = time.time()

        def transcribe_audio(samples):
            if slice_is_silent(samples, SR):
                logs.event(f"dictation: slice {len(samples) / SR:.1f}s skipped (silence)")
                return "", None, None, False
            try:
                # vad off and no conditioning on a previous window: both can drop or
                # rewrite the front of a long clip. Each slice stands on its own.
                segs, _ = self._model.transcribe(
                    samples, language="en", beam_size=1, vad_filter=False,
                    condition_on_previous_text=False,
                )
                segs = [s for s in segs if keep_whisper_segment(
                    getattr(s, "text", ""), getattr(s, "no_speech_prob", 0), getattr(s, "avg_logprob", 0))]
            except Exception as e:
                logs.event(f"dictation: slice {len(samples) / SR:.1f}s failed: {e!r}")
                return "", None, None, True
            text = " ".join(s.text.strip() for s in segs).strip()
            first = float(segs[0].start) if segs else None
            last = float(segs[-1].end) if segs else None
            logs.event(
                f"dictation: request {len(samples) / SR:.1f}s -> {len(text)} chars "
                f"first {first if first is not None else '-'}s last {last if last is not None else '-'}s"
            )
            return text, first, last, False

        def on_resplit(audio_s, first, last):
            logs.event(
                f"dictation: slice {audio_s:.1f}s result did not cover it "
                f"(first {first} last {last}); splitting so the rest is kept"
            )

        # One model call at a time, and the paste happens before the next session's
        # transcript, so rapid holds stay in order.
        with self._transcribe_lock:
            with self._lock:
                if self._closed:
                    logs.event(f"dictation: drop transcript gen {gen} (shut down)")
                    return
            text = stitch_audio(audio, SR, SEGMENT_S, transcribe_audio, on_resplit=on_resplit)
            logs.event(f"dictation: gen {gen} audio {dur:.2f}s transcript {len(text)} chars in {time.time() - t0:.1f}s")
            with self._lock:
                if self._closed:
                    logs.event(f"dictation: drop transcript gen {gen} (shut down)")
                    return
            if text:
                insert_dictation(text)

    def _state(self):
        if self.on_state:
            try:
                self.on_state()
            except Exception:
                pass
