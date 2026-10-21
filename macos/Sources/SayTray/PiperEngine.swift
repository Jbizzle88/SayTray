import Foundation

/// Persistent Piper helper process (voice preloaded), line-delimited JSON over stdin/stdout.
/// Request:  {"name","read","text","dir","noise_scale","noise_w","priority"}   Cancel: {"cmd":"cancel","read"}
/// Reply:    {"name","path","seconds"} or {"name","error"};  {"ready":true} once loaded.
final class PiperEngine {
  struct Noise { var scale: Double; var w: Double
    static let normal = Noise(scale: 0.5, w: 0.6)
    static let strict = Noise(scale: 0.333, w: 0.4)
  }
  typealias Done = (Result<(URL, Double, Int), Error>) -> Void
  struct EngineError: Error, CustomStringConvertible { let description: String }

  static let dir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/SayTray/piper")
  static var python: URL { dir.appendingPathComponent("venv/bin/python") }
  static var script: URL { dir.appendingPathComponent("saytray_piper.py") }
  static var runtimeReady: Bool {
    FileManager.default.isExecutableFile(atPath: python.path) && FileManager.default.fileExists(atPath: script.path)
  }
  static var available: Bool { runtimeReady && !installedVoices().isEmpty }
  static func installedVoices() -> [String] {
    VoiceCatalog.voices.filter { VoiceCatalog.isInstalled($0) }.map(\.id)
  }
  static func pretty(_ v: String) -> String { VoiceCatalog.voice(v)?.label ?? v }

  private struct Pending { let read: Int; let json: [String: Any]; let done: Done; var sentAt: Date; let timeout: TimeInterval }
  private var proc: Process?
  private var input: FileHandle?
  private(set) var voice = ""
  var speakerID: Int?
  private var pending: [String: Pending] = [:]
  private var quitting = false
  private var watchdog: Timer?
  private var restartsThisMinute: [Date] = []

  /// Start (or keep) the helper for `voice`. Returns false if Piper isn't usable.
  @discardableResult
  func ensure(voice v: String) -> Bool {
    guard PiperEngine.available else {
      if proc?.isRunning == true { shutdownProcess() }
      return false
    }
    guard let catalog = VoiceCatalog.voice(v), VoiceCatalog.isInstalled(catalog) else {
      if voice == v { shutdownProcess() }
      return false
    }
    let model = PiperEngine.dir.appendingPathComponent("voices/\(v).onnx")
    if proc?.isRunning == true && voice == v { return true }
    shutdownProcess()
    let p = Process()
    p.executableURL = PiperEngine.python
    p.arguments = [PiperEngine.script.path, model.path]
    var env = ProcessInfo.processInfo.environment
    env["PYTHONIOENCODING"] = "utf-8"; env["LANG"] = "en_US.UTF-8"; env["PYTHONUNBUFFERED"] = "1"
    p.environment = env
    let inP = Pipe(), outP = Pipe()
    p.standardInput = inP; p.standardOutput = outP
    let errURL = Log.root.appendingPathComponent("helper.log")
    try? FileManager.default.createDirectory(at: Log.root, withIntermediateDirectories: true)
    if !FileManager.default.fileExists(atPath: errURL.path) { FileManager.default.createFile(atPath: errURL.path, contents: nil) }
    if let eh = try? FileHandle(forWritingTo: errURL) { eh.seekToEndOfFile(); p.standardError = eh }
    p.terminationHandler = { [weak self] dead in
      DispatchQueue.main.async {
        guard let self, self.proc === dead, !self.quitting else { return }
        Log.event("piper helper exited (status \(dead.terminationStatus)); restarting")
        self.proc = nil
        self.restart()
      }
    }
    do { try p.run() } catch { Log.event("piper helper launch failed: \(error)"); return false }
    proc = p; input = inP.fileHandleForWriting; voice = v
    let out = outP.fileHandleForReading
    DispatchQueue.global(qos: .userInitiated).async { [weak self] in
      var buf = Data()
      while true {
        let d = out.availableData          // returns as soon as any bytes arrive; empty == EOF
        if d.isEmpty { break }
        buf.append(d)
        while let nl = buf.firstIndex(of: 10) {   // handles several and partial lines
          let line = buf.subdata(in: buf.startIndex..<nl)
          buf.removeSubrange(buf.startIndex...nl)
          guard let j = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
          DispatchQueue.main.async { self?.handle(j) }
        }
      }
    }
    if watchdog == nil {
      watchdog = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.checkTimeouts() }
    }
    Log.event("piper helper started for \(v)")
    return true
  }

  func synthesize(read: Int, name: String, text: String, dir: URL, noise: Noise, priority: Bool, done: @escaping Done) {
    var json: [String: Any] = ["name": name, "read": read, "text": text, "dir": dir.path,
                               "noise_scale": noise.scale, "noise_w": noise.w, "priority": priority]
    if let speakerID { json["speaker_id"] = speakerID }
    // generous: helper may be busy with earlier chunks of this read
    let timeout = 6.0 + Double(text.count) * 0.03 + Double(pending.count) * 2.0
    pending[name] = Pending(read: read, json: json, done: done, sentAt: Date(), timeout: timeout)
    send(json)
  }

  func cancel(read: Int) {
    send(["cmd": "cancel", "read": read])
    pending = pending.filter { $0.value.read != read }
  }

  func quit() {
    quitting = true
    watchdog?.invalidate(); watchdog = nil
    shutdownProcess()
  }

  // MARK: internals
  private func send(_ obj: [String: Any]) {
    guard let h = input, var d = try? JSONSerialization.data(withJSONObject: obj) else { return }
    d.append(10)
    do { try h.write(contentsOf: d) } catch { Log.event("helper write failed: \(error)") }
  }
  private func handle(_ j: [String: Any]) {
    if j["ready"] != nil { return }
    guard let name = j["name"] as? String, let p = pending.removeValue(forKey: name) else { return }
    if let path = j["path"] as? String, let secs = j["seconds"] as? Double {
      p.done(.success((URL(fileURLWithPath: path), secs, (j["phonemes"] as? Int) ?? 0)))
    } else {
      p.done(.failure(EngineError(description: "helper error: \(j["error"] ?? "unknown")")))
    }
  }
  private func checkTimeouts() {
    let now = Date()
    guard pending.values.contains(where: { now.timeIntervalSince($0.sentAt) > $0.timeout }) else { return }
    Log.event("piper helper unresponsive (\(pending.count) pending); restarting")
    restart()
  }
  private func restart() {
    let now = Date()
    restartsThisMinute = restartsThisMinute.filter { now.timeIntervalSince($0) < 60 } + [now]
    shutdownProcess()
    if restartsThisMinute.count > 3 || !ensure(voice: voice) {
      Log.event("piper helper keeps failing; failing \(pending.count) pending chunks to system voice")
      let all = pending; pending = [:]
      for (_, p) in all { p.done(.failure(EngineError(description: "helper unavailable"))) }
      return
    }
    for (k, var p) in pending { p.sentAt = Date(); pending[k] = p; send(p.json) }
  }
  private func shutdownProcess() {
    if let p = proc { proc = nil; if p.isRunning { p.terminate() } }
    try? input?.close(); input = nil
  }
}
