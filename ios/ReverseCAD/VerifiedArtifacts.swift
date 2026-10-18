import Foundation
import ReverseCADCore

/// A checksum proves file integrity, not that a result belongs to this capture.
enum ReconstructionIdentity {
    static func matches(_ result: [String: Any], scanID: String?) -> Bool {
        let reconstruction = result["reconstruction"] as? [String: Any] ?? result
        guard let scanID, !scanID.isEmpty else { return false }
        return reconstruction["scan_id"] as? String == scanID
    }
}

enum ExteriorPrintFiles {
    /// A declared multi-piece export must be complete; never silently share a subset.
    static func names(report: [String: Any]?, available: Set<String>) throws -> [String] {
        let closure = report?["closure"] as? [String: Any]
        let declared = closure?["files"] as? [String] ?? ["printable_edge.stl", "printable_edge.3mf"]
        guard !declared.isEmpty, Set(declared).count == declared.count,
              declared.allSatisfy({ available.contains($0) && ($0.hasSuffix(".stl") || $0.hasSuffix(".3mf") || $0.hasSuffix(".step")) }),
              declared.contains("printable_edge.stl") else {
            throw CoreError.integrity("Some replacement pieces are missing. Reprocess this saved scan before exporting.")
        }
        return declared + ["printable_edge.json", "counterpart.json"].filter { available.contains($0) }
    }
}

/// Publishes complete, checksum-verified artifact revisions. A failed or cancelled
/// download never changes a previously published revision or exposes a partial one.
enum VerifiedArtifactStore {
    private static let manifestName = ".verified-artifacts.json"
    private static let maximumArtifacts = 128
    private static let maximumRevisionBytes = 1_024 * 1_024 * 1_024

    private struct Entry: Codable, Equatable {
        let id: String
        let name: String
        let sha256: String
        let size: Int
    }

    private struct Manifest: Codable {
        let version: Int
        let revisionKey: String
        let artifacts: [Entry]
    }

    static func download(infos: [ArtifactInfo], baseDirectory: URL, revisionKey: String,
                         client: ServiceClient) async throws -> URL {
        let entries = try validatedEntries(infos)
        try validateComponent(revisionKey, label: "Revision identifier")
        guard baseDirectory.isFileURL else { throw CoreError.invalid("Artifact storage must be a local directory.") }
        let manager = FileManager.default
        try manager.createDirectory(at: baseDirectory, withIntermediateDirectories: true)
        try requireDirectory(baseDirectory)
        let published = baseDirectory.appendingPathComponent(revisionKey, isDirectory: true)
        if exists(published) {
            try verify(infos: infos, directory: published)
            let manifest = try readManifest(published)
            guard manifest.revisionKey == revisionKey else { throw CoreError.integrity("Stored revision identity does not match this repair.") }
            return published
        }

        let stage = baseDirectory.appendingPathComponent(".receiving-" + UUID().uuidString, isDirectory: true)
        try manager.createDirectory(at: stage, withIntermediateDirectories: false)
        defer { try? manager.removeItem(at: stage) }
        for entry in entries {
            try Task.checkCancellation()
            let file = stage.appendingPathComponent(entry.name)
            _ = try await client.downloadArtifact(id: entry.id, to: file, expectedSHA256: entry.sha256)
            try verifyFile(entry, directory: stage)
        }
        try Task.checkCancellation()
        let manifest = Manifest(version: 1, revisionKey: revisionKey, artifacts: entries)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(manifest).write(to: stage.appendingPathComponent(manifestName), options: .atomic)
        try verify(infos: infos, directory: stage)
        try Task.checkCancellation()
        do {
            // Same-parent rename publishes the entire verified set atomically. No replacement.
            try manager.moveItem(at: stage, to: published)
        } catch {
            // A concurrent request may have published this exact revision while we downloaded.
            // Reuse it only after checking the whole manifest and every byte.
            guard exists(published) else { throw error }
            try verify(infos: infos, directory: published)
            guard try readManifest(published).revisionKey == revisionKey else {
                throw CoreError.integrity("A different repair already occupies this revision directory.")
            }
        }
        try verify(infos: infos, directory: published)
        return published
    }

