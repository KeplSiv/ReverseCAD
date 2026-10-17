import XCTest
import CoreVideo
import AVFoundation
import ARKit
import ReverseCADCore
@testable import ReverseCAD

final class CaptureTests: XCTestCase {
    func testCaptureTimelinePreservesSynchronizationWithoutExportingBootOffset() throws {
        var first = CaptureTimeline(), shifted = CaptureTimeline()
        first.begin(at: 12_000); shifted.begin(at: 62_000)
        // Repeated frames and origin-reset events must not reset the capture's clock.
        first.begin(at: 12_010); shifted.begin(at: 62_010)
        for delta in [0.0, 0.002, 0.125, 5.75, 89.5] {
            XCTAssertEqual(try XCTUnwrap(first.relativeTimestamp(12_000 + delta)), delta, accuracy: 1e-9)
            XCTAssertEqual(try XCTUnwrap(shifted.relativeTimestamp(62_000 + delta)), delta, accuracy: 1e-9)
        }
        let frame = try XCTUnwrap(first.relativeTimestamp(12_001.25))
        let motion = try XCTUnwrap(first.relativeTimestamp(12_001.255))
        XCTAssertEqual(motion - frame, 0.005, accuracy: 1e-9)
        XCTAssertNil(first.relativeTimestamp(11_999.9))
        XCTAssertNil(first.relativeTimestamp(.nan))
        XCTAssertNil(first.relativeTimestamp(.infinity))
        XCTAssertNil(CaptureTimeline().relativeTimestamp(12_000))
    }

