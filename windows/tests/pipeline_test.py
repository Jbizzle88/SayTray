"""Run files through the real read pipeline (TextPrep -> PiperEngine -> BabbleGuard), no playback.
Usage: python pipeline_test.py out.json file.txt ...   Then summarizes like the macOS run_tests.sh."""
import os, sys, json, time, wave, tempfile, shutil
if not os.environ.get("SAYTRAY_LOG_DIR"):
    os.environ["SAYTRAY_LOG_DIR"] = tempfile.mkdtemp(prefix="saytray-test-logs-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from saytray.textprep import chunks, word_count
from saytray.engine import PiperEngine
from saytray.session import ReadSession

out_json, files = sys.argv[1], sys.argv[2:]
voice = os.environ.get("SB_VOICE", "en_US-norman-medium")
eng = PiperEngine()
assert eng.ensure(voice), "voice missing"
t0 = time.time(); eng.wait_ready(120); print(f"voice load+warmup {time.time() - t0:.2f}s")
base = os.path.join(tempfile.gettempdir(), "saytray-pipeline-test")
shutil.rmtree(base, ignore_errors=True)
report = []
for n, f in enumerate(files):
    text = open(f, encoding="utf-8").read()
    d = os.path.join(base, str(n + 1)); os.makedirs(d, exist_ok=True)
    s = ReadSession(1000 + n, chunks(text), d, eng)
    first = [None]; t0 = time.time()
    def upd(sess):
        if first[0] is None and sess.slots and sess.slots[0].items is not None:
            first[0] = time.time() - t0
    s.on_update = upd
    s.start()
    while not s.complete and time.time() - t0 < 300:
        time.sleep(0.02)
    def desc(sl):
        return {"key": sl.key, "text": sl.text, "words": word_count(sl.text), "phonemes": sl.phonemes,
                "attempts": [{"seconds": a, "verdict": v} for a, v in sl.attempts], "events": sl.events,
                "items": [p if k == "file" else "system:" + p for k, p in (sl.items or [])], "subs": [desc(x) for x in sl.subs]}
    report.append({"file": f, "complete": s.complete, "seconds_total": time.time() - t0,
                   "first_chunk_ready": first[0] or -1, "chunks": [desc(x) for x in s.slots]})
json.dump(report, open(out_json, "w"), indent=1)

ok = True; trig = split = sysfb = chunks_n = 0; spp = []; spw = []
def walk(c):
    global trig, split, sysfb, ok
    if c["events"]: trig += 1
    if c["subs"]: split += 1
    for it in c["items"]:
        if it.startswith("system:"): sysfb += 1
        elif not os.path.exists(it): print("MISSING", it); ok = False
        else:
            w = wave.open(it); assert w.getnframes() > 0 and w.getframerate() > 0
    if c["attempts"] and c["attempts"][-1]["verdict"] == "ok":
        if c["phonemes"]: spp.append(c["attempts"][-1]["seconds"] / c["phonemes"])
        if c["words"] >= 4: spw.append(c["attempts"][-1]["seconds"] / c["words"])
    for x in c["subs"]: walk(x)
for r in report:
    if not r["complete"]: print("INCOMPLETE", r["file"]); ok = False
    keys = [c["key"] for c in r["chunks"]]
    if keys != sorted(keys): print("ORDER BROKEN", r["file"]); ok = False
    print("%-28s chunks=%3d first_ready=%.2fs total=%.1fs" % (os.path.basename(r["file"]), len(r["chunks"]), r["first_chunk_ready"], r["seconds_total"]))
    for c in r["chunks"]:
        chunks_n += 1; walk(c)
        for e in c["events"] + [e for x in c["subs"] for e in x["events"]]:
            print("   GUARD", c["key"], e, "|", c["text"][:70])
spp.sort(); spw.sort()
if spp: print("sec/phoneme (accepted): min %.4f median %.4f max %.4f" % (spp[0], spp[len(spp) // 2], spp[-1]))
if spw: print("sec/word (>=4 words, accepted): min %.3f median %.3f max %.3f" % (spw[0], spw[len(spw) // 2], spw[-1]))
print("SUMMARY files=%d chunks=%d guard_triggered=%d split=%d system_fallback_items=%d all_complete_and_ordered=%s" % (len(report), chunks_n, trig, split, sysfb, ok))
sys.exit(0 if ok else 1)
