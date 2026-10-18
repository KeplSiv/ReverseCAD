import Foundation
import CryptoKit

public enum CaptureIO {
    public static let maximumPackageBytes = 512 * 1024 * 1024
    public static func encoder() -> JSONEncoder { let e = JSONEncoder(); e.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]; return e }
    @discardableResult public static func validatedRelativePath(_ path: String) throws -> String {
        guard !path.isEmpty, path.utf8.count <= 1024, !path.hasPrefix("/"), !path.contains("\\"), !path.contains(":"), !path.contains("\0"), path.split(separator: "/", omittingEmptySubsequences: false).allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else { throw CoreError.invalid("Unsafe scan-package path.") }
        return path
    }
    public static func safeURL(directory: URL, path: String) throws -> URL {
        try validatedRelativePath(path)
        let root = directory.standardizedFileURL.resolvingSymlinksInPath()
        let file = root.appendingPathComponent(path).standardizedFileURL
        guard file.resolvingSymlinksInPath().path.hasPrefix(root.path + "/") else { throw CoreError.invalid("Scan-package path escapes its directory.") }
        var part = root
        for component in path.split(separator: "/") {
            part.appendPathComponent(String(component))
            let values = try? part.resourceValues(forKeys: [.isSymbolicLinkKey])
            guard values?.isSymbolicLink != true else { throw CoreError.invalid("Symbolic links are not permitted in scan packages.") }
        }
        return file
    }
    public static func sha256(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    public static func sha256(file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file); defer { try? handle.close() }
        var hash = SHA256()
        while let chunk = try handle.read(upToCount: 1024*1024), !chunk.isEmpty { hash.update(data: chunk) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
    public static func readFrames(directory: URL) throws -> [CaptureFrame] {
        let url = try safeURL(directory: directory, path: "frames.jsonl")
        let size = (try url.resourceValues(forKeys: [.fileSizeKey])).fileSize ?? 0
        guard size <= 32*1024*1024 else { throw CoreError.limit("Frame metadata exceeds 32 MiB.") }
        let data = try Data(contentsOf: url)
        var frames: [CaptureFrame] = []
        for line in data.split(separator: 10) {
            let frame = try JSONDecoder().decode(CaptureFrame.self, from: Data(line)); try frame.validate()
            guard frames.count < 10000 else { throw CoreError.limit("Too many capture frames.") }
            frames.append(frame)
        }
        guard Set(frames.map(\.frameID)).count == frames.count else { throw CoreError.invalid("Duplicate capture frame identifiers.") }
        for pair in zip(frames, frames.dropFirst()) { guard pair.1.timestampS > pair.0.timestampS else { throw CoreError.invalid("Capture timestamps must increase monotonically.") } }
        return frames
    }
    public static func files(directory: URL, limit: Int = maximumPackageBytes) throws -> [(path: String, url: URL, size: Int)] {
        let root = directory.standardizedFileURL.resolvingSymlinksInPath()
        guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isSymbolicLinkKey, .isRegularFileKey, .isDirectoryKey, .fileSizeKey], options: []) else { throw CoreError.invalid("Unable to read scan package.") }
        var result: [(String,URL,Int)] = []; var bytes = 0
        while let url = enumerator.nextObject() as? URL {
            let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .isDirectoryKey, .fileSizeKey])
            guard values.isSymbolicLink != true else { throw CoreError.invalid("Symbolic links are not permitted in scan packages.") }
            if values.isDirectory == true { continue }
            guard values.isRegularFile == true, result.count < 50000 else { throw CoreError.limit("Scan package contains unsupported or too many files.") }
            let resolved = url.standardizedFileURL.resolvingSymlinksInPath()
            guard resolved.path.hasPrefix(root.path + "/") else { throw CoreError.invalid("Scan package file escapes its root.") }
            let path = String(resolved.path.dropFirst(root.path.count+1)); _ = try safeURL(directory: root, path: path)
            let size = values.fileSize ?? 0; bytes += size
            guard bytes <= limit else { throw CoreError.limit("Scan package exceeds its \(limit) byte budget.") }
            result.append((path,url,size))
        }
        return result.sorted { $0.0 < $1.0 }
    }
    public static func atomicWrite<T: Encodable>(_ value: T, to url: URL) throws { try encoder().encode(value).write(to: url, options: .atomic) }
    /// Import a bounded directory package. Platform archive extraction must reject traversal before calling this.
    public static func importPackage(from source: URL, to destination: URL) throws -> CaptureManifest {
        let manifest = try ScanPackageWriter.validate(directory: source, allowIncomplete: true)
        guard !FileManager.default.fileExists(atPath: destination.path) else { throw CoreError.invalid("Import destination already exists.") }
        let stage = destination.deletingLastPathComponent().appendingPathComponent(".import-"+UUID().uuidString)
        try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
        do {
            for file in try files(directory: source) {
                let target = try safeURL(directory: stage, path: file.path)
                try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                try FileManager.default.copyItem(at: file.url, to: target)
            }
            _ = try ScanPackageWriter.validate(directory: stage, allowIncomplete: true)
            try FileManager.default.moveItem(at: stage, to: destination)
        } catch { try? FileManager.default.removeItem(at: stage); throw error }
        return manifest
    }
}

