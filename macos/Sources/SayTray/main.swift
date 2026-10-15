import AppKit

if let i = CommandLine.arguments.firstIndex(of: "--pipeline-test") {
  // SayTray --pipeline-test <out.json> <file.txt>...   (same TextPrep + PiperEngine + guard code, no playback)
  exit(PipelineTest.run(Array(CommandLine.arguments[(i + 1)...])))
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
