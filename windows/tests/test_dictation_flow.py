"""Spacing, pre-roll, long-clip splits, and chime rewind. No microphone required."""
import collections, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.spacing import apply, merge, join_segments, simulate_inserts
from saytray.preroll import Ring, split_pcm
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

print(f"dictation flow tests: {passes} passed, {failures} failed")
sys.exit(1 if failures else 0)
