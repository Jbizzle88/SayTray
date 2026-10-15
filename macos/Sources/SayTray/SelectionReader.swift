import AppKit
import ApplicationServices

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
  static func type(_ text: String) {
    let saved = Keys.snapshot()
    let pb = NSPasteboard.general
    pb.clearContents(); pb.setString(text, forType: .string)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
      Keys.postCmd(9) // V
      DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { Keys.restore(saved) }
    }
  }
}
