"""TextPrep unit + corpus tests (port of macOS TextPrepTests). Usage: python test_textprep.py [corpus_dir] [-v]"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import regex as re
from saytray.textprep import chunks, word_count, split_in_half, BabbleGuard, MAX_CHUNK, MIN_WORDS

passes = failures = 0
def check(cond, msg):
    global passes, failures
    if cond: passes += 1
    else: failures += 1; print("FAIL:", msg)
def j(s): return " | ".join(chunks(s))

check(len(chunks("let me know.If the voice stalls, it restarts.")) == 2, "glued: " + j("let me know.If the voice stalls, it restarts."))
check("\u200B" not in j("Hello\u200B wor\u200Dld\uFEFF test here."), "zero-width stripped")
check(j("Hello\u00A0there my friend.") == "Hello there my friend.", "nbsp: " + j("Hello\u00A0there my friend."))
check("Visit example dot com today" in j("Visit https://www.example.com/a/b?c=1 today please."), "url: " + j("Visit https://www.example.com/a/b?c=1 today please."))
check("jon at example dot com" in j("Mail jon@example.com now please."), "email: " + j("Mail jon@example.com now please."))
check("50 percent and more" in j("Save 50% & more now."), "symbols: " + j("Save 50% & more now."))
check("5.99 dollars" in j("It costs $5.99 today."), "dollars: " + j("It costs $5.99 today."))
check(len(chunks("- first item here\n- second item here\n- third item here")) == 3, "bullets become sentences")
check(j("- first item here\n- second item").startswith("first item here."), "bullet marker: " + j("- first item here\n- second item"))
check(j("1. Numbered thing one\n2) Numbered thing two").startswith("Numbered thing one."), "numbered: " + j("1. Numbered thing one\n2) Numbered thing two"))
check(j("Great job 🎉🚀 team, well done 👍🏽.") == "Great job team, well done.", "emoji: " + j("Great job 🎉🚀 team, well done 👍🏽."))
check(j("**Bold** and *italic* and `code` here.") == "Bold and italic and code here.", "md inline: " + j("**Bold** and *italic* and `code` here."))
check(j("# Heading here\nSome text follows here.").startswith("Heading here."), "heading")
check("See the docs for more" in j("See [the docs](https://x.com/y) for more info."), "md link: " + j("See [the docs](https://x.com/y) for more info."))
check("Code block omitted" in j("Before.\n```\nlet x = 1\n```\nAfter that we continue."), "code fence")
check(".." not in j("Wait... what?! Really!!!"), "repeated punct: " + j("Wait... what?! Really!!!"))
check(j("He said “hello” and ‘bye’ today.") == "He said hello and 'bye' today.", "quotes: " + j("He said “hello” and ‘bye’ today."))
check("main dot swift" in j("Open main.swift in the editor now."), "dotted id: " + j("Open main.swift in the editor now."))
check("for example" in j("For e.g. this works."), "abbrev")
check(len(chunks("Okay.")) == 1, "single short")
check(len(chunks("Hi. Yes. This is a much longer sentence that follows.")) == 1, "tiny merged: " + j("Hi. Yes. This is a much longer sentence that follows."))
long_s = "this clause keeps going and going, " * 20 + "end."
check(all(len(c) <= MAX_CHUNK + 40 for c in chunks(long_s)), "long split cap")
check(len(chunks(long_s)) >= 4, "long split count")
check(len(split_in_half("one two three, four five six seven eight") or []) == 2, "split_in_half")
check(BabbleGuard.check("This sentence has exactly eight words in it.", 2.6, 36)[0], "guard normal ok")
check(not BabbleGuard.check("I couldn't hear it myself, so give Option plus a try and let me know. If the background voice ever stalls, SayTray now restarts it and tries again on its own.", 4.8, 150)[0], "guard catches babble")
check(not BabbleGuard.check("This sentence has exactly eight words in it.", 12, 36)[0], "guard too long")
check(not chunks("") and not chunks("   \n\u200B 🎉 \n"), "empty input")

d = next((a for a in sys.argv[1:] if not a.startswith("-")), os.path.join(os.path.dirname(__file__), "corpus"))
verbose = "-v" in sys.argv
allowed = re.compile(r"^[\p{L}\p{N} .,!?;:'()-]*$")
for f in sorted(os.listdir(d)):
    if not f.endswith(".txt"): continue
    cs = chunks(open(os.path.join(d, f), encoding="utf-8").read())
    check(bool(cs), f + ": produced chunks")
    for c in cs:
        check(len(c) <= MAX_CHUNK + 40, f"{f}: too long ({len(c)}): {c}")
        check(len(cs) == 1 or word_count(c) >= MIN_WORDS, f"{f}: tiny: {c}")
        check(bool(allowed.match(c)), f"{f}: odd chars: {c}")
        check(re.search(r"\p{Ll}[.!?]\p{Lu}", c) is None, f"{f}: glued: {c}")
        check(c[-1] in ".!?,;:", f"{f}: no end punct: {c}")
    if verbose:
        print("==", f); [print(f"  [{len(c)}] {c}") for c in cs]
print(f"TextPrep tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
