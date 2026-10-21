import Foundation
import SayTrayCore

var failures = 0, passes = 0
func check(_ cond: Bool, _ msg: String) { if cond { passes += 1 } else { failures += 1; print("FAIL: \(msg)") } }
func chunks(_ s: String) -> [String] { TextPrep.chunks(s) }
func joined(_ s: String) -> String { chunks(s).joined(separator: " | ") }

// Unit tests
check(chunks("let me know.If the voice stalls, it restarts.").count == 2, "glued sentence split: \(joined("let me know.If the voice stalls, it restarts."))")
check(!joined("Hello\u{200B} wor\u{200D}ld\u{FEFF} test here.").contains("\u{200B}"), "zero-width stripped")
check(joined("Hello\u{00A0}there my friend.") == "Hello there my friend.", "nbsp: \(joined("Hello\u{00A0}there my friend."))")
check(joined("Visit https://www.example.com/a/b?c=1 today please.").contains("Visit example dot com today"), "url: \(joined("Visit https://www.example.com/a/b?c=1 today please."))")
check(joined("Mail jon@example.com now please.").contains("jon at example dot com"), "email: \(joined("Mail jon@example.com now please."))")
check(joined("Save 50% & more now.").contains("50 percent and more"), "symbols: \(joined("Save 50% & more now."))")
check(joined("It costs $5.99 today.").contains("5.99 dollars"), "dollars: \(joined("It costs $5.99 today."))")
check(chunks("- first item here\n- second item here\n- third item here").count == 3, "bullets become sentences")
check(joined("- first item here\n- second item").hasPrefix("first item here."), "bullet marker stripped: \(joined("- first item here\n- second item"))")
check(joined("1. Numbered thing one\n2) Numbered thing two").hasPrefix("Numbered thing one."), "numbered list: \(joined("1. Numbered thing one\n2) Numbered thing two"))")
check(joined("Great job 🎉🚀 team, well done 👍🏽.") == "Great job team, well done.", "emoji: \(joined("Great job 🎉🚀 team, well done 👍🏽."))")
check(joined("**Bold** and *italic* and `code` here.") == "Bold and italic and code here.", "markdown inline: \(joined("**Bold** and *italic* and `code` here."))")
check(joined("# Heading here\nSome text follows here.").hasPrefix("Heading here."), "heading")
check(joined("See [the docs](https://x.com/y) for more info.").contains("See the docs for more"), "md link: \(joined("See [the docs](https://x.com/y) for more info."))")
check(joined("Before.\n```\nlet x = 1\n```\nAfter that we continue.").contains("Code block omitted"), "code fence")
check(joined("Wait... what?! Really!!!") == "Wait. what? Really!" || !joined("Wait... what?! Really!!!").contains(".."), "repeated punct: \(joined("Wait... what?! Really!!!"))")
check(joined("He said “hello” and ‘bye’ today.") == "He said hello and 'bye' today.", "quotes: \(joined("He said “hello” and ‘bye’ today."))")
check(joined("Open main.swift in the editor now.").contains("main dot swift"), "dotted identifier: \(joined("Open main.swift in the editor now."))")
check(joined("For e.g. this works.").contains("for example"), "abbrev")
check(chunks("Okay.").count == 1, "single short sentence kept")
check(chunks("Hi. Yes. This is a much longer sentence that follows.").count == 1, "tiny fragments merged: \(joined("Hi. Yes. This is a much longer sentence that follows."))")
let longS = String(repeating: "this clause keeps going and going, ", count: 20) + "end."
check(chunks(longS).allSatisfy { $0.count <= TextPrep.maxChunk + 40 }, "long split cap")
check(chunks(longS).count >= 4, "long split count")
check(TextPrep.splitInHalf("one two three, four five six seven eight")?.count == 2, "splitInHalf")
check(BabbleGuard.check(text: "This sentence has exactly eight words in it.", seconds: 2.6, phonemes: 36).ok, "guard normal ok")
check(!BabbleGuard.check(text: "I couldn't hear it myself, so give Option plus a try and let me know. If the background voice ever stalls, SayTray now restarts it and tries again on its own.", seconds: 4.8, phonemes: 150).ok, "guard catches known babble (4.8s/31 words)")
check(!BabbleGuard.check(text: "This sentence has exactly eight words in it.", seconds: 12, phonemes: 36).ok, "guard catches too long")
check(chunks("").isEmpty && chunks("   \n\u{200B} 🎉 \n").isEmpty, "empty input")

// Dictation spacing and segment concatenation (same rules as windows/saytray/spacing.py).
check(DictationSpacing.apply("there", previous: nil) == "there", "no space at empty field")
check(DictationSpacing.apply("there", previous: " ") == "there", "no double space")
check(DictationSpacing.apply("there", previous: "\n") == "there", "no space after newline")
check(DictationSpacing.apply("there", previous: "o") == " there", "space after a word")
check(DictationSpacing.apply(" there", previous: "o") == " there", "text already spaced")
check(DictationSpacing.apply(", and", previous: "o") == ", and", "punctuation is not spaced")
check(DictationSpacing.apply("(note)", previous: "o") == "(note)", "opening punct is not spaced")
check(DictationSpacing.merge("hello there", "friend") == "hello there friend", "segment append")
check(DictationSpacing.merge("hello world", "hello world and more") == "hello world and more", "partial grew")
check(DictationSpacing.merge("hello world", "hello") == "hello world", "shorter partial kept")
check(DictationSpacing.join(["the start of the sentence", "only the end"]) == "the start of the sentence only the end", "long dictation keeps the start")
func spaced(_ parts: [String]) -> String {
  var typed = ""
  for p in parts { typed += DictationSpacing.apply(p, previous: typed.last) }
  return typed
}
check(spaced(["hello", "there"]) == "hello there", "back to back words")
check(spaced(["hello", "there", "friend"]) == "hello there friend", "three inserts in order")
check(spaced(["hello\n", "there"]) == "hello\nthere", "newline then word")
check(DictationSpacing.prepare(" there", previous: " ") == "there", "prepare drops a second space")
check(DictationSpacing.prepare("  there", previous: "o") == " there", "prepare trims then adds one space")
check(DictationSpacing.prepare("there", previous: "o") == " there", "prepare spaces a bare word")
check(DictationSpacing.prepare(" \n ", previous: "o") == "", "prepare drops whitespace-only")
check(DictationSpacing.prepare("hello", previous: nil) == "hello", "prepare at empty field")
func prepared(_ parts: [String]) -> String {
  var typed = ""
  for p in parts { typed += DictationSpacing.prepare(p, previous: typed.last) }
  return typed
}
check(prepared(["hello", " there"]) == "hello there", "prepare back to back one space")
check(prepared(["hello ", " there"]) == "hello there", "prepare no double space")
check(prepared(["hello", "there", "friend"]) == "hello there friend", "prepare three in order")

check(!DictationPlan.needsResplit(audioSeconds: 30, firstWordAt: 0.2, lastWordEnd: 29.5, failed: false, characters: 400), "full slice kept")
check(DictationPlan.needsResplit(audioSeconds: 30, firstWordAt: 18, lastWordEnd: 29, failed: false, characters: 80), "first word late")
check(DictationPlan.needsResplit(audioSeconds: 30, firstWordAt: 0.2, lastWordEnd: 4, failed: false, characters: 40), "last word early")
check(DictationPlan.needsResplit(audioSeconds: 30, firstWordAt: nil, lastWordEnd: nil, failed: true, characters: 0), "failed empty slice")
check(!DictationPlan.needsResplit(audioSeconds: 30, firstWordAt: nil, lastWordEnd: nil, failed: false, characters: 400), "long text without timestamps")
check(!DictationPlan.needsResplit(audioSeconds: 5, firstWordAt: 3, lastWordEnd: 4.5, failed: false, characters: 10), "short slice accepted")
check(DictationPlan.needsResplit(audioSeconds: 30, firstWordAt: nil, lastWordEnd: nil, failed: false, characters: 20), "too little text for 30s")

func fakeLong(_ start: Double, _ end: Double) -> (String, Double?, Double?, Bool) {
  let audio = end - start
  if audio > 10 { return ("tail", audio / 2, audio - 0.1, false) }
  return ("t\(Int(start))", 0.1, audio - 0.1, false)
}
for total in [180.0, 300.0] {
  let text = DictationPlan.stitch(total: total, limit: 30, recognize: fakeLong)
  let tokens = text.split(separator: " ").map(String.init)
  let last = Int(total - 7.5)
  check(tokens.first == "t0", "\(Int(total))s starts at the beginning: \(text.prefix(24))")
  check(tokens.contains("t\(last)"), "\(Int(total))s includes the last slice t\(last)")
}

// Corpus invariants
let dir = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Tests/corpus"
let allowed = CharacterSet.letters.union(.decimalDigits).union(CharacterSet(charactersIn: " .,!?;:'()-"))
for f in ((try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? []).sorted() where f.hasSuffix(".txt") {
  let text = (try? String(contentsOfFile: dir + "/" + f, encoding: .utf8)) ?? ""
  let cs = chunks(text)
  check(!cs.isEmpty, "\(f): produced chunks")
  for c in cs {
    check(c.count <= TextPrep.maxChunk + 40, "\(f): chunk too long (\(c.count)): \(c)")
    check(cs.count == 1 || TextPrep.wordCount(c) >= TextPrep.minWords, "\(f): tiny chunk: \(c)")
    check(c.unicodeScalars.allSatisfy { allowed.contains($0) }, "\(f): odd chars: \(c)")
    check(c.range(of: "[\\p{Ll}][.!?]\\p{Lu}", options: .regularExpression) == nil, "\(f): glued: \(c)")
    check(c.last.map { ".!?,;:".contains($0) } ?? false, "\(f): no end punct: \(c)")
  }
  if CommandLine.arguments.contains("-v") { print("== \(f)"); cs.forEach { print("  [\($0.count)] \($0)") } }
}
print("TextPrep tests: \(passes) passed, \(failures) failed")
exit(failures == 0 ? 0 : 1)
