import Foundation

/// A reference-only revision never implies that rear-camera corrections were fitted.
public struct PhoneCalibrationProfile: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let revision: UUID
    public let createdAt: Date
    public let referenceArchiveSHA256: String
    public let status: String
    public let rearCalibration: String
    public let coordinateConvention: String
    public let frontToRearTransform: [Double]?

    public init(referenceArchiveSHA256: String) throws {
        guard referenceArchiveSHA256.count == 64,
              referenceArchiveSHA256.allSatisfy({ $0.isHexDigit && !$0.isUppercase }) else {
            throw CoreError.invalid("Reference archive must have a SHA-256 digest.")
        }
        self.schemaVersion = 1; self.revision = UUID(); self.createdAt = Date()
        self.referenceArchiveSHA256 = referenceArchiveSHA256
        self.status = "provisional_reference_only"
        self.rearCalibration = "factory_per_frame; no fitted corrections"
        self.coordinateConvention = "front optical x right y down z forward in metres; rear ARKit transform recorded per frame"
        self.frontToRearTransform = nil
    }

    /// Write each revision once; current.json is the only mutable pointer.
    public func save(directory: URL) throws {
        try FileManager.default.createDirectory(at:directory, withIntermediateDirectories:true)
        let revisionFile = directory.appendingPathComponent(revision.uuidString + ".json")
        guard !FileManager.default.fileExists(atPath:revisionFile.path) else {
            throw CoreError.integrity("Calibration revision already exists.")
        }
        try CaptureIO.atomicWrite(self, to:revisionFile)
        try CaptureIO.atomicWrite(self, to:directory.appendingPathComponent("current.json"))
    }
}
