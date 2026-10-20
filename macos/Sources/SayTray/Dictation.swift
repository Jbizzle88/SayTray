import AppKit
import AVFoundation
import Speech
import SBObjC

/// Push-to-talk dictation: start() on key down, stop() on key up; final text is typed at the cursor.
///
/// A generation token walls off each hold. Releasing the key and pressing it again — including while
/// the modifier stays down and while the previous result is still finalizing — cancels only the old
/// recognition task. The start chime plays before the microphone opens, so the input engine cannot
/// cut it off, and the tone is never transcribed.
final class Dictation {
  private enum Phase: String { case idle, arming, recording, finalizing }

  private var engine: AVAudioEngine?
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) ?? SFSpeechRecognizer()
  private var latest = ""
  private var delivered = true
  private var configObs: NSObjectProtocol?
  private var phase: Phase = .idle
  private var generation = 0
  private var sessionToken = UUID()
  private(set) var isRecording = false
  private var capturing = false
  var onText: ((String) -> Void)?

  func start() {
    if !Thread.isMainThread { DispatchQueue.main.async { self.start() }; return }
    switch phase {
    case .arming, .recording:
      Log.event("dictation: start ignored, already \(phase.rawValue)")
      return
    case .finalizing:
      Log.event("dictation: previous session still finalizing; delivering it and starting fresh")
      deliver(reason: "superseded")
    case .idle:
      break
    }
    generation += 1
    arm(generation)
  }

  func stop() {
    if !Thread.isMainThread { DispatchQueue.main.async { self.stop() }; return }
    switch phase {
    case .idle, .finalizing:
      return
    case .arming:
      // Drop the pending microphone open. A tap during the chime must not leave a session behind.
      generation += 1
      phase = .idle
      setRecordingUI(false)
      capturing = false
      playChime("stop")
      Log.event("dictation: cancelled before microphone opened")
    case .recording:
      let gen = generation
      capturing = false
      teardownAudio()
      phase = .finalizing
      setRecordingUI(false)
      playChime("stop")
      Log.event("dictation: stopped gen \(gen), waiting for final result")
      DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in self?.finish(gen) }
    }
  }

  /// Chime first, then open the mic on this generation. stop() during the wait bumps generation.
  private func arm(_ gen: Int) {
    phase = .arming
    latest = ""
    delivered = false
    capturing = false
    setRecordingUI(true)
    let ok = playChime("start")
    let delay = ok ? Chime.leadIn : 0
    Log.event("dictation: arming gen \(gen)")
    DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.openMic(gen, attempt: 0) }
  }

  private func openMic(_ gen: Int, attempt: Int) {
    guard gen == generation, phase == .arming else {
      Log.event("dictation: openMic skipped gen \(gen)")
      return
    }
    guard Permissions.mic == .authorized, Permissions.speech == .authorized else {
      abandon(gen, "dictation: missing mic/speech permission", beep: true)
      Permissions.requestMicAndSpeech()
      return
    }
    guard let rec = recognizer, rec.isAvailable else {
      abandon(gen, "dictation: recognizer unavailable", beep: true)
      return
    }
    let req = SFSpeechAudioBufferRecognitionRequest()
    req.shouldReportPartialResults = true
    req.addsPunctuation = true
    if rec.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
    let eng = AVAudioEngine()
    if !installTap(eng, req) {
      _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0); eng.stop() }
      if attempt < 2 {
        Log.event("dictation: installTap failed, retry \(attempt + 1)")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in self?.openMic(gen, attempt: attempt + 1) }
        return
      }
      abandon(gen, "dictation: installTap failed", beep: true)
      return
    }
    var startErr: Error?
    let exc = SBTryObjC { eng.prepare(); do { try eng.start() } catch { startErr = error } }
    if exc != nil || startErr != nil {
      Log.event("dictation: audio start failed \(exc ?? "") \(String(describing: startErr))")
      _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0); eng.stop() }
      if attempt < 2 {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in self?.openMic(gen, attempt: attempt + 1) }
        return
      }
      abandon(gen, "dictation: audio start failed", beep: true)
      return
    }
    guard gen == generation, phase == .arming else {
      _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0); eng.stop() }
      Log.event("dictation: microphone opened after cancel, closed it")
      return
    }
    engine = eng
    request = req
    capturing = true
    phase = .recording
    configObs = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: eng, queue: .main) { [weak self] _ in
      self?.handleRouteChange()
    }
    let token = UUID()
    sessionToken = token
    var newTask: SFSpeechRecognitionTask?
    let taskExc = SBTryObjC {
      newTask = rec.recognitionTask(with: req) { [weak self] result, error in
        DispatchQueue.main.async {
          // A retry or a newer hold replaces sessionToken / generation. This callback must not
          // finish that newer session (only one recognition task is allowed).
          guard let self, gen == self.generation, token == self.sessionToken else { return }
          if let r = result {
            self.latest = r.bestTranscription.formattedString
            if r.isFinal { self.finish(gen) }
          }
          if let error {
            Log.event("dictation: recognition ended: \(error.localizedDescription)")
            self.finish(gen)
          }
        }
      }
    }
    if taskExc != nil || newTask == nil {
      newTask?.cancel()
      sessionToken = UUID()
      Log.event("dictation: recognitionTask failed \(taskExc ?? "")")
      teardownAudio()
      if attempt < 2 {
        phase = .arming
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in self?.openMic(gen, attempt: attempt + 1) }
        return
      }
      abandon(gen, "dictation: recognitionTask failed", beep: true)
      return
    }
    task = newTask
    Log.event("dictation: started gen \(gen)")
  }

  /// Bluetooth headsets switch profile when the mic opens; re-install the tap with the new format.
  private func handleRouteChange() {
    guard phase == .recording, let eng = engine, let req = request else { return }
    _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0) }
    guard installTap(eng, req) else { stop(); return }
    var startErr: Error?
    let exc = SBTryObjC { if !eng.isRunning { eng.prepare(); do { try eng.start() } catch { startErr = error } } }
    if exc != nil || startErr != nil { Log.event("dictation: restart after route change failed"); stop() }
    else { Log.event("dictation: audio route changed, tap re-installed") }
  }

  private func installTap(_ eng: AVAudioEngine, _ req: SFSpeechAudioBufferRecognitionRequest) -> Bool {
    let input = eng.inputNode
    let fmt = input.inputFormat(forBus: 0)
    guard fmt.sampleRate > 0, fmt.channelCount > 0 else { Log.event("dictation: no usable input (\(fmt))"); return false }
    if let e = SBTryObjC({ input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in
      guard self?.capturing == true else { return }
      req.append(buf)
    } }) {
      Log.event("dictation: installTap failed: \(e)"); return false
    }
    return true
  }

  private func teardownAudio() {
    if let o = configObs { NotificationCenter.default.removeObserver(o); configObs = nil }
    if let eng = engine {
      _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0); eng.stop() }
      engine = nil
    }
    request?.endAudio()
  }

  private func finish(_ gen: Int) {
    guard gen == generation else { return }
    guard phase == .recording || phase == .finalizing else { return }
    deliver(reason: "final")
  }

  /// Hand the current text to the cursor and drop this session's task. Safe to call while finalizing.
  private func deliver(reason: String) {
    sessionToken = UUID()
    teardownAudio()
    let oldTask = task
    task = nil
    request = nil
    phase = .idle
    setRecordingUI(false)
    capturing = false
    if !delivered {
      delivered = true
      let t = latest.trimmingCharacters(in: .whitespacesAndNewlines)
      Log.event("dictation: delivered \(t.count) chars (\(reason))")
      if !t.isEmpty { onText?(t) }
    }
    oldTask?.cancel()
  }

  private func abandon(_ gen: Int, _ message: String, beep: Bool) {
    guard gen == generation else { return }
    sessionToken = UUID()
    teardownAudio()
    task?.cancel(); task = nil; request = nil
    phase = .idle
    setRecordingUI(false)
    capturing = false
    delivered = true
    Log.event(message)
    if beep { NSSound.beep() }
  }

  private func setRecordingUI(_ on: Bool) {
    isRecording = on
    AppState.shared.isRecording = on
  }

  /// Returns whether a start chime actually began (callers wait it out before opening the mic).
  @discardableResult
  private func playChime(_ kind: String) -> Bool {
    guard AppState.shared.chime else { return false }
    let ok = Chime.play(kind)
    Log.event("dictation: \(kind) chime \(ok ? "started" : "FAILED")")
    return kind == "start" && ok
  }
}
