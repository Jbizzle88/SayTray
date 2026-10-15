# SayTray

Free, offline menu-bar text-to-speech and push-to-talk dictation for macOS.

- **Read selected text aloud** with local Piper neural voices (Ryan high default)
- **Hold a hotkey to dictate** — text is typed at the cursor
- Speed control, voice picker, hotkey rebinding, launch at login, permission status, dictation chimes

Works fully offline after the one-time Piper voice download. No account, no cloud.

**Version:** see `VERSION` (currently 1.0.0) · **Requires:** macOS 14+

---

## Install (download zip)

1. Unzip `SayTray-*-macOS.zip`.
2. Double-click **Setup Piper Voices.command** (one-time; downloads ~360 MB of voices and creates a local Python venv). Needs [Python 3.10+](https://www.python.org/downloads/).
3. Copy `SayTray.app` into `~/Applications` (or `/Applications`).
4. **First launch (Gatekeeper):** right-click `SayTray.app` → **Open** → Open.  
   SayTray is signed with a local self-signed certificate, **not** Apple notarized. macOS will warn once; after you Open it, future launches are normal.
5. Grant **Accessibility**, **Microphone**, and **Speech Recognition** when prompted (or in Settings → SayTray).

### Install from source

```bash
cd SayTray
./support/setup_piper.sh   # once
./build.sh                 # builds, signs, installs to ~/Applications/SayTray.app
```

---

## Hotkeys (defaults)

| Action | Shortcut |
|--------|----------|
| Read selected text | **⌥\`** (Option + backtick) |
| Dictate (hold) | **⌥Space** (hold Option + Space) |

Change them in **Settings…** from the menu-bar icon.

---



### Permissions after rename / new bundle id

SayTray uses bundle id `com.jonbecherer.saytray`. That is different from SpeakBar (`com.jonbecherer.speakbar`), so macOS treats it as a **new app**. After installing, **re-grant** in **System Settings → Privacy & Security**:

1. **Accessibility** — read selection + type dictation  
2. **Microphone** — dictation  
3. **Speech Recognition** — dictation  

Use **Settings… → Grant…** in SayTray, or toggle SayTray on under each pane. You can remove any leftover SpeakBar entries. (SayTray does not use Input Monitoring.)

## Permissions

| Permission | Why |
|------------|-----|
| Accessibility | Read the selection and type dictated text |
| Microphone | Dictation |
| Speech Recognition | Dictation (Apple on-device recognition) |

If a shortcut stops working after a rebuild with a different signing identity, re-grant Accessibility.

---

## Menu

- Read Selected Text / Stop Speaking  
- Speed slider  
- Settings…  
- **Open Logs Folder** → `~/Library/Logs/SayTray/`  
- **About SayTray** (shows version)  
- Quit  

---

## Update

Replace `SayTray.app` with a newer build (or re-run `./build.sh` from source). Your settings and Piper voices stay in Application Support. Then bump and rebuild — see `RELEASING.md`.

---

## Uninstall

Double-click **Uninstall SayTray.command**, or:

```bash
./uninstall.sh              # removes app + voices/logs
./uninstall.sh --keep-data  # keeps Application Support + Logs
```

Optional: `defaults delete com.jonbecherer.saytray`

---

## Notes

- Piper voices live in `~/Library/Application Support/SayTray/piper/` (~360 MB voices + venv). They are **not** inside the zip so the download stays small.
- If Piper isn’t set up, SayTray falls back to a macOS system voice.
- Logs: `~/Library/Logs/SayTray/` (`events.log`, `guard.log`, `helper.log`, `last/`).

## License / credits

SayTray by Jon Becherer. TTS via [Piper](https://github.com/OHF-voice/piper1-gpl) (piper-tts). Voices from the rhasspy/piper-voices collection on Hugging Face.
