import Foundation
import NaturalLanguage

/// Turns arbitrary selected text into short, clean, speakable chunks for Piper.
/// Pure and deterministic; covered by TextPrepTests.
public enum TextPrep {
  public static let maxChunk = 200
  public static let minWords = 3

  public static func chunks(_ input: String) -> [String] {
    var out: [String] = []
    for line in normalizeToLines(input) {
      for s in sentences(line) { out += capSplit(s) }
    }
    return mergeTiny(out)
  }

  public static func wordCount(_ s: String) -> Int {
    s.split(whereSeparator: { $0.isWhitespace }).filter { $0.contains(where: { $0.isLetter || $0.isNumber }) }.count
  }

  // MARK: normalization
  static func re(_ t: String, _ pattern: String, _ tmpl: String, ci: Bool = false) -> String {
    t.replacingOccurrences(of: pattern, with: tmpl, options: ci ? [.regularExpression, .caseInsensitive] : .regularExpression)
  }
  static func replaceMatches(_ t: String, _ pattern: String, ci: Bool = true, _ f: ([String]) -> String) -> String {
    guard let rx = try? NSRegularExpression(pattern: pattern, options: ci ? [.caseInsensitive] : []) else { return t }
    let ns = t as NSString
    var out = ""; var last = 0
    for m in rx.matches(in: t, range: NSRange(location: 0, length: ns.length)) {
      out += ns.substring(with: NSRange(location: last, length: m.range.location - last))
      var groups: [String] = []
      for g in 0..<m.numberOfRanges {
        let r = m.range(at: g); groups.append(r.location == NSNotFound ? "" : ns.substring(with: r))
      }
      out += f(groups)
      last = m.range.location + m.range.length
    }
    return out + ns.substring(from: last)
  }
  static func dots(_ s: String) -> String { s.replacingOccurrences(of: ".", with: " dot ") }

