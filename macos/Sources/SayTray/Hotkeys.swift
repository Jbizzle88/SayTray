import AppKit
import Carbon
import CoreGraphics

/// Global hot keys via Carbon (press + release events, needed for push-to-talk).
///
/// Hold shortcuts also watch the physical keyboard. Carbon sometimes reports the chord released
/// while the key is still down (the next press then looks like a stuck or instantly-cancelled hold,
/// especially if the modifier never came up). A real key-up, a modifier release, or two missed polls
/// ends the hold. Pressing the key again while the modifier stays down starts a new hold.
final class HotKeyCenter {
  static let shared = HotKeyCenter()
  private struct Spec { var key: HotKey; var down: () -> Void; var up: () -> Void; var arm: () -> Void; var hold: Bool }
  private var specs: [UInt32: Spec] = [:]
  private var refs: [UInt32: EventHotKeyRef] = [:]
  private var monitors: [Any] = []
  private var holdingIds: Set<UInt32> = []
  private var armedMods: Set<UInt32> = []
  private var armWork: DispatchWorkItem?
  private var pendingArm: UInt32?
  private var seenHeld: Set<UInt32> = []
  private var missCount: [UInt32: Int] = [:]
  private var watch: Timer?
  private var suspended = false

  private init() {
    var types = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                 EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
    InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
      var hk = EventHotKeyID()
      GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                        MemoryLayout<EventHotKeyID>.size, nil, &hk)
      let pressed = GetEventKind(event) == UInt32(kEventHotKeyPressed)
      let id = hk.id
      DispatchQueue.main.async { HotKeyCenter.shared.fire(id, pressed: pressed) }
      return noErr
    }, 2, &types, nil, nil)
    installMonitors()
  }

  private func installMonitors() {
    let mask: NSEvent.EventTypeMask = [.keyDown, .keyUp, .flagsChanged]
    let handler: (NSEvent) -> Void = { e in
      DispatchQueue.main.async { HotKeyCenter.shared.handleMonitor(e) }
    }
    if let g = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: handler) {
      monitors.append(g)
      Log.event("hotkey: global keyboard monitor installed")
    } else {
      Log.event("hotkey: global keyboard monitor unavailable; Carbon hotkeys only")
    }
    if let local = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { e in handler(e); return e }) {
      monitors.append(local)
    }
  }

  private func fire(_ id: UInt32, pressed: Bool) {
    guard !suspended, let s = specs[id] else { return }
    if !s.hold {
      if pressed { s.down() }
      return
    }
    if pressed {
      noteDown(id)
    } else if chordPhysicallyHeld(s.key) {
      Log.event("hotkey \(s.key.label): ignoring release; chord still held")
    } else {
      noteUp(id)
    }
  }

  /// Backup path so a new Space-down while Option is still held starts a hold even if Carbon
  /// does not emit another hot-key press, and so a real key-up still stops it.
  private func handleMonitor(_ e: NSEvent) {
    guard !suspended else { return }
    for (id, s) in specs where s.hold {
      switch e.type {
      case .keyDown:
        // Repeats must not start a new hold. A poll that ends the chord while the key is still
        // down would otherwise restart dictation on the next repeat.
        if e.isARepeat { continue }
        let isDictate = e.keyCode == UInt16(truncatingIfNeeded: s.key.keyCode) && modifiersMatch(s.key, e.modifierFlags)
        if isDictate {
          flushArm()
          noteDown(id)
        } else {
          // The read hotkey, an accent, or any other key: do not open the mic.
          cancelArm()
        }
      case .keyUp:
        if e.keyCode == UInt16(truncatingIfNeeded: s.key.keyCode) { noteUp(id) }
      case .flagsChanged:
        // A modifier-less dictate key (F13) matches every modifier release. Do not arm it.
        if s.hold, s.key.carbonMods != 0, modifiersMatch(s.key, e.modifierFlags) {
          if !armedMods.contains(id) {
            armedMods.insert(id)
            scheduleArm(id)
          }
        } else {
          armedMods.remove(id)
          cancelArm()
        }
        if holdingIds.contains(id), !modifiersMatch(s.key, e.modifierFlags) { noteUp(id) }
      default:
        break
      }
    }
  }

  private func scheduleArm(_ id: UInt32) {
    armWork?.cancel()
    pendingArm = id
    let work = DispatchWorkItem { [weak self] in self?.fireArm(id, fromTimer: true) }
    armWork = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: work)
  }

  private func cancelArm() {
    armWork?.cancel()
    armWork = nil
    pendingArm = nil
  }

  private func flushArm() {
    guard let id = pendingArm else { return }
    armWork?.cancel()
    armWork = nil
    fireArm(id, fromTimer: false)
  }

  private func fireArm(_ id: UInt32, fromTimer: Bool) {
    guard pendingArm == id, let s = specs[id], s.hold, s.key.carbonMods != 0 else { return }
    // A long hold of the read shortcut's modifiers is the user about to read.
    // Leave the arm pending so the dictate key can still open the mic once.
    if fromTimer && readModifiersHeld() { return }
    pendingArm = nil
    guard modifiersMatch(s.key, NSEvent.modifierFlags) else { return }
    s.arm()
  }

  private func readModifiersHeld() -> Bool {
    let flags = NSEvent.modifierFlags
    for (_, spec) in specs where !spec.hold && spec.key.carbonMods != 0 {
      if modifiersMatch(spec.key, flags) { return true }
    }
    return false
  }

  private func noteDown(_ id: UInt32) {
    let already = holdingIds.contains(id)
    holdingIds.insert(id)
    if !already {
      missCount[id] = 0
      seenHeld.remove(id)
    }
    ensureWatch()
    if !already {
      Log.event("hotkey \(specs[id]?.key.label ?? "?"): down")
      specs[id]?.down()
    }
  }

  private func noteUp(_ id: UInt32) {
    guard holdingIds.contains(id) else { return }
    holdingIds.remove(id)
    seenHeld.remove(id)
    missCount[id] = 0
    if holdingIds.isEmpty { watch?.invalidate(); watch = nil }
    Log.event("hotkey \(specs[id]?.key.label ?? "?"): up")
    specs[id]?.up()
  }

  private func ensureWatch() {
    guard watch == nil else { return }
    let timer = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in self?.pollHeld() }
    watch = timer
    RunLoop.main.add(timer, forMode: .common)
  }

  /// Carbon can miss the key-up. After keyState has reported the chord down at least once,
  /// two polls in a row with it up ends the hold. If keyState never sees the chord, polling
  /// does not cancel — a false reading must not cut off a dictation that just started.
  private func pollHeld() {
    for id in Array(holdingIds) {
      guard let s = specs[id] else { continue }
      if chordPhysicallyHeld(s.key) {
        seenHeld.insert(id)
        missCount[id] = 0
      } else if seenHeld.contains(id) {
        missCount[id, default: 0] += 1
        if (missCount[id] ?? 0) >= 2 {
          Log.event("hotkey \(s.key.label): chord released (polled)")
          noteUp(id)
        }
      }
    }
  }

  private func chordPhysicallyHeld(_ key: HotKey) -> Bool {
    modifiersMatch(key, NSEvent.modifierFlags) &&
      CGEventSource.keyState(.combinedSessionState, key: CGKeyCode(UInt16(truncatingIfNeeded: key.keyCode)))
  }

  private func modifiersMatch(_ key: HotKey, _ flags: NSEvent.ModifierFlags) -> Bool {
    let f = flags.intersection(.deviceIndependentFlagsMask)
    func has(_ carbon: UInt32, _ flag: NSEvent.ModifierFlags) -> Bool {
      ((key.carbonMods & carbon) != 0) == f.contains(flag)
    }
    return has(UInt32(cmdKey), .command) && has(UInt32(optionKey), .option) && has(UInt32(controlKey), .control) && has(UInt32(shiftKey), .shift)
  }

  func set(id: UInt32, key: HotKey, down: @escaping () -> Void, up: @escaping () -> Void = {}, arm: @escaping () -> Void = {}, hold: Bool = false) {
    if holdingIds.contains(id) { noteUp(id) }
    armedMods.remove(id)
    specs[id] = Spec(key: key, down: down, up: up, arm: arm, hold: hold)
    register(id)
  }

  private func register(_ id: UInt32) {
    if let r = refs[id] { UnregisterEventHotKey(r); refs[id] = nil }
    guard let s = specs[id] else { return }
    var ref: EventHotKeyRef?
    let st = RegisterEventHotKey(s.key.keyCode, s.key.carbonMods, EventHotKeyID(signature: OSType(0x53504B42), id: id),
                                 GetApplicationEventTarget(), 0, &ref)
    if st == noErr, let ref { refs[id] = ref } else { Log.event("hotkey \(s.key.label) registration failed (\(st))") }
  }

  func suspend() {
    suspended = true
    for id in Array(holdingIds) { noteUp(id) }
    for (_, r) in refs { UnregisterEventHotKey(r) }
    refs = [:]
  }

  func resume() {
    suspended = false
    for id in specs.keys { register(id) }
  }
}
