"""SayTray for Windows: system tray app. Read selection (Alt+`), Piper TTS with babble guard,
push-to-talk dictation (hold Ctrl+Alt+Space)."""
import os, sys, threading, time, ctypes
from PIL import Image, ImageDraw
import pystray
from .config import Settings
from .speaker import Speaker
from .dictation import Dictation
from .hotkeys import Hotkeys
from .selection import read_selection
from .voices import (default_voice, downloads, format_size, installed_ids, normalize_speaker,
                     on_after_delete, on_before_delete, pretty_voice, remove_retired_voices, voice_size, voices)
from . import logs, settings_ui, startup

DEBUG_DIR = os.path.join(logs.ROOT, "debug")


# BRANDED_ICO: prefer assets/SayTray.ico (or app/saytray.ico) for idle; tinted overlays for state.
_BRANDED = None

def _branded_base():
    global _BRANDED
    if _BRANDED is not None:
        return _BRANDED
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "assets", "SayTray.ico"),
        os.path.join(os.path.dirname(__file__), "..", "saytray.ico"),
        os.path.join(logs.ROOT, "app", "saytray.ico"),
    ]
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.isfile(path):
            try:
                _BRANDED = Image.open(path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
                return _BRANDED
            except Exception:
                pass
    _BRANDED = False
    return None

def _icon(state):
    base = _branded_base()
    if base:
        img = base.copy()
        if state == "speaking":
            overlay = Image.new("RGBA", img.size, (40, 170, 90, 60))
            img = Image.alpha_composite(img, overlay)
        elif state == "recording":
            overlay = Image.new("RGBA", img.size, (225, 50, 50, 80))
            img = Image.alpha_composite(img, overlay)
            d = ImageDraw.Draw(img)
            d.ellipse((44, 4, 60, 20), fill=(225, 50, 50, 255), outline="white")
        return img
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = {"idle": (22, 120, 140), "speaking": (40, 170, 90), "recording": (225, 50, 50)}[state]
    d.rounded_rectangle((4, 6, 60, 46), radius=12, fill=color)
    d.polygon([(16, 44), (30, 44), (14, 60)], fill=color)
    if state == "recording":
        d.rounded_rectangle((26, 12, 38, 34), radius=6, fill="white"); d.rectangle((31, 34, 33, 40), fill="white")
    else:
        for i, h in enumerate((10, 18, 12)):
            x = 20 + i * 10
            d.rectangle((x, 26 - h // 2, x + 5, 26 + h // 2), fill="white")
    return img


class App:
    def __init__(self):
        self.settings = Settings()
        remove_retired_voices()
        self.speaker = Speaker(self.settings)
        self.dictation = Dictation(player=self.speaker.player, settings=self.settings)
        self.hotkeys = Hotkeys()
        self.speaker.on_state = self._update_icon
        self.dictation.on_state = self._update_icon
        on_before_delete(self._before_delete_voice)
        on_after_delete(self._after_delete_voice)
        downloads.add_listener(self._download_update)
        self.icon = pystray.Icon("SayTray", _icon("idle"), "SayTray", menu=self._menu())

    # actions
    def read(self):
        if self.speaker.speaking:
            self.speaker.stop()
            return
        def work():
            t = read_selection()
            if t:
                self.speaker.speak(t)
        threading.Thread(target=work, daemon=True).start()

    def _register(self):
        self.hotkeys.register(self.settings["read_hotkey"], self.read, self.settings["dictate_hotkey"],
                              lambda: threading.Thread(target=self.dictation.start, daemon=True).start(),
                              lambda: threading.Thread(target=self.dictation.stop, daemon=True).start())

    def _saved(self):
        self._register()
        self.speaker.warm_up()
        self.icon.menu = self._menu(); self.icon.update_menu()

    def _update_icon(self):
        st = "recording" if self.dictation.recording else ("speaking" if self.speaker.speaking else "idle")
        try:
            self.icon.icon = _icon(st)
            self.icon.title = {"idle": "SayTray", "speaking": "SayTray: speaking", "recording": "SayTray: listening"}[st]
        except Exception:
            pass

    def _before_delete_voice(self, voice_id):
        s = self.settings
        if s["voice"] == voice_id:
            nxt = next((i for i in installed_ids() if i != voice_id), default_voice())
            s.set(voice=nxt, speaker=normalize_speaker(nxt, s.data.get("speaker")) or 0)
        self.speaker.engine.release(voice_id)

    def _after_delete_voice(self, voice_id):
        self._saved()

    def _download_update(self, voice_id, status):
        try:
            if status.get("state") == "done":
                self.settings.set(voice=voice_id, speaker=normalize_speaker(voice_id, 0) or 0)
                self.speaker.warm_up()
                try:
                    self.icon.notify(f"{pretty_voice(voice_id)} is ready.", "SayTray")
                except Exception:
                    pass
            self.icon.menu = self._menu()
            self.icon.update_menu()
        except Exception:
            pass

    def _voice_menu(self):
        s = self.settings
        items = []
        active = downloads.active()
        if active:
            vid, st = active[0]
            items.append(pystray.MenuItem(f"{pretty_voice(vid)}: {st.get('message') or 'Downloading…'}", None, enabled=False))
        for v in voices():
            vid = v["id"]
            label = pretty_voice(vid)
            if vid in installed_ids():
                speakers = v.get("speakers") or []
                if speakers:
                    def set_sp(sid, vid=vid):
                        return lambda icon, item: (s.set(voice=vid, speaker=sid), self._saved())
                    items.append(pystray.MenuItem(label, pystray.Menu(*[
                        pystray.MenuItem(sp["label"], set_sp(sp["id"]), radio=True,
                                         checked=lambda i, vid=vid, sid=sp["id"]: s["voice"] == vid and int(s.data.get("speaker") or 0) == sid)
                        for sp in speakers
                    ])))
                else:
                    def set_voice(vid=vid):
                        return lambda icon, item: (s.set(voice=vid), self._saved())
                    items.append(pystray.MenuItem(label, set_voice(), radio=True, checked=lambda i, vid=vid: s["voice"] == vid))
            else:
                st = downloads.status(vid)
                if st.get("state") == "downloading":
                    title = f"{label} — {st.get('message') or 'Downloading…'}"
                elif st.get("state") == "error":
                    title = f"{label} — {st.get('message')}"
                else:
                    title = f"{label} — {format_size(voice_size(v))}"
                def start(vid=vid):
                    return lambda icon, item: downloads.start(vid)
                items.append(pystray.MenuItem(title, start()))
        return pystray.Menu(*items)

    def _menu(self):
        s = self.settings
        def set_speed(v):
            return lambda icon, item: (s.set(speed=v), self._saved())
        speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        return pystray.Menu(
            pystray.MenuItem(f"Read selected text ({s['read_hotkey']})", lambda: self.read(), default=True),
            pystray.MenuItem("Stop speaking", lambda: self.speaker.stop()),
            pystray.MenuItem(f"Hold {s['dictate_hotkey']} to dictate", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Speed", pystray.Menu(*[pystray.MenuItem(f"{v:g}x", set_speed(v), checked=lambda i, v=v: abs(s["speed"] - v) < 0.01, radio=True) for v in speeds])),
            pystray.MenuItem("Voice", self._voice_menu()),
            pystray.MenuItem("Settings…", lambda: settings_ui.show(s, self._saved, self.speaker.speak)),
            pystray.MenuItem("Open logs folder", lambda: os.startfile(logs.LOGS)),
            pystray.MenuItem("About SayTray", self._about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit SayTray", self._quit),
        )

    def _about(self, icon=None, item=None):
        from . import __version__
        s = self.settings
        msg = (
            f"SayTray {__version__}\n\n"
            "Free offline tray text-to-speech and push-to-talk dictation.\n\n"
            f"Read: {s['read_hotkey']}\n"
            f"Dictate (hold): {s['dictate_hotkey']}\n\n"
            "Tip: set your real microphone as the Windows default input "
            "(avoid Oculus/Steam virtual devices) before dictating.\n\n"
            "Default voice: Norman. Optional voices include LibriTTS "
            "(CC BY 4.0, Zen et al.) and Jenny (Dioco).\n"
            "See THIRD_PARTY_NOTICES for Piper, espeak-ng, and voice licenses.\n\n"
            "© Jon Becherer"
        )
        def show():
            try:
                ctypes.windll.user32.MessageBoxW(None, msg, "About SayTray", 0x40)
            except Exception:
                pass
        threading.Thread(target=show, daemon=True).start()
    def _quit(self, icon=None, item=None):
        logs.event("quit")
        self.hotkeys.clear()
        try:
            self.dictation.shutdown()
        except Exception:
            pass
        try:
            downloads.shutdown()
        except Exception:
            pass
        self.speaker.stop()
        self.icon.stop()
        os._exit(0)

    def _debug_watch(self):
        """Debug/test triggers: drop speak.txt (text to read), dictate_start / dictate_stop into %LOCALAPPDATA%\\SayTray\\debug."""
        os.makedirs(DEBUG_DIR, exist_ok=True)
        while True:
            try:
                p = os.path.join(DEBUG_DIR, "speak.txt")
                if os.path.exists(p):
                    time.sleep(0.1)
                    t = open(p, encoding="utf-8").read(); os.remove(p)
                    logs.event("debug trigger: speak"); self.speaker.speak(t)
                for name, fn in (("dictate_start", self.dictation.start), ("dictate_stop", self.dictation.stop)):
                    q = os.path.join(DEBUG_DIR, name)
                    if os.path.exists(q):
                        os.remove(q); logs.event("debug trigger: " + name); fn()
            except Exception as e:
                logs.event(f"debug watcher error: {e!r}")
            time.sleep(0.3)

    def run(self):
        self._register()
        self.speaker.warm_up()
        if self.settings["start_with_windows"] and not startup.enabled():
            startup.set_enabled(True)
        threading.Thread(target=self._debug_watch, daemon=True).start()
        logs.event(f"launched; voice={self.settings['voice']} speed={self.settings['speed']} pid={os.getpid()}")
        self.icon.run()


def main():
    # single instance
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SayTraySingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:
        logs.event("another instance is running; exiting")
        return
    try:
        App().run()
    except Exception as e:
        import traceback
        logs.event("fatal: " + traceback.format_exc())
        raise
