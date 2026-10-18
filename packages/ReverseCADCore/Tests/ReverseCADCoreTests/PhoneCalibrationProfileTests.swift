import XCTest
@testable import ReverseCADCore

final class PhoneCalibrationProfileTests: XCTestCase {
    func testReferenceDoesNotInventRearCalibrationAndRevisionsRemainRecoverable() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:root) }
        let first = try PhoneCalibrationProfile(referenceArchiveSHA256:String(repeating:"a",count:64))
        try first.save(directory:root)
        let second = try PhoneCalibrationProfile(referenceArchiveSHA256:String(repeating:"b",count:64))
        try second.save(directory:root)
        XCTAssertNil(second.frontToRearTransform)
        XCTAssertEqual(second.status,"provisional_reference_only")
        let decoder = JSONDecoder()
        XCTAssertEqual(try decoder.decode(PhoneCalibrationProfile.self,from:Data(contentsOf:root.appendingPathComponent(first.revision.uuidString+".json"))),first)
        XCTAssertEqual(try decoder.decode(PhoneCalibrationProfile.self,from:Data(contentsOf:root.appendingPathComponent("current.json"))),second)
        XCTAssertThrowsError(try first.save(directory:root))
    }
    func testRejectsMissingReferenceDigest() {
        XCTAssertThrowsError(try PhoneCalibrationProfile(referenceArchiveSHA256:"not-a-digest"))
    }
}
