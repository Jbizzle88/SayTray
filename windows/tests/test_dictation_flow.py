"""Spacing, pre-roll, long-clip splits, and chime rewind. No microphone required."""
import collections, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.spacing import apply, merge, join_segments, prepare, simulate_inserts
from saytray.preroll import Ring, split_pcm
from saytray.segments import SEGMENT_S, needs_resplit, stitch_audio
from saytray.player import queue_chime

passes = failures = 0

def check(cond, msg):
    global passes, failures
    if cond:
        passes += 1
    else:
        failures += 1
        print("FAIL:", msg)

check(apply("there", None) == "there", "empty field")
check(apply("there", " ") == "there", "no double space")
check(apply("there", "\n") == "there", "no space after newline")
check(apply("there", "\t") == "there", "no space after tab")
check(apply("there", "o") == " there", "space after a word")
check(apply(" there", "o") == " there", "already spaced")
check(apply(", and", "o") == ", and", "comma")
check(apply(". Next", "o") == ". Next", "period")
check(apply("(note)", "o") == " (note)", "opening parenthesis is spaced")
check(apply('"Stop."', "o") == ' "Stop."', "opening quote is spaced")
check(apply("$5", "o") == " $5", "dollar amount is spaced")
check(apply("” end", "o") == "” end", "closing quote stays attached")
check(apply("", "o") == "", "empty text")
check(simulate_inserts(["hello", "there"]) == "hello there", "back to back")
check(simulate_inserts(["hello", "there", "friend"]) == "hello there friend", "three in order")
check(simulate_inserts(["hello\n", "there"]) == "hello there", "a trailing newline on a phrase is trimmed")
check(prepare("there", "\n") == "there", "no space when the cursor is after a newline")
check(simulate_inserts(["hello ", "there"]) == "hello there", "previous space kept once")
check(simulate_inserts(["hello", ", and more"]) == "hello, and more", "punctuation stays attached")
check(prepare(" there", " ") == "there", "prepare drops a second space")
check(prepare("  there", "o") == " there", "prepare trims then adds one space")
check(prepare("there", "o") == " there", "prepare spaces a bare word")
check(prepare(" \n ", "o") == "", "prepare drops whitespace-only")
check(prepare("hello", None) == "hello", "prepare at empty field")
check(prepare("café — “hi”", "o") == " café — “hi”", "prepare keeps special characters")
check(simulate_inserts(["hello", " there"]) == "hello there", "extra leading space is one space")
check(simulate_inserts(["hello ", " there"]) == "hello there", "no double space when both sides have space")
check(simulate_inserts(["hello", "there", "friend"]) == "hello there friend", "prepare three in order")

check(merge("hello there", "friend") == "hello there friend", "new segment appended")
check(merge("hello world", "hello world and more") == "hello world hello world and more", "shared prefix is kept")
check(merge("hello world", "hello") == "hello world hello", "shorter slice is kept")
check(merge("I", "It is raining.") == "I It is raining.", "prefix slice is not dropped")
check(merge("Yes", "Yes, I agree.") == "Yes Yes, I agree.", "yes is not swallowed")
check(merge("We need the plan. Okay.", "We need") == "We need the plan. Okay. We need", "later slice is not trimmed")
check(merge("Thank you.", "Thank you.") == "Thank you. Thank you.", "repeated sentence is kept twice")
check(merge("", "only") == "only", "empty previous")
check(merge("kept", "") == "kept", "empty incoming")
check(join_segments(["the start of the sentence", "only the end"]) == "the start of the sentence only the end", "long dictation keeps the start")
check(join_segments(["one two", "three four", "five"]) == "one two three four five", "three segments")
check(join_segments(["hello.", "And more"]) == "hello. And more", "sentence boundary gets one space")

ring = Ring(10)
ring.push(np.arange(7, dtype=np.float32))
ring.push(np.arange(100, 107, dtype=np.float32))
snap = ring.snapshot()
check(list(snap) == [4, 5, 6, 100, 101, 102, 103, 104, 105, 106], f"ring keeps the latest samples: {list(snap)}")
ring.clear()
check(ring.snapshot().size == 0, "ring clear")
ring.push(np.arange(20, dtype=np.float32))
check(list(ring.snapshot()) == list(range(10, 20)), f"ring overflow: {list(ring.snapshot())}")

audio = np.arange(1200, dtype=np.float32)
parts = split_pcm(audio, 10, 50)  # 50s * 10 Hz = 500 samples
check([len(p) for p in parts] == [500, 500, 200], f"split lengths: {[len(p) for p in parts]}")
check(np.array_equal(np.concatenate(parts), audio), "split does not drop or reorder samples")
check(len(split_pcm(audio[:100], 10, 50)) == 1, "short clip is one segment")

