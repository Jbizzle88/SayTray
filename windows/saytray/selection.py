"""Selected-text capture (simulated Ctrl+C with clipboard restore) and typing (Ctrl+V with restore)."""
import ctypes, time
import keyboard, pyperclip
from . import logs

_user32 = ctypes.windll.user32
MODS = ("ctrl", "alt", "shift", "left windows", "right windows", "alt gr")


def _seq():
    return _user32.GetClipboardSequenceNumber()


def _wait_mods_released(timeout=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not any(keyboard.is_pressed(m) for m in MODS):
            return True
        time.sleep(0.02)
    return False


def _release_mods():
    for m in ("alt", "ctrl", "shift"):
        try:
            if keyboard.is_pressed(m):
                keyboard.release(m)
        except Exception:
            pass


def read_selection():
    """Return the selected text in the foreground app (or None). Clipboard text is restored."""
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    before = _seq()
    _release_mods()          # the hotkey's Alt is still down; Ctrl+Alt+C would not copy
    time.sleep(0.03)
    keyboard.send("ctrl+c")
    text = None
    for _ in range(30):
        time.sleep(0.02)
        if _seq() != before:
            time.sleep(0.03)
            try:
                text = pyperclip.paste()
            except Exception:
                text = None
            break
    if _seq() != before and old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
    if not text or not text.strip():
        logs.event("read: no selection captured")
        return None
    return text


def type_text(text):
    """Insert text at the cursor via clipboard + Ctrl+V, then restore the clipboard text."""
    _wait_mods_released()
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.6)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
