import Foundation
import simd
import ReverseCADCore

enum NativeCalibration {
    struct Result {var report:[String:Any];var correction:SIMD3<Float>}
    struct Link {let point:SIMD3<Float>;let observed:SIMD2<Float>;let camera:simd_float4x4;let k:simd_float3x3}
    static func signature(_ observation:NativeScanObservation)->String {
        let f=observation.frame
        return "native-rgbd-v1-\(f.rgbWidth)x\(f.rgbHeight)-\(f.depthWidth)x\(f.depthHeight)-\(f.depthCalibrationMode ?? "pixel_center")"
    }
    static func run(capture:URL,observations:inout [NativeScanObservation]) throws -> Result {
        let path=capture.appendingPathComponent("calibration/setup.json")
        guard FileManager.default.fileExists(atPath:path.path) else {
            // Old saved scans remain usable; new capture entry points require setup.
            return Result(report:["status":"legacy_factory_calibration","reference_registered":false,"reason":"This older capture has no front reference; dimensions use recorded sensor scale.","physical_accuracy_validated":false],correction:.zero)
        }
        let setup=try object(path)
        guard let first=observations.first else {throw ServiceFailure(message:"No usable views for calibration.")}
        let sig=signature(first)
        let active=capture.appendingPathComponent("calibration/active-rear-profile.json")
        if setup["same_object_required"] as? Bool==false,let saved=try? object(active),
           saved["implementation"] as? String=="ios-native-rgbd-v1",saved["camera_signature"] as? String==sig,
           saved["device_identity_sha256"] as? String==setup["device_identity_sha256"] as? String,
           saved["reference_archive_sha256"] as? String==setup["reference_archive_sha256"] as? String,
           saved["reference_registered"] as? Bool==true,
           let referenceK=saved["reference_intrinsics"] as? [Double],referenceK.count==9,
           abs(referenceK[0]/first.frame.intrinsics[0]-1)<0.05,
           abs(referenceK[4]/first.frame.intrinsics[4]-1)<0.05,
           let p=saved["correction"] as? [Double],p.count==3,p.allSatisfy(\.isFinite) {
            var report=saved;report["status"]="reused_compatible_reference";report["reused"]=true
            return Result(report:report,correction:SIMD3(Float(p[0]),Float(p[1]),Float(p[2])))
        }
        let root=capture.appendingPathComponent("calibration/front")
        let evidence=try object(root.appendingPathComponent("reference-evidence.json"))
        guard let assets=evidence["assets"] as? [String:String],let imagePath=evidence["rgb"] as? String,
              let pointsPath=evidence["points"] as? String,let w=evidence["width"] as? Int,let h=evidence["height"] as? Int,w>0,h>0,w*h<=2_000_000 else {throw ServiceFailure(message:"The saved front reference is incomplete. Repeat phone setup.")}
        for (name,hash) in assets {guard try CaptureIO.sha256(file:CaptureIO.safeURL(directory:root,path:name))==hash else{throw ServiceFailure(message:"The saved front reference failed its integrity check.")}}
        let front=try NativeImage.read(CaptureIO.safeURL(directory:root,path:imagePath)),features=front.features()
        let bytes=try Data(contentsOf:CaptureIO.safeURL(directory:root,path:pointsPath))
        guard bytes.count==w*h*16 else{throw ServiceFailure(message:"The saved front depth map is incomplete.")}
        func point(_ p:SIMD2<Float>)->SIMD3<Float>? {
            let x=Int((p.x+0.5)*Float(w)/Float(front.width)),y=Int((p.y+0.5)*Float(h)/Float(front.height))
            guard x>0,y>0,x<w-1,y<h-1 else{return nil}
            let i=(y*w+x)*16
            let p=bytes.withUnsafeBytes{b in SIMD3(b.loadUnaligned(fromByteOffset:i,as:Float.self),b.loadUnaligned(fromByteOffset:i+4,as:Float.self),b.loadUnaligned(fromByteOffset:i+8,as:Float.self))}
            return p.x.isFinite && p.y.isFinite && p.z.isFinite && p.z>0.12 ? p:nil
        }
        var matches=[NativeRegistration.Match](),links=[Link](),seen=Set<Int>()
        let indices=Array(stride(from:0,to:observations.count,by:max(1,observations.count/8)).prefix(8))
        for i in indices {
            try Task.checkCancellation();try observations[i].loadFeatures()
            let obs=observations[i]
            guard let image=obs.image,let rear=obs.features else{continue}
            for (a,b) in NativeImage.matches(features,rear) where !seen.contains(a) {
                guard let p=point(features[a].point),let q=obs.worldPoint(rear[b].point,imageWidth:image.width,imageHeight:image.height) else{continue}
                seen.insert(a);matches.append(.init(source:p,target:q))
                let uv=SIMD2((rear[b].point.x+0.5)*Float(obs.frame.depthWidth)/Float(image.width)-0.5,(rear[b].point.y+0.5)*Float(obs.frame.depthHeight)/Float(image.height)-0.5)
                links.append(Link(point:p,observed:uv,camera:obs.opticalWorld,k:obs.k))
            }
        }
        guard let fit=NativeRegistration.fit(matches) else {
            throw ServiceFailure(message:"The front reference and rear views could not be registered reliably on this phone. Keep the capture. Add sharp views of the same textured side seen by the selfie camera, or repeat the front reference with this object.")
        }
        let supported=fit.inliers.map{links[$0]}
        let refinement=refine(supported,worldFromReference:fit.pose)
        let report:[String:Any]=["schema_version":1,"implementation":"ios-native-rgbd-v1","status":"reference_registered","camera_signature":sig,
            "reference_archive_sha256":setup["reference_archive_sha256"] ?? "","device_identity_sha256":setup["device_identity_sha256"] ?? "",
            "reference_registered":true,"reference_intrinsics":first.frame.intrinsics,"matched_distinct_reference_features":fit.inliers.count,"held_out_registration_rmse_m":fit.heldOutRMSE,
            "world_from_reference":ARKitCaptureProvider.columnMajor(fit.pose),"correction": [refinement.0.x,refinement.0.y,refinement.0.z],
            "correction_applied":refinement.0 != .zero,"held_out_reprojection_before_px":refinement.1,"held_out_reprojection_after_px":refinement.2,
            "depth_scale_fitted":false,"physical_accuracy_validated":false,"scope":"front depth to rear wide RGBD registration; bounded focal/radial correction, held-out image features; no category geometry"]
        return Result(report:report,correction:refinement.0)
    }
    static func refine(_ links:[Link],worldFromReference:simd_float4x4)->(SIMD3<Float>,Float,Float) {
        func loss(_ p:SIMD3<Float>,held:Bool)->Float {
            var errors=[Float]()
            for (i,link) in links.enumerated() where (i%4==0)==held {
                let q=NativeRegistration.point(link.point,simd_inverse(link.camera)*worldFromReference)
                guard q.z>0.05 else{continue}
                var ray=SIMD3(q.x/q.z,q.y/q.z,1)
                let r=ray.x*ray.x+ray.y*ray.y,f=exp(p.x)*(1+p.y*r+p.z*r*r)
                ray.x*=f;ray.y*=f;let uv=link.k*ray
                errors.append(min(20,simd_distance(SIMD2(uv.x,uv.y),link.observed)))
            }
            return errors.isEmpty ? 20:errors.reduce(0,+)/Float(errors.count)
        }
        let before=loss(.zero,held:true)
        guard links.count>=40 else{return (.zero,before,before)}
        var p=SIMD3<Float>.zero,steps=SIMD3<Float>(0.01,0.02,0.01)
        let bounds=SIMD3<Float>(0.025,0.08,0.05)
        for _ in 0..<16 {
            for axis in 0..<3 {for sign:Float in [-1,1] {
                var test=p;test[axis]+=steps[axis]*sign
                if abs(test[axis])<=bounds[axis],loss(test,held:false)<loss(p,held:false) {p=test}
            }}
            steps *= 0.8
        }
        let after=loss(p,held:true)
        guard after<before*0.9,after<2 else{return (.zero,before,before)}
        return (p,before,after)
    }
    static func object(_ url:URL)throws->[String:Any] {
        guard let result=try JSONSerialization.jsonObject(with:Data(contentsOf:url)) as? [String:Any] else {throw ServiceFailure(message:"Invalid saved scan metadata.")};return result
    }
}
