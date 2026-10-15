"""Global hotkeys via the `keyboard` low-level hook. Read = press; dictation = hold (press starts, releasing
any key of the combo stops)."""
import keyboard
from . import logs

_ALIASES = {"ctrl": {"ctrl", "left ctrl", "right ctrl"}, "alt": {"alt", "left alt", "right alt", "alt gr"},
            "shift": {"shift", "left shift", "right shift"}, "windows": {"left windows", "right windows", "windows"}}


def _names(combo):
    out = set()
    for k in combo.lower().split("+"):
        k = k.strip()
        out |= _ALIASES.get(k, {k})
    return out


class Hotkeys:
    def __init__(self):
        self._handles = []
        self._hook = None
        self._hold_names = set()
        self._holding = False
        self._on_up = None

    def register(self, read_combo, on_read, dictate_combo, on_down, on_up):
        self.clear()
        try:
            self._handles.append(keyboard.add_hotkey(read_combo, on_read, suppress=True))
        except Exception as e:
            logs.event(f"hotkey {read_combo} registration failed: {e!r}")
        def down():
            if not self._holding:
                self._holding = True
                on_down()
        try:
            self._handles.append(keyboard.add_hotkey(dictate_combo, down, suppress=True))
        except Exception as e:
            logs.event(f"hotkey {dictate_combo} registration failed: {e!r}")
        self._hold_names, self._on_up = _names(dictate_combo), on_up
        self._hook = keyboard.hook(self._event)
        logs.event(f"hotkeys registered: read={read_combo} dictate(hold)={dictate_combo}")

    def _event(self, e):
        if self._holding and e.event_type == keyboard.KEY_UP and (e.name or "").lower() in self._hold_names:
            self._holding = False
            self._on_up()

    def clear(self):
        for h in self._handles:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._handles = []
        if self._hook:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None
