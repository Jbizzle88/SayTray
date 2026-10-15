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
