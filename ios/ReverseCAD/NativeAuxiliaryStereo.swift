import Foundation
import simd
import ReverseCADCore

/// Timestamp-aware three-camera geometry. Matches can refine an already
/// observed object sample, never create a surface in a depth/mask hole.
enum NativeAuxiliaryStereo {
    struct Pose {let time:Double;let matrix:simd_float4x4}
    static func trajectory(_ root:URL)->[Pose] {
        guard let object=try? NativeCalibration.object(root.appendingPathComponent("capture_diagnostics.json")),let rows=object["tracking"] as? [[String:Any]] else{return []}
        return rows.compactMap {r in
            guard r["tracked"] as? Bool==true,let time=r["time_s"] as? Double,let p=r["pose"] as? [Double],p.count==16 else{return nil}
            return Pose(time:time,matrix:NativeRegistration.opticalAxes*NativeRegistration.matrix(p))
        }.sorted{$0.time<$1.time}
    }
    static func at(_ time:Double,in poses:[Pose])->simd_float4x4? {
        guard poses.count>=2,time>=poses[0].time,time<=poses[poses.count-1].time,
              let i=poses.indices.dropFirst().first(where:{poses[$0].time>=time}) else{return nil}
        let a=poses[i-1],b=poses[i],gap=b.time-a.time
        guard gap>0,gap<=0.6 else{return nil}
        let f=Float((time-a.time)/gap),ta=SIMD3(a.matrix.columns.3.x,a.matrix.columns.3.y,a.matrix.columns.3.z),tb=SIMD3(b.matrix.columns.3.x,b.matrix.columns.3.y,b.matrix.columns.3.z)
        guard simd_distance(ta,tb)<0.15 else{return nil}
        let qa=simd_quatf(a.matrix),qb=simd_quatf(b.matrix)
        guard 2*acos(min(1,abs(simd_dot(qa.vector,qb.vector))))<0.35 else{return nil}
        var m=simd_float4x4(simd_slerp(qa,qb,f));m.columns.3=SIMD4(ta*(1-f)+tb*f,1);return m
    }
    static func extrinsic(_ values:[Double]) throws -> simd_float4x4 {
        guard values.count==12,values.allSatisfy(\.isFinite) else{throw ServiceFailure(message:"Missing physical camera alignment.")}
        let v=values.map{Float($0)}
        let m=simd_float4x4(columns:(SIMD4(v[0],v[1],v[2],0),SIMD4(v[3],v[4],v[5],0),SIMD4(v[6],v[7],v[8],0),SIMD4(v[9]*0.001,v[10]*0.001,v[11]*0.001,1)))
        try Geometry.validateRigidTransform(ARKitCaptureProvider.columnMajor(m))
        let baseline=simd_length(SIMD3(m.columns.3.x,m.columns.3.y,m.columns.3.z))
        guard baseline>0.001,baseline<0.08 else{throw ServiceFailure(message:"Physical camera baseline is invalid.")};return m
    }
    static func run(_ obs:inout NativeScanObservation,poses:[Pose]) throws -> [String:Int] {
        guard let value=obs.frame.multiCamera,let raw=try JSONSerialization.jsonObject(with:JSONEncoder().encode(value)) as? [String:Any],
              let cameras=raw["cameras"] as? [String:[String:Any]],let path=raw["calibration_path"] as? String else{return [:]}
        let calibration=try NativeCalibration.object(CaptureIO.safeURL(directory:obs.root,path:path))
        try obs.loadFeatures()
        guard let primary=obs.image,let features=obs.features,let primaryRaw=at(obs.frame.timestampS,in:poses) else{return [:]}
        let poseCorrection=obs.opticalWorld*simd_inverse(primaryRaw)
        var counts=[String:Int]()
        for name in ["ultra","tele"] {
            try Task.checkCancellation()
            guard let sensor=cameras[name],let imagePath=sensor["rgb_path"] as? String,let values=sensor["intrinsics"] as? [Double],
                  let width=sensor["width"] as? Int,let height=sensor["height"] as? Int,let time=sensor["timestamp_s"] as? Double,
                  let timed=at(time,in:poses),let model=calibration[name] as? [String:Any],let ex=model["from_wide_extrinsics_column_major_mm"] as? [Double] else{continue}
            let image=try NativeImage.read(CaptureIO.safeURL(directory:obs.root,path:imagePath)),auxFeatures=image.features()
            let ks=try Geometry.scaledIntrinsics(values,fromWidth:width,fromHeight:height,toWidth:image.width,toHeight:image.height).map{Float($0)}
            let k=simd_float3x3(columns:(SIMD3(ks[0],ks[1],ks[2]),SIMD3(ks[3],ks[4],ks[5]),SIMD3(ks[6],ks[7],ks[8])))
            let auxWorld=poseCorrection*timed*simd_inverse(try extrinsic(ex))
            let relative=simd_inverse(obs.opticalWorld)*auxWorld,origin=SIMD3(relative.columns.3.x,relative.columns.3.y,relative.columns.3.z)
            let rotation=simd_float3x3(columns:(SIMD3(relative.columns.0.x,relative.columns.0.y,relative.columns.0.z),SIMD3(relative.columns.1.x,relative.columns.1.y,relative.columns.1.z),SIMD3(relative.columns.2.x,relative.columns.2.y,relative.columns.2.z)))
            let matches=NativeImage.matches(features,auxFeatures)
            var links=[NativeCalibration.Link]()
            for (i,j) in matches {
                guard let p=obs.worldPoint(features[i].point,imageWidth:primary.width,imageHeight:primary.height,requireMask:true) else{continue}
                links.append(.init(point:p,observed:auxFeatures[j].point,camera:auxWorld,k:k))
            }
            let refinement=NativeCalibration.refine(links,worldFromReference:matrix_identity_float4x4),correction=refinement.0
            // A failed calibrated reprojection check cannot quietly contribute geometry.
            guard links.count>=12,refinement.2<3 else{counts[name]=0;continue}
            var accepted=0
            for (i,j) in matches {
                let uv=features[i].point
                guard let lidar=obs.cameraPoint(uv,imageWidth:primary.width,imageHeight:primary.height,requireMask:true) else{continue}
                let a=simd_normalize(lidar)
                var ray=simd_inverse(k)*SIMD3(auxFeatures[j].point.x,auxFeatures[j].point.y,1)
                let r2=ray.x*ray.x+ray.y*ray.y,f=exp(correction.x)*(1+correction.y*r2+correction.z*r2*r2)
                ray.x/=f;ray.y/=f
                let b=simd_normalize(rotation*ray),ab=simd_dot(a,b),den=1-ab*ab
                guard den>0.0003 else{continue}
                let ao=simd_dot(a,origin),bo=simd_dot(b,origin)
                let ta=(ao-ab*bo)/den,tb=(ab*ao-bo)/den
                guard ta>0,tb>0 else{continue}
                let pa=a*ta,pb=origin+b*tb
                guard simd_distance(pa,pb)<0.004,abs(pa.z-lidar.z)<max(0.008,lidar.z*0.015) else{continue}
                let x=Int((uv.x+0.5)*Float(obs.frame.depthWidth)/Float(primary.width)),y=Int((uv.y+0.5)*Float(obs.frame.depthHeight)/Float(primary.height)),w=obs.frame.depthWidth
                guard x>0,y>0,x<w-1,y<obs.frame.depthHeight-1 else{continue}
                let index=y*w+x
                obs.depth[index]=obs.depth[index]*0.75+pa.z*0.25;accepted+=1
            }
            counts[name]=accepted
        }
        return counts
    }
}
