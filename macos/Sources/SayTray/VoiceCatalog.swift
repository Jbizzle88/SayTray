import Foundation
import Combine
import CommonCrypto

struct VoiceFile: Codable, Equatable {
  var filename: String
  var url: String
  var sizeBytes: Int
  var sha256: String?
}

struct VoiceSpeaker: Codable, Equatable, Identifiable {
  var id: Int
  var label: String
}

struct CatalogVoice: Codable, Equatable, Identifiable {
  var id: String
  var label: String
  var blurb: String
  var installByDefault: Bool
  var files: [VoiceFile]
  var speakers: [VoiceSpeaker]
  var sizeBytes: Int { files.reduce(0) { $0 + $1.sizeBytes } }
  var sizeLabel: String { VoiceCatalog.formatSize(sizeBytes) }
}

struct VoiceCatalogFile: Codable {
  var defaultVoice: String
  var removed: [String]
  var voices: [CatalogVoice]
}

/// Commercial voice list. URLs live only in voices.json (bundled, and read by setup_piper.sh).
enum VoiceCatalog {
  static let hardcodedDefault = "en_US-norman-medium"
  static let file: VoiceCatalogFile? = load()
  static var defaultVoiceID: String { file?.defaultVoice ?? hardcodedDefault }
  static var voices: [CatalogVoice] { file?.voices ?? [] }

  static func formatSize(_ bytes: Int) -> String {
    "\(Int(Double(bytes) / 1048576.0 + 0.5)) MB"
  }

  static func voice(_ id: String) -> CatalogVoice? { voices.first { $0.id == id } }

  /// Saved ids that are not in the catalog (including removed voices) become Norman.
  static func resolve(saved: String) -> String {
    if voices.contains(where: { $0.id == saved }) { return saved }
    return defaultVoiceID
  }

  static func speakerID(voice: String, saved: Int) -> Int? {
    guard let speakers = self.voice(voice)?.speakers, !speakers.isEmpty else { return nil }
    if speakers.contains(where: { $0.id == saved }) { return saved }
    return speakers[0].id
  }

  static func playbackVoice(requested: String, installed: Set<String>) -> String? {
    if installed.contains(requested) { return requested }
    if installed.contains(defaultVoiceID) { return defaultVoiceID }
    return nil
  }

  static func voicesDirectory() -> URL {
    PiperEngine.dir.appendingPathComponent("voices")
  }

  static func isInstalled(_ voice: CatalogVoice) -> Bool {
    !voice.files.isEmpty && voice.files.allSatisfy {
      fileTrusted(voicesDirectory().appendingPathComponent($0.filename), expected: $0.sizeBytes, sha: $0.sha256)
    }
  }

  static func markerURL(_ url: URL) -> URL {
    URL(fileURLWithPath: url.path + ".sha256")
  }

  static func writeHashMarker(_ url: URL, sha: String) {
    let expect = sha.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    guard !expect.isEmpty else { return }
    try? Data((expect + "\n").utf8).write(to: markerURL(url), options: .atomic)
  }

