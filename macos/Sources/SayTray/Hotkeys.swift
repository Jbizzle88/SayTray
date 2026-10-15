import Carbon
import Foundation

/// Global hot keys via Carbon (press + release events, needed for push-to-talk).
final class HotKeyCenter {
  static let shared = HotKeyCenter()
  private struct Spec { var key: HotKey; var down: () -> Void; var up: () -> Void }
  private var specs: [UInt32: Spec] = [:]
  private var refs: [UInt32: EventHotKeyRef] = [:]
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
  }
  private func fire(_ id: UInt32, pressed: Bool) {
    guard let s = specs[id] else { return }
    pressed ? s.down() : s.up()
  }
  func set(id: UInt32, key: HotKey, down: @escaping () -> Void, up: @escaping () -> Void = {}) {
    specs[id] = Spec(key: key, down: down, up: up)
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
  func suspend() { for (_, r) in refs { UnregisterEventHotKey(r) }; refs = [:] }
  func resume() { for id in specs.keys { register(id) } }
}
