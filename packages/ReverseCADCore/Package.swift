// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "ReverseCADCore", platforms: [.iOS(.v17), .macOS(.v13)], products: [.library(name: "ReverseCADCore", targets: ["ReverseCADCore"])], targets: [.target(name: "ReverseCADCore"), .testTarget(name: "ReverseCADCoreTests", dependencies: ["ReverseCADCore"])])
