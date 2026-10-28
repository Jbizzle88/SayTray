"""Catalog, fallback, and retired-voice tests. No Piper install required.

Also checks that every catalog URL answers (HEAD). Set SAYTRAY_SKIP_URLS=1 to skip that.
python.org Python on macOS has no CA bundle, so those checks use certifi when it
is installed, then curl (the system trust store), and otherwise skip with a warning.
"""
import os, sys, json, shutil, ssl, subprocess, tempfile, urllib.request
if not os.environ.get("SAYTRAY_LOG_DIR"):
    os.environ["SAYTRAY_LOG_DIR"] = tempfile.mkdtemp(prefix="saytray-test-logs-")
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

def missing_ca(exc):
    """True when Python or curl has no CA bundle to verify a normal HTTPS server."""
    return "unable to get local issuer certificate" in str(exc).lower()


def urllib_context():
    """certifi's bundle when that package is installed. Otherwise Python's default store."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def head_urllib(url, opener=None):
    ctx = urllib_context()
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "SayTray"})
    open_ = opener or urllib.request.urlopen
    kwargs = {"timeout": 60}
    if ctx is not None:
        kwargs["context"] = ctx
    with open_(req, **kwargs) as r:
        length = int(r.headers.get("Content-Length") or 0)
        return r.status, length


def parse_curl_head(stdout):
    text = (stdout or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise RuntimeError("curl returned no headers")
    status = int(lines[-1].strip())
    blocks = [b for b in "\n".join(lines[:-1]).split("\n\n") if b.strip()]
    last = blocks[-1] if blocks else ""
    length = 0
    for line in last.splitlines():
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip() or 0)
    return status, length


def head_curl(url):
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl is not installed")
    # -I follows redirects as HEAD. -X HEAD does not: Hugging Face closes the body early.
    proc = subprocess.run(
        [curl, "-sS", "-I", "-L", "-A", "SayTray", "--max-time", "60", "-w", "\n%{http_code}", url],
        capture_output=True, text=True, timeout=70,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"curl exited {proc.returncode}")
    return parse_curl_head(proc.stdout)


class CatalogHeads:
    """HEAD a catalog URL. A missing CA bundle tries curl, then skips."""

    def __init__(self, urllib_head=head_urllib, curl_head=head_curl):
        self._urllib = urllib_head
        self._curl = curl_head
        self.mode = "urllib"
        self.warning = ""

    def head(self, url):
        if self.mode == "skip":
            return None
        if self.mode == "curl":
            return self._curl(url)
        try:
            return self._urllib(url)
        except Exception as e:
            if not missing_ca(e):
                raise
            try:
                got = self._curl(url)
            except Exception as curl_e:
                if missing_ca(curl_e) or "curl is not installed" in str(curl_e).lower():
                    self.mode = "skip"
                    self.warning = (
                        "skipping catalog URL checks: Python has no CA bundle "
                        f"({e}) and curl could not verify certificates either ({curl_e}). "
                        "python.org Python on macOS needs Install Certificates.command, or pip install certifi."
                    )
                    return None
                raise
            self.mode = "curl"
            self.warning = (
                "catalog URL checks are using curl because Python could not verify "
                f"HTTPS certificates ({e})."
            )
            return got


def _check_url_transport():
    sample = "HTTP/1.1 302 Found\nContent-Length: 0\n\nHTTP/1.1 200 OK\nContent-Length: 42\n\n200\n"
    check(parse_curl_head(sample) == (200, 42), "curl HEAD uses the final response")
    crlf = "HTTP/1.1 200 OK\r\ncontent-length: 7\r\n\r\n200"
    check(parse_curl_head(crlf) == (200, 7), "curl HEAD accepts CRLF headers")
    check(missing_ca(OSError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")), "a missing CA bundle is recognized")
    check(not missing_ca(OSError("SSL: no alternative certificate subject name matches")), "a hostname mismatch is not a missing CA bundle")

    calls = []
    def urllib_ok(url):
        calls.append(("urllib", url))
        return 200, 5
    def curl_unused(url):
        calls.append(("curl", url))
        raise AssertionError("curl ran when Python could verify certificates")
    ok = CatalogHeads(urllib_ok, curl_unused)
    check(ok.head("https://example.invalid/a") == (200, 5), "a working Python trust store is used")
    check(ok.mode == "urllib" and calls == [("urllib", "https://example.invalid/a")], "curl is not used when Python can verify certificates")

    def urllib_missing(url):
        calls.append("urllib")
        raise OSError("urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")
    def curl_ok(url):
        calls.append("curl")
        return 200, 9
    calls.clear()
    fell = CatalogHeads(urllib_missing, curl_ok)
    check(fell.head("https://example.invalid/a") == (200, 9), "a missing CA bundle falls back to curl")
    check(fell.head("https://example.invalid/b") == (200, 9), "later URL checks stay on curl")
    check(calls == ["urllib", "curl", "curl"], "Python is not retried after curl takes over")
    check("using curl" in fell.warning, "the curl fallback says why")

    def curl_missing_ca(url):
        calls.append("curl")
        raise RuntimeError("curl: (60) SSL certificate problem: unable to get local issuer certificate")
    calls.clear()
    skipped = CatalogHeads(urllib_missing, curl_missing_ca)
    check(skipped.head("https://example.invalid/a") is None, "missing certificates skip instead of failing")
    check(skipped.head("https://example.invalid/b") is None, "a skipped run does not keep probing")
    check(calls == ["urllib", "curl"], "the skip happens after one Python attempt and one curl attempt")
    check(skipped.mode == "skip" and "skipping catalog URL checks" in skipped.warning, "the skip warning names the missing CA bundle")

    def curl_absent(url):
        raise RuntimeError("curl is not installed")
    absent = CatalogHeads(urllib_missing, curl_absent)
    check(absent.head("https://example.invalid/a") is None and absent.mode == "skip", "no curl and no CA bundle skips")

    def urllib_other(url):
        raise OSError("HTTP Error 404: Not Found")
    def curl_should_not(url):
        raise AssertionError("curl ran for a non-certificate error")
    other = CatalogHeads(urllib_other, curl_should_not)
    raised = False
    try:
        other.head("https://example.invalid/missing")
    except OSError as e:
        raised = "404" in str(e)
    check(raised and other.mode == "urllib", "a real HEAD failure is still a failure")

    seen = {}
    real_cdc = ssl.create_default_context
    def fake_cdc(*args, **kwargs):
        seen["cafile"] = kwargs.get("cafile")
        return "ctx"
    ssl.create_default_context = fake_cdc
    old_certifi = sys.modules.get("certifi")
    import types
    fake = types.ModuleType("certifi")
    fake.where = lambda: "/bundle.pem"
    sys.modules["certifi"] = fake
    try:
        check(urllib_context() == "ctx" and seen.get("cafile") == "/bundle.pem", "URL checks use certifi when it is installed")
        class Response:
            status = 200
            headers = {"Content-Length": "5"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        def opener(req, timeout=60, context=None):
            seen["context"] = context
            seen["method"] = req.get_method()
            return Response()
        check(head_urllib("https://example.invalid/a", opener=opener) == (200, 5), "certifi context is passed to urlopen")
        check(seen.get("context") == "ctx" and seen.get("method") == "HEAD", "the catalog check is a HEAD with the certifi context")
        sys.modules["certifi"] = None
        seen.pop("context", None)
        def opener_default(req, timeout=60, context=None):
            seen["context"] = context
            return Response()
        check(urllib_context() is None, "without certifi, Python's default trust store is used")
        check(head_urllib("https://example.invalid/a", opener=opener_default) == (200, 5), "urlopen still runs without certifi")
        check(seen.get("context") is None, "no extra SSL context is passed when certifi is absent")
    finally:
        ssl.create_default_context = real_cdc
        if old_certifi is None:
            sys.modules.pop("certifi", None)
        else:
            sys.modules["certifi"] = old_certifi

_check_url_transport()

if os.environ.get("SAYTRAY_SKIP_URLS") == "1":
    print("skipping URL checks")
else:
    heads = CatalogHeads()
    announced = False
    for v in voices.voices():
        if heads.mode == "skip":
            break
        for f in v["files"]:
            if heads.mode == "skip":
                break
            try:
                got = heads.head(f["url"])
            except Exception as e:
                check(False, f"{f['filename']} HEAD failed: {e}")
                continue
            if heads.warning and not announced:
                print("warning:", heads.warning)
                announced = True
            if got is None:
                continue
            status, length = got
            check(status == 200 and length == f["sizeBytes"], f"{f['filename']} HEAD {status} {length} != {f['sizeBytes']}")
    if heads.mode == "skip" and heads.warning and not announced:
        print("warning:", heads.warning)

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
req_text = "\n".join(req)
for pin in (
    'numpy==2.2.6; python_version < "3.11"',
    'numpy==2.4.6; python_version == "3.11"',
    'numpy==2.5.4; python_version >= "3.12"',
    'pillow==12.3.0; python_version < "3.11"',
    'pillow==13.0.0; python_version >= "3.11"',
    "faster-whisper==1.2.1",
    "ctranslate2==4.8.3",
    "sounddevice==0.5.6",
    "piper-tts==1.8.0",
):
    check(pin in req_text, f"requirements pin {pin}")

def _check_trust_quick():
    vid_file = "voice.onnx"
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, vid_file)
        with open(path, "wb") as fh:
            fh.write(b"x" * 32)
        voice = {"id": "t", "files": [{"filename": vid_file, "sizeBytes": 32, "sha256": "abc"}]}
        def boom(_path):
            raise AssertionError("the menu check hashed a model")
        old = voices.sha256_file
        voices.sha256_file = boom
        try:
            check(voices.is_installed_quick(voice, d) is False, "a right-size file without a marker is not trusted yet")
            voices.write_hash_marker(path, "abc")
            with open(path + ".partial", "w", encoding="utf-8") as fh:
                fh.write("partial")
            check(voices.is_installed_quick(voice, d) is True, "a matching marker is trusted without hashing")
            voices.discard_written([path])
            check(not os.path.exists(path), "a failed download removes the file")
            check(not os.path.exists(path + ".partial"), "a failed download removes the partial")
            check(not os.path.exists(path + ".sha256"), "a failed download removes the hash marker")
        finally:
            voices.sha256_file = old

_check_trust_quick()

def _check_startup_does_not_hash():
    norman = voices.by_id("en_US-norman-medium")
    with tempfile.TemporaryDirectory() as d:
        for f in norman["files"]:
            with open(os.path.join(d, f["filename"]), "wb") as fh:
                fh.truncate(int(f["sizeBytes"]))
        def boom(_path):
            raise AssertionError("startup hashed a voice")
        old = voices.sha256_file
        voices.sha256_file = boom
        try:
            check(voices.installed_ids(d) == [], "startup does not hash unmarked voices")
            for f in norman["files"]:
                voices.write_hash_marker(os.path.join(d, f["filename"]), f.get("sha256") or "")
            check(voices.installed_ids(d) == ["en_US-norman-medium"], "markers make the voice installed without hashing")
        finally:
            voices.sha256_file = old

_check_startup_does_not_hash()

print(f"Voice catalog tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
