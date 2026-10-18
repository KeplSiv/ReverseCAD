import XCTest
import CoreVideo
import CryptoKit
@testable import ReverseCAD

final class ReferenceCaptureWriterTests: XCTestCase {
    func testOriginalBufferBytesAndArchiveArePreserved() throws {
        let writer = try ExperimentWriter(source: "synthetic public-reference test")
        defer {
            try? FileManager.default.removeItem(at: writer.url)
            try? FileManager.default.removeItem(at: writer.url.appendingPathExtension("zip"))
        }
        var optional: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, 4, 3, kCVPixelFormatType_32BGRA, nil, &optional), kCVReturnSuccess)
        let buffer = try XCTUnwrap(optional)
        CVPixelBufferLockBaseAddress(buffer, [])
        let byteCount = CVPixelBufferGetBytesPerRow(buffer) * CVPixelBufferGetHeight(buffer)
        let bytes = try XCTUnwrap(CVPixelBufferGetBaseAddress(buffer)).assumingMemoryBound(to: UInt8.self)
        for offset in 0..<byteCount { bytes[offset] = UInt8(offset % 251) }
        let expected = Data(bytes: bytes, count: byteCount)
        CVPixelBufferUnlockBaseAddress(buffer, [])
        let metadata = try writer.original(buffer, stem: "frames/source")
        let planes = try XCTUnwrap(metadata["planes"] as? [[String: Any]])
        let file = try XCTUnwrap(planes.first?["file"] as? String)
        XCTAssertEqual(try Data(contentsOf: writer.url.appendingPathComponent(file)), expected)
        let derived = writer.url.appendingPathComponent("derived")
        try FileManager.default.createDirectory(at: derived, withIntermediateDirectories: true)
        try Data("inspection-only".utf8).write(to: derived.appendingPathComponent("preview.txt"))
        try writer.checkpoint(["synthetic": true], complete: true)
        let archive = try writer.archive(), firstBytes = try Data(contentsOf: archive)
        XCTAssertFalse(firstBytes.isEmpty)
        XCTAssertEqual(try writer.archive(), archive)
        XCTAssertEqual(try Data(contentsOf: archive), firstBytes)
        XCTAssertEqual(try Data(contentsOf: writer.url.appendingPathComponent(file)), expected)
    }
    func testUnavailableMetadataDoesNotCrashCheckpoint() throws {
        let writer = try ExperimentWriter(source: "synthetic public-reference test")
        defer { try? FileManager.default.removeItem(at: writer.url) }
        writer.event("invalid_timestamp", ["offset_s": Double.nan])
        try writer.checkpoint(["unavailable": Double.infinity])
        let capabilities = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: writer.url.appendingPathComponent("capabilities.json"))) as? [String: Any])
        XCTAssertTrue(capabilities["unavailable"] is NSNull)
        let session = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: writer.url.appendingPathComponent("session.json"))) as? [String: Any])
        XCTAssertEqual(session["complete"] as? Bool, false)
    }
}
