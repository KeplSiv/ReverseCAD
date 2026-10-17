// General object reconstruction experiment. No primitive fitting or hole repair.
// swiftc -parse-as-library scripts/reconstruct_photos.swift -o work/reconstruct-photos
import Foundation
import RealityKit

@main struct ReconstructPhotos {
    static func main() async throws {
        guard CommandLine.arguments.count == 3 else {
            throw NSError(domain: "ReverseCAD", code: 1, userInfo: [NSLocalizedDescriptionKey: "Usage: reconstruct-photos IMAGE_DIRECTORY OUTPUT.usdz"])
        }
        guard PhotogrammetrySession.isSupported else {
            throw NSError(domain: "ReverseCAD", code: 2, userInfo: [NSLocalizedDescriptionKey: "Object Capture unsupported on this Mac"])
        }
        var config = PhotogrammetrySession.Configuration()
        config.featureSensitivity = .high
        config.sampleOrdering = .unordered
        config.isObjectMaskingEnabled = true
        let output = URL(fileURLWithPath: CommandLine.arguments[2])
        guard output.pathExtension.lowercased() == "usdz" else {
            throw NSError(domain: "ReverseCAD", code: 3, userInfo: [NSLocalizedDescriptionKey: "Output must use .usdz"])
        }
        let session = try PhotogrammetrySession(input: URL(fileURLWithPath: CommandLine.arguments[1]), configuration: config)
        try session.process(requests: [.modelFile(url: output, detail: .full)])
        for try await event in session.outputs {
            switch event {
            case .requestProgress(_, let fraction): print("progress \(Int(fraction * 100))%")
            case .requestError(_, let error): throw error
            case .requestComplete: print("Model written: \(output.path). Scale and detail require independent validation.")
            case .processingComplete: return
            case .invalidSample(let id, let reason): print("Invalid sample \(id): \(reason)")
            case .skippedSample(let id): print("Skipped sample \(id)")
            default: break
            }
        }
    }
}
