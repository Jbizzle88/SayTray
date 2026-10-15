# SayTray (Windows)

Free, offline system-tray text-to-speech and push-to-talk dictation.

- **Read selected text aloud** with local Piper neural voices (Ryan high default)
- **Hold a hotkey to dictate** — text is typed at the cursor (faster-whisper, local)
- Speed control, voice picker, hotkey rebinding, start with Windows, dictation chimes

Works fully offline after install downloads voices and Python packages. No account, no cloud.

**Version:** see `VERSION` (currently 1.0.0) · **Requires:** Windows 10/11, Python 3.10+

---

## Install (download zip)

1. Unzip `SayTray-*-Windows.zip`.
2. Double-click **Install.cmd** (or run `powershell -ExecutionPolicy Bypass -File install.ps1`).
3. First install downloads Python packages + ~360 MB of Piper voices into `%LOCALAPPDATA%\SayTray`.
4. SayTray appears in the tray and Start Menu; it also registers under **Settings → Apps** (per-user).

### Mic tip (important for dictation)

Set your **real microphone** as the Windows default input device. If the default is an Oculus / Steam / virtual cable device, dictation will hear silence or garbage.

---

## Hotkeys (defaults)

| Action | Shortcut |
|--------|----------|
| Read selected text | **Alt+`** |
| Dictate (hold) | **Ctrl+Alt+Space** (Alt+Space is reserved by Windows) |

Change them in **Settings…** from the tray menu.

Some apps running as Administrator can block global hotkeys unless SayTray is also elevated.

---

## Menu

- Read selected text / Stop speaking  
- Speed / Voice  
- Settings…  
- Open logs folder  
- **About SayTray** (shows version)  
- Quit  

---

## Update

Download a newer zip and run **Install.cmd** again (or `install.ps1`). Settings and voices are kept. See `RELEASING.md` for cutting a new build.

---

## Uninstall

- **Settings → Apps → SayTray → Uninstall**, or  
- Run `uninstall.ps1` from the zip / `%LOCALAPPDATA%\SayTray\app\uninstall.ps1`

`uninstall.ps1 -KeepSettings` keeps `settings.json`.

---

## Logs

`%LOCALAPPDATA%\SayTray\Logs` (`events.log`, `guard.log`, `last\`).

Debug drop files: `%LOCALAPPDATA%\SayTray\debug` (`speak.txt`, `dictate_start`, `dictate_stop`).

---

## Notes

- Clipboard restore after “read selection” is plain text only (images/rich content may be lost).
- If Piper fails, SayTray falls back to a Windows SAPI voice.

## License / credits

SayTray by Jon Becherer. TTS via [Piper](https://github.com/OHF-voice/piper1-gpl). Dictation via faster-whisper. Voices from rhasspy/piper-voices on Hugging Face.
