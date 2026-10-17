import XCTest
import simd
@testable import ReverseCAD

final class SurfacePatchNormalTests: XCTestCase {
    func testObservedJitteredPlaneRecoversNormalAndPreservesPickedPoint() throws {
        var points: [SIMD3<Float>] = []
        for row in -6...6 { for column in -6...6 {
            let x = Float(column) * 0.001, y = Float(row) * 0.001
            let jitter = Float(sin(Double(row * 13 + column * 7))) * 0.0002
            points.append(SIMD3(x, y, 0.2 * x - 0.3 * y + jitter))
        } }
        let picked = SIMD3<Float>(0.00123, -0.00074, 0.00057)
        let fit = try XCTUnwrap(SurfacePatchNormal.estimate(points: points, center: picked,
                                                           orientationHint: SIMD3(0.38, -0.08, 0.92)))
        let analyticNormal = simd_normalize(SIMD3<Float>(-0.2, 0.3, 1))
        XCTAssertGreaterThan(simd_dot(fit.normal, analyticNormal), cos(Float.pi / 90), "Plane normal must be within two degrees despite tessellation jitter and a biased hit normal")
        XCTAssertEqual(fit.point, picked, "A normal fit must never snap or move the selected observed point")
        XCTAssertLessThan(fit.rmsM, 0.00025)
        XCTAssertGreaterThanOrEqual(fit.sampleCount, 12)
    }

    func testOrientationHintChoosesSignOnly() throws {
        var points: [SIMD3<Float>] = []
        for row in -5...5 { for column in -5...5 {
            points.append(SIMD3(Float(column) * 0.001, Float(row) * 0.001, 0))
        } }
        let fit = try XCTUnwrap(SurfacePatchNormal.estimate(points: points, center: .zero,
                                                           orientationHint: SIMD3(0.6, 0.2, -0.3)))
        XCTAssertEqual(fit.normal.x, 0, accuracy: 0.00001)
        XCTAssertEqual(fit.normal.y, 0, accuracy: 0.00001)
        XCTAssertEqual(fit.normal.z, -1, accuracy: 0.00001)
    }

    func testSparseAndLineLikePatchesHaveNoClaimedSurfaceNormal() {
        XCTAssertNil(SurfacePatchNormal.estimate(points: [.zero, SIMD3(0.001, 0, 0)], center: .zero, orientationHint: SIMD3(0, 0, 1)))
        let line = (-30...30).map { SIMD3<Float>(Float($0) * 0.0002, 0, 0) }
        XCTAssertNil(SurfacePatchNormal.estimate(points: line, center: .zero, orientationHint: SIMD3(0, 0, 1)))
    }

    func testTwoMeetingPlanesAreRejectedInsteadOfAveragedIntoFakeContact() {
        var corner: [SIMD3<Float>] = []
        for row in -6...6 { for column in 0...6 {
            let along = Float(row) * 0.001, across = Float(column) * 0.001
            corner.append(SIMD3(across, along, 0))
            corner.append(SIMD3(0, along, across))
        } }
        XCTAssertNil(SurfacePatchNormal.estimate(points: corner, center: .zero, orientationHint: SIMD3(0, 0, 1)))
    }
}
