"""Player: one persistent output stream fed from a sample queue, items strictly in order.

Each chunk (Piper WAV or SAPI fallback WAV) gets ~220 ms of silence appended *before* the WSOLA
time-stretch (pitch preserved), so the stretcher's tail loss eats silence, not speech. Audio is pushed
into a continuous buffer, so nothing is cut by per-chunk stream start/stop or device latency."""
import os, threading, wave, time, queue, collections
import numpy as np
from . import logs, sapi

def markers_after_callback(pending, finished_speech, speech_left):
    """A finished chime is not speech. Idle only when no speech is still buffered."""
    pending = max(0, pending - finished_speech)
    idle = finished_speech > 0 and pending == 0 and not speech_left
    return pending, idle


def queue_chime(buf, chimes, arr, gen):
    """Put the preloaded chime at the front, rewound to the first sample.

    An in-progress copy of the same tone is dropped and replaced, so a second
    press restarts the sound instead of waiting behind one that may not be heard.
    Speech buffers stay behind the chime, in their previous order.
    """
    restarted = any(a is arr for _, a, _ in buf)
    kept = collections.deque((g, a, p) for g, a, p in buf if all(a is not c for c in chimes))
    kept.appendleft((gen, arr, 0))
    return kept, restarted


SR = 22050
PAD_S = 0.22
LEAD_S = 0.35   # silence before the first chunk of a read (device wake-up)
EDGE_S = 0.05   # small pad before stretching so WSOLA keeps the first samples


