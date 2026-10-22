"""Hold-chord tracker: modifier stays down, the main key can go up and down again."""
import os, sys, tempfile
if not os.environ.get("SAYTRAY_LOG_DIR"):
    os.environ["SAYTRAY_LOG_DIR"] = tempfile.mkdtemp(prefix="saytray-test-logs-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.chord import ChordTracker, ModifierArm

passes = failures = 0

def check(cond, msg):
    global passes, failures
    if cond:
        passes += 1
    else:
        failures += 1
        print("FAIL:", msg)

def drive(combo, steps):
    t = ChordTracker(combo)
    got = [t.event(name, down) for name, down in steps]
    return got

# Ctrl+Alt held, Space released, Space pressed again → up then down.
got = drive("ctrl+alt+space", [
    ("ctrl", True), ("alt", True), ("space", True),
    ("space", False),
    ("space", True),
    ("space", False),
    ("space", True),
])
check(got == [None, None, "down", "up", "down", "up", "down"], f"re-press space while modifiers held: {got}")

# Repeats while the chord is held do not start another session.
got = drive("ctrl+alt+space", [
    ("left ctrl", True), ("right alt", True), ("space", True),
    ("space", True), ("space", True),
])
check(got == [None, None, "down", None, None], f"key repeat ignored: {got}")

# Releasing the modifier ends the hold even if Space is still down.
got = drive("ctrl+alt+space", [
    ("ctrl", True), ("alt", True), ("space", True),
    ("left alt", False),
    ("space", False),
    ("space", True),
])
check(got == [None, None, "down", "up", None, None], f"modifier release ends hold: {got}")

# Space alone is not the chord. Adding the modifiers afterward starts it once.
got = drive("ctrl+alt+space", [
    ("space", True),
    ("control", True),
    ("alt gr", True),
])
check(got == [None, None, "down"], f"chord completes on the last key: {got}")

# Unrelated keys never change the hold.
t = ChordTracker("ctrl+alt+space")
check(t.event("a", True) is None and t.event("", True) is None, "unrelated keys")
t.event("ctrl", True); t.event("alt", True); t.event("space", True)
check(t.holding and t.event("shift", False) is None and t.holding, "shift release is not part of the chord")

# Option is not a Windows alias; the Mac default is exercised as ctrl+alt on Windows.
# A second full cycle after every key came up starts cleanly.
got = drive("ctrl+alt+space", [
    ("ctrl", True), ("alt", True), ("space", True),
    ("space", False), ("alt", False), ("ctrl", False),
    ("right ctrl", True), ("left alt", True), ("spacebar", True),
])
check(got == [None, None, "down", "up", None, None, None, None, "down"], f"fresh chord after full release: {got}")

# Twenty full press/release cycles, the way a hotkey gets spammed.
cycle = [("ctrl", True), ("alt", True), ("space", True), ("space", False), ("alt", False), ("ctrl", False)]
got = drive("ctrl+alt+space", cycle * 20)
expect = [None, None, "down", "up", None, None] * 20
check(got == expect, f"20 rapid cycles stay paired: downs={got.count('down')} ups={got.count('up')}")

# Key-repeat spam while the chord is held is still one session.
got = drive("ctrl+alt+space", [("ctrl", True), ("alt", True)] + [("space", True)] * 20 + [("space", False)])
check(got.count("down") == 1 and got.count("up") == 1, f"repeat spam is one session: {got.count('down')} down {got.count('up')} up")

arm = ModifierArm("ctrl+alt+space")
check(arm.event("ctrl", True) is False, "one modifier does not arm")
check(arm.event("alt", True) is True, "both modifiers arm once")
check(arm.event("alt", True) is False, "the arm does not repeat while they stay down")
check(arm.event("space", True) is False, "the main key does not arm by itself")
check(arm.event("alt", False) is False and arm.event("alt", True) is True, "releasing a modifier arms again on the next press")
alone = ModifierArm("ctrl+alt+space")
check(alone.event("space", True) is False, "space alone does not warm the mic")

# AltGr types characters on a German layout. It must not open the microphone.
# The real chord still treats AltGr as Alt, so Ctrl+AltGr+Space can dictate.
gr = ModifierArm("ctrl+alt+space")
check(gr.event("ctrl", True) is False, "ctrl alone does not arm")
check(gr.event("alt gr", True) is False, "AltGr does not arm")
check(gr.event("q", True) is False, "AltGr+Q does not arm")
right = ModifierArm("ctrl+alt+space")
check(right.event("ctrl", True) is False and right.event("right alt", True) is False, "right alt does not arm")
check(right.event("altgr", True) is False, "altgr does not arm")
left = ModifierArm("ctrl+alt+space")
check(left.event("ctrl", True) is False and left.event("left alt", True) is True, "left alt still arms")
f13 = ModifierArm("f13")
check(f13.event("ctrl", False) is False and f13.event("f13", True) is False, "a key with no modifiers does not arm")

import time, types
kb = types.ModuleType("keyboard")
kb.KEY_DOWN = "down"
kb.KEY_UP = "up"
kb.parse_hotkey = lambda combo: combo
kb.add_hotkey = lambda *a, **k: object()
kb.remove_hotkey = lambda h: None
kb.hook = lambda fn: fn
kb.unhook = lambda h: None
_prev = sys.modules.get("keyboard")
sys.modules["keyboard"] = kb
from saytray.hotkeys import Hotkeys

class _Ev:
    def __init__(self, name, down):
        self.name = name
        self.event_type = "down" if down else "up"

arms = []
hk = Hotkeys()
try:
    hk.register("alt+`", lambda: None, "ctrl+alt+space", lambda: None, lambda: None, on_arm=lambda: arms.append(1))
    hk._event(_Ev("ctrl", True))
    hk._event(_Ev("alt", True))
    pending = hk._arm_timer
    check(pending is not None and abs(pending.interval - 0.15) < 0.001, "modifiers wait before warming")
    hk._event(_Ev("`", True))
    check(hk._arm_timer is None and arms == [], "a following read key cancels the warm")
    hk._event(_Ev("alt", False))
    hk._event(_Ev("alt", True))
    first = hk._arm_timer
    hk._event(_Ev("alt", False))
    hk._event(_Ev("alt", True))
    second = hk._arm_timer
    check(first is not None and second is not None and first is not second and first.finished.is_set(), "a new arm replaces the previous timer")
    hk._event(_Ev("space", True))
    check(arms == [1] and hk._arm_timer is None, "the dictate key warms immediately and does not leave a timer")
    arms.clear()
    hk.clear()
    hk.register("alt+`", lambda: None, "ctrl+alt+space", lambda: None, lambda: None, on_arm=lambda: arms.append(1))
    hk._event(_Ev("ctrl", True))
    hk._event(_Ev("alt gr", True))
    hk._event(_Ev("q", True))
    check(arms == [] and hk._arm_timer is None, "AltGr+Q does not schedule a warm")
    hk.clear()
    hk.register("alt+`", lambda: None, "f13", lambda: None, lambda: None, on_arm=lambda: arms.append(1))
    hk._event(_Ev("ctrl", False))
    hk._event(_Ev("f13", True))
    time.sleep(0.05)
    check(arms == [] and hk._arm_timer is None, "F13 does not pre-warm")
    hk.clear()
    hk.register("alt+`", lambda: None, "ctrl+alt+space", lambda: None, lambda: None, on_arm=lambda: arms.append(1))
    hk._event(_Ev("ctrl", True))
    hk._event(_Ev("left alt", True))
    time.sleep(0.4)
    check(arms == [], f"holding the read modifiers does not warm the mic: {arms}")
    hk._event(_Ev("space", True))
    check(arms == [1], f"the dictate key warms once: {arms}")
    time.sleep(0.3)
    check(arms == [1], f"the wait does not warm a second time: {arms}")
    arms.clear()
    hk.clear()
    hk.register("ctrl+shift+r", lambda: None, "ctrl+alt+space", lambda: None, lambda: None, on_arm=lambda: arms.append(1))
    hk._event(_Ev("ctrl", True))
    hk._event(_Ev("alt", True))
    time.sleep(0.4)
    check(arms == [1], f"a dictate chord that is not the read chord still warms once: {arms}")
    hk._event(_Ev("space", True))
    time.sleep(0.05)
    check(arms == [1], f"space after the wait does not warm again: {arms}")
    arms.clear()
    hk.clear()
    hk.register("alt+`", lambda: None, "ctrl+alt+space", lambda: None, lambda: None, on_arm=lambda: arms.append(1))
    hk._event(_Ev("ctrl", True))
    hk._event(_Ev("alt", True))
    time.sleep(0.2)
    hk._event(_Ev("alt", False))
    hk._event(_Ev("space", True))
    check(arms == [], f"releasing the modifiers drops the pending warm: {arms}")
    arms.clear()
    hk.clear()
    sessions = []
    hk.register("alt+`", lambda: None, "ctrl+alt+space", lambda: None, lambda: None, on_modifier=lambda held: sessions.append(held))
    hk._event(_Ev("ctrl", True))
    check(sessions == [], "one modifier does not start the session")
    hk._event(_Ev("alt", True))
    hk._event(_Ev("alt", True))
    hk._event(_Ev("space", True))
    check(sessions == [True], f"the modifier session starts once: {sessions}")
    hk._event(_Ev("space", False))
    check(sessions == [True], "releasing the main key keeps the modifier session")
    hk._event(_Ev("alt", False))
    check(sessions == [True, False], f"releasing a modifier ends the session: {sessions}")
finally:
    hk.clear()
    if _prev is None:
        sys.modules.pop("keyboard", None)
    else:
        sys.modules["keyboard"] = _prev

print(f"Chord tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
