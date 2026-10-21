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
on_notice = None


class InputIncomplete(Exception):
    """Unicode typing stopped before the whole string. `sent` is UTF-16 units already typed."""

    def __init__(self, sent, message):
        super().__init__(message)
        self.sent = int(sent or 0)


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


def _wait_mods_released(timeout=1.0):
    """True when no modifier is down. timeout None waits until they are released."""
    if timeout is None:
        while _modifiers_down():
            time.sleep(0.02)
        return True
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _modifiers_down():
            return True
        time.sleep(0.02)
    return not _modifiers_down()


def _notify(message):
    logs.event("type: " + message)
    if on_notice:
        try:
            on_notice(message)
        except Exception:
            pass


def text_after_units(text, sent_units):
    """The part of `text` that comes after `sent_units` UTF-16 code units. Newlines are not units."""
    sent_units = int(sent_units or 0)
    if sent_units <= 0:
        return text or ""
    count = 0
    out = []
    for ch in text or "":
        if ch == "\r":
            continue
        if ch == "\n":
            if count >= sent_units:
                out.append(ch)
            continue
        units = len(ch.encode("utf-16-le")) // 2
        if count >= sent_units:
            out.append(ch)
        elif count + units > sent_units:
            out.append(ch)
        count += units
    return "".join(out)


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


def split_typing_steps(events, batch=32):
    """Keep Enter as its own step so it can wait until modifiers are up."""
    steps = []
    chars = []
    for kind, value in events:
        if kind == "vk":
            if chars:
                steps.append(("chars", chars))
                chars = []
            steps.append(("enter", value))
        else:
            chars.append(value)
            if len(chars) >= batch:
                steps.append(("chars", chars))
                chars = []
    if chars:
        steps.append(("chars", chars))
    return steps


def _send_unicode(text):
    """Type `text` as Unicode key events. Returns how many UTF-16 units were sent.

    Enter waits until modifiers are up, then is sent. It is not dropped and it is
    not sent as Ctrl+Enter. Raises InputIncomplete when a batch fails or Enter
    cannot be sent yet; `sent` is the units already typed.
    """
    user32 = _user32()
    if user32 is None:
        raise InputIncomplete(0, "unicode input is only available on Windows")
    events = unicode_events(text)
    if not events:
        return 0
    sent_units = 0
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

    def send_batch(batch):
        if not batch:
            return
        arr = (INPUT * len(batch))(*batch)
        sent = user32.SendInput(len(batch), arr, ctypes.sizeof(INPUT))
        if sent != len(batch):
            raise InputIncomplete(sent_units, f"SendInput sent {sent} of {len(batch)}")
        time.sleep(0.008)

    for kind, value in split_typing_steps(events):
        if kind == "enter":
            # VK_RETURN while Ctrl is down is Ctrl+Enter. Hold the newline until
            # the modifiers come up, then send a plain Enter in this same spot.
            tries = 0
            while not _wait_mods_released(None):
                tries += 1
                if tries >= 3:
                    raise InputIncomplete(sent_units, "modifiers still held")
            send_batch([one(value, 0, 0), one(value, 0, KEYEVENTF_KEYUP)])
        else:
            batch = []
            for unit in value:
                batch.append(one(0, unit, KEYEVENTF_UNICODE))
                batch.append(one(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            send_batch(batch)
            sent_units += len(value)
    return sent_units


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
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
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
        shown = "" if previous is None else repr(previous)
        if not type_text(prepared):
            logs.event(f"insert: failed {len(prepared)} chars previous={source} {shown}")
            return
        _last_inserted = prepared
        logs.event(f"insert: {len(prepared)} chars leading-space={spaced} previous={source} {shown}")


def _leave_on_clipboard(text):
    """Copy `text` and do not paste. The previous clipboard value is not restored."""
    if pyperclip is None:
        raise OSError("clipboard unavailable")
    pyperclip.copy(text)


def type_text(text):
    """Insert text at the cursor. Returns False when the text was not fully typed.

    A paste never runs while a modifier is held. If Unicode typing stops partway,
    only the untyped remainder is pasted, and only after the modifiers are up.
    If they stay down, that remainder is left on the clipboard and this returns False.
    """
    if not text:
        return False
    sent = 0
    if _modifiers_down():
        logs.event(f"type: modifiers held; unicode input ({len(text)} chars)")
        try:
            sent = _send_unicode(text) or 0
            return True
        except InputIncomplete as e:
            sent = e.sent
            logs.event(f"type: unicode stopped after {sent} units: {e}")
        except Exception as e:
            sent = int(getattr(e, "sent", 0) or 0)
            logs.event(f"type: unicode input failed: {e!r}; will paste the rest after the shortcut is released")
    remainder = text_after_units(text, sent)
    if not remainder:
        return sent > 0
    if _modifiers_down():
        logs.event("type: waiting for the shortcut to be released before pasting")
        if not _wait_mods_released(2.0):
            try:
                _leave_on_clipboard(remainder)
            except Exception as e:
                logs.event(f"type: could not leave text on the clipboard: {e!r}")
                return False
            _notify("The shortcut was still held, so SayTray did not paste. The rest of the dictation is on the clipboard.")
            return False
    try:
        with _clip_lock:
            _paste_text(remainder)
        return True
    except Exception as e:
        logs.event(f"type: paste failed: {e!r}")
        return False


def _paste_text(text):
    if pyperclip is None or keyboard is None:
        raise OSError("clipboard unavailable")
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