/// Call from one serial capture queue. Each frame is an atomic metadata commit after its assets.
public final class ScanPackageWriter: @unchecked Sendable {
    public let directory: URL
    public private(set) var manifest: CaptureManifest
    public private(set) var bytesWritten: Int = 0
    public var frameCount: Int { frames.count }
    public let maxBytes: Int
    private var frames: [CaptureFrame] = []
    private var closed = false
    private var checksums: [String:String] = [:]
    public init(directory: URL, manifest: CaptureManifest, maxBytes: Int = CaptureIO.maximumPackageBytes) throws {
        try manifest.validate()
        guard maxBytes > 0, maxBytes <= CaptureIO.maximumPackageBytes else { throw CoreError.invalid("Capture budget must be within 512 MiB.") }
        self.directory = directory; self.manifest = manifest; self.maxBytes = maxBytes
        guard !FileManager.default.fileExists(atPath: directory.appendingPathComponent("manifest.json").path) else { throw CoreError.invalid("Capture already exists; use recovery to preserve frames.") }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        self.manifest.complete = false; self.manifest.frameCount = 0
        try Data().write(to: directory.appendingPathComponent("frames.jsonl"), options: .atomic)
        try checkpoint()
    }
    private init(directory: URL, manifest: CaptureManifest, frames: [CaptureFrame], maxBytes: Int) { self.directory = directory; self.manifest = manifest; self.frames = frames; self.maxBytes = maxBytes }
    public func updateSparseCapture(_ extensionValue: JSONValue) throws {
        guard !closed else { throw CoreError.invalid("Capture is closed") }
        var next = manifest; next.sparseCapture = extensionValue; try next.validate()
        manifest = next; try checkpoint()
    }
    public func updateSegments(_ segments: [CaptureSegment]) throws {
        var next = manifest; next.segments = segments; try next.validate()
        guard Set(frames.map(\.segmentID)).isSubset(of: Set(segments.map(\.segmentID))) else { throw CoreError.invalid("Cannot remove a segment referenced by committed frames.") }
        manifest = next; try checkpoint()
    }
    public func append(frame: CaptureFrame, assets: [String:Data]) throws {
        guard !closed, frames.count < 10000 else { throw CoreError.limit("Capture is closed or has reached its frame limit.") }
        try frame.validate()
        guard frame.scanID == manifest.scanID, manifest.segments.contains(where: { $0.segmentID == frame.segmentID }), !frames.contains(where: { $0.frameID == frame.frameID }), frame.timestampS > (frames.last?.timestampS ?? -.infinity) else { throw CoreError.invalid("Frame identifiers, segment, or timestamp do not match this capture.") }
        guard Set(assets.keys) == Set(frame.assetPaths) else { throw CoreError.invalid("Frame assets must exactly match its calibrated paths.") }
        try Self.validateAssetLengths(frame: frame) { path in assets[path]?.count }
        let newBytes = assets.values.reduce(0) { $0 + $1.count }
        guard bytesWritten+newBytes+65536 <= maxBytes else { throw CoreError.limit("Capture storage budget reached. Committed frames are preserved.") }
        for path in frame.assetPaths {
            let url = try CaptureIO.safeURL(directory: directory, path: path)
            guard !FileManager.default.fileExists(atPath: url.path), !["manifest.json","frames.jsonl","checksums.json"].contains(path) else { throw CoreError.invalid("Frame asset would overwrite existing scan data.") }
        }
        for (path,data) in assets {
            let url = try CaptureIO.safeURL(directory: directory, path: path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            checksums[path] = CaptureIO.sha256(data)
        }
        var nextFrames = frames; nextFrames.append(frame)
        var jsonl = Data()
        for item in nextFrames { jsonl.append(try CaptureIO.encoder().encode(item)); jsonl.append(10) }
        try jsonl.write(to: directory.appendingPathComponent("frames.jsonl"), options: .atomic)
        frames = nextFrames; manifest.frameCount = frames.count
        try checkpoint()
    }
    public func finalizeAsset(path: String) throws {
        guard !closed, !["manifest.json","frames.jsonl","checksums.json"].contains(path) else { throw CoreError.invalid("Cannot change capture metadata through an asset path.") }
        let url = try CaptureIO.safeURL(directory: directory, path: path)
        checksums[path] = try CaptureIO.sha256(file: url)
        try checkpoint()
    }
    @discardableResult public func finish(complete: Bool = true) throws -> URL {
        manifest.complete = complete; manifest.frameCount = frames.count
        try checkpoint(full: true)
        _ = try Self.validate(directory: directory, allowIncomplete: !complete)
        closed = true; return directory
    }
    private func checkpoint(full: Bool = false) throws {
        try CaptureIO.atomicWrite(manifest, to: directory.appendingPathComponent("manifest.json"))
        let files = try CaptureIO.files(directory: directory, limit: maxBytes)
        // Immutable frame assets were hashed on write. Do not rehash all prior JPEGs or a growing movie per frame.
        // Mutable review/motion assets join the manifest at finalization or recovery.
        var current: [String:String] = full ? [:] : checksums
        for file in files where file.path != "checksums.json" {
            if full || file.path == "manifest.json" || file.path == "frames.jsonl" { current[file.path] = try CaptureIO.sha256(file: file.url) }
        }
        try CaptureIO.atomicWrite(current, to: directory.appendingPathComponent("checksums.json"))
        checksums = current
        bytesWritten = try CaptureIO.files(directory: directory, limit: maxBytes).reduce(0) { $0+$1.size }
    }
    public static func recover(directory: URL, maxBytes: Int = CaptureIO.maximumPackageBytes) throws -> ScanPackageWriter {
        _ = try CaptureIO.files(directory: directory, limit: maxBytes)
        let manifestURL = try CaptureIO.safeURL(directory: directory, path: "manifest.json")
        var manifest = try JSONDecoder().decode(CaptureManifest.self, from: Data(contentsOf: manifestURL)); try manifest.validate()
        let frames = try CaptureIO.readFrames(directory: directory)
        let oldHashes = try? JSONDecoder().decode([String:String].self, from: Data(contentsOf: CaptureIO.safeURL(directory: directory, path: "checksums.json")))
        for frame in frames {
            guard frame.scanID == manifest.scanID, manifest.segments.contains(where: { $0.segmentID == frame.segmentID }) else { throw CoreError.integrity("Recovered frame references an unknown scan or segment.") }
            try validateAssetLengths(frame: frame) { path in try? CaptureIO.safeURL(directory: directory, path: path).resourceValues(forKeys: [.fileSizeKey]).fileSize }
            for path in frame.assetPaths {
                let hash = try CaptureIO.sha256(file: CaptureIO.safeURL(directory: directory, path: path))
                if let old = oldHashes?[path], hash != old { throw CoreError.integrity("Recovered capture asset checksum failed: \(path)") }
            }
        }
        manifest.complete = false; manifest.frameCount = frames.count
        let writer = ScanPackageWriter(directory: directory, manifest: manifest, frames: frames, maxBytes: maxBytes)
        try writer.checkpoint(full: true); return writer
    }
    @discardableResult public static func validate(directory: URL, allowIncomplete: Bool = false) throws -> CaptureManifest {
        let files = try CaptureIO.files(directory: directory)
        let hashesURL = try CaptureIO.safeURL(directory: directory, path: "checksums.json")
        guard (try hashesURL.resourceValues(forKeys: [.fileSizeKey])).fileSize ?? 0 <= 8*1024*1024 else { throw CoreError.limit("Checksum metadata is too large.") }
        let hashes = try JSONDecoder().decode([String:String].self, from: Data(contentsOf: hashesURL))
        guard Set(hashes.keys) == Set(files.filter { $0.path != "checksums.json" }.map(\.path)) else { throw CoreError.integrity("Scan checksum manifest must cover every asset exactly once.") }
        for file in files where file.path != "checksums.json" {
            guard hashes[file.path] == (try CaptureIO.sha256(file: file.url)) else { throw CoreError.integrity("Scan checksum failed: \(file.path)") }
        }
        let manifest = try JSONDecoder().decode(CaptureManifest.self, from: Data(contentsOf: CaptureIO.safeURL(directory: directory, path: "manifest.json")))
        try manifest.validate()
        guard allowIncomplete || manifest.complete else { throw CoreError.invalid("Scan is incomplete; recover or explicitly review it before processing.") }
        if let ext = manifest.sparseCapture {
            for key in ["packet_path", "event_path", "calibration_path"] {
                guard let path = ext[key]?.string, hashes[path] != nil else { throw CoreError.integrity("Missing checksummed sparse capture asset.") }
            }
        }
        let frames = try CaptureIO.readFrames(directory: directory)
        guard frames.count == manifest.frameCount else { throw CoreError.integrity("Manifest frame count does not match committed frames.") }
        for frame in frames {
            guard frame.scanID == manifest.scanID, manifest.segments.contains(where: { $0.segmentID == frame.segmentID }) else { throw CoreError.invalid("Frame references an unknown scan or segment.") }
            try validateAssetLengths(frame: frame) { path in files.first { $0.path == path }?.size }
        }
        return manifest
    }
    private static func validateAssetLengths(frame: CaptureFrame, size: (String)->Int?) throws {
        guard let rgbSize = size(frame.rgbPath), rgbSize > 0 else { throw CoreError.integrity("Missing RGB keyframe.") }
        if let path = frame.depthPath, size(path) != frame.depthRowBytes * frame.depthHeight { throw CoreError.integrity("Depth file size does not match calibrated dimensions and stride.") }
        for path in [frame.confidencePath,frame.maskPath].compactMap({$0}) { guard size(path) == frame.depthWidth * frame.depthHeight else { throw CoreError.integrity("Confidence/mask dimensions do not match native depth.") } }
        for path in frame.additionalAssets ?? [] {
            guard let count=size(path),count>0 else {throw CoreError.integrity("Missing original sensor asset.")}
        }
        for (index, path) in frame.originalPlanePaths.enumerated() {
            guard size(path) == frame.rgbWidth * frame.rgbHeight / (index == 0 ? 1 : 2) else {
                throw CoreError.integrity("Original NV12 plane size does not match image dimensions.")
            }
        }
    }
}

public enum JobState: String, Codable, Sendable, CaseIterable {
    case queued, validatingInput = "validating_input", reconstructing, needsInput = "needs_input", planning, generatingCAD = "generating_cad", validatingCAD = "validating_cad", complete, cancelled, failed
    public var isTerminal: Bool { [.complete,.cancelled,.failed,.needsInput].contains(self) }
}

/// A small durable journal permits polling/resuming after process or network loss.
public struct ProcessingCheckpoint: Codable, Sendable, Equatable {
    public var projectID: String
    public var scanID: String?
    public var jobID: String?
    public var repairID: String?
    public var revision: Int?
    public var state: JobState
    public init(projectID: String, scanID: String? = nil, jobID: String? = nil, repairID: String? = nil, revision: Int? = nil, state: JobState = .queued) { self.projectID=projectID; self.scanID=scanID; self.jobID=jobID; self.repairID=repairID; self.revision=revision; self.state=state }
    public func save(to url: URL) throws { try CaptureIO.atomicWrite(self, to: url) }
    public static func load(from url: URL) throws -> Self { try JSONDecoder().decode(Self.self, from: Data(contentsOf: url)) }
}