    /// Invoke again immediately before native export, including after app restart.
    /// Presence alone is not verification: missing, changed, extra, or linked files fail closed.
    static func verify(infos: [ArtifactInfo], directory: URL) throws {
        let expected = try validatedEntries(infos)
        try requireDirectory(directory)
        let manifest = try readManifest(directory)
        guard manifest.version == 1, manifest.artifacts == expected else {
            throw CoreError.integrity("The stored artifact set does not match the requested repair revision. Download this revision again.")
        }
        try validateComponent(manifest.revisionKey, label: "Stored revision identifier")
        let contents = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        let expectedNames = Set(expected.map(\.name) + [manifestName])
        guard Set(contents.map(\.lastPathComponent)) == expectedNames else {
            throw CoreError.integrity("The repair revision contains missing or unexpected files. Export is blocked.")
        }
        for entry in expected { try verifyFile(entry, directory: directory) }
    }

    private static func validatedEntries(_ infos: [ArtifactInfo]) throws -> [Entry] {
        guard !infos.isEmpty, infos.count <= maximumArtifacts else {
            throw CoreError.limit("A repair revision must contain between 1 and 128 artifacts.")
        }
        var names = Set<String>(), ids = Set<String>(), total = 0
        for info in infos {
            try validateComponent(info.name, label: "Artifact filename")
            try validateComponent(info.id, label: "Artifact identifier")
            guard names.insert(info.name.lowercased()).inserted, ids.insert(info.id).inserted else {
                throw CoreError.integrity("The service returned duplicate artifact names or identifiers.")
            }
            guard info.sha256.count == 64,
                  info.sha256.unicodeScalars.allSatisfy({ (48...57).contains($0.value) || (97...102).contains($0.value) }) else {
                throw CoreError.integrity("Artifact checksum must be a lowercase SHA-256 digest.")
            }
            guard info.size >= 0, info.size <= CaptureIO.maximumPackageBytes,
                  info.size <= maximumRevisionBytes - total else {
                throw CoreError.limit("Artifact or revision exceeds the local download size limit.")
            }
            total += info.size
        }
        return infos.map { Entry(id: $0.id, name: $0.name, sha256: $0.sha256, size: $0.size) }
            .sorted { $0.name < $1.name }
    }

    private static func validateComponent(_ value: String, label: String) throws {
        guard !value.isEmpty, value.utf8.count <= 200, !value.hasPrefix("."),
              value.unicodeScalars.allSatisfy({ scalar in
                  (48...57).contains(scalar.value) || (65...90).contains(scalar.value) ||
                  (97...122).contains(scalar.value) || [45, 46, 95].contains(scalar.value)
              }) else {
            throw CoreError.invalid("\(label) contains unsafe path characters.")
        }
    }

    private static func exists(_ url: URL) -> Bool {
        // attributesOfItem also notices a dangling symbolic link; fileExists does not.
        (try? FileManager.default.attributesOfItem(atPath: url.path)) != nil
    }

    private static func requireDirectory(_ directory: URL) throws {
        guard directory.isFileURL else { throw CoreError.invalid("Artifact storage must be a local directory.") }
        let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        guard attributes[.type] as? FileAttributeType == .typeDirectory else {
            throw CoreError.integrity("Artifact revision must be a directory, not a symbolic link or other file.")
        }
    }

    private static func readManifest(_ directory: URL) throws -> Manifest {
        let url = directory.appendingPathComponent(manifestName)
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber, size.intValue <= 256 * 1_024 else {
            throw CoreError.integrity("Verified revision manifest is invalid.")
        }
        return try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: url))
    }

    private static func verifyFile(_ entry: Entry, directory: URL) throws {
        let file = directory.appendingPathComponent(entry.name)
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber, size.intValue == entry.size else {
            throw CoreError.integrity("\(entry.name) is missing, linked, or has the wrong byte count. Export is blocked.")
        }
        guard try CaptureIO.sha256(file: file) == entry.sha256 else {
            throw CoreError.integrity("\(entry.name) failed its revision checksum. Export is blocked.")
        }
    }
}
