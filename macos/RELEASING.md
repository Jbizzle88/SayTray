# Releasing SayTray (macOS)

For Jon: how to cut a new shareable build and upload it somewhere people can download.

## 1. Bump version

Edit `VERSION` to the new semver, e.g. `1.0.1`.  
`build.sh` reads it into `CFBundleShortVersionString` / `CFBundleVersion`.

## 2. Sanity check

```bash
./run_tests.sh          # TextPrep unit tests + pipeline
./build.sh              # install to ~/Applications
# Smoke: launch, About shows new version, read a selection, hold dictate briefly
```

## 3. Package

```bash
./package_release.sh
# → dist/SayTray-<VERSION>-macOS.zip
```

Contents: `SayTray.app`, Setup Piper Voices, Uninstall, README. Voices are **not** bundled (users run Setup once).

## 4. Upload (you do this)

Suggested host: **GitHub Releases** on a public repo.

1. Create a GitHub repo (e.g. `SayTray`) and push this tree (or only `dist/` + README).
2. Tag `v1.0.0` and create a Release.
3. Attach `dist/SayTray-1.0.0-macOS.zip` (and the Windows zip when ready).
4. Paste the Release URL wherever you want people to download.

No Apple Developer Program / notarization in v1 — document the **right-click → Open** Gatekeeper step in the Release notes (already in README).

Later, if you join the Apple Developer Program ($99/yr), you can sign with a Developer ID and notarize so Gatekeeper is silent.

## 5. Updating after ship

1. Change code / bump `VERSION`.
2. `./package_release.sh`
3. Upload the new zip to a new GitHub Release (e.g. `v1.0.1`).
4. Users replace the `.app`; Piper data stays put.

Do **not** commit secrets or the local signing private key into the public repo.

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
