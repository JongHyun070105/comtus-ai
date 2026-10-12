// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "mac-capture",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "mac-capture", targets: ["MacCaptureCLI"]),
        .library(name: "MacCaptureCore", targets: ["MacCaptureCore"]),
    ],
    targets: [
        .target(name: "MacCaptureCore"),
        .executableTarget(name: "MacCaptureCLI", dependencies: ["MacCaptureCore"]),
        .testTarget(name: "MacCaptureCoreTests", dependencies: ["MacCaptureCore"]),
    ]
)
