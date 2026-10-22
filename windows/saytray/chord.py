"""Pure hold-chord tracker. No keyboard hook, so tests can drive it with key names.

While the modifier keys stay down, releasing and pressing the non-modifier key again yields
'up' then 'down'. Releasing any required key ends the hold. Key-repeat downs are ignored.
"""

_ALIASES = {
    "ctrl": {"ctrl", "left ctrl", "right ctrl", "control", "left control", "right control"},
    "alt": {"alt", "left alt", "right alt", "alt gr"},
    "shift": {"shift", "left shift", "right shift"},
    "windows": {"left windows", "right windows", "windows"},
    "space": {"space", "spacebar"},
}

_CANON = {alias: canon for canon, aliases in _ALIASES.items() for alias in aliases}
for _name in _ALIASES:
    _CANON.setdefault(_name, _name)


def canonical(name):
    n = (name or "").strip().lower()
    if not n:
        return ""
    return _CANON.get(n, n)


def required_keys(combo):
    return {canonical(part) for part in (combo or "").split("+") if part.strip()}


def chord_parts(combo):
    return [canonical(part) for part in (combo or "").split("+") if part.strip()]


class ModifierArm:
    """Fires once when every modifier of a hold chord is down, before the main key.

    Ctrl+Alt+Space arms when Ctrl and Alt are both down. Releasing either modifier
    arms again the next time they are both down.
    """

    def __init__(self, combo):
        parts = chord_parts(combo)
        self.mods = set(parts[:-1]) if len(parts) > 1 else set()
        self.down = set()
        self.ready = False

    def event(self, name, is_down):
        raw = (name or "").strip().lower()
        # AltGr is delivered as alt gr / right alt, often with Ctrl. That is how
        # a German layout types @, and it must not open the microphone.
        if raw in ("alt gr", "altgr", "right alt"):
            return False
        key = canonical(name)
        if key not in self.mods:
            return False
        if is_down:
            self.down.add(key)
        else:
            self.down.discard(key)
        now = bool(self.mods) and self.mods <= self.down
        if now and not self.ready:
            self.ready = True
            return True
        if not now:
            self.ready = False
        return False

    def reset(self):
        self.down.clear()
        self.ready = False


class ChordTracker:
    def __init__(self, combo):
        self.required = required_keys(combo)
        self.down = set()
        self.holding = False

    def event(self, name, is_down):
        """Return 'down', 'up', or None for one key event."""
        key = canonical(name)
        if not key or key not in self.required:
            return None
        if is_down:
            self.down.add(key)
        else:
            self.down.discard(key)
        ready = self.required <= self.down
        if ready and not self.holding:
            self.holding = True
            return "down"
        if self.holding and not ready:
            self.holding = False
            return "up"
        return None

    def reset(self):
        self.down.clear()
        self.holding = False
