import AVFoundation

enum PlayItem { case file(URL), system(String) }

/// Plays items strictly in order: Piper WAVs via plain AVAudioPlayer (rate = speed), fallbacks via the system voice.
final class Player: NSObject, AVAudioPlayerDelegate, AVSpeechSynthesizerDelegate {
  private var queue: [PlayItem] = []
  private var current: AVAudioPlayer?
  private var currentUtterance: AVSpeechUtterance?
  private let synth = AVSpeechSynthesizer()
  var speed: Double = 1
  var systemVoiceID = ""
  var playLog: URL?
  var onIdle: (() -> Void)?
  var isIdle: Bool { current == nil && currentUtterance == nil && queue.isEmpty }

  override init() { super.init(); synth.delegate = self }

  func enqueue(_ items: [PlayItem]) { queue += items; next() }

  func stop() {
    queue = []
    current?.stop(); current = nil
    currentUtterance = nil
    synth.stopSpeaking(at: .immediate)
  }

  private func next() {
    guard current == nil, currentUtterance == nil else { return }
    guard !queue.isEmpty else { onIdle?(); return }
    let item = queue.removeFirst()
    switch item {
    case .file(let url):
      log("PLAY \(url.lastPathComponent)")
      guard let p = try? AVAudioPlayer(contentsOf: url) else { log("ERROR cannot open \(url.lastPathComponent)"); next(); return }
      p.enableRate = true
      p.rate = Float(min(max(speed, 0.5), 2.0))
      p.delegate = self
      current = p
      p.prepareToPlay(); p.play()
    case .system(let text):
      log("PLAY system: \(text)")
      let u = AVSpeechUtterance(string: text)
      if let v = AVSpeechSynthesisVoice(identifier: systemVoiceID) ?? AVSpeechSynthesisVoice(language: "en-US") { u.voice = v }
      let base = Double(AVSpeechUtteranceDefaultSpeechRate), maxR = Double(AVSpeechUtteranceMaximumSpeechRate)
      let r = speed >= 1 ? base + (speed - 1) * (maxR - base) / 2 : base * speed
      u.rate = Float(min(max(r, Double(AVSpeechUtteranceMinimumSpeechRate)), maxR))
      currentUtterance = u
      synth.speak(u)
    }
  }
  private func log(_ s: String) { if let l = playLog { Log.append(s, to: l) } }

  func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
    DispatchQueue.main.async { guard player === self.current else { return }; self.current = nil; self.next() }
  }
  func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
    DispatchQueue.main.async { guard player === self.current else { return }; self.current = nil; self.next() }
  }
  func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
    DispatchQueue.main.async { guard u === self.currentUtterance else { return }; self.currentUtterance = nil; self.next() }
  }
  func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) {
    DispatchQueue.main.async { guard u === self.currentUtterance else { return }; self.currentUtterance = nil; self.next() }
  }
}


/// Short dictation start/stop tones (kept off the speech queue so they never block a read).
enum Chime {
  private static var player: AVAudioPlayer?
  static func play(_ kind: String) {
    let start = kind == "start"
    let sr = 22050
    let dur = start ? 0.12 : 0.10
    let f0 = start ? 520.0 : 620.0
    let f1 = start ? 780.0 : 380.0
    let amp = start ? 0.22 : 0.12
    let n = Int(Double(sr) * dur)
    var samples = [Int16](repeating: 0, count: n)
    var phase = 0.0
    for i in 0..<n {
      let t = Double(i) / Double(sr)
      let f = f0 + (f1 - f0) * (t / dur)
      phase += 2 * .pi * f / Double(sr)
      let env = sin(.pi * min(1, max(0, t / dur)))
      samples[i] = Int16(max(-32767, min(32767, Int((amp * env * sin(phase) * 32767.0).rounded()))))
    }
    var data = Data()
    func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
    func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
    let bytes = UInt32(n * 2)
    data.append(contentsOf: Array("RIFF".utf8)); u32(36 + bytes); data.append(contentsOf: Array("WAVEfmt ".utf8))
    u32(16); u16(1); u16(1); u32(UInt32(sr)); u32(UInt32(sr * 2)); u16(2); u16(16)
    data.append(contentsOf: Array("data".utf8)); u32(bytes)
    for s in samples { u16(UInt16(bitPattern: s)) }
    do {
      let p = try AVAudioPlayer(data: data)
      p.volume = 1
      player = p
      p.prepareToPlay(); p.play()
    } catch {
      Log.event("chime error: \(error)")
    }
  }
}
