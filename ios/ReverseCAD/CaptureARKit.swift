import Foundation
import ARKit
import CoreImage
import CoreMotion
import AVFoundation
import Vision
import UIKit
import ReverseCADCore

struct CaptureLimits: Sendable {
    var durationSeconds: Double = 90
    var acceptedFrames: Int = 240
    var rejectedFrames: Int = 80
    var bytes: Int = 512 * 1024 * 1024
    var reviewFPS: Double = 15
    var minimumKeyframeSeconds: Double = 0.35
}

/// A single offset preserves RGB/depth/pose/motion alignment without exporting device uptime.
/// The origin stays in memory; only elapsed intervals between capture events are persisted.
struct CaptureTimeline {
    private var origin: TimeInterval?
    mutating func begin(at timestamp: TimeInterval) {
        if origin == nil, timestamp.isFinite { origin = timestamp }
    }
    func relativeTimestamp(_ timestamp: TimeInterval) -> TimeInterval? {
        guard let origin, timestamp.isFinite, timestamp >= origin else { return nil }
        return timestamp - origin
    }
}

/// ARKit VIO is the only pose source. Optional motion samples are diagnostic, never integrated.
/// The delegate retains at most two sets of CV buffers; segmentation/JPEG/video/I/O occur on workQueue.
final class ARKitCaptureProvider: NSObject, CaptureProvider, ARSessionDelegate, @unchecked Sendable {
    var onFrame: ((CaptureFrame) -> Void)?
    var onProgress: ((CaptureProgress) -> Void)?
    private let session: ARSession
    private let directory: URL
    private let scanID: String
    private let useDepth: Bool
    private let motionDiagnostics: Bool
    private let limits: CaptureLimits
    private let delegateQueue = DispatchQueue(label: "com.pranav.reversecad.arkit", qos: .userInitiated)
    private let workQueue = DispatchQueue(label: "com.pranav.reversecad.capture-write", qos: .userInitiated)
    private let slots = DispatchSemaphore(value: 2)
    private let lock = NSLock()
    private let ci = CIContext(options: [.cacheIntermediates: false])
    private let motion = CMMotionManager()
    private let motionQueue = OperationQueue()
    private let writer: ScanPackageWriter
    private var active = false
    private var pendingDrops = 0
    private var segment = UUID().uuidString.lowercased()
    private var segments: [CaptureSegment]
    private var selectedPoint = CGPoint(x: 0.5, y: 0.5)
    private var timeline = CaptureTimeline()
    private var lastVideoTimestamp = -Double.infinity
    private var lastKeyframeTimestamp = -Double.infinity
    private var relocalizationSegmentStarted = false
    private var previousKeyframePose: simd_float4x4?
    private var stats = CaptureProgress()
    private var viewBins = Set<Int>()
    private var video: AVAssetWriter?
    private var videoInput: AVAssetWriterInput?
    private var videoAdaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var videoStart: Double?
    private var movieFrames = 0
    private var movieDropped = 0
    private var videoFailure: String?
    private var failure: String?
    private var motionCount = 0
    private var motionDropped = 0
    private let motionSlots = DispatchSemaphore(value: 8)
    private var finishTask: Task<URL, Error>?
    private var events: [[String: Any]] = []
    private var exposureRecords: [[String: Any]] = []

    init(session: ARSession, directory: URL, scanID: String, useDepth: Bool, motionDiagnostics: Bool, limits: CaptureLimits = CaptureLimits()) throws {
        self.session = session; self.directory = directory; self.scanID = scanID; self.useDepth = useDepth
        self.motionDiagnostics = motionDiagnostics; self.limits = limits
        let initial = CaptureSegment(segmentID: segment)
        self.segments = [initial]
        self.writer = try ScanPackageWriter(directory: directory, manifest: CaptureManifest(scanID: scanID, source: useDepth ? "arkit" : "camera_manual", device: "\(UIDevice.current.model) / iOS \(UIDevice.current.systemVersion)", segments: [initial]), maxBytes: limits.bytes)
        super.init()
        motionQueue.maxConcurrentOperationCount = 1
        motionQueue.name = "com.pranav.reversecad.motion"
        let initialDiagnostics: [String: Any] = ["schema_version": 2, "timestamp_clock": "seconds_since_first_ARFrame", "scan_id": scanID, "capture_complete": false, "video_complete": false, "status": "capture_started_unfinalized; recover committed frames after interruption", "depth_units": "m", "pose_source": "ARKit visual-inertial world tracking"]
        try JSONSerialization.data(withJSONObject: initialDiagnostics, options: [.sortedKeys]).write(to: directory.appendingPathComponent("capture_diagnostics.json"), options: .atomic)
        try writer.finalizeAsset(path: "capture_diagnostics.json")
    }

