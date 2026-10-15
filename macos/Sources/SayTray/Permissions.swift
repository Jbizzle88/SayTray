import AppKit
import AVFoundation
import Speech
import ApplicationServices

enum Permissions {
  static var accessibility: Bool { AXIsProcessTrusted() }
  static func promptAccessibility() {
    let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    _ = AXIsProcessTrustedWithOptions(opts)
  }
  static var mic: AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .audio) }
  static var speech: SFSpeechRecognizerAuthorizationStatus { SFSpeechRecognizer.authorizationStatus() }
  static func requestMicAndSpeech(_ done: (() -> Void)? = nil) {
    AVCaptureDevice.requestAccess(for: .audio) { _ in
      SFSpeechRecognizer.requestAuthorization { _ in DispatchQueue.main.async { done?() } }
    }
  }
  static func open(_ pane: String) {
    if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") { NSWorkspace.shared.open(u) }
  }
}

/// Event log: ~/Library/Logs/SayTray/events.log (persistent) and the per-read debug dir.
enum Log {
  static let root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/SayTray")
  static let lastRead = root.appendingPathComponent("last")
  private static let q = DispatchQueue(label: "saytray.log")
  static func append(_ line: String, to url: URL) {
    q.async {
      try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
      let ts = ISO8601DateFormatter().string(from: Date())
      let data = Data("\(ts) \(line)\n".utf8)
      if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(data); try? h.close() }
      else { try? data.write(to: url) }
    }
  }
  static func event(_ s: String) { NSLog("SayTray: %@", s); append(s, to: root.appendingPathComponent("events.log")) }
  static func guardTrigger(_ s: String) { event("GUARD " + s); append(s, to: root.appendingPathComponent("guard.log")) }
}
