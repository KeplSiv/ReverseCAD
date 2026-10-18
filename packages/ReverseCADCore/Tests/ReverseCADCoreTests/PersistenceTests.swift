import XCTest
@testable import ReverseCADCore

final class PersistenceTests: XCTestCase {
    func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("reversecad-core-"+UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
    func frame(id: String = "0001", timestamp: Double = 1) -> CaptureFrame {
        CaptureFrame(scanID: "scan-test", segmentID: "segment", frameID: id, timestampS: timestamp, rgbPath: "rgb/\(id).jpg", rgbWidth: 2, rgbHeight: 2, depthPath: "depth/\(id).f32", depthWidth: 2, depthHeight: 2, depthRowBytes: 8, intrinsics: [2,0,0,0,2,0,0.5,0.5,1], intrinsicsWidth: 2, intrinsicsHeight: 2, worldCamera: Geometry.identity, trackingState: "normal", quality: CaptureQuality(blurScore: 50, accepted: true))
    }
    func assets(for frame: CaptureFrame) -> [String:Data] { [frame.rgbPath: Data([0xff,0xd8,0xff,0xd9]),frame.depthPath!: [Float(0.2),0.3,0.4,0.5].withUnsafeBufferPointer { Data(buffer: $0) }] }
    func writer(at url: URL) throws -> ScanPackageWriter { try ScanPackageWriter(directory: url, manifest: CaptureManifest(scanID: "scan-test", source: "synthetic", device: "unit-test", segments: [CaptureSegment(segmentID: "segment")])) }

    func testLegacyFrameDecodingDefaultsCalibrationAndNativeEncodingPreservesMatrixKey() throws {
        var original = frame()
        let legacyData = try CaptureIO.encoder().encode(original)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: legacyData) as? [String:Any])
        XCTAssertNotNil(json["T_world_camera"]); XCTAssertNil(json["worldCamera"]); XCTAssertNil(json["depth_calibration_mode"])
        XCTAssertNil(try JSONDecoder().decode(CaptureFrame.self, from: legacyData).depthCalibrationMode)
        original.depthCalibrationMode = "native_arkit"
        XCTAssertEqual(try JSONDecoder().decode(CaptureFrame.self, from: CaptureIO.encoder().encode(original)), original)
    }
    func testMissingDepthAndConfidenceAreExplicit() throws {
        var value = frame(); value.depthPath=nil; value.depthWidth=0; value.depthHeight=0; value.depthRowBytes=0
        XCTAssertNoThrow(try value.validate())
        value.confidencePath = "confidence/0001.u8"
        XCTAssertThrowsError(try value.validate())
    }
    func testFrameCommitAndChecksumCorruption() throws {
        let root=try temporaryDirectory(); let writer=try writer(at:root); let value=frame()
        try writer.append(frame:value,assets:assets(for:value)); try writer.finish()
        XCTAssertEqual(try ScanPackageWriter.validate(directory:root).frameCount,1)
        try Data([1,2,3,4]).write(to:root.appendingPathComponent(value.rgbPath))
        XCTAssertThrowsError(try ScanPackageWriter.validate(directory:root))
        XCTAssertThrowsError(try ScanPackageWriter.recover(directory:root))
    }
    func testIncompleteRecoveryPreservesCommittedFramesAndOptionalVideo() throws {
        let root=try temporaryDirectory(); let writer=try writer(at:root); let value=frame()
        try writer.append(frame:value,assets:assets(for:value))
        try FileManager.default.createDirectory(at:root.appendingPathComponent("video"),withIntermediateDirectories:true)
        try Data("unfinished-movie".utf8).write(to:root.appendingPathComponent("video/review.mov"))
        let recovered=try ScanPackageWriter.recover(directory:root)
        XCTAssertEqual(recovered.frameCount,1)
        try recovered.finish(complete:false)
        XCTAssertFalse(try ScanPackageWriter.validate(directory:root,allowIncomplete:true).complete)
        XCTAssertThrowsError(try ScanPackageWriter.validate(directory:root))
        XCTAssertEqual(try CaptureIO.readFrames(directory:root),[value])
    }
    func testDuplicateTimestampAndWrongSegmentDoNotDestroyCommittedFrame() throws {
        let root=try temporaryDirectory(); let writer=try writer(at:root); let value=frame()
        try writer.append(frame:value,assets:assets(for:value))
        let duplicate=frame(id:"0002",timestamp:1)
        XCTAssertThrowsError(try writer.append(frame:duplicate,assets:assets(for:duplicate)))
        var wrong=frame(id:"0003",timestamp:20); wrong.segmentID="new-origin"
        XCTAssertThrowsError(try writer.append(frame:wrong,assets:assets(for:wrong)))
        try writer.updateSegments([CaptureSegment(segmentID:"segment"),CaptureSegment(segmentID:"new-origin",registered:false)])
        try writer.append(frame:wrong,assets:assets(for:wrong)); try writer.finish()
        let manifest=try ScanPackageWriter.validate(directory:root)
        XCTAssertEqual(manifest.frameCount,2); XCTAssertFalse(manifest.segments[1].registered)
    }
    func testPathTraversalSymlinksAndMissingAssetRejected() throws {
        for path in ["../secret","/absolute","rgb/../secret","rgb//x","rgb\\x","rgb/x:y", "./foo"] { XCTAssertThrowsError(try CaptureIO.validatedRelativePath(path)) }
        let root=try temporaryDirectory()
        try FileManager.default.createSymbolicLink(at:root.appendingPathComponent("escape"),withDestinationURL:root.deletingLastPathComponent())
        XCTAssertThrowsError(try CaptureIO.safeURL(directory:root,path:"escape/other"))
        XCTAssertThrowsError(try CaptureIO.files(directory:root))
        let clean=try temporaryDirectory(); let writer=try writer(at:clean); let value=frame()
        XCTAssertThrowsError(try writer.append(frame:value,assets:[value.rgbPath:Data([1])]))
    }
    func testImportedPackageAndDurableJobCheckpoint() throws {
        let source=try temporaryDirectory(), root=try temporaryDirectory()
        let writer=try writer(at:source), value=frame()
        try writer.append(frame:value,assets:assets(for:value)); try writer.finish()
        let destination=root.appendingPathComponent("imported")
        let manifest=try CaptureIO.importPackage(from:source,to:destination)
        XCTAssertEqual(manifest.scanID,"scan-test")
        XCTAssertEqual(try CaptureIO.readFrames(directory:destination),[value])
        XCTAssertThrowsError(try CaptureIO.importPackage(from:source,to:destination))
        let state=ProcessingCheckpoint(projectID:"project",scanID:"scan-test",jobID:"job",state:.reconstructing)
        let journal=root.appendingPathComponent("job.json"); try state.save(to:journal)
        XCTAssertEqual(try ProcessingCheckpoint.load(from:journal),state)
        XCTAssertFalse(JobState.reconstructing.isTerminal); XCTAssertTrue(JobState.needsInput.isTerminal)
    }
    func testFixtureCrossLanguageContractAndMatrixSerialization() throws {
        let workspace=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let sample=workspace.appendingPathComponent("fixtures/sample_scan")
        let manifest=try ScanPackageWriter.validate(directory:sample)
        XCTAssertEqual(manifest.source,"synthetic")
        let frames=try CaptureIO.readFrames(directory:sample)
        XCTAssertEqual(frames.count,12)
        for value in frames {
            let encoded=try CaptureIO.encoder().encode(value)
            XCTAssertEqual(try JSONDecoder().decode(CaptureFrame.self,from:encoded),value)
            XCTAssertEqual(value.depthWidth,160); XCTAssertEqual(value.rgbWidth,320)
        }
    }
}
