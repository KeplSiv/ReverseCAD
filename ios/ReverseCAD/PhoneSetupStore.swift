import Foundation
import UIKit
import Vision
import ReverseCADCore

/// Both product flows share this setup. An old archive alone cannot satisfy the first-use gate.
struct PhoneSetupRecord: Codable, Sendable {
    let version: Int
    let directory: String
    let archive: String
    let archiveSHA256: String
    let evidenceSHA256: String
    let review: JevReferenceReview
    var deviceIdentitySHA256: String?
    var completedScanID: String?
}

enum PhoneSetupStore {
    static var directory: URL { FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("PhoneCalibrationProfiles") }
    static var deviceIdentity: String { CaptureIO.sha256(Data((UIDevice.current.identifierForVendor?.uuidString ?? "unavailable").utf8)) }
    static func load(at directory: URL = directory, deviceIdentity expectedDevice: String? = nil) -> PhoneSetupRecord? {
        guard let data=try? Data(contentsOf:directory.appendingPathComponent("setup.json")),
              let record=try? JSONDecoder().decode(PhoneSetupRecord.self,from:data),record.version==1,record.review.accepted,record.deviceIdentitySHA256==(expectedDevice ?? deviceIdentity),
              (try? CaptureIO.sha256(file:URL(fileURLWithPath:record.archive)))==record.archiveSHA256,
              (try? CaptureIO.sha256(file:URL(fileURLWithPath:record.directory).appendingPathComponent("reference-evidence.json")))==record.evidenceSHA256 else {return nil}
        return record
    }
    static func save(root: URL,archive: URL,review: JevReferenceReview,at directory: URL = directory) throws {
        guard review.accepted else {throw ServiceFailure(message:"The front reference has not passed the scene check.")}
        let record=PhoneSetupRecord(version:1,directory:root.path,archive:archive.path,archiveSHA256:try CaptureIO.sha256(file:archive),evidenceSHA256:try CaptureIO.sha256(file:root.appendingPathComponent("reference-evidence.json")),review:review,deviceIdentitySHA256:deviceIdentity)
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        try PhoneCalibrationProfile(referenceArchiveSHA256:record.archiveSHA256,referenceApproved:true).save(directory:directory)
        try CaptureIO.atomicWrite(record,to:directory.appendingPathComponent("setup.json"))
    }
    static func attach(to capture: URL) throws {
        guard let record=load() else {throw ServiceFailure(message:"Set up this phone with a front depth reference before its first scan.")}
        let source=URL(fileURLWithPath:record.directory),target=capture.appendingPathComponent("calibration/front")
        try FileManager.default.createDirectory(at:target,withIntermediateDirectories:true)
        let evidence=try JSONSerialization.jsonObject(with:Data(contentsOf:source.appendingPathComponent("reference-evidence.json"))) as? [String:Any]
        guard let assets=evidence?["assets"] as? [String:String] else {throw ServiceFailure(message:"The saved reference evidence is incomplete.")}
        for (name,hash) in assets {
            let file=try CaptureIO.safeURL(directory:source,path:name)
            guard try CaptureIO.sha256(file:file)==hash else {throw ServiceFailure(message:"The saved front reference changed. Repeat phone setup.")}
            let dest=try CaptureIO.safeURL(directory:target,path:name)
            try FileManager.default.createDirectory(at:dest.deletingLastPathComponent(),withIntermediateDirectories:true)
            if FileManager.default.fileExists(atPath:dest.path) {
                guard try CaptureIO.sha256(file:dest)==hash else {throw ServiceFailure(message:"The scan contains a different front reference.")}
            } else {try FileManager.default.copyItem(at:file,to:dest)}
        }
        try Data(contentsOf:source.appendingPathComponent("reference-evidence.json")).write(to:target.appendingPathComponent("reference-evidence.json"),options:.atomic)
        try CaptureIO.atomicWrite(record.review,to:target.appendingPathComponent("scene-review.json"))
        try cameraJSONWrite(["schema_version":1,"reference_archive_sha256":record.archiveSHA256,"evidence_sha256":record.evidenceSHA256,"device_identity_sha256":deviceIdentity,
                             "same_object_required":record.completedScanID == nil,"first_completed_scan_id":record.completedScanID as Any? ?? NSNull()],capture.appendingPathComponent("calibration/setup.json"))
        let active=directory.appendingPathComponent("active-rear-profile.json")
        if record.completedScanID != nil,let data=try? Data(contentsOf:active),
           let profile=try JSONSerialization.jsonObject(with:data) as? [String:Any],profile["reference_archive_sha256"] as? String==record.archiveSHA256 {
            try data.write(to:capture.appendingPathComponent("calibration/active-rear-profile.json"),options:.atomic)
        }
    }
    static func complete(result: URL,scanID: String,at directory: URL = directory) throws {
        guard var record=load(at:directory),let object=try JSONSerialization.jsonObject(with:Data(contentsOf:result)) as? [String:Any],
              object["reference_archive_sha256"] as? String==record.archiveSHA256,
              object["device_identity_sha256"] as? String==record.deviceIdentitySHA256,
              object["reference_registered"] as? Bool==true else {return}
        record.completedScanID=record.completedScanID ?? scanID
        let revisions=directory.appendingPathComponent("rear-revisions")
        try FileManager.default.createDirectory(at:revisions,withIntermediateDirectories:true)
        let copy=revisions.appendingPathComponent(UUID().uuidString+".json")
        try FileManager.default.copyItem(at:result,to:copy)
        if object["reference_registered"] as? Bool==true {
            try Data(contentsOf:result).write(to:directory.appendingPathComponent("active-rear-profile.json"),options:.atomic)
        }
        try CaptureIO.atomicWrite(record,to:directory.appendingPathComponent("setup.json"))
    }
}

