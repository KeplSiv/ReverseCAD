import Foundation
import SwiftUI
import Vision
import CoreImage
import ImageIO
import ReverseCADCore

struct SavedObjectIdentity: Codable {
    var sourceFramesSHA256: String
    var referenceID: String
    var anchor: [Double]
    var frameIDs: [String]
    var detections: [JevDetection]
    var confirmedIndices: [Int]
    var category: String
    var userSelected: Bool
}

@MainActor final class CapturedObjectWorkflow: ObservableObject {
    @Published var phase = "idle"
    @Published var message = ""
    @Published var failure: String?
    @Published var referenceImage: UIImage?
    @Published var identity: SavedObjectIdentity?
    private let clientFactory: () -> JevClient
    private let keyProvider: () throws -> String
    init(clientFactory: @escaping () -> JevClient = { JevClient() }, keyProvider: @escaping () throws -> String = { try PreludeJevConfiguration.apiKey() }) {
        self.clientFactory = clientFactory; self.keyProvider = keyProvider
    }
    private var task: Task<Void, Never>?
    private var generation = UUID()
    private var retryNotBefore = Date.distantPast
    var working: Bool { phase == "finding" || phase == "refining" }

    func cancel() {
        generation = UUID(); task?.cancel(); task = nil
        phase = identity == nil ? "idle" : "identified"
        message = "Cancelled. Your saved scan is preserved."
    }
    func load(project: URL, capture: URL) {
        cancel(); failure = nil; identity = nil; referenceImage = nil
        if let data = try? Data(contentsOf: project.appendingPathComponent("object-identity.json")),
           let saved = try? JSONDecoder().decode(SavedObjectIdentity.self, from: data),
           saved.frameIDs.count == saved.detections.count, saved.frameIDs.count <= 10,
           saved.anchor.count == 2, saved.anchor.allSatisfy({ $0.isFinite && (0...1).contains($0) }),
           saved.confirmedIndices.allSatisfy({ saved.frameIDs.indices.contains($0) }),
           saved.sourceFramesSHA256 == (try? CaptureIO.sha256(file: capture.appendingPathComponent("frames.jsonl"))) {
            identity = saved; phase = saved.confirmedIndices.isEmpty ? "ambiguous" : "identified"
        } else { phase = "idle" }
        if let frames = try? CaptureIO.readFrames(directory: capture), let first = RepresentativeViews.select(frames).first {
            referenceImage = UIImage(contentsOfFile: capture.appendingPathComponent(first.rgbPath).path)
        }
    }
    func find(project: URL, capture: URL, description: String, point: CGPoint? = nil) {
        guard !working else { return }
        if Date() < retryNotBefore {
            failure = "Jev reached its request limit. Retry in \(Int(ceil(retryNotBefore.timeIntervalSinceNow))) seconds."; return
        }
        cancel(); let epoch = generation; phase = "finding"; failure = nil; message = "Finding your object…"
        task = Task {
            do {
                let frames = try CaptureIO.readFrames(directory: capture)
                let views = RepresentativeViews.select(frames)
                guard views.count >= 3, let first = views.first else {
                    throw ServiceFailure(message: "Too few sharp, separated views. Keep this capture and add views from other sides before building.")
                }
                let anchor = point ?? CGPoint(x: first.captureRegion.map { $0[0] + $0[2]/2 } ?? 0.5,
                                              y: first.captureRegion.map { $0[1] + $0[3]/2 } ?? 0.5)
                let reference = try Self.requestImage(capture.appendingPathComponent(first.rgbPath))
                referenceImage = UIImage(contentsOfFile: capture.appendingPathComponent(first.rgbPath).path)
                let key = try keyProvider()
                let client = clientFactory()
                var detections = [JevDetection]()
                for (index, view) in views.enumerated() {
                    try Task.checkCancellation()
                    message = "Finding your object… \(index + 1) of \(views.count) views"
                    let jpeg = view.frameID == first.frameID ? reference : try Self.requestImage(capture.appendingPathComponent(view.rgbPath))
                    // Exactly one request per selected view. No automatic retry loop.
                    let result = try await client.identifySavedView(jpeg: jpeg, reference: reference, description: description,
                                                                  anchor: anchor, requestID: UUID(), apiKey: key)
                    try Task.checkCancellation(); guard epoch == generation else { return }
                    detections.append(result)
                }
                let confirmed = ObjectConsensus.confirmed(detections, anchor: anchor)
                let record = SavedObjectIdentity(sourceFramesSHA256: try CaptureIO.sha256(file: capture.appendingPathComponent("frames.jsonl")), referenceID: first.frameID, anchor: [anchor.x, anchor.y], frameIDs: views.map(\.frameID),
                    detections: detections, confirmedIndices: confirmed, category: detections.first?.category ?? "other", userSelected: point != nil)
                identity = record
                try CaptureIO.atomicWrite(record, to: project.appendingPathComponent("object-identity.json"))
                if confirmed.isEmpty {
                    phase = "ambiguous"; message = point == nil ? "Tap the object you meant in this saved image." : "The views still disagree. Tap the intended object to try again; your scan is saved."
                } else {
                    phase = "identified"; message = "Object identified across \(confirmed.count) views."
                }
            } catch {
                guard epoch == generation else { return }
                phase = "idle"
                if error is CancellationError { message = "Cancelled. Your saved scan is preserved." }
                else { failure = error.localizedDescription }
                if let jev = error as? JevClientError, case .rateLimited(let delay) = jev { retryNotBefore = Date().addingTimeInterval(delay) }
            }
            if epoch == generation { task = nil }
        }
    }

