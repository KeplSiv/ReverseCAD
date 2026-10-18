import Foundation

public enum CoreError: Error, LocalizedError, Equatable {
    case invalid(String), limit(String), integrity(String), service(Int, String)
    public var errorDescription: String? {
        switch self {
        case .invalid(let s), .limit(let s), .integrity(let s): return s
        case .service(let code, let message): return "Service \(code): \(message)"
        }
    }
}

public struct CaptureQuality: Codable, Sendable, Equatable {
    public var blurScore: Double
    public var accepted: Bool
    public var reasons: [String]
    enum CodingKeys: String, CodingKey { case blurScore = "blur_score", accepted, reasons }
    public init(blurScore: Double, accepted: Bool, reasons: [String] = []) { self.blurScore = blurScore; self.accepted = accepted; self.reasons = reasons }
}

public struct CaptureFrame: Codable, Sendable, Equatable {
    public var schemaVersion: Int
    public var sensorObservation: JSONValue? = nil
    public var scanID: String
    public var segmentID: String
    public var frameID: String
    public var timestampS: Double
    public var rgbPath: String
    public var rgbWidth: Int
    public var rgbHeight: Int
    public var orientation: String
    public var depthPath: String?
    public var depthWidth: Int
    public var depthHeight: Int
    public var depthRowBytes: Int
    public var depthByteOrder: String
    /// Missing on v1 synthetic fixtures: defaults semantically to pixel_center. Native ARKit uses direct scaling.
    public var depthCalibrationMode: String? = nil
    public var confidencePath: String?
    public var maskPath: String?
    /// User's visible guide box in normalized raw-image coordinates: x, y, width, height.
    public var captureRegion: [Double]? = nil
    /// Clockwise display rotation only. RGB/depth/intrinsics stay raw and calibrated.
    public var displayRotationCW: Int? = nil
    public var intrinsics: [Double]
    public var intrinsicsWidth: Int
    public var intrinsicsHeight: Int
    public var worldCamera: [Double]
    public var trackingState: String
    public var quality: CaptureQuality
    enum CodingKeys: String, CodingKey {
        case sensorObservation = "sensor_observation"
        case schemaVersion = "schema_version", scanID = "scan_id", segmentID = "segment_id", frameID = "frame_id", timestampS = "timestamp_s"
        case rgbPath = "rgb_path", rgbWidth = "rgb_width", rgbHeight = "rgb_height", orientation
        case depthPath = "depth_path", depthWidth = "depth_width", depthHeight = "depth_height", depthRowBytes = "depth_row_bytes", depthByteOrder = "depth_byte_order", confidencePath = "confidence_path", maskPath = "mask_path"
        case intrinsics, intrinsicsWidth = "intrinsics_width", intrinsicsHeight = "intrinsics_height", worldCamera = "T_world_camera", trackingState = "tracking_state", quality
        case depthCalibrationMode = "depth_calibration_mode"
        case captureRegion = "capture_region"
        case displayRotationCW = "display_rotation_cw_deg"
    }
    public init(schemaVersion: Int = 1, scanID: String, segmentID: String, frameID: String, timestampS: Double, rgbPath: String, rgbWidth: Int, rgbHeight: Int, orientation: String = "up", depthPath: String? = nil, depthWidth: Int = 0, depthHeight: Int = 0, depthRowBytes: Int = 0, depthByteOrder: String = "little", confidencePath: String? = nil, maskPath: String? = nil, intrinsics: [Double], intrinsicsWidth: Int, intrinsicsHeight: Int, worldCamera: [Double], trackingState: String, quality: CaptureQuality) {
        self.schemaVersion = schemaVersion; self.scanID = scanID; self.segmentID = segmentID; self.frameID = frameID; self.timestampS = timestampS; self.rgbPath = rgbPath; self.rgbWidth = rgbWidth; self.rgbHeight = rgbHeight; self.orientation = orientation; self.depthPath = depthPath; self.depthWidth = depthWidth; self.depthHeight = depthHeight; self.depthRowBytes = depthRowBytes; self.depthByteOrder = depthByteOrder; self.confidencePath = confidencePath; self.maskPath = maskPath; self.intrinsics = intrinsics; self.intrinsicsWidth = intrinsicsWidth; self.intrinsicsHeight = intrinsicsHeight; self.worldCamera = worldCamera; self.trackingState = trackingState; self.quality = quality
    }
    public func validate() throws {
        if let displayRotationCW, ![0,90,180,270].contains(displayRotationCW) {
            throw CoreError.invalid("Invalid display rotation")
        }
        if let r = captureRegion {
            guard r.count == 4, r.allSatisfy(\.isFinite), r[0] >= 0, r[1] >= 0,
                  r[2] > 0, r[3] > 0, r[0]+r[2] <= 1.000001, r[1]+r[3] <= 1.000001 else {
                throw CoreError.invalid("Capture guide region is invalid.")
            }
        }
        guard schemaVersion == 1, !scanID.isEmpty, !segmentID.isEmpty, !frameID.isEmpty else { throw CoreError.invalid("Capture identifiers or schema version are invalid.") }
        guard timestampS.isFinite, timestampS >= 0, quality.blurScore.isFinite else { throw CoreError.invalid("Capture time and quality must be finite.") }
        guard (1...16384).contains(rgbWidth), (1...16384).contains(rgbHeight), (1...16384).contains(intrinsicsWidth), (1...16384).contains(intrinsicsHeight) else { throw CoreError.invalid("RGB/calibration dimensions are invalid.") }
        guard orientation == "up" else { throw CoreError.invalid("Calibration requires raw up-oriented pixels; display rotations must be converted explicitly.") }
        guard ["pixel_center", "native_arkit"].contains(depthCalibrationMode ?? "pixel_center") else { throw CoreError.invalid("Unknown depth calibration mapping mode.") }
        guard intrinsics.count == 9, intrinsics.allSatisfy(\.isFinite), intrinsics[0] > 0, intrinsics[4] > 0, abs(intrinsics[8] - 1) < 1e-8 else { throw CoreError.invalid("Camera intrinsics are invalid.") }
        try Geometry.validateRigidTransform(worldCamera)
        guard ["normal", "limited", "unavailable"].contains(trackingState) else { throw CoreError.invalid("Unknown tracking state.") }
        _ = try CaptureIO.validatedRelativePath(rgbPath)
        if let depthPath {
            _ = try CaptureIO.validatedRelativePath(depthPath)
            guard (1...8192).contains(depthWidth), (1...8192).contains(depthHeight), depthRowBytes >= depthWidth * 4, depthRowBytes <= depthWidth * 4 + 65536, depthRowBytes % 4 == 0, depthByteOrder == "little" else { throw CoreError.invalid("Depth dimensions, stride, or byte order are invalid.") }
        } else if depthWidth != 0 || depthHeight != 0 || depthRowBytes != 0 || confidencePath != nil || maskPath != nil { throw CoreError.invalid("Missing depth must have zero dimensions and no confidence or depth mask.") }
        for path in [confidencePath, maskPath].compactMap({ $0 }) { _ = try CaptureIO.validatedRelativePath(path) }
        if let sensor = sensorObservation {
            guard let time = sensor["source_timestamp_s"]?.double, time.isFinite,
                  sensor["clock"]?.string == "host_monotonic_seconds" else {
                throw CoreError.invalid("Sparse image source time or clock is invalid.")
            }
            if let arrival = sensor["arrival_timestamp_s"], arrival != .null {
                guard let value = arrival.double, value.isFinite else { throw CoreError.invalid("Invalid image arrival time.") }
            }
            if let originals = sensor["original_plane_paths"] {
                guard let paths = originals.array, paths.count == 2, paths.allSatisfy({ $0.string != nil }),
                      sensor["pixel_sha256"]?.array?.count == 2 else { throw CoreError.invalid("Original NV12 image requires two planes and hashes.") }
                for path in paths { try CaptureIO.validatedRelativePath(path.string!) }
            }
        }
        guard Set(assetPaths).count == assetPaths.count else { throw CoreError.invalid("Frame asset paths must be distinct.") }
    }
    public var originalPlanePaths: [String] { sensorObservation?["original_plane_paths"]?.array?.compactMap(\.string) ?? [] }
    public var assetPaths: [String] { [rgbPath, depthPath, confidencePath, maskPath].compactMap { $0 } + originalPlanePaths }
}

