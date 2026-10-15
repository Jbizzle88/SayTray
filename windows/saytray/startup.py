"""Start-with-Windows: a shortcut in the user's Startup folder."""
import os, subprocess
from .logs import ROOT

STARTUP = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "SayTray.lnk")


def make_shortcut(lnk, target, args, workdir):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='%s';"
          "$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()") % (lnk, target, args.replace("'", "''"), workdir,
                                                                     os.path.join(ROOT, "app", "saytray.ico"))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=0x08000000)


def set_enabled(on):
    if on:
        make_shortcut(STARTUP, os.path.join(ROOT, "venv", "Scripts", "pythonw.exe"),
                      '"%s"' % os.path.join(ROOT, "app", "run_saytray.pyw"), os.path.join(ROOT, "app"))
    elif os.path.exists(STARTUP):
        os.remove(STARTUP)


def enabled():
    return os.path.exists(STARTUP)
