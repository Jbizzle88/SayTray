"""PiperEngine: one Piper voice loaded once (in-process), serving synthesis requests in order on a worker thread.
Requests carry a read id for cancellation; retries/sub-chunks are queued with priority.
Each WAV is written to <dir>/<name>.wav.part, closed, then atomically renamed before the callback."""
import os, io, wave, threading, dataclasses, time
from .logs import VOICES, event

PUNCT = set(" ,.;:!?'\"-()\u02c8\u02cc\u02d0\u02d1")  # skip spaces, punctuation, stress and length marks


class Noise:
    NORMAL = (0.5, 0.6)
    STRICT = (0.333, 0.4)


class PiperEngine:
    def __init__(self):
        self.voice_name = None
        self._voice = None
        self._want_voice = None
        self._queue = []
        self._cv = threading.Condition()
        self._fields = None
        self._t = threading.Thread(target=self._run, daemon=True, name="piper")
        self._t.start()

    # public API
    def ensure(self, voice_name):
        """Load (or switch to) a voice. Non-blocking; requests queue until it's ready."""
        if not os.path.exists(os.path.join(VOICES, voice_name + ".onnx")):
            return False
        with self._cv:
            if voice_name != self.voice_name and voice_name != self._want_voice:
                self._want_voice = voice_name
                self._cv.notify()
        return True

    def wait_ready(self, timeout=60):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._voice is not None and self._want_voice is None:
                return True
            time.sleep(0.05)
        return False

    def synthesize(self, read, name, text, out_dir, noise, priority, done):
        req = {"read": read, "name": name, "text": text, "dir": out_dir, "noise": noise, "done": done}
        with self._cv:
            if priority:
                self._queue.insert(0, req)
            else:
                self._queue.append(req)
            self._cv.notify()

    def cancel(self, read):
        with self._cv:
            self._queue = [q for q in self._queue if q["read"] != read]

    # internals
    def _config(self, ns, nw):
        from piper import SynthesisConfig
        if self._fields is None:
            self._fields = {f.name for f in dataclasses.fields(SynthesisConfig)}
        want = {"length_scale": 1.0, "noise_scale": ns, "noise_w_scale": nw, "noise_w": nw}
        return SynthesisConfig(**{k: v for k, v in want.items() if k in self._fields})

    def _load(self, name):
        from piper import PiperVoice
        t0 = time.time()
        v = PiperVoice.load(os.path.join(VOICES, name + ".onnx"))
        with wave.open(io.BytesIO(), "wb") as wf:  # warm-up
            v.synthesize_wav("Ready.", wf, syn_config=self._config(*Noise.NORMAL))
        self._voice, self.voice_name = v, name
        event(f"piper voice loaded: {name} in {time.time() - t0:.2f}s")

    def phonemes(self, text):
        try:
            return sum(1 for sent in self._voice.phonemize(text) for ph in sent if ph not in PUNCT)
        except Exception:
            return 0

    def _run(self):
        while True:
            with self._cv:
                while not self._queue and self._want_voice is None:
                    self._cv.wait()
                want = self._want_voice
                req = None if want else self._queue.pop(0)
            if want:
                try:
                    self._load(want)
                except Exception as e:
                    event(f"piper voice load failed: {want}: {e!r}")
                with self._cv:
                    if self._want_voice == want:
                        self._want_voice = None
                continue
            if self._voice is None:
                req["done"](None, "no voice loaded")
                continue
            path = os.path.join(req["dir"], req["name"] + ".wav")
            tmp = path + ".part"
            try:
                with wave.open(tmp, "wb") as wf:
                    self._voice.synthesize_wav(req["text"], wf, syn_config=self._config(*req["noise"]))
                with wave.open(tmp, "rb") as r:
                    secs = r.getnframes() / float(r.getframerate())
                os.replace(tmp, path)
                req["done"]((path, secs, self.phonemes(req["text"])), None)
            except Exception as e:
                event(f"piper synth error {req['name']}: {e!r}")
                req["done"](None, repr(e))
