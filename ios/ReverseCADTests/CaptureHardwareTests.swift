import XCTest
import ReverseCADCore
@testable import ReverseCAD

final class CaptureHardwareTests: XCTestCase {
    func testReferenceCopyIsBoundToProfileAndRejectsChangedArchive() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer {try? FileManager.default.removeItem(at:root)}
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let archive=root.appendingPathComponent("reference.zip"),profile=root.appendingPathComponent("profile.json"),capture=root.appendingPathComponent("scan")
        let bytes=Data("recorded reference fixture".utf8);try bytes.write(to:archive)
        try CaptureIO.atomicWrite(PhoneCalibrationProfile(referenceArchiveSHA256:CaptureIO.sha256(bytes)),to:profile)
        try CaptureHardware.preserveReference(archive.path,in:capture,profileURL:profile)
        XCTAssertEqual(try Data(contentsOf:capture.appendingPathComponent("calibration/reference.zip")),bytes)
        try Data("changed".utf8).write(to:archive)
        XCTAssertThrowsError(try CaptureHardware.preserveReference(archive.path,in:capture,profileURL:profile))
    }
    func testCapabilityReportDoesNotClaimUnimplementedSources() {
        let value=CaptureHardware.report()
        XCTAssertEqual(value["all_three_rear_cameras_active"] as? Bool,false)
        XCTAssertEqual(value["private_sensor_interception_active"] as? Bool,false)
        XCTAssertTrue((value["rear_calibration"] as? String)?.contains("unvalidated") == true)
    }
}
