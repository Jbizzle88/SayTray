import AppKit
import AVFoundation
import Speech
import CoreAudio
import SayTrayCore
import SBObjC

/// The microphone is released about 3 seconds after a dictation so the menu-bar
/// indicator turns off. It stays open while the dictate modifier is held.
/// "hands-free" is still classified so a headset is not opened just because Option was tapped.
enum InputRoute {
  static let releaseDelay: TimeInterval = 3

  static func kind() -> String {
    let device = defaultDevice()
    if device == 0 { return "unknown" }
    let transport = defaultTransport()
    if transport == kAudioDeviceTransportTypeBluetooth || transport == kAudioDeviceTransportTypeBluetoothLE {
      return "hands-free"
    }
    let name = defaultName()
    if nameLooksHandsFree(name) { return "hands-free" }
    if transport == 0 { return "unknown" }
    return "wired"
  }

  static func releasesQuickly() -> Bool { kind() != "wired" }

  static func idleSeconds() -> TimeInterval { releaseDelay }

  static func describe() -> String {
    let name = defaultName()
    return "\(kind()) \(name.isEmpty ? "unknown input" : name)"
  }

  private static func nameLooksHandsFree(_ name: String) -> Bool {
    let low = name.lowercased()
    if low.hasPrefix("headset (") { return true }
    return low.contains("bluetooth") || low.contains("airpod")
      || low.contains("hands-free") || low.contains("hands free")
      || low.contains(" ag audio") || low.contains("hfp") || low.contains("hsp")
  }

  private static func defaultDevice() -> AudioDeviceID {
    var device = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    var address = AudioObjectPropertyAddress(
      mSelector: kAudioHardwarePropertyDefaultInputDevice,
      mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device)
    return status == noErr ? device : 0
  }

  private static func defaultName() -> String {
    let device = defaultDevice()
    guard device != 0 else { return "" }
    var address = AudioObjectPropertyAddress(
      mSelector: kAudioDevicePropertyDeviceNameCFString,
      mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr, size > 0 else { return "" }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<CFString>.alignment)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, raw) == noErr else { return "" }
    // GetPropertyData returns a +1 CFString. takeRetainedValue releases it.
    let held = raw.load(as: Unmanaged<CFString>.self)
    return held.takeRetainedValue() as String
  }

  private static func defaultTransport() -> UInt32 {
    let device = defaultDevice()
    guard device != 0 else { return 0 }
    var transport: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    var address = AudioObjectPropertyAddress(
      mSelector: kAudioDevicePropertyTransportType,
      mScope: kAudioObjectPropertyScopeGlobal,
      mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(device, &address, 0, nil, &size, &transport)
    return status == noErr ? transport : 0
  }
}

/// Push-to-talk dictation. Every buffer from key-down to key-up is kept (the short ring
/// is only a pre-roll and does not cap the session). After release, the whole clip is
/// recognized in ≤30 s requests — under SFSpeechRecognizer's about-one-minute limit —
/// and the texts are concatenated. A result that does not cover its slice is halved and
/// recognized again, so a long hold comes out from the start through the end.
final class Dictation {
  private enum Phase: String { case idle, arming, recording, grace }
  private struct Clip { var buffer: AVAudioPCMBuffer; var seconds: Double }
  private struct Job { var gen: Int; var buffers: [AVAudioPCMBuffer]; var seconds: Double }

