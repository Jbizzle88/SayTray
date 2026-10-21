"""Global hotkeys via the `keyboard` low-level hook.

Read = press. Dictation = hold: ChordTracker turns key events into down/up, so keeping Ctrl+Alt
held and tapping Space starts a fresh dictation each time. add_hotkey is only used to suppress
the chord (its own callback is not the state machine — that machine sticks the non-modifier
key when the modifiers never come up).
"""
import queue, threading
from . import logs
from .chord import ChordTracker


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
        self._on_down = None
        self._on_up = None

    def register(self, read_combo, on_read, dictate_combo, on_down, on_up):
        import keyboard
        self.clear()
        try:
            self._handles.append(keyboard.add_hotkey(read_combo, on_read, suppress=True))
        except Exception as e:
            logs.event(f"hotkey {read_combo} registration failed: {e!r}")
        try:
            # Falsy return suppresses the chord so Space is not typed. Must stay instant —
            # the OS hook thread cannot open the microphone or sleep.
            self._handles.append(keyboard.add_hotkey(dictate_combo, lambda: None, suppress=True))
        except Exception as e:
            logs.event(f"hotkey {dictate_combo} suppress registration failed: {e!r}")
        self._tracker = ChordTracker(dictate_combo)
        self._on_down, self._on_up = on_down, on_up
        self._hook = keyboard.hook(self._event)
        logs.event(f"hotkeys registered: read={read_combo} dictate(hold)={dictate_combo}")

    def _event(self, e):
        tracker = self._tracker
        if tracker is None:
            return
        import keyboard
        action = tracker.event(e.name, e.event_type == keyboard.KEY_DOWN)
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
