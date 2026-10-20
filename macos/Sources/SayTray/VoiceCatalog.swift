import Foundation
import Combine

struct VoiceFile: Codable, Equatable {
  var filename: String
  var url: String
  var sizeBytes: Int
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
    voice.files.allSatisfy { fileHasBytes(voicesDirectory().appendingPathComponent($0.filename)) }
  }

  static func removeRetired() {
    guard let removed = file?.removed else { return }
    let dir = voicesDirectory()
    for id in removed {
      for name in ["\(id).onnx", "\(id).onnx.json", "\(id).onnx.partial"] {
        try? FileManager.default.removeItem(at: dir.appendingPathComponent(name))
      }
    }
  }

  private static func fileHasBytes(_ url: URL) -> Bool {
    let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0
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
  private struct Job { var voice: CatalogVoice; var index: Int; var bytesBefore: Int64 }
  private var jobs: [String: Job] = [:]
  private var taskVoice: [Int: String] = [:]

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
    jobs[id] = Job(voice: voice, index: 0, bytesBefore: 0)
    lock.unlock()
    DispatchQueue.main.async {
      self.fraction[id] = 0
      self.message[id] = "Starting download..."
    }
    startFile(id)
  }

  func delete(_ id: String) {
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
      try? FileManager.default.removeItem(at: dir.appendingPathComponent(file.filename))
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
    lock.unlock()
    task.resume()
  }

  private func fail(_ id: String, _ text: String) {
    lock.lock()
    jobs[id] = nil
    lock.unlock()
    DispatchQueue.main.async {
      self.fraction[id] = nil
      self.message[id] = text
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
      let size = (try FileManager.default.attributesOfItem(atPath: dest.path)[.size] as? NSNumber)?.int64Value ?? 0
      if size <= 0 { throw CocoaError(.fileReadCorruptFile) }
    } catch {
      fail(id, "Could not save \(file.filename)")
      return
    }
    let next = job.index + 1
    if next < job.voice.files.count {
      lock.lock()
      jobs[id] = Job(voice: job.voice, index: next, bytesBefore: job.bytesBefore + Int64(file.sizeBytes))
      lock.unlock()
      startFile(id)
      return
    }
    lock.lock()
    jobs[id] = nil
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
    lock.lock()
    let id = taskVoice.removeValue(forKey: task.taskIdentifier)
    lock.unlock()
    if let id { fail(id, "Download failed: \(error.localizedDescription)") }
  }
}