    func start() throws {
        guard ARWorldTrackingConfiguration.isSupported else { throw CaptureFailure.unavailable("ARKit world tracking is unsupported.") }
        let configuration = ARWorldTrackingConfiguration()
        if useDepth {
            guard ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else { throw CaptureFailure.unavailable("Native scene depth is unavailable.") }
            configuration.frameSemantics = [.sceneDepth]
        }
        // Mesh reconstruction is optional visualization. It is not used as a substitute for native depth.
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) { configuration.sceneReconstruction = .mesh }
        configuration.worldAlignment = .gravity
        configuration.environmentTexturing = .none
        session.delegateQueue = delegateQueue
        session.delegate = self
        lock.lock(); active = true; lock.unlock()
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        if motionDiagnostics { startMotionDiagnostics() }
    }

    func selectObject(point: CGPoint) {
        lock.lock(); selectedPoint = point; lock.unlock()
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        lock.lock()
        guard active else { lock.unlock(); return }
        timeline.begin(at: frame.timestamp)
        guard let elapsed = timeline.relativeTimestamp(frame.timestamp) else { lock.unlock(); return }
        let currentSegment = segment
        let point = selectedPoint
        lock.unlock()
        if elapsed >= limits.durationSeconds {
            lock.lock(); active = false; lock.unlock()
            workQueue.async { [self] in stopForBudget("Capture duration limit reached. Saved views remain available; capture another scan for missing surfaces.") }
            return
        }
        guard frame.timestamp - lastVideoTimestamp >= 1 / limits.reviewFPS else { return }
        lastVideoTimestamp = frame.timestamp
        guard slots.wait(timeout: .now()) == .success else {
            lock.lock(); pendingDrops += 1; lock.unlock()
            return
        }
        // Copy small metadata now, retain only the CVPixelBuffers (no retained ARFrame queue).
        let rgb = frame.capturedImage
        let depth = frame.sceneDepth?.depthMap
        let confidence = frame.sceneDepth?.confidenceMap
        let pose = frame.camera.transform
        let intrinsics = frame.camera.intrinsics
        let timestamp = elapsed
        let resolution = frame.camera.imageResolution
        let exposureDuration = frame.camera.exposureDuration
        let exposureOffset = frame.camera.exposureOffset
        let tracking: String
        let trackingReason: String?
        switch frame.camera.trackingState {
        case .normal: tracking = "normal"; trackingReason = nil; relocalizationSegmentStarted = false
        case .notAvailable: tracking = "unavailable"; trackingReason = "World tracking unavailable"
        case .limited(let reason):
            tracking = "limited"
            switch reason {
            case .excessiveMotion: trackingReason = "Move more slowly"
            case .insufficientFeatures: trackingReason = "Add diffuse light and a textured background"
            case .initializing: trackingReason = "Allow visual-inertial tracking to initialize"
            case .relocalizing:
                trackingReason = "Relocalizing: keep the object stationary and revisit known views"
                if !relocalizationSegmentStarted {
                    relocalizationSegmentStarted = true
                    beginUnregisteredSegment(reason: "relocalization_uncertain_origin")
                }
            @unknown default: trackingReason = "Tracking quality is limited"
            }
        }
        workQueue.async { [self] in
            defer { slots.signal() }
            autoreleasepool {
                do {
                    try process(rgb: rgb, depth: depth, confidence: confidence, pose: pose, intrinsics: intrinsics, resolution: resolution, timestamp: timestamp, segment: currentSegment, tracking: tracking, trackingReason: trackingReason, point: point, exposureDuration: exposureDuration, exposureOffset: exposureOffset)
                } catch { stopForBudget(error.localizedDescription); failure = error.localizedDescription }
            }
        }
    }

    private func process(rgb: CVPixelBuffer, depth: CVPixelBuffer?, confidence: CVPixelBuffer?, pose: simd_float4x4, intrinsics: simd_float3x3, resolution: CGSize, timestamp: Double, segment: String, tracking: String, trackingReason: String?, point: CGPoint, exposureDuration: Double, exposureOffset: Float) throws {
        guard !stats.finished else { return }
        lock.lock(); stats.dropped += pendingDrops; pendingDrops = 0; lock.unlock()
        try appendVideo(rgb, timestamp: timestamp)
        guard timestamp - lastKeyframeTimestamp >= limits.minimumKeyframeSeconds else { return }
        // Accept useful baseline/angle changes; force an overlap keyframe every 1.5 seconds.
        if let previous = previousKeyframePose, timestamp - lastKeyframeTimestamp < 1.5 {
            let distance = simd_distance(pose.columns.3, previous.columns.3)
            let angle = acos(min(1, max(-1, simd_dot(simd_normalize(pose.columns.2.xyz), simd_normalize(previous.columns.2.xyz)))))
            if distance < 0.012 && angle < 0.06 { return }
        }
        lastKeyframeTimestamp = timestamp
        let width = CVPixelBufferGetWidth(rgb), height = CVPixelBufferGetHeight(rgb)
        let blur = Self.blurScore(rgb)
        var reasons = [String]()
        if let trackingReason { reasons.append(trackingReason) }
        if blur < 7 { reasons.append("Low image detail or motion blur; steady the phone and add texture/light") }
        if useDepth && depth == nil { reasons.append("Native depth unavailable in this frame") }
        let depthWidth = depth.map(CVPixelBufferGetWidth) ?? 0
        let depthHeight = depth.map(CVPixelBufferGetHeight) ?? 0
        let depthData = try depth.map { try Self.copyRows($0, bytesPerPixel: 4, expectedFormat: kCVPixelFormatType_DepthFloat32) }
        let confidenceData = try confidence.map { try Self.copyRows($0, bytesPerPixel: 1, expectedFormat: kCVPixelFormatType_OneComponent8) }
        let validDepthFraction = depthData.map(Self.validDepthFraction) ?? 0
        if useDepth && validDepthFraction < 0.1 { reasons.append("Too little finite positive native depth; change distance or avoid reflective/transparent surfaces") }
        let poorConfidence = confidenceData.map { $0.filter({ $0 >= 1 }).count < $0.count / 8 } ?? false
        if poorConfidence { reasons.append("Too few reliable depth samples") }
        let accepted = tracking == "normal" && blur >= 7 && !poorConfidence && (!useDepth || validDepthFraction >= 0.1)
        if !accepted && stats.rejected >= limits.rejectedFrames {
            stats.dropped += 1
            stats.guidance = reasons.first ?? "Poor observation rejected"
            onProgress?(stats)
            return
        }
        let id = String(format: "%06d", stats.accepted + stats.rejected)
        let rgbPath = "rgb/\(id).jpg", depthPath = depthData == nil ? nil : "depth/\(id).f32"
        let confidencePath = confidenceData == nil ? nil : "confidence/\(id).u8"
        guard let jpg = ci.jpegRepresentation(of: CIImage(cvPixelBuffer: rgb), colorSpace: CGColorSpaceCreateDeviceRGB(), options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.88]) else { throw CaptureFailure.write("Could not encode the original-resolution RGB keyframe.") }
        var assets = [rgbPath: jpg]
        if let depthData, let depthPath { assets[depthPath] = depthData }
        if let confidenceData, let confidencePath { assets[confidencePath] = confidenceData }
        var maskPath: String?
        // Masks are native depth-size labels and derived from the original raw image with .up orientation.
        if accepted, depthWidth > 0, let mask = foregroundMask(rgb: rgb, point: point, width: depthWidth, height: depthHeight) {
            maskPath = "masks/\(id).u8"; assets[maskPath!] = mask
        }
        var capture = CaptureFrame(scanID: scanID, segmentID: segment, frameID: id, timestampS: timestamp, rgbPath: rgbPath, rgbWidth: width, rgbHeight: height, depthPath: depthPath, depthWidth: depthWidth, depthHeight: depthHeight, depthRowBytes: depthWidth * 4, confidencePath: confidencePath, maskPath: maskPath, intrinsics: Self.columnMajor(intrinsics), intrinsicsWidth: Int(resolution.width), intrinsicsHeight: Int(resolution.height), worldCamera: Self.columnMajor(pose), trackingState: tracking, quality: CaptureQuality(blurScore: blur, accepted: accepted, reasons: reasons))
        capture.depthCalibrationMode = "native_arkit"
        try writer.append(frame: capture, assets: assets)
        exposureRecords.append(["frame_id": id, "exposure_duration_s": exposureDuration, "exposure_offset_ev": exposureOffset, "confidence_available": confidence != nil, "depth_source": useDepth ? "native_sceneDepth" : "absent_camera_manual", "valid_depth_fraction": validDepthFraction, "mask_available": maskPath != nil])
        if accepted {
            stats.accepted += 1; previousKeyframePose = pose
            let azimuth = atan2(pose.columns.2.x, pose.columns.2.z)
            let elevation = asin(min(1, max(-1, pose.columns.2.y)))
            let bin = Int((azimuth + .pi) / (2 * .pi) * 12) + 12 * Int((elevation + .pi / 2) / .pi * 3)
            viewBins.insert(bin)
        } else { stats.rejected += 1 }
        stats.bytes = writer.bytesWritten
        stats.coverageViews = viewBins.count
        stats.guidance = accepted ? "Move slowly around the object, then scan from a little higher. Tap the object if the background is selected." : (reasons.first ?? "Poor observation rejected")
        onFrame?(capture); onProgress?(stats)
        // The service package budget counts every persisted record, including rejected evidence.
        if stats.accepted + stats.rejected >= limits.acceptedFrames || stats.bytes >= limits.bytes - 16 * 1024 * 1024 { stopForBudget("Capture resource budget reached. Committed frames were saved; review coverage before processing.") }
        if let capacity = try? directory.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage, capacity < 256 * 1024 * 1024 { stopForBudget("Low device storage: capture stopped with committed data preserved.") }
    }

    private func foregroundMask(rgb: CVPixelBuffer, point: CGPoint, width: Int, height: Int) -> Data? {
        let request = VNGenerateForegroundInstanceMaskRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: rgb, orientation: .up)
        do {
            try handler.perform([request])
            guard let observation = request.results?.first else { return nil }
            let instances = observation.instanceMask
            CVPixelBufferLockBaseAddress(instances, .readOnly)
            let size = (CVPixelBufferGetWidth(instances), CVPixelBufferGetHeight(instances))
            let x = min(size.0 - 1, max(0, Int(point.x * Double(size.0))))
            let y = min(size.1 - 1, max(0, Int(point.y * Double(size.1))))
            let label = CVPixelBufferGetBaseAddress(instances)?.advanced(by: y * CVPixelBufferGetBytesPerRow(instances) + x).load(as: UInt8.self) ?? 0
            CVPixelBufferUnlockBaseAddress(instances, .readOnly)
            // A background tap has no reliable selection; leave mask absent and request crop correction later.
            guard label > 0 else { return nil }
            let mask = try observation.generateMask(forInstances: IndexSet(integer: Int(label)))
            CVPixelBufferLockBaseAddress(mask, .readOnly)
            defer { CVPixelBufferUnlockBaseAddress(mask, .readOnly) }
            guard let base = CVPixelBufferGetBaseAddress(mask) else { return nil }
            let mw = CVPixelBufferGetWidth(mask), mh = CVPixelBufferGetHeight(mask), stride = CVPixelBufferGetBytesPerRow(mask)
            var bytes = Data(count: width * height)
            bytes.withUnsafeMutableBytes { dstRaw in
                let dst = dstRaw.bindMemory(to: UInt8.self)
                for y in 0..<height { for x in 0..<width {
                    // Match native ARKit normalized depth/RGB alignment (direct scaling, no resize half-pixel shift).
                    let sx = min(mw - 1, Int(Double(x) * Double(mw) / Double(width)))
                    let sy = min(mh - 1, Int(Double(y) * Double(mh) / Double(height)))
                    let value = base.advanced(by: sy * stride + sx * 4).load(as: Float.self)
                    dst[y * width + x] = value > 0.2 ? 1 : 0
                } }
            }
            return bytes
        } catch { return nil }
    }

    // timestamp uses the same capture-relative timeline as the paired CaptureFrame.
    func appendVideo(_ pixel: CVPixelBuffer, timestamp: Double) throws {
        guard videoFailure == nil else { return }
        if video == nil {
            let url = directory.appendingPathComponent("video/review.mov")
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            let writer = try AVAssetWriter(outputURL: url, fileType: .mov)
            let sourceWidth = CVPixelBufferGetWidth(pixel), sourceHeight = CVPixelBufferGetHeight(pixel)
            let ratio = min(1, 1280.0 / Double(max(sourceWidth, sourceHeight)))
            let width = max(2, Int(Double(sourceWidth) * ratio) / 2 * 2)
            let height = max(2, Int(Double(sourceHeight) * ratio) / 2 * 2)
            let input = AVAssetWriterInput(mediaType: .video, outputSettings: [AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: width, AVVideoHeightKey: height, AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 2_000_000, AVVideoExpectedSourceFrameRateKey: 15]])
            input.expectsMediaDataInRealTime = true
            let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA, kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height, kCVPixelBufferIOSurfacePropertiesKey as String: [:]])
            guard writer.canAdd(input) else { videoFailure = "Video encoder unavailable; calibrated keyframes are retained"; return }
            writer.add(input)
            guard writer.startWriting() else { videoFailure = writer.error?.localizedDescription ?? "Video start failed"; return }
            writer.startSession(atSourceTime: .zero)
            self.video = writer; videoInput = input; videoAdaptor = adaptor; videoStart = timestamp
        }
        guard let input = videoInput, let adaptor = videoAdaptor, input.isReadyForMoreMediaData, let pool = adaptor.pixelBufferPool else { movieDropped += 1; return }
        var target: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &target) == kCVReturnSuccess, let target else { movieDropped += 1; return }
        let image = CIImage(cvPixelBuffer: pixel)
        let transform = CGAffineTransform(scaleX: Double(CVPixelBufferGetWidth(target)) / image.extent.width, y: Double(CVPixelBufferGetHeight(target)) / image.extent.height)
        ci.render(image.transformed(by: transform), to: target)
        let presentation = timestamp - (videoStart ?? timestamp)
        if adaptor.append(target, withPresentationTime: CMTime(seconds: presentation, preferredTimescale: 60000)) {
            movieFrames += 1
            try appendJSONLine(["capture_timestamp_s": timestamp, "presentation_timestamp_s": presentation, "frame_index": movieFrames - 1], to: directory.appendingPathComponent("video/timestamps.jsonl"))
        } else { videoFailure = video?.error?.localizedDescription ?? "Review video encoding stopped" }
    }

    private func startMotionDiagnostics() {
        guard motion.isDeviceMotionAvailable else { return }
        motion.deviceMotionUpdateInterval = 1 / 30.0
        motion.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: motionQueue) { [weak self] sample, error in
            guard let self, let sample, error == nil else { return }
            guard self.motionSlots.wait(timeout: .now()) == .success else { return }
            let times = self.lock.withLock {
                (self.timeline.relativeTimestamp(sample.timestamp), self.timeline.relativeTimestamp(ProcessInfo.processInfo.systemUptime))
            }
            // Samples preceding the first ARFrame have no capture-relative origin yet.
            guard let timestamp = times.0, let callback = times.1 else { self.motionSlots.signal(); return }
            let record: [String: Any] = ["timestamp_s": timestamp, "clock": "seconds_since_first_ARFrame", "user_acceleration_g": [sample.userAcceleration.x, sample.userAcceleration.y, sample.userAcceleration.z], "gravity_g": [sample.gravity.x, sample.gravity.y, sample.gravity.z], "rotation_rate_rad_s": [sample.rotationRate.x, sample.rotationRate.y, sample.rotationRate.z], "attitude_quaternion_xyzw": [sample.attitude.quaternion.x, sample.attitude.quaternion.y, sample.attitude.quaternion.z, sample.attitude.quaternion.w], "reference_frame": "xArbitraryZVertical", "usage": "diagnostic_only_not_pose_estimation", "callback_capture_timestamp_s": callback]
            self.workQueue.async {
                defer { self.motionSlots.signal() }
                guard !self.stats.finished, self.motionCount < 3000 else { self.motionDropped += 1; return }
                do { try self.appendJSONLine(record, to: self.directory.appendingPathComponent("motion.jsonl")); self.motionCount += 1 } catch { self.motionDropped += 1 }
            }
        }
    }

    func sessionWasInterrupted(_ session: ARSession) {
        lock.lock(); let current = segment; let elapsed = timeline.relativeTimestamp(ProcessInfo.processInfo.systemUptime); lock.unlock()
        workQueue.async { [self] in
            var event: [String: Any] = ["event": "interrupted", "segment_id": current]
            if let elapsed { event["capture_timestamp_s"] = elapsed }
            events.append(event)
            stats.guidance = "Camera interrupted. Committed frames are preserved; a resumed origin must be registered."
            onProgress?(stats)
        }
    }

    func sessionInterruptionEnded(_ session: ARSession) {
        lock.lock()
        guard active else { lock.unlock(); return }
        lock.unlock()
        beginUnregisteredSegment(reason: "new_origin_after_interruption")
        if let configuration = session.configuration { session.run(configuration, options: [.resetTracking, .removeExistingAnchors]) }
    }

    private func beginUnregisteredSegment(reason: String) {
        lock.lock(); segment = UUID().uuidString.lowercased(); let next = segment; let elapsed = timeline.relativeTimestamp(ProcessInfo.processInfo.systemUptime); lock.unlock()
        workQueue.async { [self] in
            segments.append(CaptureSegment(segmentID: next, registered: false))
            do { try writer.updateSegments(segments) } catch { failure = error.localizedDescription }
            previousKeyframePose = nil
            var event: [String: Any] = ["event": reason, "segment_id": next]
            if let elapsed { event["capture_timestamp_s"] = elapsed }
            events.append(event)
            stats.guidance = "New tracking origin: do not merge without registration. Finish and start a new scan if registration is unavailable."
            onProgress?(stats)
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        workQueue.async { [self] in failure = error.localizedDescription; stopForBudget("ARKit stopped: \(error.localizedDescription). Saved frames are preserved.") }
    }

    private func stopForBudget(_ message: String) {
        lock.withLock { active = false }
        stats.finished = true; stats.guidance = message
        motion.stopDeviceMotionUpdates()
        session.pause()
        onProgress?(stats)
    }

    func finish() async throws -> URL {
        // UI serializes finish calls; a single Task prevents repeated asset-writer finalization.
        if let finishTask { return try await finishTask.value }
        lock.withLock { active = false }
        session.pause(); motion.stopDeviceMotionUpdates()
        let task = Task { [self] () throws -> URL in
            try await withCheckedThrowingContinuation { continuation in
                workQueue.async { [self] in
                    stats.finished = true
                    videoInput?.markAsFinished()
                    let complete: () -> Void = { [self] in
                        workQueue.async {
                            do {
                                let diagnostics: [String: Any] = ["schema_version": 2, "scan_id": self.scanID, "accepted_frames": self.stats.accepted, "rejected_frames": self.stats.rejected, "backpressure_dropped_frames": self.stats.dropped, "review_frames": self.movieFrames, "review_dropped_frames": self.movieDropped, "video_complete": self.video?.status == .completed, "video_failure": self.videoFailure ?? "", "failure": self.failure ?? "", "motion_samples": self.motionCount, "motion_dropped": self.motionDropped, "pose_source": "ARKit visual-inertial world tracking; no accelerometer integration", "depth_units": "m", "depth_kind": "native_sceneDepth", "confidence_labels": ["0": "low", "1": "medium", "2": "high"], "depth_file_layout": "tightly_packed_little_endian_float32; NaN/zero/negative invalid", "raw_image_orientation": "up", "video_orientation": "raw_sensor_landscape", "direction_bins_observed": self.viewBins.count, "coverage_note": "Observed camera directions only; not a complete-surface guarantee", "events": self.events, "exposures": self.exposureRecords, "capture_limits": ["duration_s": self.limits.durationSeconds, "accepted_frames": self.limits.acceptedFrames, "bytes": self.limits.bytes], "timestamp_alignment": ["clock": "seconds_since_first_ARFrame", "arkit_first_timestamp_s": 0, "capture_elapsed_at_finish_s": self.lock.withLock { self.timeline.relativeTimestamp(ProcessInfo.processInfo.systemUptime) } ?? 0, "video_origin_capture_timestamp_s": self.videoStart ?? 0, "origin_persisted": false], "thermal_state_at_finish": ProcessInfo.processInfo.thermalState.rawValue]
                                var finalDiagnostics = diagnostics
                                finalDiagnostics["capture_complete"] = self.stats.accepted > 0
                                finalDiagnostics["max_persisted_frames_including_rejected"] = self.limits.acceptedFrames
                                try JSONSerialization.data(withJSONObject: finalDiagnostics, options: [.prettyPrinted, .sortedKeys]).write(to: self.directory.appendingPathComponent("capture_diagnostics.json"), options: .atomic)
                                let result = try self.writer.finish(complete: self.stats.accepted > 0)
                                self.stats.bytes = self.writer.bytesWritten
                                self.onProgress?(self.stats)
                                continuation.resume(returning: result)
                            } catch { continuation.resume(throwing: error) }
                        }
                    }
                    if let video, video.status == .writing { video.finishWriting(completionHandler: complete) } else { complete() }
                }
            }
        }
        finishTask = task
        return try await task.value
    }

    private func movieBytes() -> Int {
        ((try? FileManager.default.attributesOfItem(atPath: directory.appendingPathComponent("video/review.mov").path)[.size]) as? NSNumber)?.intValue ?? 0
    }

    private func appendJSONLine(_ object: [String: Any], to url: URL) throws {
        var data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]); data.append(10)
        if !FileManager.default.fileExists(atPath: url.path) { try Data().write(to: url, options: .atomic) }
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.seekToEnd(); try handle.write(contentsOf: data)
    }

    static func copyRows(_ buffer: CVPixelBuffer, bytesPerPixel: Int, expectedFormat: OSType) throws -> Data {
        guard CVPixelBufferGetPixelFormatType(buffer) == expectedFormat else { throw CaptureFailure.write("Unexpected native depth/confidence pixel format") }
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { throw CaptureFailure.write("Missing native buffer storage") }
        let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer), stride = CVPixelBufferGetBytesPerRow(buffer)
        guard stride >= width * bytesPerPixel else { throw CaptureFailure.write("Invalid native buffer stride") }
        var data = Data(count: width * height * bytesPerPixel)
        data.withUnsafeMutableBytes { dst in
            for row in 0..<height { dst.baseAddress!.advanced(by: row * width * bytesPerPixel).copyMemory(from: base.advanced(by: row * stride), byteCount: width * bytesPerPixel) }
        }
        // iOS supported architectures are little endian; this is explicitly recorded in CaptureFrame.
        return data
    }

    static func blurScore(_ buffer: CVPixelBuffer) -> Double {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard CVPixelBufferGetPlaneCount(buffer) > 0, let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) else { return 0 }
        let width = CVPixelBufferGetWidthOfPlane(buffer, 0), height = CVPixelBufferGetHeightOfPlane(buffer, 0), stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        var sum = 0.0, squared = 0.0, count = 0.0
        for y in Swift.stride(from: 3, to: height - 3, by: 8) { for x in Swift.stride(from: 3, to: width - 3, by: 8) {
            let p = base.advanced(by: y * stride + x).assumingMemoryBound(to: UInt8.self)
            let lap = Double(Int(p[-2]) + Int(p[2]) + Int(p[-2 * stride]) + Int(p[2 * stride]) - 4 * Int(p[0]))
            sum += lap; squared += lap * lap; count += 1
        } }
        guard count > 0 else { return 0 }
        return max(0, squared / count - pow(sum / count, 2))
    }

    static func validDepthFraction(_ data: Data) -> Double {
        let count = data.count / MemoryLayout<Float>.size
        guard count > 0 else { return 0 }
        return data.withUnsafeBytes { bytes in
            var valid = 0
            for index in 0..<count {
                let depth = bytes.loadUnaligned(fromByteOffset: index * 4, as: Float.self)
                if depth.isFinite && depth > 0 && depth <= 5 { valid += 1 }
            }
            return Double(valid) / Double(count)
        }
    }

    static func columnMajor(_ matrix: simd_float4x4) -> [Double] { (0..<4).flatMap { c in (0..<4).map { r in Double(matrix[c][r]) } } }
    static func columnMajor(_ matrix: simd_float3x3) -> [Double] { (0..<3).flatMap { c in (0..<3).map { r in Double(matrix[c][r]) } } }
}

private extension SIMD4 where Scalar == Float { var xyz: SIMD3<Float> { SIMD3(x, y, z) } }
