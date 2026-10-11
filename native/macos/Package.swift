// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "Omni", platforms: [.macOS(.v13)],
                      products: [.executable(name: "Omni", targets: ["Omni"])],
                      targets: [.executableTarget(name: "Omni")])
