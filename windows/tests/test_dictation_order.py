"""Words from several dictations type in order when the audio is real speech.

Older harnesses used amplitudes of 0.001 to 0.003. Those sit on the silence
gate, so only the louder tail was typed. These clips are 0.05 to 0.08.
"""
import os, sys, tempfile, threading
import numpy as np

if not os.environ.get("SAYTRAY_LOG_DIR"):
    os.environ["SAYTRAY_LOG_DIR"] = tempfile.mkdtemp(prefix="saytray-test-logs-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import saytray.dictation as dmod
from saytray.dictation import Dictation, SR, slice_is_silent

passes = failures = 0


def check(cond, msg):
    global passes, failures
    if cond:
        passes += 1
    else:
        failures += 1
        print("FAIL:", msg)


check(not slice_is_silent(np.full(1600, 0.05, np.float32), SR), "0.05 is speech")
check(not slice_is_silent(np.full(1600, 0.002, np.float32), SR), "0.002 is above the silence gate")
check(slice_is_silent(np.full(1600, 0.0004, np.float32), SR), "0.0004 is silence")
check(slice_is_silent(np.zeros(1600, np.float32), SR), "zeros are silence")


class _Seg:
    def __init__(self, text, n):
        self.text = text
        self.start = 0.0
        self.end = n / SR
        self.no_speech_prob = 0.05
        self.avg_logprob = -0.1


class _Model:
    def __init__(self):
        self.n = 0

    def transcribe(self, samples, **kw):
        self.n += 1
        self.last_kw = kw
        seg = _Seg(f"w{self.n}", len(samples))
        rms = float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=np.float32)))))
        if rms < 0.01:
            seg.no_speech_prob = 0.95
            seg.avg_logprob = -1.2
            seg.text = "noise"
        return [seg], None


inserted = []
notices = []
old_insert = dmod.insert_dictation
dmod.insert_dictation = inserted.append
try:
    fresh = Dictation.__new__(Dictation)
    fresh._closed = False
    fresh._gen = 1
    fresh._lock = threading.Lock()
    fresh._transcribe_lock = threading.Lock()
    fresh._model = _Model()
    fresh._notify = notices.append
    amplitudes = (0.05, 0.06, 0.07, 0.08, 0.05, 0.06)
    for i, amp in enumerate(amplitudes, start=1):
        fresh._gen = i
        fresh._transcribe(np.full(8000, amp, np.float32), i)
    check(inserted == [f"w{i}" for i in range(1, 7)], f"every word types in order: {inserted}")
    fresh._gen = 9
    fresh._transcribe(np.full(8000, 0.05, np.float32), 3)
    check(inserted[-1] == "w7", "an older dictation still types after a newer one has started")
    before = len(inserted)
    fresh._gen = 3
    calls = fresh._model.n
    fresh._transcribe(np.full(8000, 0.002, np.float32), 3)
    check(fresh._model.n == calls + 1 and len(inserted) == before, "quiet audio reaches Whisper and a no-speech result is not typed")
    check(fresh._model.last_kw.get("vad_filter") is True and fresh._model.last_kw.get("temperature") == 0.0,
          f"quiet audio uses VAD and temperature 0: {fresh._model.last_kw}")
    fresh._transcribe(np.zeros(int(SR * 2), np.float32), 3)
    check(any("didn't hear anything" in n for n in notices), f"a longer silence is announced: {notices}")
    fresh._gen = 9
    fresh._transcribe(np.full(11200, 0.002, np.float32), 4)
    check(fresh._model.n == calls + 1 and len(inserted) == before, "a newer tap supersedes an older noise clip")
    fresh._closed = True
    stayed = len(inserted)
    fresh._transcribe(np.full(8000, 0.08, np.float32), 1)
    check(len(inserted) == stayed, "shutdown drops the transcript")
finally:
    dmod.insert_dictation = old_insert

print(f"dictation order tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
