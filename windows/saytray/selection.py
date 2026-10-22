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
VK_MENU = 0x12
# Not a real key. A lone Alt-up opens the menu bar; this tap first makes it a chord.
VK_UNASSIGNED = 0xE8
INPUT_KEYBOARD = 1
_MOD_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)

_clip_lock = threading.Lock()
_insert_lock = threading.Lock()
_last_inserted = ""
_last_insert_hwnd = 0
_last_insert_at = 0.0
_LAST_INSERT_S = 180.0
_cursor_fault_logged = False
_typed_prefix = ""
on_notice = None
_MOD_WAIT_S = 30.0


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


def _vk_down(vk):
    """True/False from GetAsyncKeyState, or None when Windows isn't available."""
    user32 = _user32()
    if user32 is None or not hasattr(user32, "GetAsyncKeyState"):
        return None
    try:
        return bool(user32.GetAsyncKeyState(int(vk)) & 0x8000)
    except Exception:
        return None


def _named_down(vks, name):
    """True when one of `vks` is down. None from Windows falls through to the keyboard library."""
    known = [_vk_down(vk) for vk in vks]
    if any(state is True for state in known):
        return True
    if known and all(state is False for state in known):
        return False
    if keyboard is None:
        return False
    try:
        return bool(keyboard.is_pressed(name))
    except Exception:
        return False


def _alt_blocks_unicode():
    """Alt without Ctrl turns Unicode typing into a system character the target drops."""
    return _named_down((VK_MENU, 0xA4, 0xA5), "alt") and not _named_down((0x11, 0xA2, 0xA3), "ctrl")


def _lift_alt():
    """Send Alt-up after the menu neutralizer. A physically held Alt stays down."""
    _neutralize_alt_menu()
    user32 = _user32()
    if user32 is None or not hasattr(user32, "keybd_event"):
        return
    for vk in (0xA4, 0xA5, VK_MENU):
        if not _vk_down(vk):
            continue
        try:
            user32.keybd_event(int(vk), 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass


def _wait_alt_clear(timeout=2.0):
    """True once Alt is no longer blocking Unicode. A physical hold has to be released."""
    _lift_alt()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _alt_blocks_unicode():
            return True
        time.sleep(0.02)
    return not _alt_blocks_unicode()


def _foreground_hwnd():
    user32 = _user32()
    if user32 is None or not hasattr(user32, "GetForegroundWindow"):
        return 0
    try:
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _remember_insert(text):
    """Remember what SayTray just typed, and where, for the next leading space."""
    global _last_inserted, _last_insert_hwnd, _last_insert_at
    _last_inserted = text or ""
    _last_insert_hwnd = _foreground_hwnd()
    _last_insert_at = time.monotonic()


def _recent_insert_char():
    """Last character SayTray typed in this window a moment ago, or None."""
    text = _last_inserted or ""
    if not text:
        return None
    if _last_insert_at and time.monotonic() - _last_insert_at > _LAST_INSERT_S:
        return None
    now = _foreground_hwnd()
    if now and _last_insert_hwnd and int(now) != int(_last_insert_hwnd):
        return None
    return text[-1]


def _log_cursor_fault(exc):
    global _cursor_fault_logged
    if _cursor_fault_logged:
        return
    _cursor_fault_logged = True
    logs.event(f"spacing: cursor read failed ({type(exc).__name__})")


def _focused_hwnd():
    """The control that has the caret in the foreground window, or 0."""
    user32 = _user32()
    fg = _foreground_hwnd()
    if user32 is None or not fg or not hasattr(user32, "GetWindowThreadProcessId"):
        return 0
    try:
        get_tid = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(
            ("GetWindowThreadProcessId", user32)
        )
        tid = get_tid(fg, None)
        if not tid or not hasattr(user32, "GetGUIThreadInfo"):
            return 0

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("flags", ctypes.c_ulong),
                ("hwndActive", ctypes.c_void_p),
                ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p),
                ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p),
                ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", RECT),
            ]

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        get_info = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)(
            ("GetGUIThreadInfo", user32)
        )
        if not get_info(tid, ctypes.byref(info)):
            return 0
        return int(info.hwndFocus or 0)
    except Exception:
        return 0


def _edit_previous():
    """One character before the caret in a classic Edit or RichEdit, or None."""
    user32 = _user32()
    hwnd = _focused_hwnd()
    if user32 is None or not hwnd or not hasattr(user32, "SendMessageW"):
        return None
    get_class = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)(
        ("GetClassNameW", user32)
    )
    send = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)(
        ("SendMessageW", user32)
    )
    name = ctypes.create_unicode_buffer(256)
    if get_class(hwnd, name, 256) <= 0:
        return None
    cls = (name.value or "").lower()
    if "edit" not in cls:
        return None
    WM_GETTEXTLENGTH = 0x000E
    WM_GETTEXT = 0x000D
    EM_GETSEL = 0x00B0
    n = int(send(hwnd, WM_GETTEXTLENGTH, 0, None) or 0)
    if n < 0 or n > 1_000_000:
        return None
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    if int(send(hwnd, WM_GETTEXT, n + 1, ctypes.addressof(buf)) or 0) <= 0:
        return None
    start = ctypes.c_ulong()
    end = ctypes.c_ulong()
    send(hwnd, EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end))
    text = buf.value or ""
    pos = int(start.value)
    if pos <= 0:
        return ""
    if pos > len(text):
        return None
    return text[pos - 1]


