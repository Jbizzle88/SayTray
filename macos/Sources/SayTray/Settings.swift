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
  @Published var readKey: HotKey { didSet { save(readKey, "readKey"); onHotKeysChanged?() } }
  @Published var dictateKey: HotKey { didSet { save(dictateKey, "dictateKey"); onHotKeysChanged?() } }
  @Published var isSpeaking = false { didSet { onStatusChanged?() } }
  @Published var isRecording = false { didSet { onStatusChanged?() } }
  @Published var chime: Bool { didSet { d.set(chime, forKey: "chime") } }
  init() {
    speed = d.object(forKey: "speed") as? Double ?? 1.0
    voiceID = d.string(forKey: "voiceID") ?? AppState.bestSystemVoice()
    engine = d.string(forKey: "engine") ?? "piper"
    let pv = PiperEngine.installedVoices()
    let saved = d.string(forKey: "piperVoice") ?? ""
    piperVoice = pv.contains(saved) ? saved : (pv.first { $0.contains("ryan-high") } ?? pv.first ?? "")
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
  @State private var tick = 0
  @State private var loginOn = SMAppService.mainApp.status == .enabled
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
        Text("Dictation is push-to-talk: hold the shortcut, speak, release to type at the cursor.").font(.caption).foregroundStyle(.secondary)
        Toggle("Play chime when dictation starts and stops", isOn: $st.chime)
      }
      Section("Voice") {
        Picker("Engine", selection: $st.engine) {
          Text("Piper neural (free, local)").tag("piper")
          Text("macOS system voice").tag("system")
        }
        if st.engine == "piper" {
          if PiperEngine.available {
            Picker("Piper voice", selection: $st.piperVoice) {
              ForEach(PiperEngine.installedVoices(), id: \.self) { Text(PiperEngine.pretty($0)).tag($0) }
            }
          } else {
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
    .frame(width: 520, height: 640)
    .onReceive(timer) { _ in tick += 1 }
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
