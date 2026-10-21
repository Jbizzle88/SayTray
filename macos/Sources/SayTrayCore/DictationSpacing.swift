import Foundation

/// How dictated text is joined to whatever is already at the cursor, and how
/// recognition segments are concatenated when a partial result replaces the start.
public enum DictationSpacing {
  /// Prepend one space when `previous` is a real character and `text` does not
  /// already start with space or punctuation. No space at the start of a field,
  /// after whitespace or a newline, or when that would make a double space.
  /// Trim the recognizer text, then apply the one-space rule. Whitespace-only input becomes empty.
  public static func prepare(_ text: String, previous: Character?) -> String {
    apply(text.trimmingCharacters(in: .whitespacesAndNewlines), previous: previous)
  }

  /// Brackets and $ at the start of a phrase get a space. Commas, periods, and these symbols do not.
  private static let opening: Set<Character> = ["“", "‘", "«", "(", "[", "{", "$", "¿", "¡"]
  private static let attachedSymbols: Set<Character> = ["+", "<", "=", ">", "^", "|", "~", "`"]

  public static func apply(_ text: String, previous: Character?) -> String {
    guard let first = text.first else { return text }
    if first.isWhitespace || attachedSymbols.contains(first) { return text }
    if first == "\"" || first == "'" {
      let next = text.dropFirst().first
      if next == nil || next!.isWhitespace { return text }
    } else if isPunctuation(first) && !opening.contains(first) {
      return text
    }
    guard let previous else { return text }
    if previous.isWhitespace { return text }
    return " " + text
  }

  /// Join two independent slices with spacing. A shared prefix does not drop either side.
  public static func merge(_ previous: String, _ incoming: String) -> String {
    let a = previous.trimmingCharacters(in: .whitespacesAndNewlines)
    let b = incoming.trimmingCharacters(in: .whitespacesAndNewlines)
    if a.isEmpty { return b }
    if b.isEmpty { return a }
    return a + apply(b, previous: a.last)
  }

  public static func join(_ parts: [String]) -> String {
    parts.reduce("") { merge($0, $1) }
  }

  /// Join slices that shared about a second of audio. Only a short repeated word run is dropped.
  public static func dedupeBoundary(_ left: String, _ right: String, maxWords: Int = 8) -> String {
    let lw = left.split { $0.isWhitespace }.map(String.init)
    let rw = right.split { $0.isWhitespace }.map(String.init)
    if lw.isEmpty || rw.isEmpty { return right }
    let cap = max(1, maxWords)
    var best = 0
    let limit = min(cap, lw.count, rw.count)
    if limit >= 1 {
      for n in 1...limit {
        var same = true
        for i in 0..<n {
          if !sameWord(lw[lw.count - n + i], rw[i]) { same = false; break }
        }
        if same { best = n }
      }
    }
    if best == 0 { return right }
    let kept = Array(rw.dropFirst(best))
    if kept.isEmpty { return "" }
    var tail = right[...]
    for word in rw.prefix(best) {
      if let range = tail.range(of: word) {
        tail = tail[range.upperBound...]
      } else {
        break
      }
    }
    return String(tail).trimmingCharacters(in: .whitespaces)
  }

  public static func joinOverlapped(_ parts: [String]) -> String {
    var out = ""
    for part in parts {
      let piece = out.isEmpty ? part : dedupeBoundary(out, part)
      out = merge(out, piece)
    }
    return out
  }

  private static func sameWord(_ a: String, _ b: String) -> Bool {
    func norm(_ w: String) -> String {
      String(w.lowercased().filter { $0.isLetter || $0.isNumber })
    }
    let na = norm(a), nb = norm(b)
    return !na.isEmpty && na == nb
  }

  private static func isPunctuation(_ c: Character) -> Bool {
    c.unicodeScalars.allSatisfy { CharacterSet.punctuationCharacters.contains($0) }
  }
}
