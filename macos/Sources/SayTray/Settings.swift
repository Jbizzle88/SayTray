import AppKit
import SwiftUI
import Carbon
import AVFoundation
import ServiceManagement

struct HotKey: Codable, Equatable {
  var keyCode: UInt32
  var carbonMods: UInt32
  var keyName: String
  var label: String {
    var s = ""
    if carbonMods & UInt32(controlKey) != 0 { s += "⌃" }
    if carbonMods & UInt32(optionKey) != 0 { s += "⌥" }
    if carbonMods & UInt32(shiftKey) != 0 { s += "⇧" }
    if carbonMods & UInt32(cmdKey) != 0 { s += "⌘" }
    return s + keyName
  }
  static let readDefault = HotKey(keyCode: 50, carbonMods: UInt32(optionKey), keyName: "`")
  static let dictateDefault = HotKey(keyCode: 49, carbonMods: UInt32(optionKey), keyName: "Space")
  static func from(event e: NSEvent) -> HotKey? {
    let f = e.modifierFlags
    var m: UInt32 = 0
    if f.contains(.command) { m |= UInt32(cmdKey) }
    if f.contains(.option) { m |= UInt32(optionKey) }
    if f.contains(.control) { m |= UInt32(controlKey) }
    if f.contains(.shift) { m |= UInt32(shiftKey) }
    if m == 0 { return nil }
    let names: [UInt16: String] = [53: "Esc", 49: "Space", 36: "Return", 48: "Tab", 51: "Delete", 50: "`", 123: "←", 124: "→", 125: "↓", 126: "↑",
      122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12"]
    let name = names[e.keyCode] ?? (e.charactersIgnoringModifiers ?? "?").uppercased()
    return HotKey(keyCode: UInt32(e.keyCode), carbonMods: m, keyName: name)
  }
}

/// Persisted user settings + live UI state.
final class AppState: ObservableObject {
  static let shared = AppState()
  private let d = UserDefaults.standard
  var onHotKeysChanged: (() -> Void)?
  var onVoiceChanged: (() -> Void)?
  var onStatusChanged: (() -> Void)?
  @Published var speed: Double { didSet { d.set(speed, forKey: "speed") } }
  @Published var voiceID: String { didSet { d.set(voiceID, forKey: "voiceID") } }
  @Published var engine: String { didSet { d.set(engine, forKey: "engine"); onVoiceChanged?() } }
  @Published var piperVoice: String { didSet { d.set(piperVoice, forKey: "piperVoice"); onVoiceChanged?() } }
  @Published var piperSpeaker: Int { didSet { d.set(piperSpeaker, forKey: "piperSpeaker"); onVoiceChanged?() } }
  @Published var readKey: HotKey { didSet { save(readKey, "readKey"); onHotKeysChanged?() } }
  @Published var dictateKey: HotKey { didSet { save(dictateKey, "dictateKey"); onHotKeysChanged?() } }
  @Published var isSpeaking = false { didSet { onStatusChanged?() } }
  @Published var isRecording = false { didSet { onStatusChanged?() } }
  @Published var chime: Bool { didSet { d.set(chime, forKey: "chime") } }
  init() {
    let rawSpeed = d.object(forKey: "speed") as? Double ?? 1.0
    let clamped = rawSpeed.isFinite ? min(2.0, max(0.5, rawSpeed)) : 1.0
    speed = clamped
    if clamped != rawSpeed { d.set(clamped, forKey: "speed") }
    voiceID = d.string(forKey: "voiceID") ?? AppState.bestSystemVoice()
    engine = d.string(forKey: "engine") ?? "piper"
    let saved = d.string(forKey: "piperVoice") ?? ""
    let resolved = VoiceCatalog.resolve(saved: saved)
    piperVoice = resolved
    let savedSpeaker = d.object(forKey: "piperSpeaker") as? Int ?? 0
    piperSpeaker = VoiceCatalog.speakerID(voice: resolved, saved: savedSpeaker) ?? savedSpeaker
    readKey = AppState.load("readKey") ?? .readDefault
    dictateKey = AppState.load("dictateKey") ?? .dictateDefault
    chime = d.object(forKey: "chime") as? Bool ?? true
  }
  private func save(_ k: HotKey, _ name: String) { d.set(try? JSONEncoder().encode(k), forKey: name) }
  private static func load(_ name: String) -> HotKey? {
    guard let data = UserDefaults.standard.data(forKey: name) else { return nil }
    return try? JSONDecoder().decode(HotKey.self, from: data)
  }
  static func bestSystemVoice() -> String {
    let v = AVSpeechSynthesisVoice.speechVoices().filter { $0.language == "en-US" && !$0.voiceTraits.contains(.isNoveltyVoice) }
      .sorted { $0.quality.rawValue > $1.quality.rawValue }
    return v.first?.identifier ?? ""
  }
}

struct HotKeyRecorder: View {
  @Binding var hotKey: HotKey
  @State private var recording = false
  @State private var monitor: Any?
  var body: some View {
    Button(recording ? "Press shortcut… (Esc cancels)" : hotKey.label) { recording ? stop() : start() }.frame(minWidth: 180)
  }
  private func start() {
    recording = true
    HotKeyCenter.shared.suspend()
    monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { e in
      if e.keyCode == 53 && e.modifierFlags.intersection([.command, .option, .control, .shift]).isEmpty { stop(); return nil }
      if let k = HotKey.from(event: e) { hotKey = k; stop() } else { NSSound.beep() }
      return nil
    }
  }
  private func stop() {
    recording = false
    if let m = monitor { NSEvent.removeMonitor(m) }; monitor = nil
    HotKeyCenter.shared.resume()
  }
}

struct SpeedSlider: View {
  @ObservedObject var st = AppState.shared
  var body: some View {
    HStack {
      Text("Speed")
      Slider(value: $st.speed, in: 0.5...2.0, step: 0.1)
      Text(String(format: "%.1fx", st.speed)).monospacedDigit().frame(width: 38)
    }
  }
}

struct SettingsView: View {
  @ObservedObject var st = AppState.shared
  @ObservedObject private var library = VoiceLibrary.shared
  @State private var tick = 0
  @State private var loginOn = SMAppService.mainApp.status == .enabled
  @State private var deleteID: String?
  let testSpeak: (String) -> Void
  private let timer = Timer.publish(every: 1.5, on: .main, in: .common).autoconnect()
  private var systemVoices: [(String, [AVSpeechSynthesisVoice])] {
    let g = Dictionary(grouping: AVSpeechSynthesisVoice.speechVoices(), by: { $0.language })
    return g.keys.sorted { a, b in a.hasPrefix("en") != b.hasPrefix("en") ? a.hasPrefix("en") : a < b }
      .map { k in (k, g[k]!.sorted { ($0.quality.rawValue, $1.name) > ($1.quality.rawValue, $0.name) }) }
  }
  private func quality(_ q: AVSpeechSynthesisVoiceQuality) -> String { q == .premium ? "Premium" : q == .enhanced ? "Enhanced" : "Default" }
  var body: some View {
    Form {
      Section("Shortcuts") {
        LabeledContent("Read selected text") { HotKeyRecorder(hotKey: $st.readKey) }
        LabeledContent("Dictate (hold)") { HotKeyRecorder(hotKey: $st.dictateKey) }
        Text("Dictation is push-to-talk: hold the shortcut, speak, release to type at the cursor. You can keep holding the modifier and press the key again.").font(.caption).foregroundStyle(.secondary)
        Toggle("Play chime when dictation starts and stops", isOn: $st.chime)
      }
      Section("Voice") {
        Picker("Engine", selection: $st.engine) {
          Text("Piper neural (free, local)").tag("piper")
          Text("macOS system voice").tag("system")
        }
        if st.engine == "piper" {
          if PiperEngine.runtimeReady || !VoiceCatalog.voices.isEmpty {
            ForEach(VoiceCatalog.voices) { v in voiceRow(v) }
            Text("Norman is the default. LJSpeech is included with setup. Other voices download here; sizes are the model files.")
              .font(.caption).foregroundStyle(.secondary)
          }
          if !PiperEngine.runtimeReady {
            Text("Piper isn't installed in ~/Library/Application Support/SayTray/piper; using the system voice.").font(.caption).foregroundStyle(.orange)
          }
        }
        Picker(st.engine == "piper" ? "Fallback system voice" : "System voice", selection: $st.voiceID) {
          ForEach(systemVoices, id: \.0) { lang, voices in
            Section(Locale.current.localizedString(forIdentifier: lang) ?? lang) {
              ForEach(voices, id: \.identifier) { v in Text("\(v.name) (\(quality(v.quality)))").tag(v.identifier) }
            }
          }
        }
        SpeedSlider()
        Button("Test voice") { testSpeak("Hello Jon. This is SayTray, reading at the current speed.") }
        Text("More free system voices: System Settings › Accessibility › Spoken Content › System Voice › Manage Voices.").font(.caption).foregroundStyle(.secondary)
      }
      Section("Permissions") {
        let _ = tick
        row("Accessibility (read selection, type dictation)", Permissions.accessibility) { Permissions.promptAccessibility(); Permissions.open("Privacy_Accessibility") }
        row("Microphone", Permissions.mic == .authorized) {
          if Permissions.mic == .notDetermined { Permissions.requestMicAndSpeech { tick += 1 } } else { Permissions.open("Privacy_Microphone") }
        }
        row("Speech Recognition", Permissions.speech == .authorized) {
          if Permissions.speech == .notDetermined { Permissions.requestMicAndSpeech { tick += 1 } } else { Permissions.open("Privacy_SpeechRecognition") }
        }
      }
      Section("General") {
        Toggle("Launch at login", isOn: $loginOn).onChange(of: loginOn) { _, on in
          do { if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() } }
          catch { Log.event("launch at login error: \(error)") }
          loginOn = SMAppService.mainApp.status == .enabled
        }
      }
    }
    .formStyle(.grouped)
    .frame(width: 560, height: 720)
    .onReceive(timer) { _ in tick += 1; library.refresh() }
    .alert("Delete this voice?", isPresented: Binding(get: { deleteID != nil }, set: { if !$0 { deleteID = nil } })) {
      Button("Delete", role: .destructive) {
        if let id = deleteID { library.delete(id) }
        deleteID = nil
      }
      Button("Cancel", role: .cancel) { deleteID = nil }
    } message: {
      Text("\(VoiceCatalog.voice(deleteID ?? "")?.label ?? "This voice") will be removed. You can download it again.")
    }
  }
  private func speakerBinding(_ v: CatalogVoice) -> Binding<Int> {
    Binding(
      get: { VoiceCatalog.speakerID(voice: v.id, saved: st.piperSpeaker) ?? v.speakers.first?.id ?? 0 },
      set: { id in
        if st.piperVoice != v.id { st.piperVoice = v.id }
        st.piperSpeaker = id
      }
    )
  }
  @ViewBuilder
  private func voiceRow(_ v: CatalogVoice) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      HStack {
        VStack(alignment: .leading, spacing: 2) {
          Text(v.label)
          Text(v.blurb).font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        if library.installed.contains(v.id) {
          if !v.speakers.isEmpty {
            Picker("Speaker", selection: speakerBinding(v)) {
              ForEach(v.speakers) { s in Text(s.label).tag(s.id) }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .frame(width: 190)
            .accessibilityLabel("Speaker for \(v.label)")
          }
          if st.piperVoice == v.id {
            Text("Selected").foregroundStyle(.secondary)
          } else {
            Button("Use") { st.piperVoice = v.id }.controlSize(.small)
          }
          if v.id != VoiceCatalog.defaultVoiceID {
            Button("Delete") { deleteID = v.id }.controlSize(.small)
          }
        } else if let msg = library.message[v.id], msg.hasPrefix("Downloading") || msg.hasPrefix("Starting") {
          Text(msg).font(.caption).foregroundStyle(.secondary)
          Button("Cancel") { library.cancel(v.id) }.controlSize(.small)
        } else {
          Button("Download \(v.sizeLabel)") { library.download(v.id) }.controlSize(.small)
        }
      }
      if let frac = library.fraction[v.id], let msg = library.message[v.id],
         msg.hasPrefix("Downloading") || msg.hasPrefix("Starting") {
        ProgressView(value: frac)
      }
      if let msg = library.message[v.id], msg.hasPrefix("Download failed") || msg.hasPrefix("Could not") || msg == "Wait for the download to finish" {
        Text(msg).font(.caption).foregroundStyle(.orange)
      }
    }
  }
  private func row(_ title: String, _ ok: Bool, _ action: @escaping () -> Void) -> some View {
    HStack {
      Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill").foregroundStyle(ok ? .green : .orange)
      Text(title)
      Spacer()
      if ok { Text("Granted").foregroundStyle(.secondary) } else { Button("Grant…", action: action) }
    }
  }
}