  private let preRollLimit = 0.45
  private let segmentLimit = DictationPlan.segmentLimit
  /// Slices do not share audio. Overlap made repeated phrases and lost more words.
  private let sliceOverlap = 0.0
  private let minLive = 0.15
  private let graceSeconds = 0.25

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
  private var graceGen = 0
  private var shuttingDown = false
  private var idleWork: DispatchWorkItem?
  /// Dictate modifier (Option, or Ctrl+Alt on Windows) is physically down.
  private var modifierHeld = false
  /// When the input engine last reached the running state. A young engine gets a delayed chime.
  private var engineStartedAt: Date?
  /// Give a just-started input engine this long before the start chime, so a route change does not eat it.
  private let chimeSettle: TimeInterval = 0.40
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
    // Already running: leave the one idle timer alone. A modifier tap must not
    // cancel it or start a second one.
    if let eng = engine, eng.isRunning {
      return false
    }
    idleWork?.cancel()
    idleWork = nil
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
    engineStartedAt = Date()
    Log.event("dictation: pre-roll engine running (\(InputRoute.describe()))")
    if phase == .idle { scheduleMicIdle() }
    return true
  }

  /// Keep an already-open mic for the whole modifier hold, including the gaps between rapid dictations.
  func setModifierSession(_ held: Bool) {
    if !Thread.isMainThread {
      DispatchQueue.main.async { self.setModifierSession(held) }
      return
    }
    modifierHeld = held
    if held {
      idleWork?.cancel()
      idleWork = nil
      Log.event("dictation: mic stays open while the dictate modifier is held")
    } else if phase == .idle, !capturing, !shuttingDown {
      scheduleMicIdle()
    }
  }

  func start() {
    if !Thread.isMainThread { DispatchQueue.main.async { self.start() }; return }
    if shuttingDown {
      Log.event("dictation: start ignored, shutting down")
      return
    }
    if phase == .grace { endGrace(graceGen, scheduleIdle: false) }
    if phase == .recording || phase == .arming {
      Log.event("dictation: start ignored, already \(phase.rawValue)")
      return
    }
    idleWork?.cancel()
    idleWork = nil
    if Permissions.speech != .authorized {
      Log.event("dictation: speech recognition not authorized")
      NSSound.beep()
      if Permissions.speech == .notDetermined { Permissions.requestMicAndSpeech(nil) }
      scheduleMicIdle()
      return
    }
    pressedAt = Date()
    generation += 1
    setRecordingUI(true)
    let gen = generation
    // Start capture in this turn. Samples that arrive while the engine is spinning up
    // sit in the pre-roll ring and are copied into the clip, so a cold Option-then-Space
    // still includes the beginning.
    if warmMicrophone() {
      Log.event("dictation: engine just started; capture includes audio from engine start")
    }
    engage(gen)
  }

  func stop() {
    if !Thread.isMainThread { DispatchQueue.main.async { self.stop() }; return }
    switch phase {
    case .idle, .grace:
      return
    case .arming:
      generation += 1
      phase = .idle
      setRecordingUI(false)
      Log.event("dictation: cancelled before capture")
      scheduleMicIdle()
    case .recording:
      graceGen = generation
      phase = .grace
      setRecordingUI(false)
      requestChime("stop", after: 0)
      let gen = graceGen
      DispatchQueue.main.asyncAfter(deadline: .now() + graceSeconds) { [weak self] in
        self?.endGrace(gen)
      }
    }
  }

  /// Keep a short tail after key-up, then clear the ring so it is not the next pre-roll.
  private func endGrace(_ gen: Int, scheduleIdle: Bool = true) {
    guard phase == .grace, gen == graceGen else { return }
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
    let total = audioSeconds(buffers)
    let live = max(0, total - pre)
    let latencyMs: Double
    if let pressedAt, let liveAt { latencyMs = liveAt.timeIntervalSince(pressedAt) * 1000 } else { latencyMs = -1 }
    Log.event("dictation: stopped gen \(gen) audio \(sec(total))s buffers \(buffers.count) (no duration cap) pre-roll \(Int((pre * 1000).rounded()))ms live \(sec(live))s first-buffer \(Int(latencyMs.rounded()))ms")
    if live < minLive {
      Log.event("dictation: too short, ignored")
    } else {
      jobs.append(Job(gen: gen, buffers: buffers, seconds: total))
      Log.event("dictation: queued gen \(gen) (\(jobs.count) in line)")
      pump()
    }
    if scheduleIdle { scheduleMicIdle() }
  }

  private func scheduleMicIdle() {
    idleWork?.cancel()
    idleWork = nil
    if modifierHeld {
      Log.event("dictation: mic stays open while the dictate modifier is held")
      return
    }
    guard engine != nil else { return }
    let seconds = InputRoute.idleSeconds()
    let work = DispatchWorkItem { [weak self] in self?.releaseMicrophoneIfIdle() }
    idleWork = work
    Log.event("dictation: mic stays open for \(Int(seconds))s then releases (\(InputRoute.describe()))")
    DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
  }

  private func releaseMicrophoneIfIdle() {
    guard phase == .idle, !shuttingDown, !capturing, !modifierHeld else {
      if modifierHeld { Log.event("dictation: release skipped; dictate modifier is held") }
      return
    }
    guard engine != nil else { return }
    if let eng = engine {
      _ = SBTryObjC {
        eng.inputNode.removeTap(onBus: 0)
        if eng.isRunning { eng.stop() }
      }
    }
    engine = nil
    engineStartedAt = nil
    if let o = configObs {
      NotificationCenter.default.removeObserver(o)
      configObs = nil
    }
    audioLock.lock()
    ring.removeAll()
    ringSeconds = 0
    audioLock.unlock()
    Log.event("dictation: microphone released after idle; input tap removed and engine stopped (\(InputRoute.describe()))")
  }

  /// Stop the microphone and drop any clip still being recognized. Does not type.
  func shutdown() {
    let work = {
      self.shuttingDown = true
      self.idleWork?.cancel()
      self.idleWork = nil
      self.generation += 1
      self.audioLock.lock()
      self.capturing = false
      self.session.removeAll()
      self.ring.removeAll()
      self.ringSeconds = 0
      self.audioLock.unlock()
      self.jobs.removeAll()
      self.phase = .idle
      self.setRecordingUI(false)
      if let eng = self.engine {
        _ = SBTryObjC {
          eng.inputNode.removeTap(onBus: 0)
          if eng.isRunning { eng.stop() }
        }
      }
      self.engine = nil
      if let o = self.configObs {
        NotificationCenter.default.removeObserver(o)
        self.configObs = nil
      }
      Log.event("dictation: shutdown")
    }
    if Thread.isMainThread { work() } else { DispatchQueue.main.sync(execute: work) }
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
    audioLock.lock()
    let pre = ringSeconds
    session = ring.map { $0.buffer }
    preRollAtStart = pre
    firstLiveAt = nil
    capturing = true
    audioLock.unlock()
    phase = .recording
    setRecordingUI(true)
    let age = Date().timeIntervalSince(engineStartedAt ?? .distantPast)
    let delay = max(0, chimeSettle - age)
    requestChime("start", after: delay, gen: gen)
    let chimeLabel = delay > 0.02 ? "deferred" : "now"
    Log.event("dictation: capture gen \(gen) chime=\(chimeLabel) pre-roll \(Int((pre * 1000).rounded()))ms input=\(InputRoute.describe())")
  }

  private func handleRouteChange() {
    guard let eng = engine else { return }
    Log.event("dictation: audio route changed (a chime playing now may be interrupted)")
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
    guard !shuttingDown else { pumping = false; jobs.removeAll(); return }
    guard Permissions.speech == .authorized else {
      pumping = false
      jobs.removeAll()
      Log.event("dictation: speech recognition not authorized; queued clips dropped")
      return
    }
    guard !pumping, !jobs.isEmpty else { return }
    pumping = true
    let job = jobs.removeFirst()
    let chunks = withOverlap(split(job.buffers))
    Log.event("dictation: kept \(sec(job.seconds))s in \(job.buffers.count) buffers with no duration cap; \(chunks.count) slices of <=\(Int(segmentLimit))s, \(jobs.count) still queued")
    recognizeAll(chunks, index: 0, parts: []) { [weak self] text in
      guard let self else { return }
      if self.shuttingDown {
        self.pumping = false
        Log.event("dictation: dropped transcript gen \(job.gen) (shut down)")
        return
      }
      Log.event("dictation: gen \(job.gen) audio \(sec(job.seconds))s transcript \(text.count) chars across \(chunks.count) slices")
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
        let cut = quietCutIndex(cur)
        if cut > 0, cut < cur.count {
          chunks.append(Array(cur[..<cut]))
          cur = Array(cur[cut...])
          t = cur.reduce(0) { $0 + seconds($1) }
        } else {
          chunks.append(cur)
          cur = []
          t = 0
        }
      }
      cur.append(b)
      t += d
    }
    if !cur.isEmpty { chunks.append(cur) }
    return chunks
  }

  /// Repeat about a second of audio across each cut. The same buffer object is shared;
  /// recognition reads it and does not take ownership.
  private func withOverlap(_ chunks: [[AVAudioPCMBuffer]]) -> [[AVAudioPCMBuffer]] {
    guard chunks.count > 1, sliceOverlap > 0 else { return chunks }
    func taking(_ buffers: [AVAudioPCMBuffer], fromEnd: Bool) -> [AVAudioPCMBuffer] {
      var acc = 0.0
      var picked: [AVAudioPCMBuffer] = []
      let order = fromEnd ? Array(buffers.reversed()) : buffers
      for b in order {
        picked.append(b)
        acc += seconds(b)
        if acc >= sliceOverlap { break }
      }
      return fromEnd ? Array(picked.reversed()) : picked
    }
    return chunks.indices.map { i in
      var piece: [AVAudioPCMBuffer] = []
      if i > 0 { piece.append(contentsOf: taking(chunks[i - 1], fromEnd: true)) }
      piece.append(contentsOf: chunks[i])
      if i + 1 < chunks.count { piece.append(contentsOf: taking(chunks[i + 1], fromEnd: false)) }
      return piece
    }
  }

  /// Index of a quiet buffer in the last 0.35 s, or `buffers.count` when the cut stays at the limit.
  /// Samples are not dropped and are not repeated.
  private func quietCutIndex(_ buffers: [AVAudioPCMBuffer]) -> Int {
    guard buffers.count > 1 else { return buffers.count }
    let times = buffers.map { seconds($0) }
    let total = times.reduce(0, +)
    var acc = 0.0
    var start = buffers.count
    for i in 0..<buffers.count {
      if total - acc <= 0.35 { start = i; break }
      acc += times[i]
    }
    if start <= 0 || start >= buffers.count { return buffers.count }
    let edge = bufferRMS(buffers[buffers.count - 1])
    var best = buffers.count
    var bestRMS = edge
    var i = start
    while i < buffers.count {
      let rms = bufferRMS(buffers[i])
      if rms < bestRMS {
        bestRMS = rms
        best = i
      }
      i += 1
    }
    if best > 0, best < buffers.count, bestRMS < 0.02, bestRMS < edge * 0.5 {
      return best
    }
    return buffers.count
  }

  private func bufferRMS(_ b: AVAudioPCMBuffer) -> Float {
    let n = Int(b.frameLength)
    if n == 0 { return 1 }
    if let ch = b.floatChannelData {
      var sum: Float = 0
      let p = ch[0]
      for i in 0..<n { let s = p[i]; sum += s * s }
      return sqrt(sum / Float(n))
    }
    if let ch = b.int16ChannelData {
      var sum: Float = 0
      let p = ch[0]
      for i in 0..<n {
        let s = Float(p[i]) / 32768
        sum += s * s
      }
      return sqrt(sum / Float(n))
    }
    return 1
  }

  private func recognizeAll(_ chunks: [[AVAudioPCMBuffer]], index: Int, parts: [String], done: @escaping (String) -> Void) {
    if index >= chunks.count {
      done(DictationSpacing.join(parts))
      return
    }
    let audio = audioSeconds(chunks[index])
    Log.event("dictation: slice \(index + 1)/\(chunks.count) \(sec(audio))s")
    recognizeAdaptive(chunks[index], depth: 0) { [weak self] text in
      guard let self else {
        done(DictationSpacing.join(parts + [text]))
        return
      }
      Log.event("dictation: slice \(index + 1)/\(chunks.count) \(self.sec(audio))s -> \(text.count) chars")
      self.recognizeAll(chunks, index: index + 1, parts: parts + [text], done: done)
    }
  }

  /// One request, then halve and try both halves when the transcript skips the front or the tail.
  private func recognizeAdaptive(_ buffers: [AVAudioPCMBuffer], depth: Int, done: @escaping (String) -> Void) {
    guard Permissions.speech == .authorized else {
      Log.event("dictation: speech recognition not authorized")
      done("")
      return
    }
    let audio = audioSeconds(buffers)
    recognizeOnce(buffers) { [weak self] text, first, last, failed in
      guard let self else { done(text); return }
      let again = depth < 4 && DictationPlan.needsResplit(
        audioSeconds: audio, firstWordAt: first, lastWordEnd: last, failed: failed, characters: text.count)
      guard again else { done(text); return }
      let (left, right) = self.halve(buffers)
      guard !left.isEmpty, !right.isEmpty else { done(text); return }
      let firstDesc = first.map { String(format: "%.1f", $0) } ?? "none"
      let lastDesc = last.map { String(format: "%.1f", $0) } ?? "none"
      Log.event("dictation: slice \(self.sec(audio))s result \(text.count) chars covered \(firstDesc)s..\(lastDesc)s; splitting so the rest is kept")
      self.recognizeAdaptive(left, depth: depth + 1) { leftText in
        self.recognizeAdaptive(right, depth: depth + 1) { rightText in
          done(DictationSpacing.join([leftText, rightText]))
        }
      }
    }
  }

  /// text, first-word offset, last-word end, failed. Offsets are seconds into this request.
  private func recognizeOnce(_ buffers: [AVAudioPCMBuffer], done: @escaping (String, Double?, Double?, Bool) -> Void) {
    guard let rec = recognizer, rec.isAvailable else {
      Log.event("dictation: recognizer unavailable")
      done("", nil, nil, true)
      return
    }
    let req = SFSpeechAudioBufferRecognitionRequest()
    req.shouldReportPartialResults = true
    req.addsPunctuation = true
    if rec.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
    let audio = audioSeconds(buffers)
    var text = ""
    var firstWord: Double?
    var lastWord: Double?
    var finished = false
    var task: SFSpeechRecognitionTask?
    func complete(_ reason: String) {
      guard !finished else { return }
      finished = true
      let failed = reason != "final"
      Log.event("dictation: request \(sec(audio))s -> \(text.count) chars first \(firstWord.map { String(format: "%.1f", $0) } ?? "-")s last \(lastWord.map { String(format: "%.1f", $0) } ?? "-")s (\(reason))")
      done(text, firstWord, lastWord, failed)
    }
    let exc = SBTryObjC {
      task = rec.recognitionTask(with: req) { result, error in
        DispatchQueue.main.async {
          if let r = result {
            let next = r.bestTranscription.formattedString
            // A partial is the recognizer's current guess for this whole slice. Keeping
            // every revision and gluing them together repeats the sentence.
            if !text.isEmpty, next != text {
              Log.event("dictation: partial revised (\(text.count) chars -> \(next.count))")
            }
            text = next
            let segs = r.bestTranscription.segments
            if let s = segs.first { firstWord = s.timestamp }
            if let s = segs.last { lastWord = s.timestamp + s.duration }
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
      done("", nil, nil, true)
      return
    }
    for b in buffers {
      if let err = SBTryObjC({ req.append(b) }) {
        Log.event("dictation: append failed: \(err)")
        break
      }
    }
    req.endAudio()
    // A 30 s slice can take longer than the audio to come back on device. Cancelling
    // early is what used to leave only the latest partial.
    let budget = max(90.0, audio * 4)
    DispatchQueue.main.asyncAfter(deadline: .now() + budget) {
      guard !finished else { return }
      task?.cancel()
      complete("timeout")
    }
  }

  private func halve(_ buffers: [AVAudioPCMBuffer]) -> ([AVAudioPCMBuffer], [AVAudioPCMBuffer]) {
    let mid = audioSeconds(buffers) / 2
    var left: [AVAudioPCMBuffer] = []
    var right: [AVAudioPCMBuffer] = []
    var acc = 0.0
    var passed = false
    for b in buffers {
      if !passed {
        left.append(b)
        acc += seconds(b)
        if acc >= mid { passed = true }
      } else {
        right.append(b)
      }
    }
    if right.isEmpty, left.count > 1 {
      let n = left.count / 2
      return (Array(left[..<n]), Array(left[n...]))
    }
    return (left, right)
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

  /// Log the request immediately. Playback of a start chime waits until a young input engine has settled.
  private func requestChime(_ kind: String, after delay: TimeInterval, gen: Int? = nil) {
    guard AppState.shared.chime else {
      Log.event("dictation: \(kind) chime requested but skipped (disabled)")
      return
    }
    Log.event("dictation: \(kind) chime requested")
    let play = { [weak self] in
      guard let self else { return }
      if kind == "start" {
        guard let gen, gen == self.generation, self.phase == .recording else {
          Log.event("dictation: start chime cancelled before playback")
          return
        }
      }
      let ok = Chime.play(kind)
      Log.event("dictation: \(kind) chime started=\(ok)")
    }
    if delay > 0.02 {
      let ms = Int((delay * 1000).rounded())
      Log.event("dictation: \(kind) chime waiting \(ms)ms for the input engine to settle")
      DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: play)
    } else {
      play()
    }
  }
}