public struct CaptureSegment: Codable, Sendable, Equatable {
    public var segmentID: String
    public var objectWorld: [Double]
    public var registered: Bool
    enum CodingKeys: String, CodingKey { case segmentID = "segment_id", objectWorld = "T_object_world", registered }
    public init(segmentID: String, objectWorld: [Double] = Geometry.identity, registered: Bool = true) { self.segmentID = segmentID; self.objectWorld = objectWorld; self.registered = registered }
}

public struct CaptureManifest: Codable, Sendable, Equatable {
    public var sparseCapture: JSONValue? = nil
    public var schemaVersion: Int
    public var scanID: String
    public var source: String
    public var device: String
    public var createdAt: String
    public var complete: Bool
    public var segments: [CaptureSegment]
    public var frameCount: Int
    enum CodingKeys: String, CodingKey { case sparseCapture = "sparse_capture"; case schemaVersion = "schema_version", scanID = "scan_id", source, device, createdAt = "created_at", complete, segments, frameCount = "frame_count" }
    public init(schemaVersion: Int = 1, scanID: String, source: String, device: String, createdAt: String = ISO8601DateFormatter().string(from: Date()), complete: Bool = false, segments: [CaptureSegment], frameCount: Int = 0) { self.schemaVersion = schemaVersion; self.scanID = scanID; self.source = source; self.device = device; self.createdAt = createdAt; self.complete = complete; self.segments = segments; self.frameCount = frameCount }
    public func validate() throws {
        if let ext = sparseCapture {
            guard ext["schema_version"] == .number(1), ext["mode"] == .string("sparse_range_rgb"),
                  ["capturing", "available", "unavailable"].contains(ext["status"]?.string ?? "") else { throw CoreError.invalid("Unsupported sparse capture extension.") }
            for key in ["packet_path", "event_path", "calibration_path"] {
                guard let path = ext[key]?.string else { throw CoreError.invalid("Missing sparse capture asset.") }
                try CaptureIO.validatedRelativePath(path)
            }
        }
        guard schemaVersion == 1, !scanID.isEmpty, ["synthetic", "arkit", "camera_manual"].contains(source), frameCount >= 0, frameCount <= 10000 else { throw CoreError.invalid("Invalid capture manifest.") }
        guard !segments.isEmpty, Set(segments.map(\.segmentID)).count == segments.count else { throw CoreError.invalid("Segment identifiers must be present and unique.") }
        for segment in segments { try Geometry.validateRigidTransform(segment.objectWorld) }
    }
}
