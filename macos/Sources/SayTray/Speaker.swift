import AppKit
import SayTrayCore

/// Coordinates a read: TextPrep -> ReadSession (Piper + guard) -> Player. One read at a time.
final class Speaker {
  let engine = PiperEngine()
  let player = Player()
  private var session: ReadSession?
  private var nextIndex = 0
  private var readID = 0
  var isSpeaking: Bool { session != nil || !player.isIdle }

  init() { player.onIdle = { [weak self] in self?.pump() } }

  func warmUp() { if AppState.shared.engine == "piper" { engine.ensure(voice: AppState.shared.piperVoice) } }

  func speak(_ text: String) {
    stop()
    let st = AppState.shared
    let chunks = TextPrep.chunks(text)
    guard !chunks.isEmpty else { NSSound.beep(); return }
    readID += 1
    let dir = Log.lastRead
    let fm = FileManager.default
    try? fm.removeItem(at: dir); try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
    let scalars = text.unicodeScalars.map { $0.value >= 32 && $0.value < 127 ? String($0) : String(format: "<U+%04X>", $0.value) }.joined()
    let dump = "READ \(readID) ENGINE \(st.engine) VOICE \(st.piperVoice) SPEED \(st.speed)\n--- RAW ---\n\(text)\n--- SCALARS ---\n\(scalars)\n--- CHUNKS ---\n"
      + chunks.enumerated().map { String(format: "%03d", $0.offset + 1) + ": " + $0.element }.joined(separator: "\n") + "\n"
    try? dump.write(to: dir.appendingPathComponent("input.txt"), atomically: true, encoding: .utf8)
    player.speed = st.speed
    player.systemVoiceID = st.voiceID
    player.playLog = dir.appendingPathComponent("play.log")
    let usePiper = st.engine == "piper" && engine.ensure(voice: st.piperVoice)
    let s = ReadSession(id: readID, chunks: chunks, dir: dir, engine: usePiper ? engine : nil)
    s.onUpdate = { [weak self, weak s] in guard let self, let s, self.session === s else { return }; self.pump() }
    session = s; nextIndex = 0
    st.isSpeaking = true
    s.start()
  }

  private func pump() {
    guard let s = session else { return }
    while nextIndex < s.slots.count, let items = s.slots[nextIndex].items {
      player.enqueue(items); nextIndex += 1
    }
    if nextIndex == s.slots.count && player.isIdle { session = nil; AppState.shared.isSpeaking = false }
  }

  func stop() {
    if let s = session { s.cancelled = true; engine.cancel(read: s.id) }
    session = nil
    player.stop()
    AppState.shared.isSpeaking = false
  }

  func quit() { stop(); engine.quit() }
}
