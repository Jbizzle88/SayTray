"""Hold-chord tracker: modifier stays down, the main key can go up and down again."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.chord import ChordTracker

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

print(f"Chord tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
