"""Spacing, pre-roll, long-clip splits, and chime rewind. No microphone required."""
import collections, os, sys, tempfile
import numpy as np
if not os.environ.get("SAYTRAY_LOG_DIR"):
    os.environ["SAYTRAY_LOG_DIR"] = tempfile.mkdtemp(prefix="saytray-test-logs-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.spacing import apply, dedupe_boundary, join_overlapped, merge, join_segments, prepare, simulate_inserts
from saytray.preroll import Ring, overlapped_pieces, split_pcm
from saytray.segments import SEGMENT_S, OVERLAP_S, needs_resplit, stitch_audio
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
check(apply('" and', "o") == '" and', "a closing quote stays attached")
check(apply("'", "o") == "'", "a lone quote stays attached")
check(apply("<3", "o") == "<3", "a symbol stays attached")
check(apply("+1", "o") == "+1", "plus stays attached")
check(merge("He said", '"Stop."') == 'He said "Stop."', "opening quote in a sentence")
check(merge("Stop", '" and') == 'Stop" and', "closing quote joins the previous word")
check(merge("See", "(attached)") == "See (attached)", "opening parenthesis in a sentence")
check(merge("price is", "$40") == "price is $40", "dollar amount in a sentence")
check(apply("$5", "o") == " $5", "dollar amount is spaced")
check(apply("¿Qué?", "o") == " ¿Qué?", "opening inverted question mark is spaced")
check(apply("¡Hola!", "o") == " ¡Hola!", "opening inverted exclamation mark is spaced")
check(apply("§1", "o") == " §1", "section sign is spaced")
check(dedupe_boundary("I", "It is raining.") == "It is raining.", "I and It stay separate")
check(dedupe_boundary("the quick brown fox", "brown fox jumps") == "brown fox jumps", "dedupe does not drop words")
check(join_overlapped(["the quick brown fox", "brown fox jumps"]) == "the quick brown fox brown fox jumps", "boundary words are kept")
check(join_overlapped(["the answer is no", "", "No, wait"]) == "the answer is no No, wait", "an empty slice does not drop the next words")
check(join_segments(["I", "It is raining."]) == "I It is raining.", "plain join does not dedupe")
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
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
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

check(OVERLAP_S == 0.0, "slice overlap is off")
clip = np.arange(250, dtype=np.float32)
same = overlapped_pieces(clip, 10, 2.0, 0.0)
plain = split_pcm(clip, 10, 2.0)
check(len(same) == len(plain) and all(np.array_equal(a, b) for a, b in zip(same, plain)), "zero overlap matches a plain cut")
check(sum(len(p) for p in plain) == 250, "a plain cut does not repeat samples")
heard = stitch_audio(
    np.arange(250, dtype=np.float32),
    10,
    2.0,
    lambda samples: (f"s{int(samples[0])}", 0.1, len(samples) / 10 - 0.1, False),
)
check("s0" in heard.split() and heard.split()[0] == "s0", f"stitched text keeps the start: {heard}")
check(join_overlapped(["left side", "left side again"]) == "left side left side again", "stitch join keeps a repeated phrase")

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

from saytray.selection import VK_RETURN, _MOD_WAIT_S, split_typing_steps, text_before_units, unicode_events
from saytray.config import backup_unreadable, coerce_bool, coerce_hotkey, hotkey_ok, hotkey_registerable, read_settings, sanitize, write_atomic

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
from saytray.dictation import Dictation, idle_seconds_for_input, input_releases_quickly, keep_whisper_segment, slice_is_silent, transcript_rejected
from saytray.hotkeys import HotkeySerial
from saytray.logs import event as log_event, logs_dir, purge_legacy_text_logs, rotate_if_big
log_event("dictation: test marker")
_log_path = os.path.join(logs_dir(), "events.log")
check(os.path.abspath(os.path.dirname(_log_path)) == os.path.abspath(os.environ["SAYTRAY_LOG_DIR"]),
      "dictation tests write events.log under SAYTRAY_LOG_DIR")
check("test marker" in open(_log_path, encoding="utf-8").read(), "the test marker is in the temp events log")
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
seen_wait = {}
def _mods_stay_down(timeout=None):
    seen_wait["timeout"] = timeout
    return False
sel._user32 = lambda: _fake_user
sel._wait_mods_released = _mods_stay_down
held = False
try:
    sel._send_unicode("a\nb")
except sel.InputIncomplete as e:
    held = e.sent == 1
check(held and _fake_user.sent == 1, f"Enter waits, and only the text before it is typed while modifiers stay down: sent={_fake_user.sent}")
check(seen_wait.get("timeout") == _MOD_WAIT_S, f"the Enter wait is capped: {seen_wait}")
sel._wait_mods_released = lambda timeout=None: True
_fake_user.sent = 0
check(sel._send_unicode("a\nb") == 2, "a and b are the unicode units; Enter is not one")
check(_fake_user.sent == 3, f"Enter is sent in place once the modifiers come up: {_fake_user.sent}")
sel._user32 = _old_user
sel._wait_mods_released = _old_wait
check(sel._wait_mods_released(0.01) in (True, False), "modifier wait returns a bool")
check(_MOD_WAIT_S == 30, "Enter waits at most about 30 seconds")
check(sel.text_after_units("hello world", 5) == " world", "remainder starts after the typed units")
check(sel.text_before_units("hello world", 5) == "hello", "typed prefix stops at the last full character")
check(sel.text_after_units("a\nb", 1) == "\nb", "a newline is kept when it was not typed")
check(sel.text_after_units("😀x", 2) == "x", "an emoji counts as two units")
check(sel.text_after_units("😀x", 1) == "x", "a split emoji is not typed again")
check(sel.text_before_units("😀x", 1) == "", "a split emoji is not counted as typed")

_old_mods = sel._modifiers_down
_old_uni = sel._send_unicode
_old_paste = sel._paste_text
_old_leave = sel._leave_on_clipboard
_old_notice = sel.on_notice
_old_last = sel._last_inserted
_old_wait2 = sel._wait_mods_released
_old_prev = sel._cursor_previous
try:
    sel._cursor_previous = lambda: None
    sel._last_inserted = "prior"
    sel._modifiers_down = lambda: True
    sel._wait_mods_released = lambda timeout=None: False
    sel._send_unicode = lambda text: (_ for _ in ()).throw(OSError("no input"))
    sel._paste_text = lambda text: (_ for _ in ()).throw(OSError("clipboard unavailable"))
    sel.insert_dictation("hello")
    check(sel._last_inserted == "prior", "a failed insert does not move the spacing cursor")

    pasted = []
    left = []
    notices = []
    sel.on_notice = notices.append
    sel._paste_text = pasted.append
    sel._leave_on_clipboard = left.append
    sel._send_unicode = lambda text: (_ for _ in ()).throw(sel.InputIncomplete(5, "stopped"))
    ok = sel.type_text("hello world")
    check(ok is False and pasted == [], f"paste does not run while the shortcut is held: {pasted}")
    check(left == [" world"], f"the untyped remainder is left on the clipboard: {left}")
    check(any("clipboard" in n.lower() for n in notices), f"the user is told: {notices}")
    sel._last_inserted = "prior"
    sel._send_unicode = lambda text: (_ for _ in ()).throw(sel.InputIncomplete(6, "stopped"))
    sel.insert_dictation("hello world")
    check(sel._last_inserted.endswith("hello") and "world" not in sel._last_inserted, f"a partial type moves the spacing cursor to what was typed: {sel._last_inserted!r}")

    pasted.clear()
    sel._send_unicode = lambda text: (_ for _ in ()).throw(sel.InputIncomplete(5, "stopped"))
    sel._wait_mods_released = lambda timeout=None: True
    ok = sel.type_text("hello world")
    check(ok is True and pasted == [" world"], f"after release, only the remainder is pasted: {pasted}")
finally:
    sel._modifiers_down = _old_mods
    sel._send_unicode = _old_uni
    sel._paste_text = _old_paste
    sel._leave_on_clipboard = _old_leave
    sel.on_notice = _old_notice
    sel._last_inserted = _old_last
    sel._wait_mods_released = _old_wait2
    sel._cursor_previous = _old_prev

_old_block = sel._alt_blocks_unicode
_old_wait_alt = sel._wait_alt_clear
_old_mods3 = sel._modifiers_down
_old_leave3 = sel._leave_on_clipboard
_old_uni3 = sel._send_unicode
_old_paste3 = sel._paste_text
_old_prev3 = sel._cursor_previous
_old_fg = sel._foreground_hwnd
_old_notice3 = sel.on_notice
try:
    left = []
    sent = []
    notices = []
    sel.on_notice = notices.append
    sel._alt_blocks_unicode = lambda: True
    sel._wait_alt_clear = lambda timeout=2.0: False
    sel._modifiers_down = lambda: True
    sel._leave_on_clipboard = left.append
    sel._send_unicode = lambda text: sent.append(text) or len(text)
    ok = sel.type_text("alt held text")
    check(ok is False and sent == [] and left == ["alt held text"], f"Alt alone does not report a typed result: {ok} {sent} {left}")
    check(any("Alt" in n for n in notices), f"the user is told Alt blocked typing: {notices}")
    sel._alt_blocks_unicode = lambda: False
    check(_old_wait_alt(0.4) is True, "typing proceeds once Alt stays up")
    flick = {"n": 0}
    def _flicker():
        flick["n"] += 1
        return flick["n"] > 2
    sel._alt_blocks_unicode = _flicker
    check(_old_wait_alt(0.25, settle=0.1) is False, "Alt autorepeat does not count as a release")
    sel._alt_blocks_unicode = lambda: False
    pasted = []
    sel._modifiers_down = lambda: False
    sel._paste_text = pasted.append
    sel._cursor_previous = lambda: None
    sel._foreground_hwnd = lambda: 7
    sel._remember_insert("Hello there.")
    sel._last_insert_hwnd = 7
    sel.insert_dictation("next words")
    check(pasted == [" next words"], f"the same window's recent insert supplies the leading space: {pasted}")
    pasted.clear()
    sel._last_insert_hwnd = 4
    sel.insert_dictation("next words")
    check(pasted == ["next words"], f"a different window does not reuse that insert: {pasted}")
    pasted.clear()
    sel._last_insert_hwnd = 7
    sel._last_insert_at = time.monotonic() - (sel._LAST_INSERT_S + 5)
    sel.insert_dictation("next words")
    check(pasted == ["next words"], f"an old insert does not supply the leading space: {pasted}")
finally:
    sel._alt_blocks_unicode = _old_block
    sel._wait_alt_clear = _old_wait_alt
    sel._modifiers_down = _old_mods3
    sel._leave_on_clipboard = _old_leave3
    sel._send_unicode = _old_uni3
    sel._paste_text = _old_paste3
    sel._cursor_previous = _old_prev3
    sel._foreground_hwnd = _old_fg
    sel.on_notice = _old_notice3

_seq_block = sel._alt_blocks_unicode
_seq_hold = sel._hold_menu_neutralizer
_seq_rel = sel._release_menu_neutralizer
_seq_lift = sel._lift_alt
_seq_mods = sel._modifiers_down
_seq_menu = sel._menu_open
_seq_dismiss = sel._dismiss_menu
_seq_paste = sel._paste_text
_seq_ctrl = sel._ctrl_down
_seq_notice = sel.on_notice
_seq_leave = sel._leave_on_clipboard
_seq_injected = sel._release_injected_modifiers
_seq_uni = sel._send_unicode
try:
    phase = {"alt": True, "held": False}
    order = []
    notices = []
    pasted = []
    released = []
    sel.on_notice = notices.append
    def _hold():
        order.append(("hold", phase["alt"]))
        phase["held"] = True
        return True
    def _blocks():
        if phase["held"] and phase["alt"]:
            order.append(("alt-up", True))
            phase["alt"] = False
        return phase["alt"]
    sel._hold_menu_neutralizer = _hold
    sel._release_menu_neutralizer = lambda: order.append("neutralizer-up") or True
    sel._lift_alt = lambda: order.append("lift")
    sel._alt_blocks_unicode = _blocks
    sel._modifiers_down = lambda: False
    sel._menu_open = lambda: False
    sel._dismiss_menu = lambda: False
    sel._ctrl_down = lambda: False
    sel._paste_text = lambda text: pasted.append(text) or True
    sel._release_injected_modifiers = lambda: released.append("mods")
    ok = sel.type_text("held alt phrase")
    check(ok is True and pasted == ["held alt phrase"], f"Ctrl released and Alt held still types: {ok} {pasted}")
    check(("hold", True) in order and ("alt-up", True) in order and order.index(("hold", True)) < order.index(("alt-up", True)),
          f"the menu key is held before Alt goes up: {order}")
    check(released == ["mods"], f"injected modifiers are released after that paste: {released}")
    phase["alt"] = True
    phase["held"] = False
    pasted.clear()
    notices.clear()
    left = []
    sel._leave_on_clipboard = left.append
    sel._menu_open = lambda: True
    ok = sel.type_text("menu ate it")
    check(ok is False and pasted == [] and left == ["menu ate it"], f"an open window menu is not reported as typed: {ok} {pasted} {left}")
    check(any("menu" in n.lower() for n in notices), f"the menu swallow is announced: {notices}")
    sel._menu_open = lambda: False
    sel._alt_blocks_unicode = lambda: False
    sel._modifiers_down = lambda: True
    sel._ctrl_down = lambda: True
    sel._send_unicode = lambda text: len(text)
    released.clear()
    ok = sel.type_text("while held")
    check(ok is True and released == [], f"a physically held Ctrl is not released out from under the hotkey: {ok} {released}")
finally:
    sel._alt_blocks_unicode = _seq_block
    sel._hold_menu_neutralizer = _seq_hold
    sel._release_menu_neutralizer = _seq_rel
    sel._lift_alt = _seq_lift
    sel._modifiers_down = _seq_mods
    sel._menu_open = _seq_menu
    sel._dismiss_menu = _seq_dismiss
    sel._paste_text = _seq_paste
    sel._ctrl_down = _seq_ctrl
    sel.on_notice = _seq_notice
    sel._leave_on_clipboard = _seq_leave
    sel._release_injected_modifiers = _seq_injected
    sel._send_unicode = _seq_uni

class _Clip:
    def __init__(self):
        self.value = "OLD"
    def paste(self):
        return self.value
    def copy(self, value):
        self.value = value

_old_clip = sel.pyperclip
_old_board = sel.keyboard
_old_landed = sel._paste_landed
_old_sleep = sel.time.sleep
_old_injected = sel._release_injected_modifiers
try:
    clip = _Clip()
    sel.pyperclip = clip
    sel.keyboard = type("Keys", (), {"send": lambda self, combo: None, "release": lambda self, name: None})()
    sel.time.sleep = lambda _seconds: None
    sel._release_injected_modifiers = lambda: None
    sel._paste_landed = lambda text: False
    check(sel._paste_text("dictated words") is False and clip.value == "dictated words",
          f"a swallowed paste stays on the clipboard: {clip.value}")
    clip.value = "OLD"
    sel._paste_landed = lambda text: True
    check(sel._paste_text("dictated words") is True and clip.value == "OLD",
          f"a paste that lands restores the previous clipboard: {clip.value}")
finally:
    sel.pyperclip = _old_clip
    sel.keyboard = _old_board
    sel._paste_landed = _old_landed
    sel.time.sleep = _old_sleep
    sel._release_injected_modifiers = _old_injected

import saytray.logs as _slog
_cursor_events = []
_old_cursor_log = _slog.event
_slog.event = _cursor_events.append
sel._cursor_fault_logged = False
try:
    _cursor_read = sel._cursor_previous()
finally:
    _slog.event = _old_cursor_log
check(_cursor_read is None and any("cursor read failed (" in e for e in _cursor_events), f"a failed cursor read is logged once: {_cursor_events}")
sel._cursor_fault_logged = False

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
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    data, should = read_settings(path)[:2]
    check(data == {} and should is True and os.path.exists(path + ".bad"), "bad JSON is moved aside and will be rewritten")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[1, 2]")
    data, should = read_settings(path)[:2]
    check(data == {} and should is True and not os.path.exists(path), "JSON that is not an object is moved aside")
    blocked = os.path.join(d, "locked.json")
    os.mkdir(blocked)
    with open(os.path.join(blocked, "keep.txt"), "w", encoding="utf-8") as fh:
        fh.write("stay")
    data, should = read_settings(blocked)[:2]
    check(data == {} and should is False, "a read error uses in-memory defaults and does not rewrite")
    check(not os.path.exists(blocked + ".bad") and open(os.path.join(blocked, "keep.txt"), encoding="utf-8").read() == "stay", "a read error does not move the file")
    missing, should, missing_notice = read_settings(os.path.join(d, "missing.json"))
    check(missing_notice is None, "a missing settings file is not announced as corrupt")
    check(missing == {} and should is True, "a missing settings file is not treated as corrupt")
    for name in ("events.log", "events.log.1", "guard.log", "guard.log.1"):
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write("old dictated sentence")
    last = os.path.join(d, "last")
    os.makedirs(last)
    with open(os.path.join(last, "clip.wav"), "wb") as fh:
        fh.write(b"RIFF")
    with open(os.path.join(last, "input.txt"), "w", encoding="utf-8") as fh:
        fh.write("secret")
    with open(os.path.join(last, "play.log"), "w", encoding="utf-8") as fh:
        fh.write("played")
    with open(os.path.join(last, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("keep")
    check(purge_legacy_text_logs(d) is True, "the first 1.1.0 launch purges old text logs")
    check(os.path.exists(os.path.join(d, ".purged-1.1.0")), "purge leaves a marker")
    check(not any(os.path.exists(os.path.join(d, name)) for name in ("events.log", "guard.log.1")), "old logs are gone")
    check(not os.path.exists(os.path.join(last, "clip.wav")) and not os.path.exists(os.path.join(last, "input.txt")), "old wavs and input notes are gone")
    check(open(os.path.join(last, "notes.txt"), encoding="utf-8").read() == "keep", "unrelated files in last/ stay")
    with open(os.path.join(d, "events.log"), "w", encoding="utf-8") as fh:
        fh.write("newer")
    check(purge_legacy_text_logs(d) is False and open(os.path.join(d, "events.log"), encoding="utf-8").read() == "newer", "purge runs once")
    logp = os.path.join(d, "events.log")
    with open(logp, "w", encoding="utf-8") as fh:
        fh.write("secret dictated sentence")
    check(rotate_if_big(logp, limit=8), "a full log rotates")
    check(open(logp + ".1", encoding="utf-8").read() == "secret dictated sentence", "rotation keeps one backup")
    check(not os.path.exists(logp), "the live log starts fresh")

check(not keep_whisper_segment("you", 0.9, -1.0), "high no-speech probability is dropped")
check(not keep_whisper_segment("you", 0.7, -0.6), "quiet low-confidence you is dropped")
check(keep_whisper_segment("hello there", 0.2, -0.2), "normal speech is kept")
check(not transcript_rejected("Okay, sounds good.", 2.6), "a normal short phrase is not a runaway")
runaway = "E-A-S-A-" + ("M-I-N-" * 40)
check(transcript_rejected(runaway, 2.38), "a 2 second clip of repeated letters is rejected")
check(transcript_rejected("Yes.", 2.0, compression_ratio=3.1), "a high compression ratio is rejected")
check(not keep_whisper_segment(runaway, 0.1, -0.2, audio_s=2.38), "the runaway is not typed")
check(keep_whisper_segment("Okay, sounds good.", 0.1, -0.2, audio_s=2.6), "a real short phrase is kept")
check(slice_is_silent(np.zeros(1600, np.float32), 16000), "digital silence is skipped")
check(not slice_is_silent(np.full(1600, 0.002, np.float32), 16000), "quiet speech above 0.001 is kept")
check(slice_is_silent(np.full(1600, 0.0004, np.float32), 16000), "audio under 0.001 is silence")
check(not slice_is_silent(np.full(1600, 0.05, np.float32), 16000), "audible audio is kept")
from saytray.dictation import classify_input, should_prewarm
check(idle_seconds_for_input("MacBook Pro Microphone") == 3, "a built-in mic is released after about 3 seconds")
check(idle_seconds_for_input("AirPods Pro") == 3, "Bluetooth is released after about 3 seconds")
check(idle_seconds_for_input("Headset (Hands-Free AG Audio)") == 3, "hands-free is released after about 3 seconds")
check(idle_seconds_for_input("Headset (Galaxy Buds2 Pro)") == 3, "a Windows headset name is released after about 3 seconds")
check(idle_seconds_for_input("Headset (Jabra Elite 85t Hands-") == 3, "a truncated headset name is released after about 3 seconds")
check(idle_seconds_for_input("USB Headset") == 3, "a wired headset is released after about 3 seconds")
check(classify_input("Mic", endpoint_id=r"\\?\BTHHFENUM#x") == "hands-free", "BTHHFENUM is hands-free even with a plain name")
check(classify_input("Mic", endpoint_id=r"\\?\BTHENUM#x") == "hands-free", "BTHENUM is hands-free")
check(idle_seconds_for_input("") == 3 and not input_releases_quickly(""), "an unknown input is released after about 3 seconds and is not called hands-free")
check(should_prewarm("wired", False) is True, "a closed wired mic can pre-warm")
check(should_prewarm("hands-free", False) is False, "Bluetooth waits for the main key")
check(should_prewarm("unknown", False) is False, "an unknown input waits for the main key")
check(should_prewarm("wired", True) is False, "an open mic is not pre-warmed again")
check(classify_input("Headset Microphone (Oculus Virtual Audio Device)") == "virtual", "Oculus is virtual, not a wired headset")
check(classify_input("Steam Streaming Microphone") == "virtual", "Steam Streaming is virtual")
check(classify_input("Microphone (Realtek High Definition Audio)") == "wired", "Realtek stays wired")
check(classify_input("Microsoft Sound Mapper - Input") == "pseudo", "the MME sound mapper is not a real microphone")
check(classify_input("Primary Sound Capture Driver") == "pseudo", "the primary capture driver is not a real microphone")
from saytray.dictation import choose_input_index, past_audio_slack, segment_past_audio, model_idle_label, input_open_order, resolve_pinned_index, try_open_input, resample_audio, transcript_rejected
devices = [
    {"index": 0, "name": "Headset Microphone (Oculus Virtual Audio Device)", "max_input_channels": 1},
    {"index": 1, "name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 1},
]
check(choose_input_index(devices, 0) == 1, "a virtual default yields the real microphone")
check(choose_input_index(devices, 1) is None, "a real default is left alone")
mapped = [
    {"index": 0, "name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": "MME"},
    {"index": 1, "name": "Headset Microphone (Oculus Virtual Audio Device)", "max_input_channels": 1, "hostapi": "Windows WASAPI"},
    {"index": 2, "name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 2, "hostapi": "Windows WASAPI"},
    {"index": 3, "name": "Primary Sound Capture Driver", "max_input_channels": 2, "hostapi": "MME"},
]
check(choose_input_index(mapped, 1) == 2, "Oculus as default skips the sound mapper and uses the WASAPI microphone")
oculus_devices = [
    {"index": 0, "name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": "MME"},
    {"index": 1, "name": "Headset Microphone (Oculus Virtual Audio Device)", "max_input_channels": 1, "hostapi": "Windows WASAPI"},
    {"index": 22, "name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 2, "hostapi": "Windows WASAPI", "default_samplerate": 48000},
    {"index": 3, "name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 2, "hostapi": "MME", "default_samplerate": 44100},
]
oculus_order = input_open_order(oculus_devices, 1)
check(oculus_order[:2] == [22, 3], f"Oculus falls through to Realtek WASAPI, then MME: {oculus_order}")
pinned_order = input_open_order(oculus_devices, 1, pinned_index=3)
check(pinned_order[0] == 3 and 22 in pinned_order and 1 not in pinned_order, f"a chosen Realtek mic stays selected: {pinned_order}")
_realtek = "Microphone (Realtek High Definition Audio)"
check(resolve_pinned_index(oculus_devices, 3, _realtek) == 3, "a pinned Realtek mic is still present")
check(resolve_pinned_index(oculus_devices, 99, _realtek) is None, "a missing pin falls back")
check(resolve_pinned_index(oculus_devices, 3, "Other Microphone") is None, "a reused device index is not the pinned mic")
check(input_open_order(oculus_devices, 1, None)[:2] == [22, 3], "with the pin gone, the real default mic is first")
check(len(resample_audio(np.zeros(48000, np.float32), 48000, 16000)) == 16000, "48 kHz capture is resampled to 16 kHz")

class _RateDevice:
    def __init__(self):
        self.opened = []
    def WasapiSettings(self, auto_convert=False):
        return {"auto_convert": auto_convert}
    def InputStream(self, **kw):
        self.opened.append(kw)
        stream = type("Stream", (), {})()
        stream.active = False
        stream.kw = kw
        stream.closed = False
        rate = float(kw.get("samplerate") or 0)
        extra = kw.get("extra_settings")
        device = kw.get("device")
        def start():
            if device == 22 and rate == 16000 and not extra:
                raise OSError("Invalid sample rate")
            if device == 22 and rate not in (16000, 48000):
                raise OSError("Invalid sample rate")
            if device == 22 and rate == 16000 and not (extra or {}).get("auto_convert"):
                raise OSError("Invalid sample rate")
            stream.active = True
        def close():
            stream.closed = True
            stream.active = False
        stream.start = start
        stream.close = close
        return stream

_rate_sd = _RateDevice()
_rate_info = oculus_devices[2]
_published = []
def _remember_rate(rate):
    _published.append(rate)
_orig_start_factory = _rate_sd.InputStream
def _input_stream(**kw):
    stream = _orig_start_factory(**kw)
    orig_start = stream.start
    def start():
        check(_published and _published[-1] == float(kw.get("samplerate") or 0),
              f"the callback rate is published before the stream starts: {_published} {kw.get('samplerate')}")
        orig_start()
    stream.start = start
    return stream
_rate_sd.InputStream = _input_stream
_opened_stream, _opened_rate = try_open_input(_rate_sd, 22, _rate_info, lambda *a, **k: None, announce_rate=_remember_rate)
check(_opened_stream is not None and _opened_stream.active and _opened_rate == 16000 and _rate_sd.opened[0].get("extra_settings"),
      f"WASAPI opens with automatic rate conversion: {_opened_rate} {_rate_sd.opened}")
_rate_sd.opened.clear()
def _no_convert(**kw):
    raise OSError("no converter")
_rate_sd.WasapiSettings = _no_convert
_opened_stream, _opened_rate = try_open_input(_rate_sd, 22, _rate_info, lambda *a, **k: None, announce_rate=_remember_rate)
check(_opened_stream is not None and _opened_stream.active and _opened_rate == 48000,
      f"WASAPI falls back to the device rate: {_opened_rate}")
_mme_stream, _mme_rate = try_open_input(_rate_sd, 3, oculus_devices[3], lambda *a, **k: None, announce_rate=_remember_rate)
check(_mme_stream is not None and _mme_stream.active and _mme_rate == 16000, f"MME opens at 16 kHz: {_mme_rate}")
check(past_audio_slack(1.4) >= 1.0 and not segment_past_audio(2.0, 1.4), "Send it. ending at 2.0s on 1.4s of audio is kept")
check(not segment_past_audio(5.1, 4.16), "Yes. ending at 5.1s on 4.16s of audio is kept")
check(segment_past_audio(18.0, 0.5), "an end far past a short clip is still dropped")
check(model_idle_label(600) == "10 minutes", f"the unload log uses the real idle limit: {model_idle_label(600)}")
check(model_idle_label(90) == "90 seconds", f"a non-whole number of minutes is stated in seconds: {model_idle_label(90)}")
check(should_prewarm("virtual", False) is False, "a virtual mic is not pre-warmed")
from saytray.dictation import _PKEY_DEVICE_BUS, _PKEY_DEVICE_ENUMERATOR, propvariant_size
check(propvariant_size() == 24, f"PROPVARIANT is 24 bytes, got {propvariant_size()}")
check(_PKEY_DEVICE_BUS == ("b3f8fa53-0004-438e-9003-51a46e139bfc", 2), "Bluetooth is read from the endpoint bus path")
check(_PKEY_DEVICE_ENUMERATOR[1] == 24, "the enumerator name is read too")
check("PropVariantClear" in open(os.path.join(os.path.dirname(__file__), "..", "saytray", "dictation.py"), encoding="utf-8").read(), "the property string is freed")

class _Live:
    active = True

def _bare_dictation(kind, active):
    fresh = Dictation.__new__(Dictation)
    fresh._closed = False
    fresh._lock = threading.Lock()
    fresh._open_lock = threading.Lock()
    fresh._phase = "idle"
    fresh._input_kind = kind
    fresh._input_name = "Mic"
    fresh._endpoint_id = ""
    fresh._instance_id = ""
    fresh._stream = _Live() if active else None
    fresh._idle_timer = None
    fresh._idle_token = None
    fresh._modifier_held = False
    fresh._ring = Ring(8)
    return fresh

wired_open = _bare_dictation("wired", True)
opened = [wired_open.warm() for _ in range(20)]
check(opened == [False] * 20 and wired_open._idle_timer is None, "an open wired mic does not re-warm or stack timers")
hands_free = _bare_dictation("hands-free", False)
check(hands_free.warm() is False and hands_free._idle_timer is None, "Bluetooth does not pre-warm")
armed = _bare_dictation("wired", True)
armed._after_open()
first_timer = armed._idle_timer
check(first_timer is not None and first_timer.is_alive(), "the launch open arms one idle timer")
armed._phase = "recording"
before = armed._idle_timer
armed._after_open()
check(armed._idle_timer is before, "a recording open does not replace the idle timer")
armed._phase = "idle"
armed._arm_mic_idle()
second_timer = armed._idle_timer
check(second_timer is not first_timer and first_timer.finished.is_set(), "a new idle timer replaces the previous one")
check(abs(second_timer.interval - 3) < 1e-6, f"the idle window is 3 seconds, not 10 minutes: {second_timer.interval}")
second_timer.cancel()
if first_timer.is_alive():
    first_timer.cancel()

class _Stream:
    def __init__(self):
        self.events = []
        self.active = True
    def stop(self):
        self.events.append("stop")
        self.active = False
    def close(self):
        self.events.append("close")

released = _bare_dictation("wired", False)
stream = _Stream()
released._stream = stream
released._idle_token = 1.0
released._close_if_idle(1.0)
check(released._stream is None and stream.events == ["stop", "close"], f"release stops and closes the input stream: {stream.events}")
held_open = _bare_dictation("hands-free", False)
held_stream = _Stream()
held_open._stream = held_stream
held_open._modifier_held = True
held_open._idle_token = 2.0
held_open._close_if_idle(2.0)
check(held_open._stream is held_stream and held_stream.events == [], "a held modifier does not stop the input stream")
session = _bare_dictation("wired", True)
session.set_modifier_session(True)
check(session._modifier_held and session._idle_timer is None, "a modifier session does not start the release timer")
session._arm_mic_idle()
check(session._idle_timer is None, "idle arming waits while the modifier is held")
session._phase = "recording"
session.set_modifier_session(False)
check(session._idle_timer is None and not session._modifier_held, "letting the modifier go during a hold does not release yet")
session._phase = "idle"
session.set_modifier_session(False)
release_timer = session._idle_timer
check(release_timer is not None and abs(release_timer.interval - 3) < 1e-6, "letting the modifier go releases the mic after 3 seconds")
release_timer.cancel()

early = np.arange(int(16000 * 0.20), dtype=np.float32)
cold = Ring(int(16000 * 0.45))
cold.push(early)
pre = cold.snapshot()
live = np.full(160, 0.5, np.float32)
audio = np.concatenate([pre, live] if pre.size else [live])
check(pre.size == early.size and float(audio[0]) == float(early[0]) and float(audio[pre.size]) == 0.5, "a cold start keeps every sample buffered from engine start")
long_wait = Ring(int(16000 * 0.45))
long_wait.push(np.arange(16000, dtype=np.float32))
snap = long_wait.snapshot()
check(snap.size == int(16000 * 0.45) and float(snap[0]) == 16000 - snap.size, "audio older than the pre-roll is not kept")
check(hotkey_ok("ctrl+alt+ö") and hotkey_ok("ctrl+alt+é"), "a layout-specific hotkey is kept")
import types
_kb = types.ModuleType("keyboard")
def _parse(combo):
    if "ö" in combo or "é" in combo:
        raise ValueError("not on this layout")
    return combo
_kb.parse_hotkey = _parse
import sys as _sys
_prev_kb = _sys.modules.get("keyboard")
_sys.modules["keyboard"] = _kb
try:
    check(hotkey_registerable("ctrl+alt+ö") is False, "a hotkey the layout cannot type is not registered")
    check(hotkey_ok("ctrl+alt+ö") is True, "that hotkey is still saved")
    check(hotkey_registerable("ctrl+alt+space") is True, "a normal hotkey still registers")
finally:
    if _prev_kb is None:
        _sys.modules.pop("keyboard", None)
    else:
        _sys.modules["keyboard"] = _prev_kb

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
    def __init__(self):
        self.kwargs = {}
        self.calls = 0
    def transcribe(self, samples, **kw):
        self.kwargs = kw
        self.calls += 1
        seg = _Seg()
        seg.no_speech_prob = getattr(self, "force_nsp", seg.no_speech_prob)
        seg.avg_logprob = getattr(self, "force_lp", seg.avg_logprob)
        if getattr(self, "force_text", None):
            seg.text = self.force_text
        if getattr(self, "force_end", None):
            seg.end = self.force_end
        return [seg], None

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
    audio = np.full(8000, 0.1, np.float32)
    fresh._transcribe(audio, 1)
    check(inserted == ["second phrase"] and fresh._model.calls == 1, f"an earlier dictation is typed when a newer one has started: {inserted}")
    inserted.clear()
    fresh._model.calls = 0
    fresh._transcribe(audio, 2)
    check(inserted == ["second phrase"], f"the current session still types: {inserted}")
    check(fresh._model.kwargs.get("vad_filter") is True and fresh._model.kwargs.get("temperature") == 0.0,
          f"a short clip uses temperature 0 and the VAD filter: {fresh._model.kwargs}")
    check(fresh._model.kwargs.get("no_speech_threshold") == 0.6, "no_speech_threshold stays on")
    inserted.clear()
    notices = []
    fresh._notify = notices.append
    fresh._gen = 1
    fresh._transcribe(np.zeros(8000, np.float32), 1)
    check(inserted == [], "silence is not typed")
    check(not any("didn't hear anything" in n for n in notices), f"a half-second tap does not notify: {notices}")
    notices.clear()
    fresh._transcribe(np.zeros(32000, np.float32), 1)
    check(inserted == [], "two seconds of silence is not typed")
    check(any("didn't hear anything" in n for n in notices), f"a longer silence tells the user: {notices}")
    inserted.clear()
    fresh._closed = True
    fresh._transcribe(audio, 1)
    check(inserted == [], "shutdown drops the transcript")
    fresh._closed = False
    fresh._gen = 4
    fresh._model.force_end = 18.0
    fresh._model.calls = 0
    inserted.clear()
    fresh._transcribe(np.full(8000, 0.1, np.float32), 4)
    check(inserted == [] and fresh._model.calls == 1, "a timestamp past the audio is not typed")
    calls = fresh._model.calls
    fresh._gen = 6
    fresh._transcribe(np.full(11200, 0.002, np.float32), 5)
    check(fresh._model.calls == calls and inserted == [], "a newer tap supersedes an older noise clip")
    fresh._model.force_end = 2.0
    fresh._model.force_text = None
    fresh._model.force_nsp = 0.1
    fresh._gen = 8
    inserted.clear()
    fresh._transcribe(np.full(int(16000 * 1.4), 0.024, np.float32), 8)
    check(inserted == ["second phrase"], f"Send it. is typed when Whisper's end is 2.0s: {inserted}")
    fresh._model.force_end = 5.1
    fresh._gen = 9
    inserted.clear()
    fresh._transcribe(np.full(int(16000 * 4.16), 0.017, np.float32), 9)
    check(inserted == ["second phrase"], f"Yes. is typed when Whisper's end is 5.1s: {inserted}")
    fresh._model.force_end = None
    fresh._gen = 10
    inserted.clear()
    calls = fresh._model.calls
    fresh._transcribe(np.full(int(16000 * 1.45), 0.0025, np.float32), 10)
    check(fresh._model.calls == calls + 1 and inserted == ["second phrase"], f"quiet speech is transcribed and typed: {inserted}")
    check(fresh._model.kwargs.get("vad_filter") is True and fresh._model.kwargs.get("temperature") == 0.0,
          f"quiet speech uses VAD and temperature 0: {fresh._model.kwargs}")
    fresh._model.force_nsp = 0.95
    fresh._model.force_lp = -1.0
    fresh._model.force_text = "E-A-S-A."
    fresh._gen = 11
    inserted.clear()
    notices.clear()
    fresh._transcribe(np.full(int(16000 * 3.29), 0.0018, np.float32), 11)
    check(inserted == [], "a quiet clip Whisper marks as no-speech is not typed")
    check(any("didn't recognize any words" in n for n in notices), f"no recognized words is announced: {notices}")
    check(fresh._model.kwargs.get("vad_filter") is True, "a 3s clip still uses the VAD filter")
    fresh._model.force_nsp = 0.1
    fresh._model.force_lp = -0.2
    fresh._model.force_text = "E-A-S-A-" + ("M-I-N-" * 40)
    fresh._gen = 13
    inserted.clear()
    fresh._transcribe(np.full(int(16000 * 2.38), 0.02, np.float32), 13)
    check(inserted == [], "a repeated hallucination from a short clip is not typed")
    fresh._model.force_nsp = 0.1
    fresh._model.force_lp = -0.2
    fresh._model.force_text = None
    fresh._model.force_end = None
    fresh._gen = 12
    inserted.clear()
    fresh._model = None
    slept = {"n": 0}
    _old_sleep = dmod.time.sleep
    def _sleep_until_ready(seconds):
        slept["n"] += 1
        if slept["n"] >= 150:
            fresh._model = _Model()
    dmod.time.sleep = _sleep_until_ready
    try:
        fresh._transcribe(np.full(8000, 0.1, np.float32), 12)
    finally:
        dmod.time.sleep = _old_sleep
    check(slept["n"] >= 150 and inserted == ["second phrase"], f"the first dictation waits past 10s for the model: {slept['n']} {inserted}")
    fresh._model = None
    fresh._gen = 20
    fresh._model_loading = False
    fresh._model_lock = None
    inserted.clear()
    waited = time.time()
    fresh._transcribe(np.full(8000, 0.1, np.float32), 1)
    check(inserted == [] and time.time() - waited < 2, f"a clip still waiting on the model is not typed into a newer session: {inserted}")
finally:
    dmod.insert_dictation = old_insert

def _open_while_playing(stream):
    sd = types.ModuleType("sounddevice")
    sd._initialized = True
    events = []
    sd._terminate = lambda: events.append("terminate")
    sd._initialize = lambda: events.append("initialize")
    devices = [
        {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Headset Microphone (Oculus Virtual Audio Device)", "max_input_channels": 1, "hostapi": 1},
        {"name": "Microphone (Realtek High Definition Audio)", "max_input_channels": 2, "hostapi": 1},
    ]
    apis = [
        {"name": "MME", "default_input_device": 0},
        {"name": "Windows WASAPI", "default_input_device": 1},
    ]
    def query_devices(*args, **kwargs):
        if kwargs.get("kind") == "input":
            return {"name": devices[1]["name"]}
        if args:
            return devices[int(args[0])]
        return list(devices)
    sd.query_devices = query_devices
    sd.query_hostapis = lambda: list(apis)
    sd.default = types.SimpleNamespace(device=(1, 2))
    opened = []
    class _In:
        def __init__(self, **kw):
            self.active = False
            opened.append(kw)
        def start(self):
            self.active = True
        def stop(self):
            self.active = False
        def close(self):
            self.active = False
    sd.InputStream = _In
    prev = sys.modules.get("sounddevice")
    sys.modules["sounddevice"] = sd
    mic = None
    try:
        mic = _bare_dictation("virtual", False)
        mic.player = types.SimpleNamespace(_stream=stream)
        ok = mic._open_warm()
        return ok, events, opened
    finally:
        if prev is None:
            sys.modules.pop("sounddevice", None)
        else:
            sys.modules["sounddevice"] = prev
        if mic is not None and getattr(mic, "_idle_timer", None) is not None:
            mic._idle_timer.cancel()

_play_ok, _play_events, _play_opened = _open_while_playing(types.SimpleNamespace(active=True, closed=False))
check(_play_ok and _play_events == [] and _play_opened and _play_opened[0].get("device") == 2,
      f"opening the mic during playback does not restart PortAudio and skips the mapper: {_play_ok} {_play_events} {_play_opened}")
_stopped_ok, _stopped_events, _stopped_opened = _open_while_playing(types.SimpleNamespace(active=False, closed=False))
check(_stopped_ok and _stopped_events == [] and _stopped_opened,
      f"a stopped output stream still blocks a PortAudio restart: {_stopped_ok} {_stopped_events}")
_idle_ok, _idle_events, _idle_opened = _open_while_playing(None)
check(_idle_ok and _idle_events == ["terminate", "initialize"] and _idle_opened and _idle_opened[0].get("device") == 2,
      f"PortAudio restarts only when no stream is open: {_idle_ok} {_idle_events} {_idle_opened}")

_unload_events = []
_old_unload_log = dmod.logs.event
dmod.logs.event = _unload_events.append
try:
    unloading = _bare_dictation("wired", False)
    unloading._model_lock = threading.Lock()
    unloading._model_token = 1.0
    unloading._model = object()
    unloading._model_loading = False
    unloading._unload_model(1.0)
finally:
    dmod.logs.event = _old_unload_log
check(any("whisper unloaded after 10 minutes idle" in e for e in _unload_events), f"unload log uses the idle limit: {_unload_events}")

_load_seen = []
_loader = _bare_dictation("wired", False)
_loader._model_lock = threading.Lock()
_loader._model = None
_loader._model_loading = False
_loader._model_token = None
_loader._model_timer = None
def _keep_load(token):
    time.sleep(0.05)
    with _loader._model_lock:
        if token != _loader._model_token:
            _loader._model_loading = False
            _load_seen.append("discard")
            return
        _loader._model = "ready"
        _loader._model_loading = False
        _load_seen.append("kept")
_loader._load_model = _keep_load
_loader._ensure_model()
_loader._ensure_model()
time.sleep(0.3)
check(_loader._model == "ready" and _load_seen == ["kept"], f"a second ensure does not discard the load: {_load_seen} {_loader._model}")

class _ReadSpeaker:
    def __init__(self, speaking):
        self.speaking = speaking
        self.stopped = False
    def stop(self):
        self.stopped = True
        self.speaking = False

class _Listen:
    def __init__(self):
        self.drop_preroll = False
        self.started = False
    def start(self):
        self.started = True

from saytray.dictation import begin_dictation
_talking = _ReadSpeaker(True)
_listen = _Listen()
begin_dictation(_talking, _listen)
check(_talking.stopped and _listen.drop_preroll and _listen.started, "dictation stops a read before it listens")
_quiet = _ReadSpeaker(False)
_listen2 = _Listen()
begin_dictation(_quiet, _listen2)
check((not _quiet.stopped) and (not _listen2.drop_preroll) and _listen2.started, "dictation leaves a quiet player alone")

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

import builtins
import saytray.config as cfg
from saytray.config import Settings

def _check_locked_settings():
    """A change after a locked read merges onto the real file instead of replacing it."""
    real_open = builtins.open
    old_path = cfg.PATH
    try:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            saved = {"speed": 1.6, "dictate_hotkey": "ctrl+alt+ö", "voice": "en_US-norman-medium"}
            with real_open(path, "w", encoding="utf-8") as fh:
                json.dump(saved, fh)
            state = {"block": True}

            def guarded(file, mode="r", *args, **kwargs):
                target = os.path.abspath(file) if isinstance(file, (str, os.PathLike)) else ""
                writing = any(flag in mode for flag in ("w", "a", "+"))
                if target == os.path.abspath(path) and not writing and state["block"]:
                    raise PermissionError("locked")
                return real_open(file, mode, *args, **kwargs)

            cfg.PATH = path
            builtins.open = guarded
            settings = Settings()
            check(settings._unreadable, "a locked settings file is kept unread")
            untouched = json.loads(real_open(path, encoding="utf-8").read())
            check(untouched.get("speed") == 1.6 and untouched.get("dictate_hotkey") == "ctrl+alt+ö", f"a locked read does not rewrite the file: {untouched}")
            state["block"] = False
            settings.set(speed=1.2)
            disk = json.loads(real_open(path, encoding="utf-8").read())
            check(disk.get("speed") == 1.2, f"the new speed is written: {disk.get('speed')}")
            check(disk.get("dictate_hotkey") == "ctrl+alt+ö", f"the saved hotkey stays: {disk.get('dictate_hotkey')}")
            with real_open(path, "w", encoding="utf-8") as fh:
                json.dump(saved, fh)
            before = real_open(path, "rb").read()
            state["block"] = True
            stuck = Settings()
            stuck.set(speed=1.2)
            check(stuck["speed"] == 1.2 and stuck._unreadable, "a still-locked file keeps the change in memory")
            check(real_open(path, "rb").read() == before, "a still-locked file is not overwritten")
    finally:
        builtins.open = real_open
        cfg.PATH = old_path

_check_locked_settings()

def _check_save_and_startup():
    old_replace = os.replace
    old_tries = cfg._REPLACE_TRIES
    old_wait = cfg._REPLACE_WAIT_S
    old_path = cfg.PATH
    cfg._REPLACE_TRIES = 2
    cfg._REPLACE_WAIT_S = 0
    try:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            cfg.write_atomic(path, {"speed": 1.0, "voice": "en_US-norman-medium"})
            def fail_replace(src, dst):
                raise PermissionError("locked")
            os.replace = fail_replace
            raised = False
            try:
                cfg.write_atomic(path, {"speed": 1.4, "voice": "en_US-norman-medium"})
            except OSError:
                raised = True
            check(raised, "a locked replace is reported")
            check(not os.path.exists(path + ".tmp"), "a failed save removes settings.json.tmp")
            check(json.load(open(path, encoding="utf-8"))["speed"] == 1.0, "the previous settings stay on disk")
            os.replace = old_replace
            cfg.PATH = path
            settings = cfg.Settings()
            os.replace = fail_replace
            settings.set(speed=1.7)
            check(settings["speed"] == 1.7 and settings._unreadable, "a failed save keeps the new value to merge later")
            check(settings._held.get("speed") == 1.7, "the unsaved change is remembered")
            check(not os.path.exists(path + ".tmp"), "settings.set removes the temp file")
            os.replace = old_replace
            settings.set(speed=1.7)
            check(json.load(open(path, encoding="utf-8"))["speed"] == 1.7 and not settings._unreadable, "the next save writes the held change")
            bom = os.path.join(d, "bom.json")
            with open(bom, "w", encoding="utf-8-sig") as fh:
                json.dump({"speed": 1.5, "voice": "en_US-norman-medium"}, fh)
            data, should, notice = cfg.read_settings(bom)
            check(should and notice is None and data.get("speed") == 1.5, f"a Notepad BOM file is read: {data} {notice}")
            bad = os.path.join(d, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{")
            cfg.PATH = bad
            reset = cfg.Settings()
            check(bool(reset.reset_notice), "corrupt settings produce a one-time notice")
            check(os.path.exists(bad + ".bad") or os.path.exists(bad + ".bad." + ""), "the corrupt file is kept beside the new one")
            from saytray.selection import previous_class
            check(previous_class("r") == "letter" and previous_class(" ") == "space", "a dictated character is logged by class")
            check(previous_class(".") == "punct" and previous_class(None) == "none", "punctuation and an empty field have classes")
            sel_src = open(os.path.join(os.path.dirname(__file__), "..", "saytray", "selection.py"), encoding="utf-8").read()
            check("repr(previous)" not in sel_src, "the previous character is not written to the log")
            from saytray import startup
            blocked_msg = []
            ok, msg = startup.set_enabled(
                True, shortcut_path=os.path.join(d, "missing.lnk"),
                write_shortcut=lambda *a: "access denied",
                set_run=lambda *a: None,
                clear_run=lambda: None,
                run_present=lambda: False,
            )
            check(ok is False and "Quarantine" in msg, f"a blocked startup tells the user how to allow SayTray: {msg}")
            blocked_msg.append(msg)
            remembered = {}
            def remember(target, args):
                remembered["args"] = args
            ok, msg = startup.set_enabled(
                True, shortcut_path=os.path.join(d, "nope.lnk"),
                write_shortcut=lambda *a: "access denied",
                set_run=remember,
                clear_run=lambda: None,
                run_present=lambda: True,
            )
            check(ok is True and msg == "" and remembered.get("args"), "a blocked shortcut falls back to the Run key")
            install = open(os.path.join(os.path.dirname(__file__), "..", "install.ps1"), encoding="utf-8").read()
            check("Test-Path -LiteralPath $lnk" in install and "Quarantine" in install, "the installer checks shortcuts and explains a block")
            check("CurrentVersion\\Run" in install, "the installer can save a Run key")
            check("ExecutionPolicy Bypass" not in install, "the installed commands do not use ExecutionPolicy Bypass")
            check("try {" in install and "Could not copy uninstall.ps1" in install, "a blocked uninstall.ps1 copy does not abort the install")
            check("built-in uninstall command" in install, "Apps & Features is not pointed at a missing uninstall script")
            check("Stop-Process" in install and "run_saytray.pyw" in install, "the fallback uninstall quits SayTray first")
            check("@('app','venv','debug')" in install and "Settings and voices are kept" in install, "the fallback uninstall keeps settings and voices")
            check("Remove-Item -LiteralPath '$R' -Recurse" not in install, "the fallback uninstall does not delete the whole SayTray folder")
            check("EncodedCommand" not in install, "the fallback uninstall is a readable command")
            uninst = open(os.path.join(os.path.dirname(__file__), "..", "uninstall.ps1"), encoding="utf-8").read()
            check("Stop-Process" in uninst and "run_saytray.pyw" in uninst, "uninstall stops SayTray first")
            check("CurrentVersion\\Run" in uninst, "uninstall removes the startup Run key")
            check('@("app", "venv", "debug")' in uninst, "uninstall removes the program files")
            check("Remove-Item $R -Recurse" not in uninst and '"voices"' not in uninst, "uninstall keeps settings and voices")
            check("test_dictation_order.py" in open(os.path.join(os.path.dirname(__file__), "..", "run_tests.ps1"), encoding="utf-8").read()
                  and "test_requirements_wheels.py" in open(os.path.join(os.path.dirname(__file__), "..", "run_tests.ps1"), encoding="utf-8").read(),
                  "run_tests.ps1 includes the order and wheel suites")
            start_src = open(os.path.join(os.path.dirname(__file__), "..", "saytray", "startup.py"), encoding="utf-8").read()
            check("powershell" not in start_src.lower(), "startup does not launch PowerShell to write a shortcut")
            speaker_src = open(os.path.join(os.path.dirname(__file__), "..", "saytray", "speaker.py"), encoding="utf-8").read()
            check("SAYTRAY_DEBUG" in speaker_src and "saytray-read-" in speaker_src, "read audio is kept only in debug mode")
            check('logs.event("read: stopped")' in speaker_src, "stopping a read is written to the log")
    finally:
        os.replace = old_replace
        cfg._REPLACE_TRIES = old_tries
        cfg._REPLACE_WAIT_S = old_wait
        cfg.PATH = old_path

_check_save_and_startup()

print(f"dictation flow tests: {passes} passed, {failures} failed")
sys.exit(1 if failures else 0)
