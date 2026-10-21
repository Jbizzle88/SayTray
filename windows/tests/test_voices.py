"""Catalog, fallback, and retired-voice tests. No Piper install required.

Also checks that every catalog URL answers (HEAD). Set SAYTRAY_SKIP_URLS=1 to skip that.
"""
import os, sys, json, tempfile, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray import voices

passes = failures = 0

def check(cond, msg):
    global passes, failures
    if cond:
        passes += 1
    else:
        failures += 1
        print("FAIL:", msg)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAC = os.path.join(ROOT, "macos", "Sources", "SayTray", "voices.json")
WIN = os.path.join(ROOT, "windows", "saytray", "voices.json")

check(open(MAC, "rb").read() == open(WIN, "rb").read(), "macOS and Windows catalogs are identical")

cat = voices.catalog()
ids = [v["id"] for v in voices.voices()]
check(cat["defaultVoice"] == "en_US-norman-medium", "default is Norman")
check(voices.default_voice() == "en_US-norman-medium", "default_voice()")
defaults = [v["id"] for v in voices.voices() if v.get("installByDefault")]
check(defaults == ["en_US-norman-medium", "en_US-ljspeech-high"], f"default downloads: {defaults}")
check(all(v["id"] != "jenny-dioco" or v["label"] == "Jenny (Dioco)" for v in voices.voices()), "Jenny label")
check(voices.pretty_voice("jenny-dioco") == "Jenny (Dioco)", "pretty Jenny")
check(voices.pretty_voice("en_US-norman-medium") == "Norman (medium)", "pretty Norman")

banned = ["en_US-ryan-high", "en_US-lessac-high", "en_US-amy-medium", "en_US-libritts_r-medium"]
check(cat.get("removed") == banned, f"removed list: {cat.get('removed')}")
check(not any(b in ids for b in banned), "banned voices are not in the catalog")

libri = voices.by_id("en_US-libritts-high")
check([s["id"] for s in libri["speakers"]] == [0, 2, 4], "LibriTTS speakers 0, 2, 4")
check([s["label"] for s in libri["speakers"]] == ["Speaker 1 (Female)", "Speaker 2 (Male)", "Speaker 3 (Female)"], "speaker labels")
check(voices.normalize_speaker("en_US-libritts-high", 2) == 2, "keep speaker 2")
check(voices.normalize_speaker("en_US-libritts-high", 1) == 0, "unknown speaker falls back to 0")
check(voices.normalize_speaker("en_US-libritts-high", None) == 0, "missing speaker falls back to 0")
check(voices.normalize_speaker("en_US-norman-medium", 2) is None, "Norman has no speaker")
check(voices.normalize_speaker("jenny-dioco", 0) is None, "Jenny has no speaker")

jenny = voices.by_id("jenny-dioco")
check(all("huggingface.co" not in f["url"] and f["url"].endswith(os.path.basename(f["url"])) for f in jenny["files"]), "Jenny URLs")
check(jenny["files"][0]["url"] == "https://sfo3.digitaloceanspaces.com/bkmdls/jenny.onnx", "Jenny onnx URL")
check(jenny["files"][1]["url"] == "https://sfo3.digitaloceanspaces.com/bkmdls/jenny.onnx.json", "Jenny json URL")
check("libritts_r" not in json.dumps(libri), "LibriTTS is not LibriTTS-R")
check(all(f["url"].startswith("https://") and f["sizeBytes"] > 0 and f["filename"] for v in voices.voices() for f in v["files"]), "urls and sizes")
import re
for v in voices.voices():
    for f in v["files"]:
        check("resolve/main/" not in f["url"], f"{f['filename']} is not a floating main URL")
        check(re.fullmatch(r"[0-9a-f]{64}", f.get("sha256") or "") is not None, f"{f['filename']} has a sha256")
pinned = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"
for v in voices.voices():
    if v["id"] == "jenny-dioco":
        continue
    for f in v["files"]:
        check(pinned in f["url"], f"{f['filename']} is pinned to {pinned[:8]}")

# 63,531,379 + 4,968 and 114,199,011 + 4,970 = 177,740,328 bytes = 170 MiB.
default_bytes = sum(voices.voice_size(v) for v in voices.voices() if v["installByDefault"])
check(default_bytes == 177740328, f"default download bytes {default_bytes}")
check(voices.format_size(default_bytes) == "170 MB", voices.format_size(default_bytes))
check(voices.format_size(voices.voice_size(voices.by_id("en_US-norman-medium"))) == "61 MB", "Norman size label")
check(voices.format_size(voices.voice_size(voices.by_id("en_US-ljspeech-high"))) == "109 MB", "LJSpeech size label")
check(voices.format_size(voices.voice_size(libri)) == "130 MB", "LibriTTS size label")

