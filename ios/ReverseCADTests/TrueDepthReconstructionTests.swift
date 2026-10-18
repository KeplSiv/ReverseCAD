import XCTest
import AVFoundation
import simd
import UIKit
@testable import ReverseCAD

final class TrueDepthReconstructionTests:XCTestCase {
    static func fixture(step:Bool=false) throws -> URL {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let w=32,h=24;var frames=[[String:Any]](),entries=[[String:Any]]()
        let format=UIGraphicsImageRendererFormat();format.scale=1
        let image=UIGraphicsImageRenderer(size:CGSize(width:64,height:48),format:format).image {ctx in
            UIColor.red.setFill();ctx.fill(CGRect(x:0,y:0,width:64,height:24));UIColor.blue.setFill();ctx.fill(CGRect(x:0,y:24,width:64,height:24))
        }
        try XCTUnwrap(image.pngData()).write(to:root.appendingPathComponent("rgb.png"))
        let table=[Float](repeating:0,count:8);try table.withUnsafeBytes{Data($0)}.write(to:root.appendingPathComponent("inverse.bin"))
        for i in 0..<8 {
            let values=(0..<w*h).map {j -> Float in step && j%w>=16 ? 0.8:0.5}
            let file="depth\(i).bin";try values.withUnsafeBytes{Data($0)}.write(to:root.appendingPathComponent(file))
            let id="front-\(i)"
            frames.append(["id":id,"camera":"front","width":64,"height":48,"rgb":"rgb.png","mirrored":false,"rotation_degrees":0,"settings":["zoom_factor":1,"video_scale_and_crop_factor":1,"geometric_correction_enabled":false]])
            entries.append(["rgb_frame":id,"is_filtered":false,"accuracy":1,"sensor":"front_TrueDepth",
                "calibration":["intrinsics":[[60,0,32],[0,60,24],[0,0,1]],"reference_size":[64,48],"distortion_center":[32,24],"inverse_distortion_float32_table":"inverse.bin"],
                "depth":["pixel_format":UInt32(kCVPixelFormatType_DepthFloat32),"planes":[["file":file,"width":w,"height":h,"row_bytes":w*4]]]])
        }
        try cameraJSONWrite(["complete":true,"frames":frames,"av_depth":entries],root.appendingPathComponent("session.json"))
        return root
    }
    func testSavedPhysicalReferenceReplayWhenAvailable() throws {
        let root=URL(fileURLWithPath:"/Users/pranav/frankly/build/validation-v3/capture-2026-10-18T11-35-28Z-F63307")
        guard FileManager.default.fileExists(atPath:root.appendingPathComponent("session.json").path) else { throw XCTSkip("Local physical reference is not installed on this host") }
        let surface=try TrueDepthReconstruction.build(dataset:root)
        XCTAssertGreaterThan(surface.vertices.count,30)
        XCTAssertEqual(surface.summary["frames_with_per_frame_calibration"],8)
    }
    func testMetricUnprojectionAndLUTDirection() throws {
        let K=simd_float3x3(columns:(SIMD3(100,0,0),SIMD3(0,100,0),SIMD3(50,50,1)))
        let p=try TrueDepthReconstruction.rectifiedPoint(SIMD2(70,50),depth:0.5,K:K,referenceSize:SIMD2(100,100),center:SIMD2(50,50),inverse:[0.1,0.1])
        XCTAssertEqual(p.x,0.11,accuracy:0.000001);XCTAssertEqual(p.y,0,accuracy:0.000001);XCTAssertEqual(p.z,0.5)
        XCTAssertThrowsError(try TrueDepthReconstruction.rectifiedPoint(SIMD2(70,50),depth:0.5,K:K,referenceSize:SIMD2(100,100),center:SIMD2(.nan,50),inverse:[0,0]))
    }
    func testStableDepthRejectsHolesAndLargeVariation() {
        XCTAssertNil(TrueDepthReconstruction.stableDepth([.nan,.nan,0,0,0.5,0.5,0.5,0.5]))
        XCTAssertNil(TrueDepthReconstruction.stableDepth([0.4,0.6,0.4,0.6,0.4,0.6,0.4,0.6]))
        XCTAssertEqual(TrueDepthReconstruction.stableDepth(Array(repeating:0.5,count:8))?.median,0.5)
    }
    func testEachFramesOwnCalibrationAndMirroringRejection() throws {
        let root=try Self.fixture();defer {try? FileManager.default.removeItem(at:root)}
        let path=root.appendingPathComponent("session.json")
        var session=try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:path)) as? [String:Any])
        var entries=try XCTUnwrap(session["av_depth"] as? [[String:Any]])
        var calibration=try XCTUnwrap(entries[0]["calibration"] as? [String:Any])
        calibration["intrinsics"]=[[60.01,0,32],[0,60.01,24],[0,0,1]]
        entries[0]["calibration"]=calibration;session["av_depth"]=entries
        try cameraJSONWrite(session,path)
        XCTAssertGreaterThan(try TrueDepthReconstruction.build(dataset:root).vertices.count,30)
        var frames=try XCTUnwrap(session["frames"] as? [[String:Any]])
        frames[0]["mirrored"]=true;session["frames"]=frames
        try cameraJSONWrite(session,path)
        XCTAssertThrowsError(try TrueDepthReconstruction.build(dataset:root))
    }
    func testBuildMeasuresDirectPointsAndExportsSelectionWithoutAffectingCalibration() throws {
        let root=try Self.fixture();defer {try? FileManager.default.removeItem(at:root)}
        let surface=try TrueDepthReconstruction.build(dataset:root)
        XCTAssertEqual(surface.vertices.count,30*22);XCTAssertGreaterThan(surface.triangles.count,0)
        let a=try XCTUnwrap(surface.sample(at:[0.25,0.25])),b=try XCTUnwrap(surface.sample(at:[0.5,0.25]))
        XCTAssertEqual(try XCTUnwrap(surface.measurement(a,b)["distance_mm"] as? Double),133.333333,accuracy:0.001)
        XCTAssertNil(surface.sample(at:[0,0]))
        let selected=surface.indices(in:[0.2,0.2,0.5,0.5]);XCTAssertLessThan(selected.count,surface.vertices.count)
        let out=root.appendingPathComponent("export");try surface.export(to:out,region:[0.2,0.2,0.5,0.5])
        let record=try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:out.appendingPathComponent("inspection.json"))) as? [String:Any])
        XCTAssertEqual(record["crop_affects_calibration"] as? Bool,false)
        XCTAssertTrue(FileManager.default.fileExists(atPath:out.appendingPathComponent("points.ply").path))
        let top=surface.vertices[a].color;XCTAssertGreaterThan(top.x,top.z)
    }
    func testTrianglesDoNotBridgeDepthDiscontinuities() throws {
        let root=try Self.fixture(step:true);defer {try? FileManager.default.removeItem(at:root)}
        let surface=try TrueDepthReconstruction.build(dataset:root)
        for i in stride(from:0,to:surface.triangles.count,by:3) {
            let z=(0..<3).map {surface.vertices[Int(surface.triangles[i+$0])].position.z}
            XCTAssertLessThan((z.max() ?? 0)-(z.min() ?? 0),0.006)
        }
    }
}
