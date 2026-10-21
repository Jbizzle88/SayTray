"""Settings window (tkinter, own thread)."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from .config import hotkey_ok, pretty_voice
from .voices import (by_id, default_voice, delete_voice, downloads, format_size, is_installed,
                     normalize_speaker, voice_size, voices)
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
        root.resizable(False, True)
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

        voice_v = tk.StringVar(value=settings["voice"])
        user_picked = {"on": False}
        box = ttk.LabelFrame(f, text="Piper voices", padding=8)
        box.grid(row=r, column=0, columnspan=2, sticky="we", pady=6)
        r += 1
        ttk.Label(box, text="Norman is the default. Other voices download when you ask (~size shown).",
                  foreground="#666").grid(row=0, column=0, columnspan=3, sticky="w")
        status_vars = {}
        buttons = {}
        for i, v in enumerate(voices()):
            vid = v["id"]
            ttk.Label(box, text=pretty_voice(vid), width=22).grid(row=i + 1, column=0, sticky="w", pady=2)
            status_vars[vid] = tk.StringVar()
            ttk.Label(box, textvariable=status_vars[vid], width=28).grid(row=i + 1, column=1, sticky="w")
            bf = ttk.Frame(box)
            bf.grid(row=i + 1, column=2, sticky="e")
            buttons[vid] = bf

        speaker_v = tk.StringVar()

        def choose(vid):
            user_picked["on"] = True
            voice_v.set(vid)

        def start_download(vid):
            downloads.start(vid)
            choose(vid)

        def do_delete(vid):
            if not messagebox.askyesno("Delete voice", f"Delete {pretty_voice(vid)}?\nYou can download it again."):
                return
            try:
                delete_voice(vid)
            except Exception as e:
                messagebox.showerror("SayTray", str(e))
                return
            voice_v.set(settings["voice"])

        button_mode = {}

        def paint():
            if not root.winfo_exists():
                return
            if not user_picked["on"]:
                saved_voice = settings["voice"]
                if saved_voice and voice_v.get() != saved_voice:
                    voice_v.set(saved_voice)
            for v in voices():
                vid = v["id"]
                st = downloads.status(vid)
                installed = is_installed(v)
                if installed and voice_v.get() == vid:
                    status_vars[vid].set("Selected")
                    mode = "selected"
                elif installed:
                    status_vars[vid].set("Installed - " + v.get("blurb", ""))
                    mode = "installed"
                elif st.get("state") == "downloading":
                    status_vars[vid].set(st.get("message") or "Downloading...")
                    mode = "downloading"
                elif st.get("state") == "error":
                    status_vars[vid].set(st.get("message") or "Download failed")
                    mode = "error"
                else:
                    status_vars[vid].set(f"{format_size(voice_size(v))} - {v.get('blurb', '')}")
                    mode = "available"
                if button_mode.get(vid) == mode:
                    continue
                button_mode[vid] = mode
                bf = buttons[vid]
                for child in bf.winfo_children():
                    child.destroy()
                if mode in ("selected", "installed"):
                    sps = v.get("speakers") or []
                    if sps:
                        labels = [s["label"] for s in sps]
                        box = ttk.Combobox(bf, textvariable=speaker_v, state="readonly", width=22, values=labels)
                        box.pack(side="left", padx=(0, 4))
                        if speaker_v.get() not in labels:
                            want = normalize_speaker(vid, settings.data.get("speaker"))
                            speaker_v.set(next((s["label"] for s in sps if s["id"] == want), labels[0]))
                        box.bind("<<ComboboxSelected>>", lambda _e, vid=vid: choose(vid))
                    if mode != "selected":
                        ttk.Button(bf, text="Use", width=8, command=lambda vid=vid: choose(vid)).pack(side="left")
                    if vid != default_voice():
                        ttk.Button(bf, text="Delete", width=8, command=lambda vid=vid: do_delete(vid)).pack(side="left", padx=2)
                elif mode == "downloading":
                    ttk.Button(bf, text="Cancel", width=10, command=lambda vid=vid: downloads.cancel(vid)).pack(side="left")
                else:
                    ttk.Button(bf, text="Download", width=10, command=lambda vid=vid: start_download(vid)).pack(side="left")
            root.after(400, paint)

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
        ttk.Label(f, text="Dictation is push-to-talk: hold the shortcut, speak, release to type at the cursor. You can keep holding the modifier and press the key again.",
                  foreground="#666").grid(row=r, column=0, columnspan=2, sticky="w"); r += 1

        def speaker_id():
            v = by_id(voice_v.get())
            sps = (v or {}).get("speakers") or []
            for s in sps:
                if s["label"] == speaker_v.get():
                    return int(s["id"])
            return normalize_speaker(voice_v.get(), settings.data.get("speaker")) or 0

        def save(close=True):
            read = read_v.get().strip()
            dictate = dict_v.get().strip()
            if not hotkey_ok(read):
                messagebox.showerror("SayTray", "That read shortcut isn't one SayTray can register.")
                return
            if not hotkey_ok(dictate):
                messagebox.showerror("SayTray", "That dictate shortcut isn't one SayTray can register.")
                return
            voice = voice_v.get() if user_picked["on"] else settings["voice"]
            settings.set(read_hotkey=read, dictate_hotkey=dictate,
                         voice=voice or settings["voice"], speaker=speaker_id(), sapi_voice=sapi_v.get(),
                         speed=round(float(speed_v.get()) * 10) / 10, start_with_windows=bool(start_v.get()), chime=bool(chime_v.get()))
            startup.set_enabled(bool(start_v.get()))
            on_saved()
            if close:
                root.destroy()
        bf = ttk.Frame(f); bf.grid(row=r, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(bf, text="Test voice", command=lambda: (save(False), test_speak("Hello Jon. This is SayTray, reading at the current speed."))).pack(side="left", padx=4)
        ttk.Button(bf, text="Save", command=save).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=root.destroy).pack(side="left")
        paint()
        root.attributes("-topmost", True); root.after(300, lambda: root.attributes("-topmost", False))
        root.mainloop()
    finally:
        _open[0] = False
