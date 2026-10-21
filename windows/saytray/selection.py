"""Selected-text capture (simulated Ctrl+C with clipboard restore) and typing.

Ctrl+V is used when no modifier is held. While Ctrl+Alt is still down (the
back-to-back dictation hotkey), the paste would become Ctrl+Alt+V and miss,
so those characters are sent as Unicode key events instead.
"""
import ctypes, threading, time
try:
    import keyboard
except ImportError:
    keyboard = None
try:
    import pyperclip
except ImportError:
    pyperclip = None
from . import logs
from .spacing import prepare

MODS = ("ctrl", "alt", "shift", "left windows", "right windows", "alt gr")
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
INPUT_KEYBOARD = 1

_clip_lock = threading.Lock()
_insert_lock = threading.Lock()
_last_inserted = ""


def _user32():
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    return getattr(windll, "user32", None)


def _seq():
    user32 = _user32()
    if user32 is None:
        return 0
    return user32.GetClipboardSequenceNumber()


def _modifiers_down():
    if keyboard is None:
        return False
    try:
        return any(keyboard.is_pressed(m) for m in MODS)
    except Exception:
        return False


def _release_mods():
    if keyboard is None:
        return
    for m in ("alt", "ctrl", "shift"):
        try:
            if keyboard.is_pressed(m):
                keyboard.release(m)
        except Exception:
            pass


def unicode_events(text):
    """Key events for `text`. Newline is Enter, CR is skipped, emoji is a UTF-16 pair."""
    events = []
    for ch in text or "":
        if ch == "\r":
            continue
        if ch == "\n":
            events.append(("vk", VK_RETURN))
            continue
        encoded = ch.encode("utf-16-le")
        for i in range(0, len(encoded), 2):
            events.append(("u", int.from_bytes(encoded[i:i + 2], "little")))
    return events


def _send_unicode(text):
    user32 = _user32()
    if user32 is None:
        raise OSError("unicode input is only available on Windows")
    events = unicode_events(text)
    if not events:
        return
    ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", INPUTUNION)]

    def one(vk, scan, flags):
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))

    for start in range(0, len(events), 32):
        batch = []
        for kind, value in events[start:start + 32]:
            if kind == "vk":
                batch.append(one(value, 0, 0))
                batch.append(one(value, 0, KEYEVENTF_KEYUP))
            else:
                batch.append(one(0, value, KEYEVENTF_UNICODE))
                batch.append(one(0, value, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        arr = (INPUT * len(batch))(*batch)
        sent = user32.SendInput(len(batch), arr, ctypes.sizeof(INPUT))
        if sent != len(batch):
            raise OSError(f"SendInput sent {sent} of {len(batch)}")


def read_selection():
    """Return the selected text in the foreground app (or None). Clipboard text is restored."""
    with _clip_lock:
        return _read_selection_locked()


def _read_selection_locked():
    if pyperclip is None or keyboard is None:
        logs.event("read: clipboard unavailable")
        return None
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
    raw = text or ""
    if not raw.strip():
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
        prepared = prepare(raw, previous)
        if not prepared:
            return
        spaced = prepared != raw.strip()
        _last_inserted = prepared
        shown = "" if previous is None else repr(previous)
        logs.event(f"insert: {len(prepared)} chars leading-space={spaced} previous={source} {shown}")
        type_text(prepared)


def type_text(text):
    """Insert text at the cursor, then restore the clipboard when a paste was used."""
    if not text:
        return
    if _modifiers_down():
        logs.event(f"type: modifiers held; unicode input ({len(text)} chars)")
        _send_unicode(text)
        return
    with _clip_lock:
        _paste_text(text)


def _paste_text(text):
    if pyperclip is None or keyboard is None:
        logs.event("type: clipboard unavailable")
        return
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