  public static func normalizeToLines(_ input: String) -> [String] {
    var t = input.precomposedStringWithCompatibilityMapping
    t = t.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
    // Markdown structure
    t = re(t, "```[\\s\\S]*?(```|$)", "\nCode block omitted.\n")
    t = re(t, "`([^`\\n]+)`", "$1")
    t = re(t, "!\\[([^\\]]*)\\]\\([^)]*\\)", "$1")
    t = re(t, "\\[([^\\]]+)\\]\\(([^)\\s]+)\\)", "$1")
    t = re(t, "(\\*\\*|__|~~)(.+?)\\1", "$2")
    t = re(t, "(?<![\\w*])\\*(?!\\s)([^*\\n]+?)(?<!\\s)\\*(?![\\w*])", "$1")
    t = re(t, "(?m)^[ \\t]{0,3}#{1,6}[ \\t]+", "")
    t = re(t, "(?m)^[ \\t]*>+[ \\t]?", "")
    t = re(t, "(?m)^[ \\t]*([-*_][ \\t]*){3,}$", "")
    t = re(t, "(?m)^[ \\t]*\\|?[ \\t]*:?-{3,}:?[ \\t]*(\\|[ \\t]*:?-{3,}:?[ \\t]*)*\\|?[ \\t]*$", "")
    t = re(t, "(?m)^[ \\t]*\\|(.*)\\|[ \\t]*$", "$1")
    // Abbreviations
    for (a, b) in [("e.g.", "for example"), ("i.e.", "that is"), ("etc.", "etcetera."), ("vs.", "versus"), ("approx.", "approximately")] {
      t = t.replacingOccurrences(of: a, with: b, options: .caseInsensitive)
    }
    // URLs, emails, bare domains, dotted identifiers
    t = replaceMatches(t, "\\b(?:https?://|www\\.)[^\\s<>()\\[\\]\"']+") { g in
      var u = g[0]; var tail = ""
      while let c = u.last, ".,;:!?".contains(c) { tail = String(c) + tail; u.removeLast() }
      var host = URL(string: u.lowercased().hasPrefix("www.") ? "https://" + u : u)?.host ?? "a website"
      if host.hasPrefix("www.") { host.removeFirst(4) }
      return " " + dots(host) + tail + " "
    }
    t = replaceMatches(t, "\\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,})\\b") { g in
      " " + dots(g[1]) + " at " + dots(g[2]) + " "
    }
    t = replaceMatches(t, "\\b[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.(?:com|org|net|io|dev|ai|app|co|edu|gov|us|uk|me|tv)\\b") { g in dots(g[0]) }
    t = re(t, "(?<=[A-Za-z])\\.(?=[A-Za-z]{2,}\\b)(?![A-Z][a-z])", " dot ")
    // Symbols and typography
    let reps: [(String, String)] = [
      ("\u{2018}", "'"), ("\u{2019}", "'"), ("\u{201A}", "'"), ("\u{201B}", "'"), ("`", "'"),
      ("\u{201C}", ""), ("\u{201D}", ""), ("\u{201E}", ""), ("\u{201F}", ""), ("\u{00AB}", ""), ("\u{00BB}", ""), ("\"", ""),
      ("\u{2013}", ", "), ("\u{2014}", ", "), ("\u{2015}", ", "), ("\u{2026}", ", "),
      ("\u{2192}", " to "), ("\u{21D2}", " to "), ("\u{2190}", " from "), ("\u{00B0}", " degrees "),
      ("\u{2022}", "\n- "), ("\u{2028}", "\n"), ("\u{2029}", "\n"), ("\u{0085}", "\n"), ("\t", " "),
      ("&", " and "), ("%", " percent "), ("@", " at "), ("+", " plus "), ("=", " equals "),
      ("\\", " "), ("|", ", "), ("<", " "), (">", " "), ("{", " "), ("}", " "), ("[", " "), ("]", " "),
      ("^", " "), ("*", " "), ("_", " "),
    ]
    t = re(t, "\\$(\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)", "$1 dollars")
    t = re(t, "\u{20AC}(\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)", "$1 euros")
    t = re(t, "\u{00A3}(\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)", "$1 pounds")
    t = re(t, "#(?=\\d)", " number ")
    t = re(t, "~(?=\\d)", " about ")
    t = re(t, "(?<=\\w)/(?=\\w)", " slash ")
    for (a, b) in reps { t = t.replacingOccurrences(of: a, with: b) }
    // Strip controls, zero-width/format chars, variation selectors, emoji and pictographs
    t = String(String.UnicodeScalarView(t.unicodeScalars.compactMap { sc -> Unicode.Scalar? in
      if sc.value == 0x0A { return sc }
      if sc.value == 0x200B || sc.value == 0x2060 { return " " }
      let p = sc.properties
      if p.generalCategory == .control || p.generalCategory == .format { return nil }
      if (0xFE00...0xFE0F).contains(sc.value) || (0x1F3FB...0x1F3FF).contains(sc.value) { return nil }
      if p.isEmojiPresentation || (p.isEmoji && sc.value >= 0x2190) { return " " }
      if p.generalCategory == .otherSymbol || p.generalCategory == .mathSymbol { return " " }
      return sc
    }))
    // Repeated punctuation, glued sentences ("know.If"), stray spacing
    t = re(t, "[!?]*\\?[!?]*", "?"); t = re(t, "!+", "!"); t = re(t, "\\.{2,}", ", ")
    t = re(t, "([,;:])[,;:\\s]*(?=[,;:])", "")
    t = re(t, "([\\p{Ll}\\p{N})'][.!?])(?=\\p{Lu})", "$1\n")
    // Lines -> sentences
    var lines: [String] = []
    for raw in t.components(separatedBy: "\n") {
      var l = raw
      l = re(l, "^\\s*(?:[-*+\u{25E6}\u{25AA}\u{25AB}\u{25CF}\u{25CB}\u{00B7}\u{2023}\u{2043}]|\\(?\\d{1,3}[.)]|[a-zA-Z][.)])\\s+", "")
      l = re(l, "^\\s*-\\s+", "")
      l = re(l, "[^\\p{L}\\p{N}\\s.,!?;:'()-]", " ")
      l = re(l, "\\s+-+\\s+", ", ")
      l = re(l, "\\(\\s*\\)", " ")
      l = re(l, "\\s+", " ")
      l = re(l, "\\s+([,.;:!?)])", "$1")
      l = re(l, "([,;:])(?=[.!?])", "")
      l = re(l, "^[\\s,.;:!?)'-]+", "")
      l = l.trimmingCharacters(in: .whitespaces)
      guard l.contains(where: { $0.isLetter || $0.isNumber }) else { continue }
      if let c = l.last {
        if ",;:-(".contains(c) { l.removeLast(); l = l.trimmingCharacters(in: .whitespaces) + "." }
        else if !".!?".contains(c) { l += "." }
      }
      lines.append(l)
    }
    return lines
  }