for saved in ["", None, "en_US-ryan-high", "en_US-lessac-high", "en_US-amy-medium", "en_US-libritts_r-medium", "nope"]:
    check(voices.resolve_saved_voice(saved) == "en_US-norman-medium", f"fallback {saved!r}")
for saved in ["en_US-norman-medium", "en_US-kristin-medium", "jenny-dioco", "en_US-libritts-high", "en_GB-cori-high"]:
    check(voices.resolve_saved_voice(saved) == saved, f"keep {saved}")

installed = {"en_US-norman-medium", "en_US-ljspeech-high"}
check(voices.playback_voice("en_US-kristin-medium", installed) == "en_US-norman-medium", "missing optional plays Norman")
check(voices.playback_voice("en_US-ljspeech-high", installed) == "en_US-ljspeech-high", "installed voice plays itself")
check(voices.playback_voice("en_US-norman-medium", set()) is None, "nothing installed")
check(voices.playback_voice("en_US-ryan-high", {"en_US-norman-medium"}) == "en_US-norman-medium", "retired id plays Norman when Norman is installed")

# Installers must not hard-code the old voices; they read the catalog.
for rel in ("macos/support/setup_piper.sh", "macos/package_release.sh", "windows/install.ps1", "windows/requirements.txt",
            "windows/saytray/config.py", "macos/Sources/SayTray/PipelineTest.swift", "windows/tests/pipeline_test.py"):
    text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    for b in banned:
        check(b not in text, f"{rel} still mentions {b}")
req = open(os.path.join(ROOT, "windows", "requirements.txt"), encoding="utf-8").read().splitlines()
check(any(line.strip() == "piper-tts==1.8.0" for line in req), "piper-tts pinned to 1.8.0")
check(not any(line.strip() == "piper-tts" for line in req), "unpinned piper-tts removed")

def write_voice(directory, voice_id):
    v = voices.by_id(voice_id)
    for f in v["files"]:
        path = os.path.join(directory, f["filename"])
        with open(path, "wb") as fh:
            fh.truncate(int(f["sizeBytes"]))
        sha = (f.get("sha256") or "").strip()
        if sha:
            with open(path + ".sha256", "w", encoding="utf-8") as fh:
                fh.write(sha + "\n")

with tempfile.TemporaryDirectory() as d:
    for voice_id in banned:
        open(os.path.join(d, voice_id + ".onnx"), "wb").write(b"x")
        open(os.path.join(d, voice_id + ".onnx.json"), "wb").write(b"{}")
    write_voice(d, "en_US-norman-medium")
    short = os.path.join(d, "en_US-ljspeech-high.onnx")
    with open(short, "wb") as fh:
        fh.truncate(4)
    check(not voices.is_installed(voices.by_id("en_US-ljspeech-high"), d), "short file is not an installed voice")
    check(voices.installed_ids(d) == ["en_US-norman-medium"], "retired files are not offered as voices")
    check(voices.playback_voice("en_US-ryan-high", voices.installed_ids(d)) == "en_US-norman-medium", "playback ignores retired files")
    gone = voices.remove_retired_voices(d)
    check(len(gone) == 8, f"removed {len(gone)} retired files")
    check(not any(os.path.exists(os.path.join(d, b + ".onnx")) for b in banned), "retired onnx gone")
    check(voices.installed_ids(d) == ["en_US-norman-medium"], f"installed after cleanup: {voices.installed_ids(d)}")
    refused = False
    try:
        voices.delete_voice("en_US-norman-medium", d)
    except ValueError:
        refused = True
    check(refused, "Norman cannot be deleted")
    check(voices.installed_ids(d) == ["en_US-norman-medium"], "Norman files stay after a delete attempt")
    voices.delete_voice("en_US-ljspeech-high", d)
    check(not os.path.exists(short), "a non-default voice can be deleted")
    norman = voices.by_id("en_US-norman-medium")
    small = next(f for f in norman["files"] if f["filename"].endswith(".onnx.json"))
    corrupt = os.path.join(d, small["filename"])
    os.remove(corrupt + ".sha256")
    check(not voices.file_trusted(corrupt, small["sizeBytes"], small["sha256"]), "a right-size file with no matching hash is not installed")
    check(not voices.is_installed(norman, d), "Norman is not installed when a file's hash does not match")
    voices.write_hash_marker(corrupt, small["sha256"])
    check(voices.file_trusted(corrupt, small["sizeBytes"], small["sha256"]), "a matching .sha256 marker is trusted")
    check(voices.is_installed(norman, d), "marker restores the installed check without re-reading the model")

def head(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "SayTray"})
    with urllib.request.urlopen(req, timeout=60) as r:
        length = int(r.headers.get("Content-Length") or 0)
        return r.status, length

