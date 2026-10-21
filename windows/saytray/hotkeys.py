"""Global hotkeys via the `keyboard` low-level hook.

Read = press. Dictation = hold: ChordTracker turns key events into down/up, so keeping Ctrl+Alt
held and tapping Space starts a fresh dictation each time. add_hotkey is only used to suppress
the chord (its own callback is not the state machine — that machine sticks the non-modifier
key when the modifiers never come up).
"""
import queue, threading
from . import logs
from .chord import ChordTracker, ModifierArm, canonical, chord_parts
from .config import hotkey_registerable

_ARM_DELAY_S = 0.15


class HotkeySerial:
    """Run dictate down/up on one thread, in the order the keys arrived.

    A quick tap used to start and stop on two threads, so stop could run first
    and the microphone stayed on.
    """

    def __init__(self):
        self._q = queue.Queue()
        self._t = threading.Thread(target=self._run, daemon=True, name="hotkey-serial")
        self._t.start()

    def submit(self, fn):
        self._q.put(fn)

    def _run(self):
        while True:
            fn = self._q.get()
            try:
                fn()
            except Exception as e:
                logs.event(f"hotkey handler failed: {e!r}")


class Hotkeys:
    def __init__(self):
        self._handles = []
        self._hook = None
        self._tracker = None
        self._arm = None
        self._on_down = None
        self._on_up = None
        self._on_arm = None
        self._on_unusable = None
        self._arm_timer = None
        self._dictate_main = ""

    def register(self, read_combo, on_read, dictate_combo, on_down, on_up, on_arm=None, on_unusable=None):
        import keyboard
        self.clear()
        self._on_unusable = on_unusable
        self._bind(keyboard, read_combo, on_read, suppress=True)
        # Falsy return suppresses the chord so Space is not typed. Must stay instant —
        # the OS hook thread cannot open the microphone or sleep.
        self._bind(keyboard, dictate_combo, lambda: None, suppress=True)
        self._tracker = ChordTracker(dictate_combo)
        self._arm = ModifierArm(dictate_combo)
        parts = chord_parts(dictate_combo)
        self._dictate_main = parts[-1] if len(parts) > 1 else ""
        self._on_down, self._on_up, self._on_arm = on_down, on_up, on_arm
        self._hook = keyboard.hook(self._event)
        logs.event(f"hotkeys registered: read={read_combo} dictate(hold)={dictate_combo}")

    def _bind(self, keyboard, combo, callback, suppress):
        if not hotkey_registerable(combo):
            logs.event(f"hotkey {combo} skipped; it does not match this keyboard layout")
            if self._on_unusable:
                try:
                    self._on_unusable(combo)
                except Exception:
                    pass
            return
        try:
            self._handles.append(keyboard.add_hotkey(combo, callback, suppress=suppress))
        except Exception as e:
            logs.event(f"hotkey {combo} registration failed: {e!r}")
            if self._on_unusable:
                try:
                    self._on_unusable(combo)
                except Exception:
                    pass

    def _event(self, e):
        tracker = self._tracker
        if tracker is None:
            return
        import keyboard
        is_down = e.event_type == keyboard.KEY_DOWN
        key = canonical(e.name)
        if self._arm is not None and self._arm.mods and self._arm.event(e.name, is_down):
            self._schedule_arm()
        if is_down and self._dictate_main:
            if key == self._dictate_main:
                self._flush_arm()
            elif self._arm is None or key not in self._arm.mods:
                self._cancel_arm()
        action = tracker.event(e.name, is_down)
        if action == "down" and self._on_down:
            self._on_down()
        elif action == "up" and self._on_up:
            self._on_up()

    def clear(self):
        import keyboard
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
        if self._tracker is not None:
            self._tracker.reset()
        self._tracker = None
        if self._arm is not None:
            self._arm.reset()
        self._arm = None
        self._cancel_arm()
        self._dictate_main = ""

    def _schedule_arm(self):
        """Wait briefly so a read-hotkey or other key can cancel the pre-warm."""
        self._cancel_arm()
        timer = threading.Timer(_ARM_DELAY_S, self._flush_arm)
        timer.daemon = True
        self._arm_timer = timer
        timer.start()

    def _cancel_arm(self):
        timer = self._arm_timer
        self._arm_timer = None
        if timer is not None:
            timer.cancel()

    def _flush_arm(self):
        self._cancel_arm()
        if self._on_arm:
            self._on_arm()
