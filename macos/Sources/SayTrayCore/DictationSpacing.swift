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
  private static let opening: Set<Character> = ["“", "‘", "«", "(", "[", "{", "$"]
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

  private static func isPunctuation(_ c: Character) -> Bool {
    c.unicodeScalars.allSatisfy { CharacterSet.punctuationCharacters.contains($0) }
  }
}
