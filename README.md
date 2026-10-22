# SayTray

**Free, offline text-to-speech + push-to-talk dictation** for macOS (menu bar) and Windows (system tray).

- Read selected text aloud with local [Piper](https://github.com/OHF-voice/piper1-gpl) neural voices
- Hold a hotkey to dictate — text is typed at the cursor
- Speed control, voice picker, hotkey rebinding, launch at login/startup, dictation chimes
- No account, no cloud (after a one-time voice download)

**Current source version:** 1.1.0

Build from source with the macOS and Windows READMEs. The v1.0.0 zip files on the GitHub release install an older voice set (including voices this build no longer ships) and are not the install for this version. A 1.1.0 package is published from `package_release.sh` / `package_release.ps1` when a release is cut.

All releases: https://github.com/Jbizzle88/SayTray/releases

### First run (both platforms)

Piper voices are **not** inside the zip. Setup downloads two voices the first time (**about 170 MB**): **Norman (medium)**, the default, and **LJSpeech (high)**. More commercially licensed voices (Kristin, John, Cori, LibriTTS, Bryce, and Jenny (Dioco)) download later from the voice list inside the app. They are stored in your user Application Support / LocalAppData folder.

### macOS notes

1. Unzip, run **Setup Piper Voices**, copy `SayTray.app` to `~/Applications` (or `/Applications`).
2. **Gatekeeper:** the app is self-signed, not Apple-notarized. First open: **right-click → Open → Open**.
3. **Permissions** (System Settings → Privacy & Security): grant **Accessibility**, **Microphone**, and **Speech Recognition**.

Defaults: **⌥\`** read · **⌥Space** (hold) dictate.

### Windows notes

1. Unzip, double-click **Install.cmd** (needs Python 3.10+ on PATH).
2. Set your **real microphone** as the Windows default input (avoid Oculus/Steam virtual devices).
3. Appears in the tray + Start Menu; uninstall from Settings → Apps.

Defaults: **Alt+\`** read · **Ctrl+Alt+Space** (hold) dictate.

## Source layout

```
macos/     Swift package + build/package scripts
windows/   Python tray app + Install.cmd / install.ps1
dist/      Packaged zips (also attached to GitHub Releases)
```

Platform-specific install docs: [`macos/README.md`](macos/README.md), [`windows/README.md`](windows/README.md).  
How to cut a new release: [`macos/RELEASING.md`](macos/RELEASING.md) / [`windows/RELEASING.md`](windows/RELEASING.md).

## License

MIT — see [LICENSE](LICENSE). Piper (GPL-3.0-or-later), espeak-ng (GPL-3.0-or-later), and the voice models have their own licenses — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). LibriTTS is CC BY 4.0. The optional Irish/UK voice is labeled Jenny (Dioco).
