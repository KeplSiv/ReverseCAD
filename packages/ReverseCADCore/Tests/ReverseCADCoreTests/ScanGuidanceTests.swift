import XCTest
import simd
@testable import ReverseCADCore

final class ScanGuidanceTests: XCTestCase {
    func testQualityAndFramingTakePriorityOverOrbit() {
        var guide = ScanGuidance()
        func prompt(_ x: Float = 0.5, sharp: Bool = true, tracking: Bool = true) -> String {
            guide.update(camera: [0,0,0.3], target: .zero, screenPoint: [x,0.5], sharp: sharp, tracking: tracking, reliableDepth: true, accepted: true)
        }
        XCTAssertTrue(prompt(tracking: false).contains("tracking"))
        XCTAssertTrue(prompt(sharp: false).contains("sharp"))
        XCTAssertTrue(prompt(0.1).contains("Aim left"))
        XCTAssertTrue(guide.covered.isEmpty)
        XCTAssertTrue(prompt().contains("Move right"))
        XCTAssertEqual(guide.covered.count, 1)
    }
    func testRotationInPlaceDoesNotCreateCoverageAndNewRingIsRequested() {
        var guide = ScanGuidance()
        for _ in 0..<30 {
            _ = guide.update(camera: [0,0,0.3], target: .zero, screenPoint: [0.5,0.5], sharp: true, tracking: true, reliableDepth: true, accepted: true)
        }
        XCTAssertEqual(guide.covered.count, 1)
        var last = ""
        for step in 0..<100 {
            let angle = Float(step) * 0.06
            last = guide.update(camera: [sin(angle)*0.3,0,cos(angle)*0.3], target: .zero, screenPoint: [0.5,0.5], sharp: true, tracking: true, reliableDepth: true, accepted: true)
        }
        XCTAssertTrue(last.contains("Raise"))
        XCTAssertGreaterThanOrEqual(guide.covered.count, 9)
    }
}
