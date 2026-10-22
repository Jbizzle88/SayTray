// swift-tools-version:5.9
import PackageDescription
let package = Package(
  name: "SayTray",
  platforms: [.macOS(.v14)],
  targets: [
    .target(name: "SBObjC", path: "Sources/SBObjC"),
    .target(name: "SayTrayCore", path: "Sources/SayTrayCore"),
    .executableTarget(name: "SayTray", dependencies: ["SBObjC", "SayTrayCore"], path: "Sources/SayTray", exclude: ["voices.json"]),
    .executableTarget(name: "TextPrepTests", dependencies: ["SayTrayCore"], path: "Sources/TextPrepTests"),
  ]
)
