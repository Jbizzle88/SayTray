import AppKit
import AVFoundation
import Speech
import SayTrayCore
import SBObjC

/// Push-to-talk dictation. The microphone stays warm and keeps ~450 ms of audio so the
/// start of a phrase is not lost to engine startup or the chime. Recognition runs after
/// the key is released, in ≤50 s pieces, so a long hold is concatenated instead of
/// keeping only the last segment. Results are handed to `onText` in press order.
final class Dictation {
  private enum Phase: String { case idle, arming, recording }
  private struct Clip { var buffer: AVAudioPCMBuffer; var seconds: Double }
  private struct Job { var gen: Int; var buffers: [AVAudioPCMBuffer]; var seconds: Double }

  private let preRollLimit = 0.45
  private let segmentLimit = 50.0
  private let minLive = 0.15

  private var engine: AVAudioEngine?
  private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) ?? SFSpeechRecognizer()
  private var configObs: NSObjectProtocol?
  private let audioLock = NSLock()
  private var ring: [Clip] = []
  private var ringSeconds = 0.0
  private var session: [AVAudioPCMBuffer] = []
  private var capturing = false
  private var preRollAtStart = 0.0
  private var pressedAt: Date?
  private var firstLiveAt: Date?
  private var phase: Phase = .idle
  private var generation = 0
  private var jobs: [Job] = []
  private var pumping = false
  private var loggedCopyFail = false
  private(set) var isRecording = false
  var onText: ((String) -> Void)?

  /// Start the input engine before the first hotkey so the chime does not share a turn
  /// with `AVAudioEngine.start()`, and so a pre-roll already exists. Returns true when
  /// this call is the one that started the engine.
  @discardableResult
  func warmMicrophone() -> Bool {
    if !Thread.isMainThread {
      DispatchQueue.main.async { self.warmMicrophone() }
      return false
    }
    guard Permissions.mic == .authorized else {
      Log.event("dictation: pre-roll waiting for microphone permission")
      return false
    }
    if let eng = engine, eng.isRunning { return false }
    let created = engine == nil
    let eng = engine ?? AVAudioEngine()
    if created {
      guard installTap(eng) else {
        Log.event("dictation: pre-roll tap failed")
        return false
      }
      engine = eng
      if let o = configObs { NotificationCenter.default.removeObserver(o) }
      configObs = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: eng, queue: .main) { [weak self] _ in
        self?.handleRouteChange()
      }
    }
    var startErr: Error?
    let exc = SBTryObjC { eng.prepare(); do { try eng.start() } catch { startErr = error } }
    if exc != nil || startErr != nil || !eng.isRunning {
      Log.event("dictation: pre-roll start failed \(exc ?? "") \(String(describing: startErr))")
      return false
    }
    Log.event("dictation: pre-roll engine running")
    return true
  }

  func start() {
    if !Thread.isMainThread { DispatchQueue.main.async { self.start() }; return }
    if phase == .recording || phase == .arming {
      Log.event("dictation: start ignored, already \(phase.rawValue)")
      return
    }
    pressedAt = Date()
    generation += 1
    setRecordingUI(true)
    let gen = generation
    let justStarted = warmMicrophone()
    if justStarted {
      phase = .arming
      Log.event("dictation: engine just started; playing the chime on the next turn")
      DispatchQueue.main.async { [weak self] in self?.engage(gen) }
    } else {
      engage(gen)
    }
  }

  func stop() {
    if !Thread.isMainThread { DispatchQueue.main.async { self.stop() }; return }
    switch phase {
    case .idle:
      return
    case .arming:
      generation += 1
      phase = .idle
      setRecordingUI(false)
      Log.event("dictation: cancelled before capture")
    case .recording:
      let gen = generation
      audioLock.lock()
      capturing = false
      let buffers = session
      session = []
      let pre = preRollAtStart
      let liveAt = firstLiveAt
      ring.removeAll()
      ringSeconds = 0
      audioLock.unlock()
      phase = .idle
      setRecordingUI(false)
      playChime("stop")
      let total = audioSeconds(buffers)
      let live = max(0, total - pre)
      let latencyMs: Double
      if let pressedAt, let liveAt { latencyMs = liveAt.timeIntervalSince(pressedAt) * 1000 } else { latencyMs = -1 }
      Log.event("dictation: stopped gen \(gen) audio \(sec(total))s pre-roll \(Int((pre * 1000).rounded()))ms live \(sec(live))s first-buffer \(Int(latencyMs.rounded()))ms")
      if live < minLive {
        Log.event("dictation: too short, ignored")
        return
      }
      jobs.append(Job(gen: gen, buffers: buffers, seconds: total))
      Log.event("dictation: queued gen \(gen) (\(jobs.count) in line)")
      pump()
    }
  }

  private func engage(_ gen: Int) {
    guard gen == generation else {
      Log.event("dictation: engage skipped gen \(gen)")
      return
    }
    guard engine?.isRunning == true else {
      phase = .idle
      setRecordingUI(false)
      Log.event("dictation: microphone not running")
      NSSound.beep()
      return
    }
    let chimeLabel: String
    switch playChime("start") {
    case .some(true): chimeLabel = "played"
    case .some(false): chimeLabel = "FAILED"
    case .none: chimeLabel = "off"
    }
    audioLock.lock()
    let pre = ringSeconds
    session = ring.map { $0.buffer }
    preRollAtStart = pre
    firstLiveAt = nil
    capturing = true
    audioLock.unlock()
    phase = .recording
    setRecordingUI(true)
    Log.event("dictation: capture gen \(gen) chime=\(chimeLabel) pre-roll \(Int((pre * 1000).rounded()))ms")
  }

  private func handleRouteChange() {
    guard let eng = engine else { return }
    Log.event("dictation: audio route changed")
    _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0) }
    guard installTap(eng) else {
      Log.event("dictation: tap re-install failed after route change")
      return
    }
    var startErr: Error?
    let exc = SBTryObjC { if !eng.isRunning { eng.prepare(); do { try eng.start() } catch { startErr = error } } }
    if exc != nil || startErr != nil {
      Log.event("dictation: route restart failed \(exc ?? "") \(String(describing: startErr))")
    } else {
      Log.event("dictation: tap re-installed after route change")
    }
  }

  private func installTap(_ eng: AVAudioEngine) -> Bool {
    let input = eng.inputNode
    let fmt = input.inputFormat(forBus: 0)
    guard fmt.sampleRate > 0, fmt.channelCount > 0 else {
      Log.event("dictation: no usable input (\(fmt))")
      return false
    }
    if let e = SBTryObjC({ input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in
      self?.take(buf)
    } }) {
      Log.event("dictation: installTap failed: \(e)")
      return false
    }
    return true
  }

  private func take(_ buf: AVAudioPCMBuffer) {
    guard let copy = copyBuffer(buf) else { return }
    audioLock.lock()
    pushRing(copy)
    if capturing {
      if firstLiveAt == nil { firstLiveAt = Date() }
      session.append(copy)
    }
    audioLock.unlock()
  }

  private func pushRing(_ copy: AVAudioPCMBuffer) {
    let dur = seconds(copy)
    ring.append(Clip(buffer: copy, seconds: dur))
    ringSeconds += dur
    while ringSeconds > preRollLimit, ring.count > 1 {
      ringSeconds -= ring.removeFirst().seconds
    }
  }

  private func pump() {
    guard !pumping, !jobs.isEmpty else { return }
    pumping = true
    let job = jobs.removeFirst()
    let chunks = split(job.buffers)
    Log.event("dictation: transcribing gen \(job.gen) \(sec(job.seconds))s in \(chunks.count) segment(s), \(jobs.count) still queued")
    recognizeAll(chunks, index: 0, parts: []) { [weak self] text in
      guard let self else { return }
      Log.event("dictation: gen \(job.gen) audio \(sec(job.seconds))s transcript \(text.count) chars")
      if !text.isEmpty { self.onText?(text) }
      self.pumping = false
      self.pump()
    }
  }

  private func split(_ buffers: [AVAudioPCMBuffer]) -> [[AVAudioPCMBuffer]] {
    var chunks: [[AVAudioPCMBuffer]] = []
    var cur: [AVAudioPCMBuffer] = []
    var t = 0.0
    for b in buffers {
      let d = seconds(b)
      if t + d > segmentLimit, !cur.isEmpty {
        chunks.append(cur)
        cur = []
        t = 0
      }
      cur.append(b)
      t += d
    }
    if !cur.isEmpty { chunks.append(cur) }
    return chunks
  }

  private func recognizeAll(_ chunks: [[AVAudioPCMBuffer]], index: Int, parts: [String], done: @escaping (String) -> Void) {
    if index >= chunks.count {
      done(DictationSpacing.join(parts))
      return
    }
    Log.event("dictation: segment \(index + 1)/\(chunks.count) \(sec(audioSeconds(chunks[index])))s")
    recognizeChunk(chunks[index]) { [weak self] text in
      guard let self else {
        done(DictationSpacing.join(parts + [text]))
        return
      }
      self.recognizeAll(chunks, index: index + 1, parts: parts + [text], done: done)
    }
  }

  private func recognizeChunk(_ buffers: [AVAudioPCMBuffer], done: @escaping (String) -> Void) {
    guard let rec = recognizer, rec.isAvailable else {
      Log.event("dictation: recognizer unavailable")
      done("")
      return
    }
    let req = SFSpeechAudioBufferRecognitionRequest()
    req.shouldReportPartialResults = true
    req.addsPunctuation = true
    if rec.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
    var text = ""
    var finished = false
    var task: SFSpeechRecognitionTask?
    func complete(_ reason: String) {
      guard !finished else { return }
      finished = true
      Log.event("dictation: segment \(text.count) chars (\(reason))")
      done(text)
    }
    let exc = SBTryObjC {
      task = rec.recognitionTask(with: req) { result, error in
        DispatchQueue.main.async {
          if let r = result {
            let next = r.bestTranscription.formattedString
            let merged = DictationSpacing.merge(text, next)
            if !text.isEmpty, merged != next, !next.hasPrefix(text), !text.hasPrefix(next) {
              Log.event("dictation: partial replaced earlier text (\(text.count) chars); concatenating")
            }
            text = merged
            if r.isFinal { complete("final") }
          }
          if let error {
            Log.event("dictation: recognition ended: \(error.localizedDescription)")
            complete("error")
          }
        }
      }
    }
    if exc != nil || task == nil {
      finished = true
      Log.event("dictation: recognitionTask failed \(exc ?? "")")
      done("")
      return
    }
    for b in buffers { req.append(b) }
    req.endAudio()
    DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
      guard !finished else { return }
      task?.cancel()
      complete("timeout")
    }
  }

  private func sec(_ x: Double) -> String { String(format: "%.2f", x) }

  private func seconds(_ b: AVAudioPCMBuffer) -> Double {
    guard b.format.sampleRate > 0 else { return 0 }
    return Double(b.frameLength) / b.format.sampleRate
  }

  private func audioSeconds(_ buffers: [AVAudioPCMBuffer]) -> Double {
    buffers.reduce(0) { $0 + seconds($1) }
  }

  private func copyBuffer(_ src: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
    guard src.frameLength > 0,
          let dst = AVAudioPCMBuffer(pcmFormat: src.format, frameCapacity: src.frameLength) else { return nil }
    dst.frameLength = src.frameLength
    let frames = Int(src.frameLength)
    let channels = Int(src.format.channelCount)
    if let s = src.floatChannelData, let d = dst.floatChannelData {
      for c in 0..<channels { d[c].update(from: s[c], count: frames) }
      return dst
    }
    if let s = src.int16ChannelData, let d = dst.int16ChannelData {
      for c in 0..<channels { d[c].update(from: s[c], count: frames) }
      return dst
    }
    if !loggedCopyFail {
      loggedCopyFail = true
      let fmt = src.format
      DispatchQueue.main.async { Log.event("dictation: buffer format not copied (\(fmt))") }
    }
    return nil
  }

  private func setRecordingUI(_ on: Bool) {
    isRecording = on
    AppState.shared.isRecording = on
  }

  /// nil when chimes are turned off, otherwise whether playback started.
  @discardableResult
  private func playChime(_ kind: String) -> Bool? {
    guard AppState.shared.chime else {
      Log.event("dictation: \(kind) chime skipped (disabled)")
      return nil
    }
    return Chime.play(kind)
  }
}
