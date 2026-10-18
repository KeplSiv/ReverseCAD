import XCTest
@testable import ReverseCADCore

final class ObservedSurfaceTests: XCTestCase {
    private func frame() -> CaptureFrame {
        var f=CaptureFrame(scanID:"scan",segmentID:"segment",frameID:"frame",timestampS:0,rgbPath:"rgb.jpg",rgbWidth:3,rgbHeight:3,depthPath:"depth.f32",depthWidth:3,depthHeight:3,depthRowBytes:12,confidencePath:"confidence.u8",maskPath:"mask.u8",intrinsics:[100,0,0,0,100,0,1,1,1],intrinsicsWidth:3,intrinsicsHeight:3,worldCamera:Geometry.identity,trackingState:"normal",quality:CaptureQuality(blurScore:20,accepted:true,reasons:[]))
        f.depthCalibrationMode="native_arkit";return f
    }
    private func data(_ values: [Float]) -> Data { values.withUnsafeBytes { Data($0) } }
    func testDepthPreviewPreservesMaskHolesAndRejectsDepthEdges() throws {
        let f=frame(), confidence=Data(repeating:2,count:9)
        let full=try ObservedSurface.depth(frame:f,depth:data(Array(repeating:0.5,count:9)),confidence:confidence,mask:Data(repeating:1,count:9),stride:1)
        XCTAssertEqual(full.triangles.count,8)
        var mask=Data(repeating:1,count:9);mask[4]=0
        let hole=try ObservedSurface.depth(frame:f,depth:data(Array(repeating:0.5,count:9)),confidence:confidence,mask:mask,stride:1)
        XCTAssertLessThan(hole.triangles.count,full.triangles.count)
        let edge=try ObservedSurface.depth(frame:f,depth:data([0.5,0.5,1,0.5,0.5,1,0.5,0.5,1]),confidence:confidence,mask:Data(repeating:1,count:9),stride:1)
        XCTAssertEqual(edge.triangles.count,4)
        XCTAssertThrowsError(try ObservedSurface.depth(frame:f,depth:Data(),confidence:confidence,mask:mask))
        var large=f;large.depthWidth=5;large.depthHeight=5;large.depthRowBytes=20
        var smallHole=Data(repeating:1,count:25);smallHole[12]=0
        let coarse=try ObservedSurface.depth(frame:large,depth:data(Array(repeating:0.5,count:25)),confidence:Data(repeating:2,count:25),mask:smallHole,stride:4)
        XCTAssertTrue(coarse.triangles.isEmpty)
    }
    func testAccumulatorAddsObservedSurfacesWithoutDuplicateOrInventedFaces() {
        var a=ObservedSurfaceAccumulator()
        let first=ObservedSurface(vertices:[[0,0,0],[0.01,0,0],[0,0.01,0]],triangles:[[0,1,2]])
        a.add(first);a.add(first)
        XCTAssertEqual(a.vertices.count,3);XCTAssertEqual(a.triangles.count,1)
        a.add(ObservedSurface(vertices:[[0,0,0.02],[0.01,0,0.02],[0,0.01,0.02]],triangles:[[0,1,2]]))
        XCTAssertEqual(a.vertices.count,6);XCTAssertEqual(a.triangles.count,2)
        a.add(ObservedSurface(vertices:[[Double.nan,0,0]],triangles:[[0,1,2]]))
        XCTAssertEqual(a.vertices.count,6);XCTAssertEqual(a.triangles.count,2)
    }
}