start = np.zeros(4, np.float32)
stop = np.ones(4, np.float32)
speech = np.full(4, 2, np.float32)
buf = collections.deque([(1, speech, 10), (1, start, 50)])
buf, restarted = queue_chime(buf, (start, stop), start, 3)
check(restarted, "second chime counts as a rewind")
check(buf[0][1] is start and buf[0][2] == 0, "chime rewound to the first sample and plays first")
check(len(buf) == 2 and buf[1][1] is speech and buf[1][2] == 10, f"speech kept behind the chime: {[(id(a), p) for _, a, p in buf]}")
buf, restarted = queue_chime(collections.deque(), (start, stop), stop, 1)
check(not restarted and buf[0][1] is stop and buf[0][2] == 0, "first chime is queued at the start")

# A later partial that replaces the string must not erase the beginning, even across
# dozens of recognizer resets (what a multi-minute hold used to do).
out = ""
seq = ["the beginning stays here"] + [f"segment {i} only" for i in range(40)]
for part in seq:
    out = merge(out, part)
check(out.startswith("the beginning stays here"), f"40 resets keep the start: {out[:60]}")
check("segment 0 only" in out and out.endswith("segment 39 only"), "40 resets keep every segment")

check(not needs_resplit(30, 0.2, 29.5, False, 400), "full slice kept")
check(needs_resplit(30, 18, 29, False, 80), "first word late")
check(needs_resplit(30, 0.2, 4, False, 40), "last word early")
check(needs_resplit(30, None, None, True, 0), "failed empty slice")
check(not needs_resplit(30, None, None, False, 400), "long text without timestamps")
check(not needs_resplit(5, 3, 4.5, False, 10), "short slice accepted")
check(needs_resplit(30, None, None, False, 20), "too little text for 30s")

def captured(seconds, sr=10):
    """Append-only session beside a 450 ms ring. The ring must not eat the session."""
    ring = Ring(max(1, int(sr * 0.45)))
    session = []
    for sec in range(seconds):
        chunk = np.full(sr, sec, np.float32)
        ring.push(chunk)
        session.append(chunk.copy())
    audio = np.concatenate(session)
    return audio, ring.snapshot()

for seconds in (180, 300):
    audio, snap = captured(seconds)
    check(len(audio) == seconds * 10, f"{seconds}s session length")
    check(float(audio[0]) == 0 and float(audio[-1]) == seconds - 1, f"{seconds}s keeps first and last second")
    check(snap.size <= int(10 * 0.45), f"ring stayed a pre-roll during {seconds}s, size {snap.size}")

def covered(seconds):
    """A recognizer that returns only the tail of any slice longer than 10s.
    After halving, the leaf slices tile the whole clip and the text starts at sample 0.
    """
    sr = 10
    audio = np.arange(seconds * sr, dtype=np.float32)
    leaves = []

    def fake(samples):
        dur = len(samples) / sr
        origin = int(samples[0])
        if dur > 10:
            mid = len(samples) // 2
            return f"t{int(samples[mid])}", dur / 2, dur - 0.1, False
        leaves.append((origin, origin + len(samples)))
        return f"t{origin}", 0.1, dur - 0.1, False

    text = stitch_audio(audio, sr, SEGMENT_S, fake)
    leaves.sort()
    cursor = 0
    gaps = []
    for start, end in leaves:
        if start != cursor:
            gaps.append((cursor, start))
        cursor = end
    check(not gaps and cursor == len(audio) and leaves[0][0] == 0, f"{seconds}s leaves cover the clip, gaps {gaps[:3]} end {cursor}")
    tokens = text.split()
    check(tokens[0] == "t0", f"{seconds}s transcript starts at t0: {tokens[:4]}")
    check(f"t{leaves[-1][0]}" in tokens, f"{seconds}s transcript includes the last slice")
    parts = split_pcm(audio, sr, SEGMENT_S)
    check(sum(len(p) for p in parts) == len(audio) and parts[0][0] == 0 and parts[-1][-1] == audio[-1], f"{seconds}s split keeps every sample")

covered(180)
covered(300)

# Five minutes at the Windows dictation rate: no sample dropped, first and last kept.
full = np.arange(5 * 60 * 16000, dtype=np.float32)
pieces = split_pcm(full, 16000, SEGMENT_S)
check(len(pieces) == 10, f"5 min is 10 slices of 30s, got {len(pieces)}")
check(sum(len(p) for p in pieces) == len(full), "5 min split drops nothing")
check(pieces[0][0] == 0 and pieces[-1][-1] == full[-1], "5 min keeps the first and last sample")

# A quiet moment just before a loud edge moves the cut earlier. Loud audio does not.
quiet = np.concatenate([
    np.full(65, 0.5, np.float32),
    np.zeros(33, np.float32),
    np.full(2, 0.5, np.float32),
    np.full(40, 0.5, np.float32),
])
quiet_parts = split_pcm(quiet, 100, 1.0)
check(len(quiet_parts[0]) < 100, f"quiet cut moved earlier: {len(quiet_parts[0])}")
check(np.array_equal(np.concatenate(quiet_parts), quiet), "quiet cut drops nothing")

