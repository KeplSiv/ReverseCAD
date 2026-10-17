import XCTest
@testable import ReverseCADCore

final class GeometryTests: XCTestCase {
    func testIndependentNativeARKitRayWithNoncentralPixelAndTwoTransforms() throws {
        // Direct native scale: fx=250, fy=200, cx=150, cy=100. CV ray=(.04,-.04,.4).
        // AR ray=(.04,.04,-.4), z90 rotation and translation ->(.06,.24,-.1), object offset ->(.04,.27,-.06).
        let pose: [Double] = [0,1,0,0,-1,0,0,0,0,0,1,0,0.1,0.2,0.3,1]
        var object = Geometry.identity; object[12] = -0.02; object[13] = 0.03; object[14] = 0.04
        let point = try Geometry.unproject(u: 175, v: 80, depthMeters: 0.4, intrinsics: [1000,0,0,0,800,0,600,400,1], intrinsicsWidth: 1200, intrinsicsHeight: 800, depthWidth: 300, depthHeight: 200, worldCamera: pose, objectWorld: object, depthCalibrationMode: "native_arkit")
        for (actual, expected) in zip(Geometry.metersToMillimeters(point), [40.0,270.0,-60.0]) { XCTAssertEqual(actual, expected, accuracy: 0.01) }
    }
    func testIndependentResizedSyntheticPixelCenterRay() throws {
        let point = try Geometry.unproject(u: 89.5, v: 49.5, depthMeters: 0.25, intrinsics: [400,0,0,0,400,0,319.5,239.5,1], intrinsicsWidth: 640, intrinsicsHeight: 480, depthWidth: 160, depthHeight: 120, worldCamera: Geometry.identity)
        for (actual, expected) in zip(point, [0.025,0.025,-0.25]) { XCTAssertEqual(actual, expected, accuracy: 1e-12) }
    }
    func testNativeAndResizedCalibrationMustNotConflatePrincipalPoints() throws {
        let k: [Double] = [1000,0,0,0,800,0,600,400,1]
        let native = try Geometry.scaledIntrinsics(k, fromWidth: 1200, fromHeight: 800, toWidth: 300, toHeight: 200, mode: "native_arkit")
        let resized = try Geometry.scaledIntrinsics(k, fromWidth: 1200, fromHeight: 800, toWidth: 300, toHeight: 200)
        XCTAssertEqual(native[6],150); XCTAssertEqual(native[7],100)
        XCTAssertEqual(resized[6],149.625); XCTAssertEqual(resized[7],99.625)
        XCTAssertThrowsError(try Geometry.scaledIntrinsics(k, fromWidth: 1200, fromHeight: 800, toWidth: 300, toHeight: 200, mode: "display_portrait"))
    }
    func testPreviewUnitsConvertExactlyOnce() {
        XCTAssertEqual(Geometry.millimetersToMeters([123.5, -27, 4]), [0.1235,-0.027,0.004])
        XCTAssertEqual(Geometry.metersToMillimeters([0.1235,-0.027,0.004]), [123.5,-27,4])
    }
    func testReflectionsScaleAndNonfiniteTransformsRejected() {
        var reflected = Geometry.identity; reflected[0] = -1
        XCTAssertThrowsError(try Geometry.validateRigidTransform(reflected))
        var scaled = Geometry.identity; scaled[5] = 2
        XCTAssertThrowsError(try Geometry.validateRigidTransform(scaled))
        var invalid = Geometry.identity; invalid[12] = .nan
        XCTAssertThrowsError(try Geometry.validateRigidTransform(invalid))
    }
    func testInvalidDepthAndCalibrationRejected() {
        for depth in [0.0,-1,.nan,.infinity] {
            XCTAssertThrowsError(try Geometry.unproject(u: 1, v: 1, depthMeters: depth, intrinsics: [2,0,0,0,2,0,1,1,1], intrinsicsWidth: 2, intrinsicsHeight: 2, depthWidth: 2, depthHeight: 2, worldCamera: Geometry.identity))
        }
        XCTAssertThrowsError(try Geometry.scaledIntrinsics([0,0,0,0,0,0,0,0,1], fromWidth: 2, fromHeight: 2, toWidth: 2, toHeight: 2))
    }
    func testPaddedStridePreservesOnlyRealBytes() throws {
        let original = Data([1,2,3,4,99,99,99,99,5,6,7,8,99,99,99,99])
        XCTAssertEqual(try Geometry.tightlyPackedRows(original, width: 4, height: 2, rowBytes: 8, bytesPerPixel: 1), Data([1,2,3,4,5,6,7,8]))
        XCTAssertThrowsError(try Geometry.tightlyPackedRows(original, width: 4, height: 2, rowBytes: 3, bytesPerPixel: 1))
    }
}
