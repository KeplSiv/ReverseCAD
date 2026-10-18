import XCTest
import simd
import UIKit
import ReverseCADCore
@testable import ReverseCAD

final class NativeReconstructionTests:XCTestCase {
    func temporary()throws->URL {let url=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString);try FileManager.default.createDirectory(at:url,withIntermediateDirectories:true);return url}
    func testFusionPreservesASubVoxelHole()throws {
        let p:[SIMD3<Float>]=[SIMD3(0,0,0),SIMD3(0.01,0,0),SIMD3(0.01,0.01,0),SIMD3(0,0.01,0),SIMD3(0.0042,0.0042,0),SIMD3(0.0052,0.0042,0),SIMD3(0.0052,0.0052,0),SIMD3(0.0042,0.0052,0)]
        let f=[[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]
        var fusion=NativeSurfaceFusion(voxel:0.002);try fusion.add(NativeMesh(vertices:p,faces:f))
        let result=try fusion.finish()
        XCTAssertEqual(result.faces.count,8);XCTAssertEqual(result.vertices.count,8);XCTAssertEqual(result.boundaryEdges,8)
    }
    func testLocalSavedSessionProducesVerifiedModelAndExportsWithoutService()throws {
        let root=try temporary();defer{try? FileManager.default.removeItem(at:root)}
        let fixture=try NativeValidation.fixture(at:root)
        let before=try CaptureIO.sha256(file:fixture.capture.appendingPathComponent("frames.jsonl"))
        let result=try NativeReconstruction.run(capture:fixture.capture,project:root,target:fixture.target,repair:false,thicknessMM:nil,progress:{_ in})
        XCTAssertEqual(result.report["processing_location"] as? String,"iPhone")
        XCTAssertEqual(result.report["network_requests"] as? Int,0)
        try VerifiedArtifactStore.verify(infos:result.infos,directory:result.directory)
        XCTAssertTrue(result.infos.contains{$0.name=="observed_object.stl"})
        XCTAssertTrue(result.infos.contains{$0.name=="observed_object.ply"})
        XCTAssertTrue(result.infos.contains{$0.name=="observed_object.step"})
        XCTAssertFalse(result.infos.contains{$0.name.contains("rgb") || $0.name.contains("key") || $0.name=="frames.jsonl"})
        XCTAssertEqual(try CaptureIO.sha256(file:fixture.capture.appendingPathComponent("frames.jsonl")),before)
        let model=try JSONDecoder().decode(MeshPreview.self,from:Data(contentsOf:result.directory.appendingPathComponent("scan_preview.json")))
        XCTAssertGreaterThan(model.triangles.count,100)
        let check=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("NativeExportValidation")
        try? FileManager.default.removeItem(at:check);try FileManager.default.copyItem(at:result.directory,to:check)
        print("NATIVE_EXPORT_VALIDATION \(check.path)")
        // Retry is a new complete revision using the same original capture.
        let retry=try NativeReconstruction.run(capture:fixture.capture,project:root,target:fixture.target,repair:false,thicknessMM:nil,progress:{_ in})
        XCTAssertNotEqual(retry.directory,result.directory)
        try VerifiedArtifactStore.verify(infos:result.infos,directory:result.directory)
    }
    func testCancellationDoesNotPublishOrDeleteCapture() async throws {
        let root=try temporary();defer{try? FileManager.default.removeItem(at:root)}
        let fixture=try NativeValidation.fixture(at:root)
        let task=Task {try Task.checkCancellation();return try NativeReconstruction.run(capture:fixture.capture,project:root,target:fixture.target,repair:false,thicknessMM:nil,progress:{_ in})}
        task.cancel()
        do {_ = try await task.value;XCTFail("Cancelled computation published a model")} catch is CancellationError {} catch {XCTFail(error.localizedDescription)}
        XCTAssertTrue(FileManager.default.fileExists(atPath:fixture.capture.appendingPathComponent("manifest.json").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath:root.appendingPathComponent("revisions").path))
    }
    func testGlobalRegistrationRejectsScaleAndHoldsOutIndependentPoints() {
        let points=(0..<160).map{i in SIMD3<Float>(Float(i%13)*0.02,Float(i%7)*0.03,Float(i%11)*0.015+0.4)}
        var transform=simd_float4x4(simd_quatf(angle:0.6,axis:simd_normalize(SIMD3<Float>(1,2,3))));transform.columns.3=SIMD4(0.3,-0.2,0.1,1)
        var pairs=points.map{NativeRegistration.Match(source:$0,target:NativeRegistration.point($0,transform))}
        for i in 0..<30 {pairs[i] = .init(source:points[i],target:points[i]+SIMD3(0.7,0.6,0.5))}
        let result=NativeRegistration.fit(pairs)
        XCTAssertNotNil(result);XCTAssertLessThan(result?.heldOutRMSE ?? 1,0.0001)
        XCTAssertNil(NativeRegistration.fit(points.map{.init(source:$0,target:$0*1.5)}))
    }
    func testRepairRequiresThicknessAndDoesNotFillInteriorHole()throws {
        var vertices=[SIMD3<Float>](),faces=[[Int]]()
        for y in 0...35 {for x in 0...50 {vertices.append(SIMD3(Float(x)*0.002,Float(y)*0.002,0))}}
        for y in 0..<35 {for x in 0..<50 {
            if x>=35 && y>=25 {continue}
            if (20...25).contains(x) && (13...18).contains(y) {continue}
            let a=y*51+x;faces += [[a,a+1,a+52],[a,a+52,a+51]]
        }}
        var fusion=NativeSurfaceFusion(voxel:0.0001);try fusion.add(NativeMesh(vertices:vertices,faces:faces))
        let mesh=try fusion.finish(),root=try temporary();defer{try? FileManager.default.removeItem(at:root)}
        let proposal=try NativeRepair.build(mesh:mesh,thicknessMM:nil,directory:root)
        XCTAssertNotNil(proposal.preview,proposal.reason);XCTAssertFalse(proposal.printable);XCTAssertTrue(proposal.files.isEmpty)
        let solid=try NativeRepair.build(mesh:mesh,thicknessMM:3,directory:root)
        XCTAssertTrue(solid.printable,solid.reason);XCTAssertEqual(solid.report["piece_count"] as? Int,1)
        XCTAssertEqual(solid.preview?.boundaryEdges,0)
        XCTAssertFalse(solid.preview?.vertices.contains{ $0.x>0.040 && $0.x<0.054 && $0.y>0.025 && $0.y<0.040 } ?? true)
        XCTAssertEqual(mesh.faces.count,faces.count)
        let stl=try Data(contentsOf:root.appendingPathComponent("repair_1.stl"))
        XCTAssertTrue(String(decoding:stl.prefix(80),as:UTF8.self).contains("inferred repair"))
        let step=try String(contentsOf:root.appendingPathComponent("repair_1.step"))
        XCTAssertTrue(step.contains("Inferred repair facets"))
        XCTAssertFalse(step.contains("Observed facets"))
    }
    func testAuxiliaryPoseUsesExposureTimeAndNeverExtrapolates()throws {
        var next=matrix_identity_float4x4;next.columns.3.x=0.02
        let poses=[NativeAuxiliaryStereo.Pose(time:1,matrix:matrix_identity_float4x4),.init(time:1.2,matrix:next)]
        XCTAssertEqual(try XCTUnwrap(NativeAuxiliaryStereo.at(1.1,in:poses)).columns.3.x,0.01,accuracy:0.0001)
        XCTAssertNil(NativeAuxiliaryStereo.at(0.99,in:poses));XCTAssertNil(NativeAuxiliaryStereo.at(1.21,in:poses))
        let matrix=try NativeAuxiliaryStereo.extrinsic([1,0,0,0,1,0,0,0,1,14,0,0])
        XCTAssertEqual(matrix.columns.3.x,0.014,accuracy:0.00001)
    }
    func testFrontReferenceRegistersAndCompatibleProfileReusesWithoutImages()throws {
        let root=try temporary();defer{try? FileManager.default.removeItem(at:root)}
        let fixture=try NativeValidation.fixture(at:root)
        var frame=try XCTUnwrap(CaptureIO.readFrames(directory:fixture.capture).first)
        let format=UIGraphicsImageRendererFormat();format.scale=1
        let image=UIGraphicsImageRenderer(size:CGSize(width:320,height:240),format:format).image {ctx in
            var seed:UInt64=42
            for y in stride(from:0,to:240,by:3) {for x in stride(from:0,to:320,by:3) {
                seed=seed &* 6364136223846793005 &+ 1
                UIColor(white:CGFloat((seed>>32)%255)/255,alpha:1).setFill();ctx.fill(CGRect(x:x,y:y,width:3,height:3))
            }}
        }
        try XCTUnwrap(image.jpegData(compressionQuality:1)).write(to:fixture.capture.appendingPathComponent(frame.rgbPath))
        let z=[Float](repeating:0.5,count:160*120)
        try z.withUnsafeBytes{Data($0)}.write(to:fixture.capture.appendingPathComponent(try XCTUnwrap(frame.depthPath)))
        let confidence=Data(repeating:2,count:160*120)
        try confidence.write(to:fixture.capture.appendingPathComponent(try XCTUnwrap(frame.confidencePath)))
        frame.worldCamera=Geometry.identity
        let observation=try NativeScanObservation(root:fixture.capture,frame:frame)
        let front=fixture.capture.appendingPathComponent("calibration/front")
        try FileManager.default.createDirectory(at:front,withIntermediateDirectories:true)
        try FileManager.default.copyItem(at:fixture.capture.appendingPathComponent(frame.rgbPath),to:front.appendingPathComponent("front.jpg"))
        var map=[Float]()
        for y in 0..<120 {for x in 0..<160 {
            let p=simd_inverse(observation.k)*SIMD3(Float(x),Float(y),1)*0.5
            map += [p.x,p.y,p.z,0.003]
        }}
        try map.withUnsafeBytes{Data($0)}.write(to:front.appendingPathComponent("points.f32"))
        try cameraJSONWrite(["rgb":"front.jpg","points":"points.f32","width":160,"height":120,"assets":["front.jpg":try CaptureIO.sha256(file:front.appendingPathComponent("front.jpg")),"points.f32":try CaptureIO.sha256(file:front.appendingPathComponent("points.f32"))]],front.appendingPathComponent("reference-evidence.json"))
        var setup:[String:Any]=["same_object_required":true,"reference_archive_sha256":"test-reference","device_identity_sha256":"test-device"]
        try cameraJSONWrite(setup,fixture.capture.appendingPathComponent("calibration/setup.json"))
        var observations=[observation]
        let result=try NativeCalibration.run(capture:fixture.capture,observations:&observations)
        XCTAssertEqual(result.report["reference_registered"] as? Bool,true)
        XCTAssertEqual(result.report["depth_scale_fitted"] as? Bool,false)
        setup["same_object_required"]=false
        try cameraJSONWrite(setup,fixture.capture.appendingPathComponent("calibration/setup.json"))
        try cameraJSONWrite(result.report,fixture.capture.appendingPathComponent("calibration/active-rear-profile.json"))
        try FileManager.default.removeItem(at:front)
        let reused=try NativeCalibration.run(capture:fixture.capture,observations:&observations)
        XCTAssertEqual(reused.report["status"] as? String,"reused_compatible_reference")
    }
    @MainActor func testNormalAppEntryReconstructsWithUnavailableServiceAndRestoresRevision() async throws {
        let root=try temporary();defer{try? FileManager.default.removeItem(at:root)}
        let model=AppModel(rootURL:root)
        model.create(name:"Local integration fixture",synthetic:false)
        let project=try XCTUnwrap(model.projectDirectory)
        let fixture=try NativeValidation.fixture(at:project)
        let scan=try XCTUnwrap(model.scanDirectory)
        try FileManager.default.moveItem(at:fixture.capture,to:scan)
        model.didCapture(scan)
        model.serverURL="http://127.0.0.1:1";model.token=""
        model.update{$0.repairScope="standalone_scan";$0.scanTarget=try? JSONSerialization.data(withJSONObject:fixture.target)}
        model.uploadAndReconstruct()
        for _ in 0..<300 where model.busy {try await Task.sleep(for:.milliseconds(100))}
        XCTAssertFalse(model.busy);XCTAssertNil(model.error);XCTAssertNotNil(model.scanMesh)
        XCTAssertTrue(model.standaloneExportFormats.contains("STL"))
        let expected=model.scanMesh
        // Simulate a crash that left obsolete root caches after publication.
        try? FileManager.default.removeItem(at:project.appendingPathComponent("scan_preview.json"))
        try? FileManager.default.removeItem(at:project.appendingPathComponent("reconstruction.json"))
        model.loadDerived()
        XCTAssertEqual(model.scanMesh,expected)
        XCTAssertTrue(model.standaloneExportFormats.contains("STL"))
    }
}
