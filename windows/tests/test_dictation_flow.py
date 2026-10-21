"""Spacing, pre-roll, long-clip splits, and chime rewind. No microphone required."""
import collections, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.spacing import apply, merge, join_segments, simulate_inserts
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
check(apply("(note)", "o") == "(note)", "opening punctuation")
check(apply("", "o") == "", "empty text")
check(simulate_inserts(["hello", "there"]) == "hello there", "back to back")
check(simulate_inserts(["hello", "there", "friend"]) == "hello there friend", "three in order")
check(simulate_inserts(["hello\n", "there"]) == "hello\nthere", "after newline")
check(simulate_inserts(["hello ", "there"]) == "hello there", "previous space kept once")
check(simulate_inserts(["hello", ", and more"]) == "hello, and more", "punctuation stays attached")

check(merge("hello there", "friend") == "hello there friend", "new segment appended")
check(merge("hello world", "hello world and more") == "hello world and more", "partial grew")
check(merge("hello world", "hello") == "hello world", "shorter partial does not erase")
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

print(f"dictation flow tests: {passes} passed, {failures} failed")
sys.exit(1 if failures else 0)
