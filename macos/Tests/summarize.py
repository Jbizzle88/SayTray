import json, sys, wave, os
r = json.load(open(sys.argv[1]))
ok = True; trig = 0; chunks = 0; sysfb = 0; split = 0; resynth_ok = 0
rows = []
def walk(c, depth=0):
    global trig, sysfb, split, resynth_ok, ok
    if c["events"]: trig += 1
    if c["subs"]: split += 1
    if len(c["attempts"]) == 2 and c["attempts"][-1]["verdict"] == "ok" and not c["subs"]: resynth_ok += 1
    for it in c["items"]:
        if it.startswith("system:"): sysfb += 1
        elif not os.path.exists(it): print("MISSING", it); ok = False
        else:
            w = wave.open(it); assert w.getframerate() > 0 and w.getnframes() > 0
    for s in c["subs"]: walk(s, depth + 1)
for f in r:
    if not f["complete"]: print("INCOMPLETE", f["file"]); ok = False
    for c in f["chunks"]:
        chunks += 1; walk(c)
        final = c["attempts"][-1] if c["attempts"] else None
        if final: rows.append((final["seconds"] / max(1, c["words"]), c["words"], final["verdict"], c["text"][:70], final["seconds"] / max(1, c.get("phonemes", 0) or 1)))
    print("%-34s chunks=%3d first_ready=%.2fs total=%.1fs" % (os.path.basename(f["file"]), len(f["chunks"]), f["first_chunk_ready"], f["seconds_total"]))
    for c in f["chunks"]:
        for e in c["events"] + [e for s in c["subs"] for e in s["events"]]:
            print("   GUARD", c["key"], e, "|", c["text"][:80])
    keys = [c["key"] for c in f["chunks"]]
    if keys != sorted(keys): print("ORDER BROKEN", f["file"]); ok = False
spw = sorted(x[0] for x in rows if x[1] >= 4)
spp = sorted(x[4] for x in rows if x[2] == "ok")
if spp: print("sec/phoneme (accepted chunks): min %.4f  median %.4f  max %.4f" % (spp[0], spp[len(spp)//2], spp[-1]))
if spw: print("sec/word (>=4 words): min %.3f  median %.3f  max %.3f" % (spw[0], spw[len(spw)//2], spw[-1]))
print("SUMMARY files=%d chunks=%d guard_triggered=%d resynth_fixed=%d split=%d system_fallback_items=%d all_complete_and_ordered=%s" % (len(r), chunks, trig, resynth_ok, split, sysfb, ok))
sys.exit(0 if ok else 1)