from saytray.selection import VK_RETURN, split_typing_steps, unicode_events
from saytray.config import backup_unreadable, coerce_bool, coerce_hotkey, sanitize, write_atomic

events = unicode_events("a\r\nb")
check(events == [("u", ord("a")), ("vk", VK_RETURN), ("u", ord("b"))], f"newline is enter, CR skipped: {events}")
grin = unicode_events("😀")
check(grin == [("u", 0xD83D), ("u", 0xDE00)], f"emoji is a surrogate pair: {grin}")
cafe = unicode_events("café")
check(cafe[3] == ("u", ord("é")), f"accented character stays one unit: {cafe}")
long_text = "Hello, world! " * 400
check(len(unicode_events(long_text)) == len(long_text), "long text keeps every character")

bad = sanitize({
    "speed": "fast",
    "chime": "false",
    "start_with_windows": "true",
    "read_hotkey": "not a key",
    "dictate_hotkey": "ctrl+alt+space",
    "speaker": -3,
    "voice": "",
    "extra": "junk",
})
check(bad["speed"] == 1.0, "bad speed falls back")
check(bad["chime"] is False, 'string "false" is not True')
check(coerce_bool("false", True) is False, "coerce_bool rejects the string false")
check(bad["start_with_windows"] is True, "string true is True")
check(bad["read_hotkey"] == "alt+`", f"bad hotkey falls back: {bad['read_hotkey']}")
check(bad["dictate_hotkey"] == "ctrl+alt+space", "good hotkey kept")
check(bad["speaker"] == 0, "negative speaker falls back")
check(bad["voice"] == "en_US-norman-medium", "empty voice falls back")
check(bad["extra"] == "junk", "unknown settings are kept")
check(sanitize({"speaker": 90})["speaker"] == 90, "speaker ids are not capped")
for kept in ("ctrl+alt+ö", "ctrl+shift+page up", "ctrl+num lock", "windows+print screen", "alt gr+space"):
    check(coerce_hotkey(kept, "alt+`") == kept, f"recorded hotkey kept: {kept}")
check(coerce_hotkey("not a key", "alt+`") == "alt+`", "unknown key still falls back")
check(sanitize({"speed": 9, "chime": 0})["speed"] == 2.0, "speed clamps to 2")
check(sanitize({"speed": 0.1})["speed"] == 0.5, "speed clamps to 0.5")
check(sanitize({"chime": False})["chime"] is False, "real false stays false")

import json, tempfile, threading, time
import saytray.selection as sel
import saytray.dictation as dmod
from saytray.dictation import Dictation, keep_whisper_segment, slice_is_silent
from saytray.hotkeys import HotkeySerial
from saytray.logs import rotate_if_big
from saytray.player import markers_after_callback

steps = split_typing_steps(unicode_events("hi\nthere"))
check([s[0] for s in steps] == ["chars", "enter", "chars"], f"newline is its own step: {steps}")
check(steps[1] == ("enter", VK_RETURN), "the newline step is Enter")
wide = split_typing_steps(unicode_events("a" * 33), batch=32)
check([len(s[1]) for s in wide] == [32, 1], "unicode is paced in batches")

class _FakeUser32:
    def __init__(self):
        self.sent = 0
    def SendInput(self, n, arr, size):
        self.sent += 1
        return n

_fake_user = _FakeUser32()
_old_user = sel._user32
_old_wait = sel._wait_mods_released
sel._user32 = lambda: _fake_user
sel._wait_mods_released = lambda timeout=1.0: False
sel._send_unicode("a\nb")
check(_fake_user.sent == 2, f"Enter is skipped while a modifier is held: {_fake_user.sent}")
sel._wait_mods_released = lambda timeout=1.0: True
_fake_user.sent = 0
sel._send_unicode("a\nb")
check(_fake_user.sent == 3, f"Enter is sent once modifiers are up: {_fake_user.sent}")
sel._user32 = _old_user
sel._wait_mods_released = _old_wait
check(sel._wait_mods_released(0.01) in (True, False), "modifier wait returns a bool")