    func build(project: URL, capture: URL, completion: @escaping ([String: Any]) -> Void) {
        guard !working, let identity, !identity.confirmedIndices.isEmpty else { return }
        cancel(); let epoch = generation; phase = "refining"; failure = nil; message = "Building your 3D model… Preparing object masks on this phone."
        task = Task {
            do {
                let worker = Task.detached(priority: .userInitiated) { try SavedObjectMasks.prepare(capture: capture, identity: identity) }
                let target = try await withTaskCancellationHandler(operation: { try await worker.value }, onCancel: { worker.cancel() })
                try Task.checkCancellation(); guard epoch == generation else { return }
                phase = "identified"; task = nil; completion(target)
            } catch {
                guard epoch == generation else { return }
                phase = "identified"; task = nil
                if !(error is CancellationError) { failure = error.localizedDescription }
            }
        }
    }
    nonisolated static func requestImage(_ url: URL) throws -> Data {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceThumbnailMaxPixelSize: 1280, kCGImageSourceCreateThumbnailWithTransform: false] as CFDictionary),
              min(image.width, image.height) > 0 else {
            throw ServiceFailure(message: "A saved image could not be read. The original scan is preserved.")
        }
        let scale = max(1, 280.0 / Double(min(image.width, image.height)))
        let size = CGSize(width: Double(image.width)*scale, height: Double(image.height)*scale)
        guard max(size.width,size.height) <= 1568 else { throw JevClientError.invalidInput }
        let format = UIGraphicsImageRendererFormat(); format.scale = 1; format.opaque = true
        let prepared = UIGraphicsImageRenderer(size: size, format: format).image { _ in UIImage(cgImage: image).draw(in: CGRect(origin: .zero,size: size)) }
        guard let data = prepared.jpegData(compressionQuality: 0.88) else { throw JevClientError.invalidInput }
        return data
    }
}

