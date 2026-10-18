import XCTest
import CoreGraphics
@testable import ReverseCADCore

final class CaptureFirstTests: XCTestCase {
    func frame(_ id: Int, x: Double, blur: Double = 80) -> CaptureFrame {
        var pose = Geometry.identity; pose[12] = x
        return CaptureFrame(scanID: "scan", segmentID: "segment", frameID: String(id), timestampS: Double(id), rgbPath: "rgb/\(id).jpg", rgbWidth: 640, rgbHeight: 480, intrinsics: [500,0,0,0,500,0,320,240,1], intrinsicsWidth: 640, intrinsicsHeight: 480, worldCamera: pose, trackingState: "normal", quality: CaptureQuality(blurScore: blur, accepted: true))
    }
    func testThirdsAndInverseDisplayMappingForRotatedAndCroppedPreview() {
        for size in [CGSize(width: 390, height: 600), CGSize(width: 800, height: 360)] {
            let guide = CaptureFraming.centerCell(in: CGRect(origin: .zero, size: size))
            XCTAssertEqual(guide.width, size.width/3, accuracy: 1e-8)
            XCTAssertEqual(guide.height, size.height/3, accuracy: 1e-8)
            for transform in [CGAffineTransform.identity, CGAffineTransform(a: 0, b: 1.5, c: -1.2, d: 0, tx: 1.1, ty: -0.25), CGAffineTransform(a: -1, b: 0, c: 0, d: -1, tx: 1, ty: 1)] {
                let raw = CaptureFraming.rawRegion(rect: guide, viewport: size, displayTransform: transform)
                let display = raw.applying(transform)
                XCTAssertEqual(display.minX, 1.0/3, accuracy: 1e-8)
                XCTAssertEqual(display.maxY, 2.0/3, accuracy: 1e-8)
            }
        }
    }
    func testSelectionRejectsBlurAndDuplicatesAndKeepsInitialReference() {
        var frames = (0..<40).map { frame($0, x: Double($0/2)*0.03) }
        frames.insert(frame(100, x: 4, blur: 1), at: 0)
        let selection = RepresentativeViews.select(frames)
        XCTAssertEqual(selection.first?.frameID, "0")
        XCTAssertEqual(selection.count, 10)
        XCTAssertFalse(selection.contains { $0.frameID == "100" })
        for (i,a) in selection.enumerated() { for b in selection.dropFirst(i+1) { XCTAssertGreaterThanOrEqual(RepresentativeViews.separation(a,b),1) } }
        XCTAssertEqual(RepresentativeViews.select((0..<30).map { frame($0,x:0) }).count,1)
        var rotated = frame(50,x:0); rotated.worldCamera[8] = 1; rotated.worldCamera[10] = 0
        XCTAssertEqual(RepresentativeViews.select([frame(0,x:0),rotated]).count,1)
    }
    func testConsensusNeedsSameInstanceMajorityAndReferenceContainsTap() throws {
        func detection(category: String = "tool", present: Double = 0.99, count: String = "one") throws -> JevDetection {
            let response: [String: Any] = ["model": "fixture", "answers": ["present": ["noul": present], "instances": ["choice": count, "confidence": 0.99], "category": ["choice": category, "confidence": 0.99], "target": ["box": ["left": 0.2,"right": 0.7,"top": 0.2,"bottom": 0.7], "confidence": 0.99]]]
            return try JevClient.interpret(data: JSONSerialization.data(withJSONObject: response), jpeg: Data([1]), description: "", requestID: UUID())
        }
        let yes = try detection(), no = try detection(present: 0.1), other = try detection(category: "toy"), ambiguous = try detection(count: "several")
        XCTAssertEqual(ObjectConsensus.confirmed([yes,yes,yes,no],anchor: CGPoint(x:0.5,y:0.5)),[0,1,2])
        XCTAssertTrue(ObjectConsensus.confirmed([yes,yes,other,ambiguous],anchor: CGPoint(x:0.5,y:0.5)).isEmpty)
        XCTAssertTrue(ObjectConsensus.confirmed([yes,yes,yes],anchor: CGPoint(x:0.9,y:0.5)).isEmpty)
    }
}