enum FrontReferenceEvidence {
    static func prepare(root: URL,box: CGRect = SelectionBox.initial) throws -> (image: URL, metrics: [String:Any]) {
        let surface=try TrueDepthReconstruction.build(dataset:root)
        let selected=surface.indices(in:[box.minX,box.minY,box.maxX,box.maxY])
        let selectedFraction=Double(selected.count)/max(1,Double(surface.width*surface.height)*box.width*box.height)
        // The rectangle may cover only one ninth of the image. Judge numerical
        // coverage inside that selection, not against unrelated empty background.
        guard surface.summary["single_frame_fallback"]==0,selected.count>=100,selectedFraction>=0.15 else {
            throw ServiceFailure(message:"Too little stable front depth. Move closer, improve the light, and hold the phone still. Your original capture is saved.")
        }
        let color=try TrueDepthReconstruction.safeAsset(surface.colorPath,root:root)
        guard let image=UIImage(contentsOfFile:color.path)?.cgImage else {throw ServiceFailure(message:"The reference photo could not be read.")}
        guard let session=try JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("session.json"))) as? [String:Any],
              let frames=session["frames"] as? [[String:Any]],frames.count>=6 else {throw ServiceFailure(message:"The front reference is incomplete.")}
        var maximumShift=0.0
        for frame in frames {
            try Task.checkCancellation()
            guard let path=frame["rgb"] as? String else {continue}
            let registration=VNHomographicImageRegistrationRequest(targetedImageURL:try TrueDepthReconstruction.safeAsset(path,root:root))
            try VNImageRequestHandler(cgImage:image).perform([registration])
            guard let transform=registration.results?.first?.warpTransform else {throw ServiceFailure(message:"The front reference is too unclear to track. Improve the light and try again.")}
            // Translation alone misses rotation and perspective motion. Check
            // the image corners and center before pooling stationary depth.
            for p in [SIMD3<Float>(0,0,1),SIMD3(Float(image.width),0,1),SIMD3(0,Float(image.height),1),SIMD3(Float(image.width),Float(image.height),1),SIMD3(Float(image.width)/2,Float(image.height)/2,1)] {
                let q=transform*p
                guard q.z.isFinite,abs(q.z)>0.000001 else {throw ServiceFailure(message:"The reference moved too much to align. Hold the phone still and try again.")}
                maximumShift=max(maximumShift,Double(hypot(q.x/q.z-p.x,q.y/q.z-p.y)))
            }
        }
        guard maximumShift<=3 else {throw ServiceFailure(message:"The phone moved during the front reference. Hold it still for this short burst, then walk around the object during scanning.")}
        let cells=Set(surface.vertices.map{min(3,Int($0.imagePoint.x*4))+4*min(3,Int($0.imagePoint.y*4))})
        // Dense correspondence map uses the already-tested per-frame calibration and rejects mixed edges.
        var points=[Float](repeating: .nan,count:surface.width*surface.height*4)
        for vertex in surface.vertices {
            let i=(Int(vertex.depthPixel.y)*surface.width+Int(vertex.depthPixel.x))*4
            points[i]=vertex.position.x;points[i+1]=vertex.position.y;points[i+2]=vertex.position.z;points[i+3]=vertex.sigmaZ
        }
        let pointPath="reference-points.f32"
        try points.withUnsafeBytes{Data($0)}.write(to:root.appendingPathComponent(pointPath),options:.atomic)
        var metrics:[String:Any]=surface.summary
        metrics["maximum_burst_corner_motion_px"]=maximumShift;metrics["supported_cells_of_16"]=cells.count
        metrics["selected_stable_fraction"]=selectedFraction;metrics["selected_supported_points"]=selected.count
        let evidence:[String:Any]=["schema_version":1,"source":"synchronized_front_truedepth_and_selfie_rgb","coordinate_frame":"front_optical_x_right_y_down_z_forward_metres","depth_kind":"optical_axis_z","rgb":surface.colorPath,
                                  "rgb_width":image.width,"rgb_height":image.height,"points":pointPath,"width":surface.width,"height":surface.height,"point_layout":"little_endian_float32_xyz_sigma_z","metrics":metrics,
                                  "assets":[surface.colorPath:try CaptureIO.sha256(file:color),pointPath:try CaptureIO.sha256(file:root.appendingPathComponent(pointPath))],
                                  "accuracy":"Measured TrueDepth reference; systematic error remains possible. No category or Jev-derived dimensions."]
        try cameraJSONWrite(evidence,root.appendingPathComponent("reference-evidence.json"))
        return (color,metrics)
    }
}

