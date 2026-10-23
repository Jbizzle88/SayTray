# SayTray (Windows)

Free, offline system-tray text-to-speech and push-to-talk dictation.

- **Read selected text aloud** with local Piper neural voices (Norman medium default, LJSpeech high included)
- **Hold a hotkey to dictate** — text is typed at the cursor (faster-whisper, local)
- Speed control, voice picker, hotkey rebinding, start with Windows, dictation chimes

Works fully offline after install downloads voices and Python packages. No account, no cloud.

**Version:** see `VERSION` (currently 1.1.0) · **Requires:** Windows 10/11, Python 3.10+

---

## Install (download zip)

1. Unzip `SayTray-*-Windows.zip`.
2. Double-click **Install.cmd** (or run `powershell -File install.ps1`). If Windows says scripts are disabled, run `powershell -ExecutionPolicy RemoteSigned -File install.ps1`.
3. First install downloads Python packages + about **170 MB** of Piper voices (Norman and LJSpeech) into `%LOCALAPPDATA%\SayTray`.
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

Download a newer zip and run **Install.cmd** again (or `install.ps1`). Settings are kept. Re-running install downloads Norman and LJSpeech if they are missing (~170 MB) and deletes the old Ryan, Lessac, Amy, and LibriTTS-R files if they are still in the voices folder. A saved voice that SayTray no longer ships falls back to Norman. Optional voices (Kristin, John, Cori, LibriTTS, Bryce, Jenny (Dioco)) download from the Voice menu or Settings. See `RELEASING.md` for cutting a new build.

---

## Uninstall

- **Settings → Apps → SayTray → Uninstall**, or  
- Run `uninstall.ps1` from the zip / `%LOCALAPPDATA%\SayTray\app\uninstall.ps1`

Uninstall stops SayTray, removes the program files, shortcuts, and the startup Run key, and keeps `settings.json` and downloaded voices. `-KeepSettings` does the same.

---

## Logs

`%LOCALAPPDATA%\SayTray\Logs` (`events.log`, `guard.log`). Dictation text is not written there. The last read's audio is kept only while `SAYTRAY_DEBUG=1`.

Debug drop files: `%LOCALAPPDATA%\SayTray\debug` (`speak.txt`, `dictate_start`, `dictate_stop`).

## If Avast or AVG quarantines SayTray

An install that stops the app, replaces files, and writes a Startup shortcut can be treated as suspicious. If `install.ps1`, `uninstall.ps1`, or `SayTray.lnk` disappear, or a later launch says it could not turn on startup:

1. Open Avast or AVG → Menu → Quarantine.
2. Restore those files and report the detection as a false positive.
3. Allow `%LOCALAPPDATA%\SayTray` (Avast exception, and Windows Security → Exclusions).
4. Run the installer again.

The installer checks that the shortcuts exist and, if the Startup shortcut is blocked, saves launch-at-startup under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

---

## Notes

- Clipboard restore after “read selection” is plain text only (images/rich content may be lost).
- If Piper fails, or the selected voice is not downloaded, SayTray uses Norman when that file is installed, then a Windows SAPI voice.
- **Voices:** Norman (medium, default, male US), LJSpeech (high, female US). Optional: Kristin (medium), John (medium), Cori (high, UK), LibriTTS (high; Speaker 1 (Female), Speaker 2 (Male), Speaker 3 (Female)), Bryce (medium), and Jenny (Dioco). Sizes are shown next to voices that are not downloaded yet.

## License / credits

SayTray by Jon Becherer. TTS via [Piper](https://github.com/OHF-voice/piper1-gpl) (piper-tts 1.8.0, GPL-3.0-or-later) and espeak-ng (GPL-3.0-or-later). Dictation via faster-whisper. Voice licenses, the LibriTTS CC BY 4.0 credit, and the Jenny (Dioco) credit are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
