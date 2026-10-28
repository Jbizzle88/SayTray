"""Start with Windows.

The Startup-folder shortcut is created from this process. A behavior shield
flags a shell that writes into the Startup folder. If that write is blocked,
SayTray uses the
per-user Run key instead and says so.
"""
import os
from . import logs
from .logs import ROOT

STARTUP = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup",
    "SayTray.lnk",
)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "SayTray"
BLOCKED_MESSAGE = (
    "SayTray couldn't turn on launch at startup. Antivirus or folder permissions "
    "blocked the Startup shortcut and the registry Run key. Open Avast or AVG, "
    "choose Menu, then Quarantine, and restore SayTray.lnk, install.ps1, and "
    "uninstall.ps1 if they are listed. Allow the folder %LOCALAPPDATA%\\SayTray "
    "in the antivirus and in Windows Security exclusions, then turn Start with "
    "Windows on again from SayTray's settings."
)


def _command(target, args):
    return f'"{target}" {args}'


def _run_present():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
            return True
    except Exception:
        return False


def _set_run_value(target, args):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _command(target, args))


def _clear_run_value():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except FileNotFoundError:
        return
    except OSError:
        raise


def _write_shortcut(lnk, target, args, workdir):
    """Write one .lnk. Returns an error string, or '' when the file is there."""
    icon = os.path.join(ROOT, "app", "saytray.ico")
    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
    except OSError as e:
        return f"could not create the folder ({e})"
    try:
        import comtypes.client
        shell = comtypes.client.CreateObject("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk)
        shortcut.TargetPath = target
        shortcut.Arguments = args
        shortcut.WorkingDirectory = workdir
        shortcut.IconLocation = icon
        shortcut.Save()
    except Exception as e:
        err = f"{e!r}"
    else:
        err = ""
    if os.path.exists(lnk):
        return ""
    return err or "the shortcut file was missing after writing it"


def _paths():
    target = os.path.join(ROOT, "venv", "Scripts", "pythonw.exe")
    args = '"%s"' % os.path.join(ROOT, "app", "run_saytray.pyw")
    workdir = os.path.join(ROOT, "app")
    return target, args, workdir


def enabled(shortcut_path=None, run_present=None):
    path = STARTUP if shortcut_path is None else shortcut_path
    present = _run_present if run_present is None else run_present
    return os.path.exists(path) or bool(present())


def set_enabled(on, shortcut_path=None, write_shortcut=None, set_run=None, clear_run=None, run_present=None):
    """Turn launch-at-startup on or off. Returns (ok, message).

    message is for a one-time tray notice when it cannot be turned on.
    """
    path = STARTUP if shortcut_path is None else shortcut_path
    write = _write_shortcut if write_shortcut is None else write_shortcut
    remember = _set_run_value if set_run is None else set_run
    forget = _clear_run_value if clear_run is None else clear_run
    present = _run_present if run_present is None else run_present
    target, args, workdir = _paths()
    if not on:
        errors = []
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                errors.append(str(e))
        try:
            forget()
        except OSError as e:
            errors.append(str(e))
        if errors:
            logs.event("startup: could not turn off launch at startup: " + "; ".join(errors))
            return False, ""
        return True, ""
    err = write(path, target, args, workdir)
    if os.path.exists(path):
        try:
            forget()
        except OSError:
            pass
        return True, ""
    logs.event(f"startup: shortcut could not be created ({err})")
    try:
        remember(target, args)
    except OSError as e:
        logs.event(f"startup: run key could not be set ({e})")
        return False, BLOCKED_MESSAGE
    if not present():
        logs.event("startup: run key could not be set (missing after write)")
        return False, BLOCKED_MESSAGE
    logs.event("startup: using the registry Run key because the Startup shortcut was blocked")
    return True, ""
