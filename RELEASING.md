# Releasing SayTray

1. Bump `VERSION` in `macos/` and `windows/` (same semver).
2. On a Mac: `cd macos && ./package_release.sh` → `dist/SayTray-<V>-macOS.zip`
3. On Windows: `cd windows; .\package_release.ps1` → `dist/SayTray-<V>-Windows.zip`
4. Copy both zips into this repo’s `dist/`, commit if desired, then:

```bash
gh release create vX.Y.Z \
  --repo Jbizzle88/SayTray \
  --title "SayTray X.Y.Z" \
  --notes-file - \
  dist/SayTray-X.Y.Z-macOS.zip \
  dist/SayTray-X.Y.Z-Windows.zip <<'NOTES'
## SayTray X.Y.Z

### macOS
- Gatekeeper: right-click the app → Open (self-signed, not notarized).
- Grant Accessibility, Microphone, and Speech Recognition in System Settings → Privacy & Security.

### Windows
- Set your real microphone as the Windows default input (avoid Oculus/Steam virtual devices).

### First run (both)
- Piper voices download once (~360 MB) via Setup Piper Voices (Mac) or Install.cmd (Windows).
NOTES
```
