import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
  private var item: NSStatusItem!
  let speaker = Speaker()
  private let dictation = Dictation()
  private var settingsWindow: NSWindow?
  private let st = AppState.shared

  func applicationDidFinishLaunching(_ n: Notification) {
    item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu(); menu.delegate = self; item.menu = menu
    updateIcon()
    st.onStatusChanged = { [weak self] in DispatchQueue.main.async { self?.updateIcon() } }
    st.onHotKeysChanged = { [weak self] in self?.registerHotKeys() }
    st.onVoiceChanged = { [weak self] in self?.speaker.warmUp() }
    dictation.onText = { SelectionReader.type($0) }
    registerHotKeys()
    VoiceCatalog.removeRetired()
    speaker.warmUp()
    // Debug/test trigger: post distributed notification "com.jonbecherer.saytray.debugSpeak" with the text as object.
    DistributedNotificationCenter.default().addObserver(forName: Notification.Name("com.jonbecherer.saytray.debugSpeak"), object: nil, queue: .main) { [weak self] n in
      if let t = n.object as? String, !t.isEmpty { self?.speaker.speak(t) }
    }
    DistributedNotificationCenter.default().addObserver(forName: Notification.Name("com.jonbecherer.saytray.debugDictate"), object: nil, queue: .main) { [weak self] n in
      if (n.object as? String) == "start" { self?.dictation.start() } else { self?.dictation.stop() }
    }
    if !Permissions.accessibility { Permissions.promptAccessibility() }
    if Permissions.mic == .notDetermined || Permissions.speech == .notDetermined { Permissions.requestMicAndSpeech() }
    Log.event("launched; accessibility=\(Permissions.accessibility) mic=\(Permissions.mic.rawValue) speech=\(Permissions.speech.rawValue)")
  }

  func applicationWillTerminate(_ n: Notification) { speaker.quit() }

  private func updateIcon() {
    let name = st.isRecording ? "mic.fill" : (st.isSpeaking ? "speaker.wave.3.fill" : "text.bubble")
    item.button?.image = NSImage(systemSymbolName: name, accessibilityDescription: "SayTray")
    item.button?.contentTintColor = st.isRecording ? .systemRed : nil
  }

  private func registerHotKeys() {
    HotKeyCenter.shared.set(id: 1, key: st.readKey, down: { [weak self] in self?.readSelection() })
    HotKeyCenter.shared.set(id: 2, key: st.dictateKey, down: { [weak self] in self?.dictation.start() }, up: { [weak self] in self?.dictation.stop() }, hold: true)
  }

  @objc private func readSelection() {
    if speaker.isSpeaking { speaker.stop(); return }
    if !Permissions.accessibility { Permissions.promptAccessibility() }
    SelectionReader.read { [weak self] text in
      guard let t = text, !t.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { NSSound.beep(); return }
      self?.speaker.speak(t)
    }
  }
  @objc private func stopSpeaking() { speaker.stop() }

  func menuNeedsUpdate(_ menu: NSMenu) {
    menu.removeAllItems()
    let r = NSMenuItem(title: "Read Selected Text (\(st.readKey.label))", action: #selector(readSelection), keyEquivalent: ""); r.target = self
    menu.addItem(r)
    let s = NSMenuItem(title: "Stop Speaking", action: speaker.isSpeaking ? #selector(stopSpeaking) : nil, keyEquivalent: ""); s.target = self
    menu.addItem(s)
    let d = NSMenuItem(title: "Hold \(st.dictateKey.label) to dictate", action: nil, keyEquivalent: ""); d.isEnabled = false
    menu.addItem(d)
    menu.addItem(.separator())
    let sl = NSMenuItem()
    let host = NSHostingView(rootView: SpeedSlider().padding(.horizontal, 14).padding(.vertical, 4))
    host.frame = NSRect(x: 0, y: 0, width: 260, height: 30)
    sl.view = host; menu.addItem(sl)
    menu.addItem(.separator())
    let set = NSMenuItem(title: "Settings…", action: #selector(openSettings), keyEquivalent: ","); set.target = self
    menu.addItem(set)
    let logs = NSMenuItem(title: "Open Logs Folder", action: #selector(openLogs), keyEquivalent: ""); logs.target = self
    menu.addItem(logs)
    let about = NSMenuItem(title: "About SayTray", action: #selector(showAbout), keyEquivalent: ""); about.target = self
    menu.addItem(about)
    menu.addItem(.separator())
    menu.addItem(NSMenuItem(title: "Quit SayTray", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
  }

  @objc private func openLogs() {
    try? FileManager.default.createDirectory(at: Log.root, withIntermediateDirectories: true)
    NSWorkspace.shared.open(Log.root)
  }

  @objc private func showAbout() {
    let info = Bundle.main.infoDictionary
    let ver = (info?["CFBundleShortVersionString"] as? String) ?? "?"
    let build = (info?["CFBundleVersion"] as? String) ?? "?"
    let alert = NSAlert()
    alert.messageText = "SayTray"
    alert.informativeText = """
    Version \(ver) (\(build))

    Free offline menu-bar text-to-speech and push-to-talk dictation.

    Read: \(st.readKey.label)
    Dictate (hold): \(st.dictateKey.label)

    Default voice: Norman. Optional voices include LibriTTS (CC BY 4.0, Zen et al.) and Jenny (Dioco).
    See THIRD_PARTY_NOTICES for Piper, espeak-ng, and voice licenses.

    © Jon Becherer
    """
    alert.alertStyle = .informational
    if let img = NSImage(named: "SayTray") ?? NSApp.applicationIconImage {
      alert.icon = img
    }
    alert.addButton(withTitle: "OK")
    alert.runModal()
  }

  @objc private func openSettings() {
    if settingsWindow == nil {
      let view = SettingsView(testSpeak: { [weak self] in self?.speaker.speak($0) })
      let w = NSWindow(contentViewController: NSHostingController(rootView: view))
      w.title = "SayTray Settings"; w.styleMask = [.titled, .closable, .miniaturizable]
      w.isReleasedWhenClosed = false; w.center()
      settingsWindow = w
    }
    NSApp.activate(ignoringOtherApps: true)
    settingsWindow?.makeKeyAndOrderFront(nil)
  }
}
