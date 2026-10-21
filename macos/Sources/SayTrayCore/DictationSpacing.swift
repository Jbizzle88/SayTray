import Foundation

/// How dictated text is joined to whatever is already at the cursor, and how
/// recognition segments are concatenated when a partial result replaces the start.
public enum DictationSpacing {
  /// Prepend one space when `previous` is a real character and `text` does not
  /// already start with space or punctuation. No space at the start of a field,
  /// after whitespace or a newline, or when that would make a double space.
  public static func apply(_ text: String, previous: Character?) -> String {
    guard let first = text.first else { return text }
    if first.isWhitespace || isPunctuation(first) { return text }
    guard let previous else { return text }
    if previous.isWhitespace { return text }
    return " " + text
  }

  /// Keep a growing transcript. If the recognizer restarts and sends only the
  /// latest segment, append it instead of dropping what came before.
  public static func merge(_ previous: String, _ incoming: String) -> String {
    let a = previous.trimmingCharacters(in: .whitespacesAndNewlines)
    let b = incoming.trimmingCharacters(in: .whitespacesAndNewlines)
    if a.isEmpty { return b }
    if b.isEmpty { return a }
    if b.hasPrefix(a) { return b }
    if a.hasPrefix(b) { return a }
    return a + apply(b, previous: a.last)
  }

  public static func join(_ parts: [String]) -> String {
    parts.reduce("") { merge($0, $1) }
  }

  private static func isPunctuation(_ c: Character) -> Bool {
    c.unicodeScalars.allSatisfy { CharacterSet.punctuationCharacters.contains($0) }
  }
}