  /// Size match, then the catalog hash. A matching `.sha256` marker skips reading the file again.
  /// After the first successful hash the marker is trusted on later launches; the model is not
  /// read again just to paint the menu. A missing marker is hashed off the main thread.
  static func fileTrusted(_ url: URL, expected: Int, sha: String?) -> Bool {
    guard fileMatches(url, expected: expected) else { return false }
    let expect = (sha ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if expect.isEmpty { return true }
    if let stored = try? String(contentsOf: markerURL(url), encoding: .utf8),
       stored.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == expect {
      return true
    }
    let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
    let size = (attrs?[.size] as? NSNumber)?.int64Value ?? 0
    let mtime = (attrs?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
    let key = "\(url.path)|\(size)|\(mtime)|\(expect)"
    trustLock.lock()
    if let cached = trustCache[key] {
      trustLock.unlock()
      return cached
    }
    trustLock.unlock()
    // The first hash of a model is tens of megabytes. Never do it on the main thread.
    if Thread.isMainThread { return false }
    guard let digest = sha256Hex(url) else { return false }
    let ok = digest == expect
    if ok {
      writeHashMarker(url, sha: digest)
    } else {
      try? FileManager.default.removeItem(at: markerURL(url))
    }
    trustLock.lock()
    trustCache[key] = ok
    trustLock.unlock()
    return ok
  }

  private static let trustLock = NSLock()
  private static var trustCache: [String: Bool] = [:]

  /// Hash installed voices that have no marker, off the main thread, then call `done` on a background queue.
  static func trustInBackground(_ done: @escaping () -> Void) {
    DispatchQueue.global(qos: .utility).async {
      for voice in voices {
        _ = isInstalled(voice)
      }
      done()
    }
  }

  static func removeRetired() {
    guard let removed = file?.removed else { return }
    let dir = voicesDirectory()
    for id in removed {
      for name in ["\(id).onnx", "\(id).onnx.json", "\(id).onnx.partial", "\(id).onnx.sha256", "\(id).onnx.json.sha256"] {
        try? FileManager.default.removeItem(at: dir.appendingPathComponent(name))
      }
    }
  }

  /// Streaming SHA-256 of a downloaded file. Compared at download time.
  static func sha256Hex(_ url: URL) -> String? {
    guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
    defer { try? handle.close() }
    var ctx = CC_SHA256_CTX()
    CC_SHA256_Init(&ctx)
    while true {
      let data = handle.readData(ofLength: 64 * 1024)
      if data.isEmpty { break }
      data.withUnsafeBytes { raw in
        _ = CC_SHA256_Update(&ctx, raw.baseAddress, CC_LONG(data.count))
      }
    }
    var digest = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
    CC_SHA256_Final(&digest, &ctx)
    return digest.map { String(format: "%02x", $0) }.joined()
  }

  /// Exact catalog size. A short or corrupt download is not a voice.
  static func fileMatches(_ url: URL, expected: Int) -> Bool {
    let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0
    if expected > 0 { return size == Int64(expected) }
    return size > 0
  }

  private static func load() -> VoiceCatalogFile? {
    let decoder = JSONDecoder()
    let candidates = [
      Bundle.main.url(forResource: "voices", withExtension: "json"),
      URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("voices.json"),
    ]
    for url in candidates.compactMap({ $0 }) {
      if let data = try? Data(contentsOf: url), let parsed = try? decoder.decode(VoiceCatalogFile.self, from: data) {
        return parsed
      }
    }
    return nil
  }
}

/// Downloads optional catalog voices into Application Support and deletes them on request.
final class VoiceLibrary: NSObject, ObservableObject, URLSessionDownloadDelegate {
  static let shared = VoiceLibrary()
  @Published private(set) var installed: Set<String> = []
  @Published private(set) var fraction: [String: Double] = [:]
  @Published private(set) var message: [String: String] = [:]

  private var session: URLSession!
  private let lock = NSLock()
  private struct Job { var voice: CatalogVoice; var index: Int; var bytesBefore: Int64; var wrote: [String] }
  private var jobs: [String: Job] = [:]
  private var taskVoice: [Int: String] = [:]
  private var liveTask: [String: URLSessionDownloadTask] = [:]

  override init() {
    super.init()
    session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    refresh()
  }

  func refresh() {
    let ids = Set(VoiceCatalog.voices.filter { VoiceCatalog.isInstalled($0) }.map(\.id))
    let apply = { if self.installed != ids { self.installed = ids } }
    if Thread.isMainThread { apply() } else { DispatchQueue.main.async(execute: apply) }
  }

  func download(_ id: String) {
    lock.lock()
    if jobs[id] != nil { lock.unlock(); return }
    guard let voice = VoiceCatalog.voice(id) else { lock.unlock(); return }
    jobs[id] = Job(voice: voice, index: 0, bytesBefore: 0, wrote: [])
    lock.unlock()
    DispatchQueue.main.async {
      self.fraction[id] = 0
      self.message[id] = "Starting download..."
    }
    startFile(id)
  }

  func shutdown() {
    lock.lock()
    let tasks = Array(liveTask.values)
    jobs.removeAll()
    taskVoice.removeAll()
    liveTask.removeAll()
    let live = session
    lock.unlock()
    for task in tasks { task.cancel() }
    live?.invalidateAndCancel()
    Log.event("voices: downloads cancelled")
  }

  /// Stop one download and return the row to idle. A click after it has finished does nothing.
  func cancel(_ id: String) {
    lock.lock()
    let task = liveTask.removeValue(forKey: id)
    if let task { taskVoice.removeValue(forKey: task.taskIdentifier) }
    let wrote = jobs[id]?.wrote ?? []
    let active = jobs[id] != nil || task != nil
    jobs[id] = nil
    lock.unlock()
    guard active else { return }
    task?.cancel()
    let dir = VoiceCatalog.voicesDirectory()
    for name in wrote {
      let dest = dir.appendingPathComponent(name)
      try? FileManager.default.removeItem(at: dest)
      try? FileManager.default.removeItem(at: URL(fileURLWithPath: dest.path + ".partial"))
      try? FileManager.default.removeItem(at: VoiceCatalog.markerURL(dest))
    }
    DispatchQueue.main.async {
      self.fraction[id] = nil
      self.message[id] = nil
      self.refresh()
    }
  }

  func delete(_ id: String) {
    if id == VoiceCatalog.defaultVoiceID {
      DispatchQueue.main.async { self.message[id] = "Norman stays installed. It is the default voice." }
      return
    }
    lock.lock()
    let busy = jobs[id] != nil
    lock.unlock()
    if busy {
      DispatchQueue.main.async { self.message[id] = "Wait for the download to finish" }
      return
    }
    guard let voice = VoiceCatalog.voice(id) else { return }
    if AppState.shared.piperVoice == id {
      let other = VoiceCatalog.voices.map(\.id).first { $0 != id && installed.contains($0) } ?? VoiceCatalog.defaultVoiceID
      AppState.shared.piperVoice = other
    }
    let dir = VoiceCatalog.voicesDirectory()
    for file in voice.files {
      let dest = dir.appendingPathComponent(file.filename)
      try? FileManager.default.removeItem(at: dest)
      try? FileManager.default.removeItem(at: URL(fileURLWithPath: dest.path + ".partial"))
      try? FileManager.default.removeItem(at: VoiceCatalog.markerURL(dest))
    }
    DispatchQueue.main.async {
      self.fraction[id] = nil
      self.message[id] = nil
      self.refresh()
    }
  }

  private func startFile(_ id: String) {
    lock.lock()
    guard let job = jobs[id], job.index < job.voice.files.count else { lock.unlock(); return }
    let file = job.voice.files[job.index]
    lock.unlock()
    guard let url = URL(string: file.url) else { fail(id, "Bad download URL"); return }
    var request = URLRequest(url: url)
    request.setValue("SayTray", forHTTPHeaderField: "User-Agent")
    let task = session.downloadTask(with: request)
    lock.lock()
    taskVoice[task.taskIdentifier] = id
    liveTask[id] = task
    lock.unlock()
    task.resume()
  }

  private func fail(_ id: String, _ text: String) {
    lock.lock()
    let wrote = jobs[id]?.wrote ?? []
    jobs[id] = nil
    liveTask[id] = nil
    lock.unlock()
    let dir = VoiceCatalog.voicesDirectory()
    for name in wrote {
      let dest = dir.appendingPathComponent(name)
      try? FileManager.default.removeItem(at: dest)
      try? FileManager.default.removeItem(at: URL(fileURLWithPath: dest.path + ".partial"))
      try? FileManager.default.removeItem(at: VoiceCatalog.markerURL(dest))
    }
    DispatchQueue.main.async {
      self.fraction[id] = nil
      self.message[id] = text
      self.refresh()
    }
  }

  func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
    lock.lock()
    guard let id = taskVoice[downloadTask.taskIdentifier], let job = jobs[id] else { lock.unlock(); return }
    let fileTotal = Int64(job.voice.files[job.index].sizeBytes)
    let written = fileTotal > 0 ? min(totalBytesWritten, fileTotal) : totalBytesWritten
    let overall = job.bytesBefore + written
    let total = Int64(max(job.voice.sizeBytes, 1))
    lock.unlock()
    let frac = min(0.99, Double(overall) / Double(total))
    DispatchQueue.main.async {
      self.fraction[id] = frac
      self.message[id] = "Downloading... \(Int(frac * 100))%"
    }
  }

  func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
    lock.lock()
    let id = taskVoice.removeValue(forKey: downloadTask.taskIdentifier)
    let job = id.flatMap { jobs[$0] }
    lock.unlock()
    guard let id, let job else { return }
    let code = (downloadTask.response as? HTTPURLResponse)?.statusCode ?? 0
    guard code == 200 else {
      try? FileManager.default.removeItem(at: location)
      fail(id, "Download failed (HTTP \(code))")
      return
    }
    let file = job.voice.files[job.index]
    let expected = Int64(file.sizeBytes)
    let got = (try? FileManager.default.attributesOfItem(atPath: location.path)[.size] as? NSNumber)?.int64Value ?? 0
    if expected > 0 ? got != expected : got <= 0 {
      try? FileManager.default.removeItem(at: location)
      let detail = expected > 0 ? "\(got) of \(expected) bytes" : "empty file"
      fail(id, "Download incomplete: \(file.filename) (\(detail))")
      return
    }
    if let expect = file.sha256?.lowercased(), !expect.isEmpty {
      let hashed = VoiceCatalog.sha256Hex(location)
      if hashed != expect {
        try? FileManager.default.removeItem(at: location)
        fail(id, "Download checksum mismatch: \(file.filename)")
        return
      }
    }
    lock.lock()
    let still = jobs[id] != nil
    lock.unlock()
    if !still {
      try? FileManager.default.removeItem(at: location)
      return
    }
    let dir = VoiceCatalog.voicesDirectory()
    let dest = dir.appendingPathComponent(file.filename)
    do {
      try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
      if FileManager.default.fileExists(atPath: dest.path) { try FileManager.default.removeItem(at: dest) }
      do { try FileManager.default.moveItem(at: location, to: dest) }
      catch {
        try FileManager.default.copyItem(at: location, to: dest)
        try? FileManager.default.removeItem(at: location)
      }
    } catch {
      try? FileManager.default.removeItem(at: dest)
      fail(id, "Could not save \(file.filename)")
      return
    }
    if let expect = file.sha256?.lowercased(), !expect.isEmpty {
      VoiceCatalog.writeHashMarker(dest, sha: expect)
    }
    let wrote = job.wrote + [file.filename]
    let next = job.index + 1
    if next < job.voice.files.count {
      lock.lock()
      jobs[id] = Job(voice: job.voice, index: next, bytesBefore: job.bytesBefore + Int64(file.sizeBytes), wrote: wrote)
      lock.unlock()
      startFile(id)
      return
    }
    lock.lock()
    jobs[id] = nil
    liveTask[id] = nil
    lock.unlock()
    DispatchQueue.main.async {
      self.fraction[id] = 1
      self.message[id] = "Downloaded"
      self.refresh()
      AppState.shared.piperVoice = id
      if let sid = VoiceCatalog.speakerID(voice: id, saved: AppState.shared.piperSpeaker) {
        AppState.shared.piperSpeaker = sid
      }
    }
  }

  func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
    guard let error else { return }
    let ns = error as NSError
    if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
    lock.lock()
    let id = taskVoice.removeValue(forKey: task.taskIdentifier)
    if let id, liveTask[id] === task { liveTask[id] = nil }
    let job = id.flatMap { jobs[$0] }
    lock.unlock()
    if let id, job != nil { fail(id, "Download failed: \(error.localizedDescription)") }
  }
}