    func testNativeFloatDepthCopiesRespectPaddedStrideAndPreserveInvalidSamples() throws {
        let width = 3, height = 2, rowBytes = 64
        let allocation = UnsafeMutableRawPointer.allocate(byteCount: rowBytes * height, alignment: 64)
        defer { allocation.deallocate() }
        allocation.initializeMemory(as: UInt8.self, repeating: 0xAB, count: rowBytes * height)
        let values: [Float] = [0.30, 0.45, .nan, 0, -1, 0.60]
        for y in 0..<height { for x in 0..<width { allocation.advanced(by: y * rowBytes + x * 4).storeBytes(of: values[y * width + x], as: Float.self) } }
        var buffer: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreateWithBytes(kCFAllocatorDefault, width, height, kCVPixelFormatType_DepthFloat32, allocation, rowBytes, nil, nil, nil, &buffer), kCVReturnSuccess)
        let data = try ARKitCaptureProvider.copyRows(XCTUnwrap(buffer), bytesPerPixel: 4, expectedFormat: kCVPixelFormatType_DepthFloat32)
        XCTAssertEqual(data.count, width * height * 4)
        let floats = data.withUnsafeBytes { raw in (0..<6).map { raw.loadUnaligned(fromByteOffset: $0 * 4, as: Float.self) } }
        XCTAssertEqual(floats[0], 0.30); XCTAssertEqual(floats[1], 0.45); XCTAssertTrue(floats[2].isNaN)
        XCTAssertEqual(floats[3], 0); XCTAssertEqual(floats[4], -1); XCTAssertEqual(floats[5], 0.60)
        XCTAssertEqual(ARKitCaptureProvider.validDepthFraction(data), 0.5, accuracy: 1e-12)
        XCTAssertThrowsError(try ARKitCaptureProvider.copyRows(XCTUnwrap(buffer), bytesPerPixel: 1, expectedFormat: kCVPixelFormatType_OneComponent8))
    }

    func testNativeConfidenceCopiesRespectStride() throws {
        let width = 5, height = 3
        var buffer: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_OneComponent8, [kCVPixelBufferBytesPerRowAlignmentKey: 64] as CFDictionary, &buffer), kCVReturnSuccess)
        let pixel = try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(pixel, [])
        let base = try XCTUnwrap(CVPixelBufferGetBaseAddress(pixel)), rowBytes = CVPixelBufferGetBytesPerRow(pixel)
        XCTAssertGreaterThan(rowBytes, width)
        for y in 0..<height { for x in 0..<width { base.advanced(by: y * rowBytes + x).storeBytes(of: UInt8((y * width + x) % 3), as: UInt8.self) } }
        CVPixelBufferUnlockBaseAddress(pixel, [])
        let data = try ARKitCaptureProvider.copyRows(pixel, bytesPerPixel: 1, expectedFormat: kCVPixelFormatType_OneComponent8)
        XCTAssertEqual(Array(data), (0..<15).map { UInt8($0 % 3) })
    }

    func testColumnMajorSerializationDoesNotTransposeAsymmetricPose() {
        let matrix = simd_float4x4(columns: (SIMD4(0, 1, 0, 0), SIMD4(-1, 0, 0, 0), SIMD4(0, 0, 1, 0), SIMD4(0.123, -0.234, 0.456, 1)))
        let values = ARKitCaptureProvider.columnMajor(matrix)
        XCTAssertEqual(Array(values.prefix(12)), [0,1,0,0,-1,0,0,0,0,0,1,0])
        XCTAssertEqual(values[12], 0.123, accuracy: 1e-7)
        XCTAssertEqual(values[13], -0.234, accuracy: 1e-7)
        XCTAssertEqual(values[14], 0.456, accuracy: 1e-7)
    }

    func testReplayUsesSameFrameContractAndPreservesRawEvidence() async throws {
        let sample = try XCTUnwrap(Bundle.main.url(forResource: "SampleScan", withExtension: nil))
        let destination = FileManager.default.temporaryDirectory.appendingPathComponent("replay-"+UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: destination) }
        let provider = ReplayCaptureProvider(source: sample, destination: destination)
        let result = try await provider.finish()
        let sourceManifest = try ScanPackageWriter.validate(directory: sample)
        let manifest = try ScanPackageWriter.validate(directory: result)
        XCTAssertEqual(manifest.source, "synthetic"); XCTAssertNotEqual(manifest.scanID, sourceManifest.scanID)
        let sourceFrames = try CaptureIO.readFrames(directory: sample), frames = try CaptureIO.readFrames(directory: result)
        XCTAssertEqual(frames.count, sourceFrames.count)
        for (original, replayed) in zip(sourceFrames, frames) {
            XCTAssertEqual(original.timestampS, replayed.timestampS); XCTAssertEqual(original.worldCamera, replayed.worldCamera)
            XCTAssertEqual(original.intrinsics, replayed.intrinsics); XCTAssertEqual(original.quality, replayed.quality)
            for path in original.assetPaths { XCTAssertEqual(try CaptureIO.sha256(file: sample.appendingPathComponent(path)), try CaptureIO.sha256(file: result.appendingPathComponent(path))) }
        }
    }

    func testRealAVAssetWriterReviewMovieAndTimestampMapping() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("video-"+UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let provider = try ARKitCaptureProvider(session: ARSession(), directory: directory, scanID: "video-contract-test", useDepth: false, motionDiagnostics: false)
        var pixel: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, 160, 120, kCVPixelFormatType_32BGRA, [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &pixel), kCVReturnSuccess)
        let rgb = try XCTUnwrap(pixel)
        CVPixelBufferLockBaseAddress(rgb, [])
        memset(CVPixelBufferGetBaseAddress(rgb), 127, CVPixelBufferGetBytesPerRow(rgb)*120)
        CVPixelBufferUnlockBaseAddress(rgb, [])
        var timeline = CaptureTimeline()
        timeline.begin(at: 1000)
        for index in 0..<8 {
            try provider.appendVideo(rgb, timestamp: XCTUnwrap(timeline.relativeTimestamp(1000 + Double(index) * 0.1)))
            try await Task.sleep(nanoseconds: 30_000_000)
        }
        _ = try await provider.finish()
        let asset = AVURLAsset(url: directory.appendingPathComponent("video/review.mov"))
        let tracks = try await asset.loadTracks(withMediaType: .video)
        XCTAssertEqual(tracks.count, 1)
        let duration = try await asset.load(.duration)
        XCTAssertGreaterThan(duration.seconds, 0.4)
        let records = try String(contentsOf: directory.appendingPathComponent("video/timestamps.jsonl")).split(separator: "\n")
        XCTAssertGreaterThan(records.count, 4)
        for line in records {
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Double])
            XCTAssertEqual(try XCTUnwrap(object["capture_timestamp_s"]), try XCTUnwrap(object["presentation_timestamp_s"]), accuracy: 1e-8)
            XCTAssertLessThan(try XCTUnwrap(object["capture_timestamp_s"]), 1)
        }
        let diagnostics = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("capture_diagnostics.json"))) as? [String: Any])
        XCTAssertEqual(diagnostics["video_complete"] as? Bool, true)
        XCTAssertEqual(diagnostics["accepted_frames"] as? Int, 0, "Video-only test must never masquerade as captured metric observations")
        let alignment = try XCTUnwrap(diagnostics["timestamp_alignment"] as? [String: Any])
        XCTAssertEqual(alignment["clock"] as? String, "seconds_since_first_ARFrame")
        XCTAssertEqual(alignment["origin_persisted"] as? Bool, false)
        XCTAssertNil(alignment["system_uptime_at_finish_s"])
    }

    func testNativeScanExportCreatesPortableZIP() async throws {
        let sample = try XCTUnwrap(Bundle.main.url(forResource: "SampleScan", withExtension: nil))
        let exported = try await CaptureExport.archive(directory: sample)
        defer { try? FileManager.default.removeItem(at: exported) }
        let handle = try FileHandle(forReadingFrom: exported)
        defer { try? handle.close() }
        XCTAssertEqual(try handle.read(upToCount: 4), Data([0x50,0x4B,0x03,0x04]))
        XCTAssertGreaterThan(try exported.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0, 1000)
        _ = try ScanPackageWriter.validate(directory: sample)
    }
}
