import XCTest
import ReverseCADCore
import UIKit
@testable import ReverseCAD

final class PhoneSetupTests: XCTestCase {
    func testStationarySyntheticReferenceProducesPortableMap() throws {
        let root=try TrueDepthReconstructionTests.fixture()
        defer {try? FileManager.default.removeItem(at:root)}
        let format=UIGraphicsImageRendererFormat();format.scale=1
        let image=UIGraphicsImageRenderer(size:CGSize(width:320,height:240),format:format).image {context in
            for y in 0..<60 {for x in 0..<80 {
                let seed=(x*73856093) ^ (y*19349663)
                UIColor(white:CGFloat(seed%251)/250,alpha:1).setFill()
                context.fill(CGRect(x:x*4,y:y*4,width:4,height:4))
            }}
        }
        try XCTUnwrap(image.pngData()).write(to:root.appendingPathComponent("rgb.png"))
        let file=root.appendingPathComponent("session.json")
        var session=try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:file)) as? [String:Any])
        session["frames"]=(session["frames"] as! [[String:Any]]).map {frame in var f=frame;f["width"]=320;f["height"]=240;return f}
        session["av_depth"]=(session["av_depth"] as! [[String:Any]]).map {entry in
            var e=entry,c=e["calibration"] as! [String:Any]
            c["intrinsics"]=[[300,0,160],[0,300,120],[0,0,1]];c["reference_size"]=[320,240];c["distortion_center"]=[160,120];e["calibration"]=c;return e
        }
        try cameraJSONWrite(session,file)
        let result=try FrontReferenceEvidence.prepare(root:root,box:CGRect(x:0,y:0,width:1,height:1))
        XCTAssertEqual(result.image.lastPathComponent,"rgb.png")
        XCTAssertGreaterThan(result.metrics["selected_supported_points"] as? Int ?? 0,100)
        XCTAssertEqual(try Data(contentsOf:root.appendingPathComponent("reference-points.f32")).count,32*24*16)
        XCTAssertTrue(FileManager.default.fileExists(atPath:root.appendingPathComponent("reference-evidence.json").path))
    }
    func testFirstUseGateRequiresApprovedReferenceAndRejectsChangedEvidence() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer {try? FileManager.default.removeItem(at:root)}
        let source=root.appendingPathComponent("source"),profiles=root.appendingPathComponent("profiles")
        try FileManager.default.createDirectory(at:source,withIntermediateDirectories:true)
        let archive=source.appendingPathComponent("reference.zip")
        try Data("original".utf8).write(to:archive)
        let evidence=source.appendingPathComponent("reference-evidence.json")
        try Data("evidence".utf8).write(to:evidence)
        let reviewJSON=Data("{\"model\":\"fixture\",\"imageSHA256\":\"sample\",\"decision\":\"adequate\",\"confidence\":0.9,\"box\":{\"left\":0.1,\"top\":0.1,\"right\":0.9,\"bottom\":0.9}}".utf8)
        let review=try JSONDecoder().decode(JevReferenceReview.self,from:reviewJSON)
        XCTAssertNil(PhoneSetupStore.load(at:profiles))
        try PhoneSetupStore.save(root:source,archive:archive,review:review,at:profiles)
        XCTAssertNotNil(PhoneSetupStore.load(at:profiles))
        let profile=try JSONDecoder().decode(PhoneCalibrationProfile.self,from:Data(contentsOf:profiles.appendingPathComponent("current.json")))
        XCTAssertEqual(profile.status,"front_reference_approved")
        XCTAssertNil(profile.frontToRearTransform)
        let result=source.appendingPathComponent("phone-calibration.json")
        try cameraJSONWrite(["reference_archive_sha256":"wrong-reference","reference_registered":true],result)
        try PhoneSetupStore.complete(result:result,scanID:"incorrect",at:profiles)
        XCTAssertNil(PhoneSetupStore.load(at:profiles)?.completedScanID)
        try cameraJSONWrite(["reference_archive_sha256":CaptureIO.sha256(file:archive),"device_identity_sha256":"different-phone","reference_registered":true,"correction_applied":false],result)
        try PhoneSetupStore.complete(result:result,scanID:"incorrect-device",at:profiles)
        XCTAssertNil(PhoneSetupStore.load(at:profiles)?.completedScanID)
        try cameraJSONWrite(["reference_archive_sha256":CaptureIO.sha256(file:archive),"device_identity_sha256":PhoneSetupStore.deviceIdentity,"reference_registered":true,"correction_applied":false],result)
        try PhoneSetupStore.complete(result:result,scanID:"first",at:profiles)
        XCTAssertEqual(PhoneSetupStore.load(at:profiles)?.completedScanID,"first")
        try Data("changed".utf8).write(to:evidence)
        XCTAssertNil(PhoneSetupStore.load(at:profiles))
    }

    func testMovingPhysicalReferenceIsRejectedWithoutChangingOriginals() throws {
        let source=URL(fileURLWithPath:"/Users/pranav/frankly/build/validation-v3/capture-2026-10-18T11-35-28Z-F63307")
        guard FileManager.default.fileExists(atPath:source.appendingPathComponent("session.json").path) else {throw XCTSkip("Saved phone reference is unavailable")}
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.copyItem(at:source,to:root)
        defer {try? FileManager.default.removeItem(at:root)}
        // The known ruler occupies a narrow vertical strip in the original,
        // unrotated image; background coverage is not object coverage.
        let original=try CaptureIO.sha256(file:root.appendingPathComponent("session.json"))
        XCTAssertThrowsError(try FrontReferenceEvidence.prepare(root:root,box:CGRect(x:0.39,y:0.1,width:0.13,height:0.8))) {error in
            XCTAssertTrue(error.localizedDescription.contains("moved"),error.localizedDescription)
        }
        XCTAssertEqual(try CaptureIO.sha256(file:root.appendingPathComponent("session.json")),original)
        XCTAssertFalse(FileManager.default.fileExists(atPath:root.appendingPathComponent("reference-evidence.json").path))
    }
}
