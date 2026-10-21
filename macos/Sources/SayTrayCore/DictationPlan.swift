import Foundation

/// How a long dictation is cut into recognizer-sized slices and put back together.
///
/// Apple's speech request dies around one minute, and a later partial can contain only
/// the latest slice. Slices stay under that limit. If a result does not cover its slice,
/// the slice is halved and recognized again, then concatenated from front to back.
public enum DictationPlan {
  public static let segmentLimit: Double = 30
  /// Below this length a slice is accepted as-is. Halving further does not help.
  public static let minSlice: Double = 8

  /// True when this slice's transcript does not account for the whole slice, so the
  /// caller should halve the audio and recognize both halves.
  public static func needsResplit(audioSeconds: Double, firstWordAt: Double?, lastWordEnd: Double?, failed: Bool, characters: Int) -> Bool {
    guard audioSeconds > minSlice else { return false }
    if let first = firstWordAt, first > 2 { return true }
    if let last = lastWordEnd, audioSeconds - last > 8 { return true }
    if failed && characters == 0 { return true }
    if audioSeconds > 12 && characters < Int(audioSeconds * 3) { return true }
    return false
  }

  /// Recognize `total` seconds in ≤`limit` slices. `recognize` is (start, end) →
  /// text, first-word offset, last-word end, failed. Offsets are relative to the slice.
  /// A slice whose result does not cover it is halved until it does, or until `depthLimit`.
  public static func stitch(
    total: Double,
    limit: Double = segmentLimit,
    depthLimit: Int = 4,
    recognize: (Double, Double) -> (String, Double?, Double?, Bool)
  ) -> String {
    guard total > 0, limit > 0 else { return "" }
    var parts: [String] = []
    var t = 0.0
    while t < total - 0.000_001 {
      let end = min(total, t + limit)
      parts.append(slice(t, end, 0, depthLimit, recognize))
      if end <= t { break }
      t = end
    }
    return DictationSpacing.join(parts)
  }

  private static func slice(
    _ start: Double, _ end: Double, _ depth: Int, _ depthLimit: Int,
    _ recognize: (Double, Double) -> (String, Double?, Double?, Bool)
  ) -> String {
    let (text, first, last, failed) = recognize(start, end)
    let audio = end - start
    if depth < depthLimit && needsResplit(audioSeconds: audio, firstWordAt: first, lastWordEnd: last, failed: failed, characters: text.count) {
      let mid = start + audio / 2
      guard mid > start, mid < end else { return text }
      let left = slice(start, mid, depth + 1, depthLimit, recognize)
      let right = slice(mid, end, depth + 1, depthLimit, recognize)
      return DictationSpacing.join([left, right])
    }
    return text
  }
}