def _load(path):
    with wave.open(path, "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def _resample(a, sr):
    if sr == SR or len(a) == 0:
        return a
    n = int(round(len(a) * SR / sr))
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


def stretch(a, speed):
    """WSOLA time-stretch; output length is corrected to exactly len(a)/speed."""
    if abs(speed - 1.0) < 0.01 or len(a) < 2048:
        return a
    from audiotsm import wsola
    from audiotsm.io.array import ArrayReader, ArrayWriter
    writer = ArrayWriter(channels=1)
    wsola(channels=1, speed=speed).run(ArrayReader(a.reshape(1, -1)), writer)
    out = writer.data.reshape(-1).astype(np.float32)
    want = int(round(len(a) / speed))
    if len(out) < want:
        out = np.concatenate([out, np.zeros(want - len(out), np.float32)])
    return out[:want]


def prepare(a, sr, speed, lead=0.0):
    a = _resample(a, sr)
    a = np.concatenate([np.zeros(int(SR * EDGE_S), np.float32), a, np.zeros(int(SR * PAD_S * max(1.0, speed)), np.float32)])
    a = stretch(a, speed)
    if lead > 0:
        a = np.concatenate([np.zeros(int(SR * lead), np.float32), a])
    return a


class Player:
    def __init__(self, settings):
        self.settings = settings
        self._items = queue.Queue()
        self._gen = 0
        self._buf = collections.deque()       # (gen, ndarray, marker_id)
        self._buf_lock = threading.Lock()
        self._pending_markers = 0              # chunks pushed but not fully played
        self._preparing = False
        self._stream = None
        self._stream_lock = threading.Lock()
        self.play_log = None
        self.on_idle = None
        self._chime_pcm = {"start": self._tone("start"), "stop": self._tone("stop")}
        threading.Thread(target=self._run, daemon=True, name="player").start()
        # keep the output stream open (feeding silence when idle) so HDMI/Bluetooth outputs never sleep
        threading.Thread(target=self._keepalive, daemon=True, name="player-keepalive").start()

    def _keepalive(self):
        while True:
            try:
                self._ensure_stream()
            except Exception as e:
                logs.event(f"player: keepalive stream error: {e!r}")
                self._stream = None
            time.sleep(2.0)

    @property
    def idle(self):
        return self._items.empty() and not self._preparing and self._pending_markers == 0


    def _tone(self, kind):
        """Precomputed start (rising) or stop (falling) tone. The same array is replayed."""
        import math
        if kind == "start":
            dur, f0, f1, amp = 0.12, 520.0, 780.0, 0.18
        else:
            dur, f0, f1, amp = 0.10, 620.0, 380.0, 0.10
        n = int(SR * dur)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        freq = f0 + (f1 - f0) * (t / dur)
        phase = 2 * math.pi * np.cumsum(freq) / SR
        env = np.sin(np.pi * np.clip(t / dur, 0, 1)).astype(np.float32)
        tone = (amp * env * np.sin(phase)).astype(np.float32)
        pad = np.zeros(int(SR * 0.02), np.float32)
        return np.concatenate([pad, tone, pad])

    def _is_chime(self, arr):
        return any(arr is clip for clip in self._chime_pcm.values())

    def play_chime(self, kind="start"):
        """Restart the preloaded tone at the head of the output buffer so a rapid repeat is heard."""
        logs.event(f"chime {kind}: requested")
        arr = self._chime_pcm.get(kind)
        if arr is None:
            logs.event(f"chime {kind}: started=False no preloaded buffer")
            return False
        thread = threading.current_thread().name
        try:
            self._ensure_stream()
        except Exception as e:
            logs.event(f"chime {kind}: FAILED stream on thread {thread}: {e!r}")
            return False
        with self._buf_lock:
            self._buf, restarted = queue_chime(self._buf, tuple(self._chime_pcm.values()), arr, self._gen)
        logs.event(f"chime {kind}: {'rewound' if restarted else 'queued'} preloaded {len(arr)} samples on thread {thread}")
        return True

    def new_generation(self):
        self._gen += 1
        return self._gen

    def enqueue(self, items, gen):
        for it in items:
            self._items.put((gen, it))

    def stop(self):
        self._gen += 1
        try:
            while True:
                self._items.get_nowait()
        except queue.Empty:
            pass
        with self._buf_lock:
            # Speech stops; a dictation chime already in the buffer keeps playing.
            self._buf = collections.deque(item for item in self._buf if self._is_chime(item[1]))
            self._pending_markers = 0

    def _log(self, s):
        if self.play_log:
            logs.append(s, self.play_log)

    # audio callback: pull continuously from the buffer, silence when empty
    def _callback(self, outdata, frames, t, status):
        out = outdata[:, 0]
        filled = 0
        finished = 0
        with self._buf_lock:
            while filled < frames and self._buf:
                gen, arr, pos = self._buf[0]
                take = min(frames - filled, len(arr) - pos)
                out[filled:filled + take] = arr[pos:pos + take]
                filled += take
                pos += take
                if pos >= len(arr):
                    self._buf.popleft()
                    if not self._is_chime(arr):
                        finished += 1
                else:
                    self._buf[0] = (gen, arr, pos)
            speech_left = any(not self._is_chime(item[1]) for item in self._buf)
            self._pending_markers, idle_now = markers_after_callback(self._pending_markers, finished, speech_left)
        out[filled:] = 0
        if idle_now and self.on_idle and self._items.empty() and not self._preparing:
            threading.Thread(target=self.on_idle, daemon=True).start()

    def _ensure_stream(self):
        import sounddevice as sd
        from .portaudio import lock as portaudio_lock
        # Held across open so dictation cannot restart PortAudio underneath this stream.
        with portaudio_lock():
            with self._stream_lock:
                self._ensure_stream_locked(sd)

    def _ensure_stream_locked(self, sd):
        if self._stream is None or not self._stream.active:
            try:
                if self._stream is not None:
                    self._stream.close()
            except Exception:
                pass
            self._stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32", callback=self._callback,
                                           latency="high", blocksize=1024)
            self._stream.start()
            logs.event(f"player: output stream opened on {sd.query_devices(kind='output')['name']}")

    def _run(self):
        while True:
            gen, (kind, val) = self._items.get()
            if gen != self._gen:
                continue
            self._preparing = True
            try:
                if kind == "file":
                    path = val
                    self._log("PLAY " + os.path.basename(path))
                else:
                    path = os.path.join(os.path.dirname(self.play_log or logs.last_dir()), f"sapi-{time.time_ns()}.wav")
                    self._log(f"PLAY system: {len(val)} chars")
                    sapi.render(val, path, self.settings["sapi_voice"])
                a, sr = _load(path)
                with self._buf_lock:
                    starting = not self._buf      # nothing queued: this is the start of a readout
                a = prepare(a, sr, float(self.settings["speed"]), LEAD_S if starting else 0.0)
                self._ensure_stream()
                with self._buf_lock:
                    if gen == self._gen:
                        self._buf.append((gen, a, 0))
                        self._pending_markers += 1
            except Exception as e:
                logs.event(f"player error: {e!r}")
                self._log(f"ERROR {e!r}")
                self._stream = None
            finally:
                self._preparing = False
            # stay at most ~1 chunk ahead so stop() is instant and speed changes apply quickly
            while self._pending_markers > 1 and gen == self._gen:
                time.sleep(0.02)
