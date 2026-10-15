"""Settings window (tkinter, own thread)."""
import threading
import tkinter as tk
from tkinter import ttk
from .config import installed_voices, pretty_voice
from . import sapi, startup

_open = [False]


def show(settings, on_saved, test_speak):
    if _open[0]:
        return
    _open[0] = True
    threading.Thread(target=_run, args=(settings, on_saved, test_speak), daemon=True).start()


def _run(settings, on_saved, test_speak):
    try:
        root = tk.Tk()
        root.title("SayTray Settings")
        root.resizable(False, False)
        f = ttk.Frame(root, padding=14)
        f.grid()
        r = 0
        def row(label, widget):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=4)
            widget.grid(row=r, column=1, sticky="we", pady=4)
            r += 1

        read_v = tk.StringVar(value=settings["read_hotkey"])
        dict_v = tk.StringVar(value=settings["dictate_hotkey"])
        def recorder(var):
            fr = ttk.Frame(f)
            ttk.Entry(fr, textvariable=var, width=22).pack(side="left")
            def rec():
                import keyboard
                var.set("press keys…")
                def grab():
                    var.set(keyboard.read_hotkey(suppress=False))
                threading.Thread(target=grab, daemon=True).start()
            ttk.Button(fr, text="Record", command=rec).pack(side="left", padx=4)
            return fr
        row("Read selected text", recorder(read_v))
        row("Dictate (hold)", recorder(dict_v))

        vmap = {pretty_voice(v): v for v in installed_voices()}
        voice_v = tk.StringVar(value=pretty_voice(settings["voice"]))
        row("Piper voice", ttk.Combobox(f, textvariable=voice_v, values=list(vmap), state="readonly", width=30))
        sv = sapi.voices()
        sapi_v = tk.StringVar(value=settings["sapi_voice"] or (sv[0] if sv else ""))
        row("Fallback Windows voice", ttk.Combobox(f, textvariable=sapi_v, values=sv, state="readonly", width=30))

        speed_v = tk.DoubleVar(value=settings["speed"])
        sf = ttk.Frame(f)
        lbl = ttk.Label(sf, text=f"{settings['speed']:.1f}x", width=5)
        sc = ttk.Scale(sf, from_=0.5, to=2.0, variable=speed_v, length=200,
                       command=lambda v: lbl.config(text=f"{round(float(v) * 10) / 10:.1f}x"))
        sc.pack(side="left"); lbl.pack(side="left")
        row("Speed", sf)

        start_v = tk.BooleanVar(value=startup.enabled())
        row("", ttk.Checkbutton(f, text="Start with Windows", variable=start_v))
        chime_v = tk.BooleanVar(value=bool(settings["chime"]))
        row("", ttk.Checkbutton(f, text="Play chime when dictation starts and stops", variable=chime_v))
        ttk.Label(f, text="Dictation is push-to-talk: hold the shortcut, speak, release to type at the cursor.",
                  foreground="#666").grid(row=r, column=0, columnspan=2, sticky="w"); r += 1

        def save(close=True):
            settings.set(read_hotkey=read_v.get().strip() or "alt+`", dictate_hotkey=dict_v.get().strip() or "ctrl+alt+space",
                         voice=vmap.get(voice_v.get(), settings["voice"]), sapi_voice=sapi_v.get(),
                         speed=round(float(speed_v.get()) * 10) / 10, start_with_windows=bool(start_v.get()), chime=bool(chime_v.get()))
            startup.set_enabled(bool(start_v.get()))
            on_saved()
            if close:
                root.destroy()
        bf = ttk.Frame(f); bf.grid(row=r, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(bf, text="Test voice", command=lambda: (save(False), test_speak("Hello Jon. This is SayTray, reading at the current speed."))).pack(side="left", padx=4)
        ttk.Button(bf, text="Save", command=save).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=root.destroy).pack(side="left")
        root.attributes("-topmost", True); root.after(300, lambda: root.attributes("-topmost", False))
        root.mainloop()
    finally:
        _open[0] = False