@MainActor final class FrontReferenceReviewModel: ObservableObject {
    @Published var working=false
    @Published var message=""
    @Published var review:JevReferenceReview?
    @Published var image:UIImage?
    private var task:Task<Void,Never>?
    private var generation=UUID()
    private var retryAfter=Date.distantPast
    func cancel() {generation=UUID();task?.cancel();task=nil;working=false}
    func check(root:URL,box:CGRect) {
        guard !working else {return}
        guard Date()>=retryAfter else {message="Jev is rate limited. Retry in \(Int(ceil(retryAfter.timeIntervalSinceNow))) seconds.";return}
        cancel();let epoch=generation;review=nil;working=true;message="Checking front depth and scene…"
        // Let the user adjust the saved selection even when its original box
        // has insufficient depth; a failed check never requires a new scan.
        if let data=try? Data(contentsOf:root.appendingPathComponent("session.json")),
           let session=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
           let frames=session["frames"] as? [[String:Any]], !frames.isEmpty,
           let path=frames[frames.count/2]["rgb"] as? String,
           let url=try? TrueDepthReconstruction.safeAsset(path,root:root) {image=UIImage(contentsOfFile:url.path)}
        task=Task {
            do {
                let worker=Task.detached {try FrontReferenceEvidence.prepare(root:root,box:box)}
                let result=try await withTaskCancellationHandler(operation:{try await worker.value},onCancel:{worker.cancel()})
                try Task.checkCancellation();guard epoch==generation else{return}
                image=UIImage(contentsOfFile:result.image.path);message="Jev is checking this first object…"
                let jpeg=try CapturedObjectWorkflow.requestImage(result.image)
                let verdict=try await JevClient().reviewReference(jpeg:jpeg,box:box,apiKey:ReverseCADJevConfiguration.apiKey())
                try Task.checkCancellation();guard epoch==generation else{return}
                review=verdict;message=verdict.guidance
            } catch {
                guard epoch==generation else{return}
                message=error is CancellationError ? "Cancelled. The saved reference can be checked again." : error.localizedDescription
                if let error=error as? JevClientError {retryAfter=Date().addingTimeInterval(error.retryAfter)}
            }
            if epoch==generation {working=false;task=nil}
        }
    }
}
