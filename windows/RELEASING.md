# Releasing SayTray (Windows)

For Jon: cut a shareable zip and upload it next to the macOS build.

## 1. Bump version

Edit `VERSION` (e.g. `1.0.1`). `install.ps1` stamps `saytray/_version.py` and the Add/Remove Programs entry from it.

## 2. Sanity check

```powershell
.\run_tests.ps1
.\install.ps1 -NoLaunch   # or full install
# Smoke: tray icon, About shows version, read a selection, hold dictate briefly
```

## 3. Package

```powershell
.\package_release.ps1
# → dist\SayTray-<VERSION>-Windows.zip
```

The zip is source + Install.cmd (no venv/voices). Recipients run Install.cmd once.

## 4. Upload

Attach the zip to the same **GitHub Release** as the macOS build (`SayTray-1.0.0-macOS.zip` + `SayTray-1.0.0-Windows.zip`).

## 5. Updating after ship

1. Change code / bump `VERSION`.
2. `.\package_release.ps1`
3. New GitHub Release with the new zip.
4. Users re-run Install.cmd; voices/settings stay in `%LOCALAPPDATA%\SayTray`.

## Publish a GitHub Release (Jbizzle88/SayTray)

Combined repo: https://github.com/Jbizzle88/SayTray

1. Bump `VERSION` in this platform folder (keep macos/ and windows/ in sync when shipping both).
2. Build the package (`./package_release.sh` here → `dist/SayTray-<VERSION>-macOS.zip`).
3. Copy the zip into the combined repo `dist/` (or build Windows too), then:

```bash
gh release create v1.0.1 \
  --repo Jbizzle88/SayTray \
  --title "SayTray 1.0.1" \
  --notes-file RELEASE_NOTES.md \
  dist/SayTray-1.0.1-macOS.zip \
  dist/SayTray-1.0.1-Windows.zip
```

Include in the notes: Mac Gatekeeper right-click → Open; Mac Accessibility / Microphone / Speech Recognition; Windows default-mic tip; first-run ~170 MB voice download (Norman + LJSpeech).

Tag format: `vMAJOR.MINOR.PATCH`.