def _modifiers_down():
    """Real modifier state. The keyboard library can stay True for seconds after release."""
    if any(_vk_down(vk) for vk in _MOD_VKS):
        return True
    if all(_vk_down(vk) is False for vk in _MOD_VKS):
        return False
    if keyboard is None:
        return False
    try:
        return any(keyboard.is_pressed(m) for m in MODS)
    except Exception:
        return False


def _tap_vk(vk):
    user32 = _user32()
    if user32 is None or not hasattr(user32, "keybd_event"):
        return False
    try:
        user32.keybd_event(int(vk), 0, 0, 0)
        user32.keybd_event(int(vk), 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def _neutralize_alt_menu():
    """Send VK 0xE8 before Alt goes up so Windows does not open the menu bar."""
    if _vk_down(VK_MENU) is False and _vk_down(0xA4) is False and _vk_down(0xA5) is False:
        return False
    return _tap_vk(VK_UNASSIGNED)


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


def text_before_units(text, sent_units):
    """Characters fully covered by `sent_units` UTF-16 units. A split pair is not included."""
    sent_units = int(sent_units or 0)
    if sent_units <= 0:
        return ""
    count = 0
    out = []
    for ch in text or "":
        if ch == "\r":
            continue
        if ch == "\n":
            if count < sent_units:
                out.append(ch)
            continue
        units = len(ch.encode("utf-16-le")) // 2
        if count + units <= sent_units:
            out.append(ch)
        count += units
        if count >= sent_units:
            break
    return "".join(out)


def text_after_units(text, sent_units):
    """The part of `text` still to send. A character split across the failure is not sent again."""
    sent_units = int(sent_units or 0)
    if sent_units <= 0:
        return text or ""
    count = 0
    out = []
    started = False
    for ch in text or "":
        if ch == "\r":
            continue
        if ch == "\n":
            if started or count >= sent_units:
                out.append(ch)
            continue
        units = len(ch.encode("utf-16-le")) // 2
        if count >= sent_units:
            out.append(ch)
            started = True
        elif count + units > sent_units:
            # The high surrogate was already typed. Skip the whole character.
            started = True
        count += units
    return "".join(out)


def _release_mods():
    alt_down = _vk_down(VK_MENU)
    if alt_down:
        _neutralize_alt_menu()
    if keyboard is None:
        return
    for name, vk in (("alt", VK_MENU), ("ctrl", 0x11), ("shift", 0x10)):
        down = _vk_down(vk)
        if down is None:
            try:
                down = keyboard.is_pressed(name)
            except Exception:
                down = False
        if not down:
            continue
        if name == "alt" and not alt_down:
            _neutralize_alt_menu()
        try:
            keyboard.release(name)
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
            if not _wait_mods_released(_MOD_WAIT_S):
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


def _cursor_previous_uia():
    """One character before the caret via UI Automation. Raises when the read fails."""
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


def _cursor_previous():
    """One character before the caret, '' at the start of the field, or None if it can't be read."""
    fault = None
    try:
        return _cursor_previous_uia()
    except Exception as exc:
        fault = exc
    try:
        edit = _edit_previous()
    except Exception as exc:
        edit = None
        fault = fault or exc
    if edit is not None:
        return edit
    if fault is not None:
        _log_cursor_fault(fault)
    return None


def previous_class(previous):
    """letter, number, space, punct, or none. The character itself is not logged."""
    if not previous:
        return "none"
    if str(previous).isspace():
        return "space"
    if any(ch.isalpha() for ch in str(previous)):
        return "letter"
    if any(ch.isdigit() for ch in str(previous)):
        return "number"
    return "punct"


def insert_dictation(text):
    """Space back-to-back dictations, then type. Calls are serialized so pastes stay in order."""
    raw = text or ""
    if not raw.strip():
        return
    with _insert_lock:
        read = _cursor_previous()
        if read is None:
            previous = _recent_insert_char()
            source = "last-insert" if previous else "none"
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
        kind = previous_class(previous)
        if not type_text(prepared):
            if _typed_prefix:
                _remember_insert(_typed_prefix)
            logs.event(f"insert: failed {len(prepared)} chars previous={source} class={kind}")
            return
        _remember_insert(prepared)
        logs.event(f"insert: {len(prepared)} chars leading-space={spaced} previous={source} class={kind}")


def _leave_on_clipboard(text):
    """Copy `text` and do not paste. The previous clipboard value is not restored."""
    if pyperclip is None:
        raise OSError("clipboard unavailable")
    pyperclip.copy(text)


def type_text(text):
    """Insert text at the cursor. Returns False when the text was not fully typed.

    A paste never runs while a modifier is held. Unicode typing is used while
    Ctrl is held, because a paste would become Ctrl+Alt+V. Alt alone turns
    that Unicode into a system character the target drops, so Alt is released
    or the call waits and then returns False instead of claiming success.
    If Unicode typing stops partway, only the untyped remainder is pasted, and
    only after the modifiers are up. If they stay down, that remainder is left
    on the clipboard and this returns False.
    """
    global _typed_prefix
    if not text:
        _typed_prefix = ""
        return False
    sent = 0
    _typed_prefix = ""
    _neutralize_alt_menu()
    if _alt_blocks_unicode():
        logs.event("type: Alt is held without Ctrl; waiting so the text is not dropped")
        if not _wait_alt_clear(2.0):
            logs.event("type: Alt stayed down; the text was not typed")
            try:
                _leave_on_clipboard(text)
            except Exception as e:
                logs.event(f"type: could not leave text on the clipboard: {e!r}")
                return False
            _notify("Alt was still held, so SayTray did not type. The dictation is on the clipboard.")
            return False
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
    _typed_prefix = text_before_units(text, sent)
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