  static func sentences(_ line: String) -> [String] {
    let tok = NLTokenizer(unit: .sentence); tok.string = line
    var out: [String] = []
    tok.enumerateTokens(in: line.startIndex..<line.endIndex) { r, _ in
      let s = line[r].trimmingCharacters(in: .whitespaces)
      if !s.isEmpty { out.append(s) }
      return true
    }
    return out.isEmpty ? [line] : out
  }

  /// Split a sentence longer than maxChunk at clause boundaries, else at word boundaries.
  static func capSplit(_ s: String) -> [String] {
    if s.count <= maxChunk { return [s] }
    let words = s.split(separator: " ").map(String.init)
    let parts = Int((Double(s.count) / Double(maxChunk)).rounded(.up))
    let target = Double(s.count) / Double(parts)
    var out: [String] = []; var cur = ""
    for w in words {
      let isLast = out.count >= parts - 1
      if !cur.isEmpty && Double(cur.count + 1 + w.count) > min(target * 1.15, Double(maxChunk)) {
        out.append(cur.last.map { ",;:".contains($0) } == true ? cur : cur + ","); cur = ""
      }
      cur += (cur.isEmpty ? "" : " ") + w
      if !isLast, Double(cur.count) >= target * 0.75, let c = w.last, ",;:".contains(c) { out.append(cur); cur = "" }
    }
    if !cur.isEmpty { out.append(cur) }
    return out
  }

  /// Merge fragments under minWords words into a neighbor.
  static func mergeTiny(_ chunks: [String]) -> [String] {
    var out: [String] = []
    for c in chunks {
      if let last = out.last, wordCount(c) < minWords || wordCount(last) < minWords, last.count + c.count + 1 <= maxChunk + 40 {
        out[out.count - 1] = last + " " + c
      } else { out.append(c) }
    }
    return out
  }

  /// Split a chunk roughly in half (clause break near the middle, else word break). nil if too short.
  public static func splitInHalf(_ s: String) -> [String]? {
    let words = s.split(separator: " ").map(String.init)
    guard words.count >= 6 else { return nil }
    let mid = words.count / 2
    var best = mid
    for d in 0..<(words.count / 3) {
      let i = mid - 1 - d, j = mid - 1 + d
      if i >= 2, let c = words[i].last, ",;:".contains(c) { best = i + 1; break }
      if j <= words.count - 3, let c = words[j].last, ",;:".contains(c) { best = j + 1; break }
    }
    let a = words[..<best].joined(separator: " "), b = words[best...].joined(separator: " ")
    return [a, b]
  }
}

/// Detects Piper babble/skip from audio duration vs. text length.
/// Primary metric: seconds per phoneme (Piper's own phonemizer). Normal speech ~0.045-0.09 s/phoneme;
/// observed babble/skips ~0.030-0.037. Word/char ratios are a wide sanity net.
public enum BabbleGuard {
  public struct Verdict { public let ok: Bool; public let secPerPhoneme: Double; public let secPerWord: Double; public let reason: String }
  public static var minSPP = 0.043, maxSPP = 0.16, minSPW = 0.12, maxSPW = 1.0
  public static func check(text: String, seconds: Double, phonemes: Int) -> Verdict {
    let w = max(1, TextPrep.wordCount(text))
    let spw = seconds / Double(w)
    let spp = phonemes > 0 ? seconds / Double(phonemes) : 0
    var reason = ""
    if seconds < 0.15 { reason = "empty audio" }
    else if phonemes >= 12 && spp < minSPP { reason = "too fast for its phonemes (skipped speech)" }
    else if phonemes >= 12 && spp > maxSPP { reason = "too slow for its phonemes (babble)" }
    else if w >= 4 && spw < minSPW { reason = "too short per word" }
    else if w >= 4 && spw > maxSPW { reason = "too long per word" }
    return Verdict(ok: reason.isEmpty, secPerPhoneme: spp, secPerWord: spw, reason: reason)
  }
}
