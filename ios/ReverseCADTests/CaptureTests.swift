import XCTest
import SceneKit
import CoreVideo
import AVFoundation
import ARKit
import ReverseCADCore
@testable import ReverseCAD

final class CaptureTests: XCTestCase {
    @MainActor
    func testPieceIdentityColorsReachSceneKitWithoutOrangeTint() throws {
        let part = MeshPreview(vertices: [[0,0,0],[10,0,0],[0,10,0]], triangles: [[0,1,2]],
                               colors: [[0.12,0.72,1],[0.12,0.72,1],[0.12,0.72,1]])
        let preview = GeometryPreview(scan: nil, part: part, selectionMode: "none")
        let coordinator = preview.makeCoordinator()
        let view = GeometrySceneView(frame: CGRect(x:0,y:0,width:300,height:400));view.scene = SCNScene()
        coordinator.view = view;coordinator.update(preview)
        let node = try XCTUnwrap(view.scene?.rootNode.childNode(withName:"Inferred replacement", recursively:true))
        let source = try XCTUnwrap(node.geometry?.sources(for:.color).first)
        XCTAssertEqual(source.vectorCount,3)
        XCTAssertEqual(node.geometry?.firstMaterial?.diffuse.contents as? UIColor,UIColor.white)
        var malformed=part;malformed.colors=[[Double.nan,0,0]]
        XCTAssertNil(malformed.validatedColors)
    }
    @MainActor
    func testPreviewRendersOnlyWhileAttachedAndRefitsAfterResize() throws {
        let part = MeshPreview(vertices: [[-34,-70,-152],[-12,-70,-152],[-34,-49,-152],[-34,-70,-132]],
                               triangles: [[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
        let preview = GeometryPreview(scan: nil, part: part, selectionMode: "none")
        let coordinator = preview.makeCoordinator()
        let view = GeometrySceneView(frame: .zero)
        view.scene = SCNScene()
        coordinator.view = view
        view.onViewportChange = { coordinator.fitCamera() }
        coordinator.update(preview)
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
        let controller = UIViewController()
        window.rootViewController = controller
        window.makeKeyAndVisible()
        defer { window.isHidden = true }
        controller.view.addSubview(view)
        XCTAssertTrue(view.rendersContinuously)
        XCTAssertTrue(view.isPlaying)
        view.frame = CGRect(x: 20, y: 140, width: 350, height: 400)
        view.layoutIfNeeded()
        for vertex in part.vertices {
            let p = view.projectPoint(SCNVector3(vertex[0]/1000, vertex[1]/1000, vertex[2]/1000))
            XCTAssertTrue(p.x > 0 && p.x < 350 && p.y > 0 && p.y < 400 && p.z > 0 && p.z < 1)
        }
        view.removeFromSuperview()
        XCTAssertFalse(view.rendersContinuously)
        XCTAssertFalse(view.isPlaying)
        controller.view.addSubview(view)
        XCTAssertTrue(view.rendersContinuously)
        XCTAssertTrue(view.isPlaying)
    }

    @MainActor
    func testPreviewFitsVisiblePieceAcrossViewportShapes() throws {
        let part = MeshPreview(vertices: [[0,0,0],[18,0,0],[0,18,0],[0,0,18]],
                               triangles: [[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
        let distantScan = MeshPreview(vertices: [[1000,1000,1000],[1500,1500,1500]])
        var preview = GeometryPreview(scan: distantScan, part: part, showScan: false, selectionMode: "none")
        let coordinator = preview.makeCoordinator()
        let view = GeometrySceneView(frame: .zero)
        view.scene = SCNScene()
        coordinator.view = view
        view.onViewportChange = { coordinator.fitCamera() }
        coordinator.update(preview)
        for size in [CGSize(width: 300, height: 500), CGSize(width: 500, height: 180)] {
            view.frame = CGRect(origin: .zero, size: size)
            view.layoutSubviews()
            let target = view.defaultCameraController.target
            XCTAssertEqual(target.x, 0.009, accuracy: 0.0001)
            XCTAssertEqual(target.y, 0.009, accuracy: 0.0001)
            for vertex in part.vertices {
                let p = view.projectPoint(SCNVector3(vertex[0]/1000, vertex[1]/1000, vertex[2]/1000))
                XCTAssertGreaterThan(p.x, 0)
                XCTAssertLessThan(p.x, Float(size.width))
                XCTAssertGreaterThan(p.y, 0)
                XCTAssertLessThan(p.y, Float(size.height))
                XCTAssertGreaterThan(p.z, 0)
                XCTAssertLessThan(p.z, 1)
            }
        }
        preview.showScan = true
        coordinator.update(preview)
        XCTAssertGreaterThan(view.defaultCameraController.target.x, 0.5)
        preview.showScan = false
        coordinator.update(preview)
        XCTAssertEqual(view.defaultCameraController.target.x, 0.009, accuracy: 0.0001)
    }

    @MainActor
    func testExplicitDiagnosticsCleanupPreservesScanAssetsAndHashes() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let scan = root.appendingPathComponent("project/scan")
        try FileManager.default.createDirectory(at: scan, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let photo = Data("saved photograph".utf8)
        try photo.write(to: scan.appendingPathComponent("frame.jpg"))
        try Data("old diagnostics".utf8).write(to: scan.appendingPathComponent("capture_diagnostics.json"))
        let hashes = ["frame.jpg": "preserved", "capture_diagnostics.json": "removed"]
        try JSONEncoder().encode(hashes).write(to: scan.appendingPathComponent("checksums.json"))
        XCTAssertEqual(try AppModel.removeSavedCaptureDiagnostics(root: root), 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: scan.appendingPathComponent("capture_diagnostics.json").path))
        XCTAssertEqual(try Data(contentsOf: scan.appendingPathComponent("frame.jpg")), photo)
        XCTAssertEqual(try JSONDecoder().decode([String:String].self, from: Data(contentsOf: scan.appendingPathComponent("checksums.json"))), ["frame.jpg": "preserved"])
        XCTAssertEqual(try AppModel.removeSavedCaptureDiagnostics(root: root), 0)
    }
    func testGuideStaysCenteredInsideAvailableCameraViewport() {
        // Portrait sheet, small phone, landscape, and embedded legacy preview.
        for size in [CGSize(width: 390, height: 400), CGSize(width: 320, height: 180),
                     CGSize(width: 700, height: 110), CGSize(width: 360, height: 280)] {
            let bounds = CGRect(origin: .zero, size: size)
            let guide = GuidedARView.guideRect(in: bounds)
            XCTAssertTrue(bounds.contains(guide))
            XCTAssertEqual(guide.midX, bounds.midX, accuracy: 0.01)
            XCTAssertEqual(guide.midY, bounds.midY, accuracy: 0.01)
            XCTAssertGreaterThan(guide.minY, 0)
            XCTAssertLessThan(guide.maxY, bounds.maxY)
        }
    }
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