if os.environ.get("SAYTRAY_SKIP_URLS") == "1":
    print("skipping URL checks")
else:
    for v in voices.voices():
        for f in v["files"]:
            try:
                status, length = head(f["url"])
                check(status == 200 and length == f["sizeBytes"], f"{f['filename']} HEAD {status} {length} != {f['sizeBytes']}")
            except Exception as e:
                check(False, f"{f['filename']} HEAD failed: {e}")

def _check_downloader():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    payload = b"voice-bytes"
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/sample.onnx":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, fmt, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "sample.onnx")
            voices.downloads._download(f"http://127.0.0.1:{server.server_address[1]}/sample.onnx", dest, 0, len(payload), len(payload), "sample")
            import hashlib
            good = hashlib.sha256(payload).hexdigest()
            voices.downloads._download(
                f"http://127.0.0.1:{server.server_address[1]}/sample.onnx",
                dest, 0, len(payload), len(payload), "sample", sha=good)
            check(open(dest, "rb").read() == payload, "downloader writes the response")
            check(open(dest + ".sha256", encoding="utf-8").read().strip() == good, "downloader writes the hash marker")
            mismatch = os.path.join(d, "mismatch.onnx")
            bad_hash = False
            bad_msg = ""
            try:
                voices.downloads._download(
                    f"http://127.0.0.1:{server.server_address[1]}/sample.onnx",
                    mismatch, 0, len(payload), len(payload), "mismatch", sha="0" * 64)
            except Exception as e:
                bad_hash = True
                bad_msg = str(e)
            check(bad_hash and "checksum" in bad_msg, f"checksum mismatch rejected: {bad_msg}")
            check(not os.path.exists(mismatch) and not os.path.exists(mismatch + ".partial"), "bad checksum leaves no file")
            short = os.path.join(d, "short.onnx")
            rejected = False
            message = ""
            try:
                voices.downloads._download(
                    f"http://127.0.0.1:{server.server_address[1]}/sample.onnx",
                    short, 0, 100, 100, "short")
            except Exception as e:
                rejected = True
                message = str(e)
            check(rejected and "incomplete" in message, f"short body rejected: {message}")
            check(not os.path.exists(short) and not os.path.exists(short + ".partial"), "short download leaves no file")
            check(voices.size_matches(len(payload), len(payload)), "exact size matches")
            check(not voices.size_matches(len(payload) - 1, len(payload)), "short size does not match")
            check(not voices.size_matches(0, 0), "empty file is not a match when size is unknown")
            missing = os.path.join(d, "missing.onnx")
            failed = False
            try:
                voices.downloads._download(f"http://127.0.0.1:{server.server_address[1]}/nope", missing, 0, 1, 1, "missing")
            except Exception:
                failed = True
            check(failed and not os.path.exists(missing) and not os.path.exists(missing + ".partial"), "failed download leaves no file")
    finally:
        server.shutdown()

_check_downloader()

def _check_cancel():
    vid = "en_US-kristin-medium"
    dl = voices.Downloads()
    try:
        dl._current = "busy"
        dl._cancel.add(vid)
        dl.start(vid)
        check(vid not in dl._cancel, "starting a download clears a stale cancel flag")
        check(vid in dl._queue, "the voice is queued again")
        check(dl._current == "busy", "a busy worker is not replaced")
        dl.cancel(vid)
        check(dl.status(vid)["state"] == "idle", "cancelling a queued voice returns it to idle")
        check(vid not in dl._cancel and vid not in dl._queue, "a queued cancel is not remembered")
        dl.start(vid)
        check(vid in dl._queue and vid not in dl._cancel, "download works again after cancel")
        dl._queue = [v for v in dl._queue if v != vid]
        dl._status[vid] = {"state": "done", "fraction": 1.0, "message": "Downloaded"}
        dl.cancel(vid)
        check(vid not in dl._cancel, "a late cancel is ignored")
        check(dl.status(vid)["state"] == "done", "a late cancel does not mark the voice as failed")
        other = voices.Downloads()
        other._current = vid
        other._cancel.add(vid)
        check(other.start(vid) is True and vid in other._again and vid not in other._cancel, "a click during cancel asks for a restart")
        other.shutdown()
    finally:
        dl.shutdown()

_check_cancel()

req_lines = [line.strip() for line in req if line.strip() and not line.strip().startswith("#")]
check(all("==" in line for line in req_lines), f"every Windows requirement is pinned: {req_lines}")
for pin in ("faster-whisper==1.2.1", "ctranslate2==4.8.3", "numpy==2.5.4", "sounddevice==0.5.6"):
    check(pin in req_lines, f"requirements pin {pin}")

print(f"Voice catalog tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
