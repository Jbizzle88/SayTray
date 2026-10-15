import AppKit
import AVFoundation
import Speech
import SBObjC

/// Push-to-talk dictation: start() on key down, stop() on key up; final text is typed at the cursor.
final class Dictation {
  private var engine: AVAudioEngine?
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) ?? SFSpeechRecognizer()
  private var latest = ""
  private var delivered = true
  private var configObs: NSObjectProtocol?
  private(set) var isRecording = false
  private var capturing = false   // false while the start chime plays so it is never transcribed
  var onText: ((String) -> Void)?

  func start() {
    guard !isRecording else { return }
    guard Permissions.mic == .authorized, Permissions.speech == .authorized else {
      Log.event("dictation: missing mic/speech permission"); Permissions.requestMicAndSpeech(); NSSound.beep(); return
    }
    guard let rec = recognizer, rec.isAvailable else { Log.event("dictation: recognizer unavailable"); NSSound.beep(); return }
    let req = SFSpeechAudioBufferRecognitionRequest()
    req.shouldReportPartialResults = true
    req.addsPunctuation = true
    if rec.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
    // Fresh engine each time so route changes (Bluetooth, unplugged mics) never leave a stale format.
    let eng = AVAudioEngine()
    guard installTap(eng, req) else { NSSound.beep(); return }
    var startErr: Error?
    let exc = SBTryObjC { eng.prepare(); do { try eng.start() } catch { startErr = error } }
    if exc != nil || startErr != nil {
      Log.event("dictation: audio start failed \(exc ?? "") \(String(describing: startErr))")
      _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0) }
      NSSound.beep(); return
    }
    engine = eng; request = req; latest = ""; delivered = false; isRecording = true; capturing = false
    AppState.shared.isRecording = true
    configObs = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: eng, queue: .main) { [weak self] _ in
      self?.handleRouteChange()
    }
    task = rec.recognitionTask(with: req) { [weak self] result, error in
      DispatchQueue.main.async {
        guard let self else { return }
        if let r = result {
          self.latest = r.bestTranscription.formattedString
          if r.isFinal { self.finish() }
        }
        if let error { Log.event("dictation: recognition ended: \(error.localizedDescription)"); self.finish() }
      }
    }
    // Chime after the mic is open; keep capturing off until it finishes so the tone is never transcribed.
    if AppState.shared.chime {
      Chime.play("start")
      DispatchQueue.main.asyncAfter(deadline: .now() + 0.20) { [weak self] in self?.capturing = true }
    } else {
      capturing = true
    }
    Log.event("dictation: started")
  }

  /// Bluetooth headsets switch profile when the mic opens; re-install the tap with the new format.
  private func handleRouteChange() {
    guard isRecording, let eng = engine, let req = request else { return }
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

  private func stopAudio() {
    guard isRecording else { return }
    if let o = configObs { NotificationCenter.default.removeObserver(o); configObs = nil }
    if let eng = engine { _ = SBTryObjC { eng.inputNode.removeTap(onBus: 0); eng.stop() } }
    engine = nil
    request?.endAudio()
    isRecording = false
    AppState.shared.isRecording = false
  }

  func stop() {
    guard isRecording else { return }
    capturing = false
    stopAudio()
    if AppState.shared.chime { Chime.play("stop") }
    Log.event("dictation: stopped, waiting for final result")
    DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in self?.finish() }
  }

  private func finish() {
    stopAudio()
    guard !delivered else { return }
    delivered = true
    task?.cancel(); task = nil; request = nil
    let t = latest.trimmingCharacters(in: .whitespacesAndNewlines)
    Log.event("dictation: delivered \(t.count) chars")
    if !t.isEmpty { onText?(t) }
  }
}