/// Derived masks live alongside, never over, original calibrated observations.
/// Jev anchors periodically reset local tracking; unanchored, weak or absent masks are excluded.
enum SavedObjectMasks {
    static func prepare(capture: URL, identity: SavedObjectIdentity) throws -> [String: Any] {
        guard identity.sourceFramesSHA256 == (try CaptureIO.sha256(file: capture.appendingPathComponent("frames.jsonl"))) else {
            throw ServiceFailure(message: "The identification belongs to a different capture. Identify this saved scan again.")
        }
        let frames = try CaptureIO.readFrames(directory: capture)
        let seeds = Dictionary(uniqueKeysWithValues: identity.confirmedIndices.compactMap { index -> (String, JevDetection.Box)? in
            guard let box = identity.detections[index].box else { return nil }
            return (identity.frameIDs[index], box)
        })
        let generation = "masks/objects/" + UUID().uuidString.lowercased()
        let stage = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: stage) }
        var records = [String: Any]()
        var tracker: VNTrackObjectRequest?
        var sequence = VNSequenceRequestHandler()
        var seedFrame: CaptureFrame?
        for frame in frames {
            try Task.checkCancellation()
            guard frame.quality.accepted, frame.depthWidth > 0, frame.depthHeight > 0 else { continue }
            let url = try CaptureIO.safeURL(directory: capture, path: frame.rgbPath)
            guard let imageSource = CGImageSourceCreateWithURL(url as CFURL, nil), let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else { continue }
            let box: CGRect
            let source: String
            if identity.frameIDs.contains(frame.frameID), seeds[frame.frameID] == nil {
                tracker = nil; seedFrame = nil; continue
            }
            if let seed = seeds[frame.frameID] {
                box = CGRect(x: seed.left, y: seed.top, width: seed.right-seed.left, height: seed.bottom-seed.top)
                tracker = VNTrackObjectRequest(detectedObjectObservation: VNDetectedObjectObservation(boundingBox: CGRect(x: box.minX, y: 1-box.maxY, width: box.width, height: box.height)))
                tracker?.trackingLevel = .accurate; sequence = VNSequenceRequestHandler(); seedFrame = frame
                source = "jev_reference_match_and_local_instance_mask"
            } else {
                guard let anchor = seedFrame, anchor.segmentID == frame.segmentID,
                      frame.timestampS - anchor.timestampS <= 12,
                      RepresentativeViews.separation(frame, anchor) < 12, let tracker else { continue }
                try sequence.perform([tracker], on: image, orientation: .up)
                guard let observation = tracker.results?.first as? VNDetectedObjectObservation, observation.confidence >= 0.8 else {
                    seedFrame = nil; continue
                }
                tracker.inputObservation = observation
                let b = observation.boundingBox; box = CGRect(x: b.minX, y: 1-b.maxY, width: b.width, height: b.height)
                source = "local_tracking_from_jev_reference_match"
            }
            guard let mask = try mask(image: image, box: box, width: frame.depthWidth, height: frame.depthHeight) else { continue }
            let name = frame.frameID + ".u8"
            try mask.write(to: stage.appendingPathComponent(name), options: .atomic)
            records[frame.frameID] = ["mask_path": generation + "/" + name, "mask_sha256": CaptureIO.sha256(mask),
                "rgb_sha256": try CaptureIO.sha256(file: url), "source": source,
                "box": [box.minX, box.minY, box.width, box.height]]
        }
        guard records.count >= 3 else { throw ServiceFailure(message: "The object could not be separated in enough views. Your scan is saved. Try choosing the object again, or add sharp views that separate it from the table and hands.") }
        try Task.checkCancellation()
        // No suspension from commit through checksum repair. Original evidence is never rewritten.
        let destination = capture.appendingPathComponent(generation)
        try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.moveItem(at: stage, to: destination)
        var hashes = [String: String]()
        for file in try CaptureIO.files(directory: capture) where file.path != "checksums.json" { hashes[file.path] = try CaptureIO.sha256(file: file.url) }
        try CaptureIO.atomicWrite(hashes, to: capture.appendingPathComponent("checksums.json"))
        return ["workflow": "capture_first_v1", "confirmed": true, "reference_frame_id": identity.referenceID,
                "category": identity.category, "metric_evidence": false, "frames": records,
                "evidence": identity.confirmedIndices.map { ["frame_id": identity.frameIDs[$0], "detection": identity.detections[$0].objectRecord] }]
    }

    static func mask(image: CGImage, box: CGRect, width: Int, height: Int) throws -> Data? {
        let request = VNGenerateForegroundInstanceMaskRequest()
        let hands = VNDetectHumanHandPoseRequest(); hands.maximumHandCount = 2
        try VNImageRequestHandler(cgImage: image, orientation: .up).perform([request, hands])
        // Do not fuse a transient hand into the object even if foreground segmentation merges them.
        for hand in hands.results ?? [] {
            for joint in (try hand.recognizedPoints(.all)).values where joint.confidence >= 0.3 {
                if box.contains(CGPoint(x: joint.location.x, y: 1-joint.location.y)) { return nil }
            }
        }
        guard let observation = request.results?.first else { return nil }
        let labels = observation.instanceMask
        CVPixelBufferLockBaseAddress(labels, .readOnly)
        let w = CVPixelBufferGetWidth(labels), h = CVPixelBufferGetHeight(labels), stride = CVPixelBufferGetBytesPerRow(labels)
        guard let base = CVPixelBufferGetBaseAddress(labels)?.assumingMemoryBound(to: UInt8.self) else { CVPixelBufferUnlockBaseAddress(labels, .readOnly); return nil }
        var counts = [UInt8: Int](), totals = [UInt8: Int]()
        for y in 0..<h { for x in 0..<w {
            let label = base[y*stride+x]; guard label > 0 else { continue }
            totals[label, default: 0] += 1
            if box.contains(CGPoint(x: (Double(x)+0.5)/Double(w), y: (Double(y)+0.5)/Double(h))) { counts[label, default: 0] += 1 }
        } }
        CVPixelBufferUnlockBaseAddress(labels, .readOnly)
        let ranked = counts.sorted { $0.value > $1.value }
        guard let best = ranked.first, best.value >= 8,
              Double(best.value) / Double(totals[best.key] ?? 1) >= 0.6,
              ranked.count < 2 || Double(best.value) > Double(ranked[1].value) * 1.4 else { return nil }
        // The full instance silhouette can extend beyond the Jev box or framing guide.
        let buffer = try observation.generateMask(forInstances: IndexSet(integer: Int(best.key)))
        return rasterize(buffer, width: width, height: height)
    }

    static func rasterize(_ buffer: CVPixelBuffer, width: Int, height: Int) -> Data? {
        guard width > 0, height > 0 else { return nil }
        CVPixelBufferLockBaseAddress(buffer, .readOnly); defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let mw = CVPixelBufferGetWidth(buffer), mh = CVPixelBufferGetHeight(buffer), ms = CVPixelBufferGetBytesPerRow(buffer)
        let format = CVPixelBufferGetPixelFormatType(buffer)
        guard let raw = CVPixelBufferGetBaseAddress(buffer), [kCVPixelFormatType_OneComponent8, kCVPixelFormatType_OneComponent32Float].contains(format) else { return nil }
        var data = Data(count: width*height)
        data.withUnsafeMutableBytes { output in
            let pixels = output.bindMemory(to: UInt8.self)
            for y in 0..<height { for x in 0..<width {
                let row = raw.advanced(by: min(mh-1,y*mh/height)*ms), sx = min(mw-1,x*mw/width)
                let value: Float = format == kCVPixelFormatType_OneComponent32Float ? row.load(fromByteOffset: sx*4, as: Float.self) : Float(row.load(fromByteOffset: sx, as: UInt8.self))/255
                pixels[y*width+x] = value.isFinite && value > 0.5 ? 255 : 0
            } }
        }
        return data
    }
}
