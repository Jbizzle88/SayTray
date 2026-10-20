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
