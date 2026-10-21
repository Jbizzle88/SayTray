"""Selected-text capture (simulated Ctrl+C with clipboard restore) and typing (Ctrl+V with restore)."""
import ctypes, threading, time
import keyboard, pyperclip
from . import logs
from .spacing import apply

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


_insert_lock = threading.Lock()
_last_inserted = ""


def _cursor_previous():
    """One character before the caret, '' at the start of the field, or None if it can't be read."""
    try:
        import comtypes.client
        try:
            from comtypes.gen import UIAutomationClient as UIA
        except Exception:
            UIA = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(UIA.CUIAutomation)
        el = uia.GetFocusedElement()
        unk = el.GetCurrentPattern(UIA.UIA_TextPatternId)
        text = unk.QueryInterface(UIA.IUIAutomationTextPattern)
        ranges = text.GetSelection()
        if ranges.Length == 0:
            return ""
        clone = ranges.GetElement(0).Clone()
        moved = clone.MoveEndpointByUnit(UIA.TextPatternRangeEndpoint_Start, UIA.TextUnit_Character, -1)
        if not moved:
            return ""
        got = clone.GetText(2) or ""
        return got[0] if got else ""
    except Exception:
        return None


def insert_dictation(text):
    """Space back-to-back dictations, then type. Calls are serialized so pastes stay in order."""
    global _last_inserted
    raw = (text or "").strip()
    if not raw:
        return
    with _insert_lock:
        read = _cursor_previous()
        if read is None:
            previous = _last_inserted[-1] if _last_inserted else None
            source = "last-insert" if _last_inserted else "none"
        elif read == "":
            previous = None
            source = "boundary"
        else:
            previous = read
            source = "cursor"
        prepared = apply(raw, previous)
        spaced = prepared != raw
        _last_inserted = prepared
        shown = "" if previous is None else repr(previous)
        logs.event(f"insert: {len(prepared)} chars leading-space={spaced} previous={source} {shown}")
        type_text(prepared)


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