_old_mods = sel._modifiers_down
_old_uni = sel._send_unicode
_old_paste = sel._paste_text
_old_last = sel._last_inserted
sel._last_inserted = "prior"
sel._modifiers_down = lambda: True
sel._send_unicode = lambda text: (_ for _ in ()).throw(OSError("no input"))
sel._paste_text = lambda text: (_ for _ in ()).throw(OSError("clipboard unavailable"))
sel.insert_dictation("hello")
check(sel._last_inserted == "prior", "a failed insert does not move the spacing cursor")
sel._modifiers_down = _old_mods
sel._send_unicode = _old_uni
sel._paste_text = _old_paste
sel._last_inserted = _old_last

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "settings.json")
    write_atomic(path, {"voice": "en_US-norman-medium", "extra": 1})
    check(json.load(open(path, encoding="utf-8"))["extra"] == 1, "atomic write keeps unknown keys")
    check(not os.path.exists(path + ".tmp"), "atomic write removes the temp file")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    bak = backup_unreadable(path)
    check(bak.endswith(".bad") and not os.path.exists(path), f"corrupt settings are moved aside: {bak}")
    check("not json" in open(bak, encoding="utf-8").read(), "the backup keeps the corrupt bytes")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[]")
    bak2 = backup_unreadable(path)
    check(".bad." in os.path.basename(bak2) and os.path.exists(bak), "a second corrupt file does not overwrite the first backup")
    logp = os.path.join(d, "events.log")
    with open(logp, "w", encoding="utf-8") as fh:
        fh.write("secret dictated sentence")
    check(rotate_if_big(logp, limit=8), "a full log rotates")
    check(open(logp + ".1", encoding="utf-8").read() == "secret dictated sentence", "rotation keeps one backup")
    check(not os.path.exists(logp), "the live log starts fresh")

check(not keep_whisper_segment("you", 0.9, -1.0), "high no-speech probability is dropped")
check(not keep_whisper_segment("you", 0.7, -0.6), "quiet low-confidence you is dropped")
check(keep_whisper_segment("hello there", 0.2, -0.2), "normal speech is kept")
check(slice_is_silent(np.zeros(1600, np.float32), 16000), "digital silence is skipped")
check(not slice_is_silent(np.full(1600, 0.05, np.float32), 16000), "audible audio is kept")

pending, idle = markers_after_callback(2, 0, True)
check(pending == 2 and idle is False, "a finished chime does not mark speech idle")
pending, idle = markers_after_callback(1, 1, False)
check(pending == 0 and idle is True, "idle when the last speech buffer finishes")
pending, idle = markers_after_callback(2, 1, True)
check(pending == 1 and idle is False, "speech still buffered stays active")

order = []
started = threading.Event()
serial = HotkeySerial()
def _start_key():
    started.set()
    time.sleep(0.05)
    order.append("start")
def _stop_key():
    started.wait(1)
    order.append("stop")
serial.submit(_start_key)
serial.submit(_stop_key)
deadline = time.time() + 1
while len(order) < 2 and time.time() < deadline:
    time.sleep(0.01)
check(order == ["start", "stop"], f"hotkey down and up stay in order: {order}")

class _Seg:
    text = "second phrase"
    start = 0.1
    end = 0.4
    no_speech_prob = 0.1
    avg_logprob = -0.2

class _Model:
    def transcribe(self, samples, **kw):
        return [_Seg()], None

inserted = []
old_insert = dmod.insert_dictation
dmod.insert_dictation = inserted.append
try:
    fresh = Dictation.__new__(Dictation)
    fresh._closed = False
    fresh._gen = 2
    fresh._lock = threading.Lock()
    fresh._transcribe_lock = threading.Lock()
    fresh._model = _Model()
    fresh._notify = lambda message: None
    audio = np.full(3200, 0.1, np.float32)
    fresh._transcribe(audio, 1)
    check(inserted == ["second phrase"], f"an older dictation still types when a newer one has started: {inserted}")
    inserted.clear()
    fresh._closed = True
    fresh._transcribe(audio, 1)
    check(inserted == [], "shutdown drops the transcript")
finally:
    dmod.insert_dictation = old_insert

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
guard_files = [
    "windows/saytray/speaker.py",
    "windows/saytray/session.py",
    "windows/saytray/player.py",
    "macos/Sources/SayTray/Speaker.swift",
    "macos/Sources/SayTray/ReadSession.swift",
    "macos/Sources/SayTray/Player.swift",
]
for rel in guard_files:
    body = open(os.path.join(root, rel), encoding="utf-8").read()
    check("--- RAW ---" not in body and "SCALARS" not in body, f"{rel} does not store the read text")
    check("| {s.text}" not in body and "| \\(s.text)" not in body, f"{rel} does not log the chunk text")
mac_app = open(os.path.join(root, "macos/Sources/SayTray/App.swift"), encoding="utf-8").read()
check("#if DEBUG" in mac_app and "debugDictate" in mac_app, "macOS debug triggers are debug-only")
win_app = open(os.path.join(root, "windows/saytray/app.py"), encoding="utf-8").read()
check('SAYTRAY_DEBUG' in win_app, "Windows debug trigger is gated")

print(f"dictation flow tests: {passes} passed, {failures} failed")
sys.exit(1 if failures else 0)
