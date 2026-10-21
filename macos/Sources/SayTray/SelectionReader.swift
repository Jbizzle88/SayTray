import AppKit
import ApplicationServices
import SayTrayCore

/// Synthetic key presses and clipboard save/restore.
enum Keys {
  static func postCmd(_ code: CGKeyCode) {
    let src = CGEventSource(stateID: .combinedSessionState)
    for down in [true, false] {
      let e = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: down)
      e?.flags = .maskCommand
      e?.post(tap: .cghidEventTap)
    }
  }
  static func snapshot() -> [NSPasteboardItem] {
    (NSPasteboard.general.pasteboardItems ?? []).map { item in
      let n = NSPasteboardItem()
      for t in item.types { if let d = item.data(forType: t) { n.setData(d, forType: t) } }
      return n
    }
  }
  static func restore(_ items: [NSPasteboardItem]) {
    let pb = NSPasteboard.general
    pb.clearContents()
    if !items.isEmpty { pb.writeObjects(items) }
  }
}

enum SelectionReader {
  /// Selected text in the frontmost app: Accessibility first, then Cmd+C with clipboard restore.
  static func read(_ done: @escaping (String?) -> Void) {
    if let s = axSelectedText() { done(s); return }
    let pb = NSPasteboard.general
    let saved = Keys.snapshot()
    let before = pb.changeCount
    Keys.postCmd(8) // C
    var tries = 0
    func poll() {
      tries += 1
      if pb.changeCount != before || tries > 12 {
        let s = pb.changeCount != before ? pb.string(forType: .string) : nil
        Keys.restore(saved)
        done(s)
      } else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.05, execute: poll) }
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.05, execute: poll)
  }
  private static func axSelectedText() -> String? {
    let sys = AXUIElementCreateSystemWide()
    var focused: CFTypeRef?
    guard AXUIElementCopyAttributeValue(sys, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
          let f = focused, CFGetTypeID(f) == AXUIElementGetTypeID() else { return nil }
    var sel: CFTypeRef?
    guard AXUIElementCopyAttributeValue(f as! AXUIElement, kAXSelectedTextAttribute as CFString, &sel) == .success,
          let s = sel as? String, !s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
    return s
  }
  /// Type text at the cursor via pasteboard + Cmd+V, then restore the clipboard.
  /// Rapid dictations queue here so one paste cannot overwrite the next, and a single
  /// space is added when the previous character is not whitespace.
  private static var pending: [String] = []
  private static var typing = false
  private static var lastInserted = ""

  static func type(_ text: String) {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return }
    DispatchQueue.main.async {
      pending.append(trimmed)
      pump()
    }
  }

  private static func pump() {
    guard !typing, !pending.isEmpty else { return }
    typing = true
    let raw = pending.removeFirst()
    let read = cursorRead()
    let previous: Character?
    let source: String
    switch read {
    case .char(let c):
      previous = c
      source = "cursor"
    case .boundary:
      previous = nil
      source = "boundary"
    case .unavailable:
      previous = lastInserted.last
      source = lastInserted.isEmpty ? "none" : "last-insert"
    }
    let text = DictationSpacing.apply(raw, previous: previous)
    let spaced = text != raw
    lastInserted = text
    Log.event("insert: \(text.count) chars leading-space=\(spaced) previous=\(source)\(previous.map { " '\($0)'" } ?? "") queued=\(pending.count)")
    let saved = Keys.snapshot()
    let pb = NSPasteboard.general
    pb.clearContents()
    pb.setString(text, forType: .string)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
      Keys.postCmd(9) // V
      DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) {
        Keys.restore(saved)
        typing = false
        pump()
      }
    }
  }

  private enum CursorRead { case unavailable, boundary, char(Character) }

  /// Character immediately before the caret, when the focused control exposes it.
  private static func cursorRead() -> CursorRead {
    let sys = AXUIElementCreateSystemWide()
    var focused: CFTypeRef?
    guard AXUIElementCopyAttributeValue(sys, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
          let f = focused, CFGetTypeID(f) == AXUIElementGetTypeID() else { return .unavailable }
    let el = f as! AXUIElement
    var rangeRef: CFTypeRef?
    guard AXUIElementCopyAttributeValue(el, kAXSelectedTextRangeAttribute as CFString, &rangeRef) == .success,
          let rangeRef, CFGetTypeID(rangeRef) == AXValueGetTypeID() else { return .unavailable }
    var range = CFRange()
    guard AXValueGetValue(rangeRef as! AXValue, .cfRange, &range) else { return .unavailable }
    if range.location <= 0 { return .boundary }
    var one = CFRange(location: range.location - 1, length: 1)
    guard let axRange = AXValueCreate(.cfRange, &one) else { return .unavailable }
    var out: CFTypeRef?
    guard AXUIElementCopyParameterizedAttributeValue(el, kAXStringForRangeParameterizedAttribute as CFString, axRange, &out) == .success,
          let s = out as? String, let c = s.first else { return .unavailable }
    return .char(c)
  }
}
