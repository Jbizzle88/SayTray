import Foundation
import SayTrayCore

/// One read: chunks -> Piper WAVs (with babble guard) -> ordered PlayItems.
final class ReadSession {
  final class Slot {
    let text: String
    let key: String
    weak var parent: Slot?
    var items: [PlayItem]?
    var subs: [Slot] = []
    var attempts: [(seconds: Double, verdict: String)] = []
    var events: [String] = []
    var phonemes = 0
    init(text: String, key: String, parent: Slot? = nil) { self.text = text; self.key = key; self.parent = parent }
  }
  let id: Int
  let dir: URL
  let slots: [Slot]
  private let engine: PiperEngine?
  var cancelled = false
  var onUpdate: (() -> Void)?
  var resolvedCount: Int { slots.filter { $0.items != nil }.count }
  var isComplete: Bool { slots.allSatisfy { $0.items != nil } }

  init(id: Int, chunks: [String], dir: URL, engine: PiperEngine?) {
    self.id = id; self.dir = dir; self.engine = engine
    slots = chunks.enumerated().map { Slot(text: $0.element, key: String(format: "%03d", $0.offset + 1)) }
  }

  func start() {
    guard let engine else { for s in slots { s.items = [.system(s.text)] }; onUpdate?(); return }
    for s in slots { submit(s, engine: engine, attempt: 0) }
  }

  /// attempt 0: normal noise. 1: strict noise. Sub-chunks: 0 = strict only.
  private func submit(_ s: Slot, engine: PiperEngine, attempt: Int) {
    let isSub = s.parent != nil
    let noise: PiperEngine.Noise = (attempt == 0 && !isSub) ? .normal : .strict  // subs and retries: lower noise
    let name = "r\(id)-\(s.key)-a\(attempt)"
    engine.synthesize(read: id, name: name, text: s.text, dir: dir, noise: noise, priority: attempt > 0 || isSub) { [weak self] result in
      guard let self, !self.cancelled else { return }
      switch result {
      case .failure(let e):
        self.trigger(s, "engine failure (\(e)); using system voice")
        self.resolve(s, [.system(s.text)])
      case .success(let (url, secs, phonemes)):
        let v = BabbleGuard.check(text: s.text, seconds: secs, phonemes: phonemes)
        s.attempts.append((secs, v.ok ? "ok" : v.reason))
        s.phonemes = phonemes
        if v.ok { self.resolve(s, [.file(url)]); return }
        let detail = String(format: "%.2fs, %d phonemes, %.3f s/phoneme, %.3f s/word", secs, phonemes, v.secPerPhoneme, v.secPerWord)
        if !isSub && attempt == 0, let halves = TextPrep.splitInHalf(s.text) {
          // Smaller inputs are the most reliable fix; synthesize both halves with lower noise.
          self.trigger(s, "\(v.reason) (\(detail)); splitting into 2 parts with lower noise")
          s.subs = halves.enumerated().map { Slot(text: $0.element, key: "\(s.key)s\($0.offset)", parent: s) }
          for sub in s.subs { self.submit(sub, engine: engine, attempt: 0) }
        } else if attempt == 0 {
          self.trigger(s, "\(v.reason) (\(detail)); re-synthesizing with lower noise")
          self.submit(s, engine: engine, attempt: 1)
        } else {
          self.trigger(s, "\(v.reason) again (\(detail)); using system voice")
          self.resolve(s, [.system(s.text)])
        }
      }
    }
  }

  private func trigger(_ s: Slot, _ msg: String) {
    s.events.append(msg)
    Log.guardTrigger("read \(id) chunk \(s.key): \(msg) (\(s.text.count) chars)")
    Log.append("GUARD chunk \(s.key): \(msg)", to: dir.appendingPathComponent("play.log"))
  }

  private func resolve(_ s: Slot, _ items: [PlayItem]) {
    s.items = items
    if let p = s.parent, p.subs.allSatisfy({ $0.items != nil }) { p.items = p.subs.flatMap { $0.items ?? [] } }
    onUpdate?()
  }
}
