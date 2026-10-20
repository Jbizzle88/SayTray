import Foundation
import SayTrayCore

/// Runs files through the real read pipeline (TextPrep -> PiperEngine -> BabbleGuard) and writes a JSON report.
enum PipelineTest {
  static func run(_ args: [String]) -> Int32 {
    guard args.count >= 2 else { print("usage: --pipeline-test out.json files..."); return 2 }
    let engine = PiperEngine()
    let voice = ProcessInfo.processInfo.environment["SB_VOICE"] ?? "en_US-norman-medium"
    guard engine.ensure(voice: voice) else { print("piper unavailable"); return 3 }
    var report: [[String: Any]] = []
    let base = FileManager.default.temporaryDirectory.appendingPathComponent("saytray-pipeline-test")
    try? FileManager.default.removeItem(at: base)
    for (n, file) in args.dropFirst().enumerated() {
      guard let text = try? String(contentsOfFile: file, encoding: .utf8) else { continue }
      let dir = base.appendingPathComponent("\(n + 1)")
      try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
      let s = ReadSession(id: 1000 + n, chunks: TextPrep.chunks(text), dir: dir, engine: engine)
      let t0 = Date()
      var firstReady: Double?
      s.onUpdate = { if firstReady == nil, s.slots.first?.items != nil { firstReady = Date().timeIntervalSince(t0) } }
      s.start()
      while !s.isComplete && Date().timeIntervalSince(t0) < 300 { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
      func describe(_ slot: ReadSession.Slot) -> [String: Any] {
        let items: [String] = (slot.items ?? []).map { if case .file(let u) = $0 { return u.path } else if case .system(let t) = $0 { return "system:" + t } else { return "" } }
        return ["key": slot.key, "text": slot.text, "words": TextPrep.wordCount(slot.text), "chars": slot.text.count, "phonemes": slot.phonemes,
                "attempts": slot.attempts.map { ["seconds": $0.seconds, "verdict": $0.verdict] },
                "events": slot.events, "items": items, "subs": slot.subs.map(describe)]
      }
      report.append(["file": file, "complete": s.isComplete, "seconds_total": Date().timeIntervalSince(t0),
                     "first_chunk_ready": firstReady ?? -1, "chunks": s.slots.map(describe)])
      print("\(file): \(s.slots.count) chunks, complete=\(s.isComplete)")
    }
    engine.quit()
    if let d = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted]) { try? d.write(to: URL(fileURLWithPath: args[0])) }
    return 0
  }
}
