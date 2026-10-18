import Foundation
import UIKit
import AVFoundation
import simd

/// Calibration belongs to one delivered frame. Values may change during a burst.
struct TrueDepthFrameCalibration {
    let K:simd_float3x3
    let inverseK:simd_float3x3
    let size:SIMD2<Float>
    let center:SIMD2<Float>
    let inverse:[Float]
    let forward:[Float]?
    var radius:Float {simd_length(simd_max(center,size-center))}
    func magnification(_ r:Float,table:[Float]) -> Float {
        let index=min(Float(table.count-1),max(0,r/radius*Float(table.count-1)))
        let lo=min(table.count-2,Int(index)),a=index-Float(lo)
        return table[lo]*(1-a)+table[lo+1]*a
    }
    func ray(at pixel:SIMD2<Float>) -> SIMD3<Float> {
        let delta=pixel-center
        let rectified=center+delta*(1+magnification(simd_length(delta),table:inverse))
        let v=inverseK*SIMD3(rectified.x,rectified.y,1)
        return v/v.z
    }
    func observedPixel(for ray:SIMD3<Float>) -> SIMD2<Float> {
        let projected=K*ray
        let rectified=SIMD2(projected.x/projected.z,projected.y/projected.z)
        let delta=rectified-center,r=simd_length(delta)
        if let forward {return center+delta*(1+magnification(r,table:forward))}
        // Legacy files may lack the forward LUT. Invert the recorded inverse
        // radial map, rather than applying its correction in the wrong direction.
        guard r>0 else {return center}
        var lo:Float=0,hi=max(radius*2,r*2)
        for _ in 0..<24 {
            let mid=(lo+hi)/2
            if mid*(1+magnification(mid,table:inverse))<r {lo=mid} else {hi=mid}
        }
        return center+delta*((lo+hi)/2/r)
    }
    static func load(_ entry:[String:Any],root:URL) throws -> Self {
        guard let c=entry["calibration"] as? [String:Any],let numbers=c["intrinsics"] as? [[NSNumber]],numbers.count==3,numbers.allSatisfy({$0.count==3 && $0.allSatisfy({$0.floatValue.isFinite})}),
              let dimensionNumbers=c["reference_size"] as? [NSNumber],dimensionNumbers.count==2,dimensionNumbers.allSatisfy({$0.floatValue.isFinite && $0.floatValue>0}),
              let originNumbers=c["distortion_center"] as? [NSNumber],originNumbers.count==2,originNumbers.allSatisfy({$0.floatValue.isFinite}),
              let inverseFile=c["inverse_distortion_float32_table"] as? String else {throw CameraLabError.message("Frame is missing finite camera calibration")}
        let rows=numbers.map { $0.map(\.floatValue) },dims=dimensionNumbers.map(\.floatValue),origin=originNumbers.map(\.floatValue)
        let K=simd_float3x3(columns:(SIMD3(rows[0][0],rows[1][0],rows[2][0]),SIMD3(rows[0][1],rows[1][1],rows[2][1]),SIMD3(rows[0][2],rows[1][2],rows[2][2])))
        guard K[0][0]>0,K[1][1]>0,abs(K[0][2])<0.000001,abs(K[1][2])<0.000001,abs(K[2][2]-1)<0.000001,abs(simd_determinant(K))>0.000001 else {throw CameraLabError.message("Frame has invalid camera intrinsics")}
        func table(_ name:String) throws -> [Float] {
            let data=try Data(contentsOf:TrueDepthReconstruction.safeAsset(name,root:root))
            guard data.count>=8,data.count%4==0 else {throw CameraLabError.message("Frame has an invalid distortion lookup table")}
            let values:[Float]=data.withUnsafeBytes {b in (0..<data.count/4).map{b.loadUnaligned(fromByteOffset:$0*4,as:Float.self)}}
            guard values.allSatisfy({$0.isFinite && $0 > -0.95}) else {throw CameraLabError.message("Frame has nonfinite or noninvertible distortion")}
            return values
        }
        let inverse=try table(inverseFile)
        let forward=try (c["distortion_float32_table"] as? String).map {try table($0)}
        return Self(K:K,inverseK:simd_inverse(K),size:SIMD2(dims[0],dims[1]),center:SIMD2(origin[0],origin[1]),inverse:inverse,forward:forward)
    }
}

struct TrueDepthVertex:Sendable {
    let position:SIMD3<Float>
    let color:SIMD4<Float>
    let imagePoint:SIMD2<Float>
    let depthPixel:SIMD2<Int>
    let sigmaZ:Float
}

/// A measured visible surface in optical camera coordinates and metres.
/// Triangles connect only supported samples; they are a derived display surface.
struct TrueDepthReconstruction:Identifiable,Sendable {
    let id=UUID()
    let vertices:[TrueDepthVertex]
    let triangles:[UInt32]
    let pixelToVertex:[Int32]
    let width:Int
    let height:Int
    let frameID:String
    let colorPath:String
    let originalCount:Int
    let summary:[String:Double]

    static func rectifiedPoint(_ pixel:SIMD2<Float>,depth:Float,K:simd_float3x3,referenceSize:SIMD2<Float>,center:SIMD2<Float>,inverse:[Float]) throws -> SIMD3<Float> {
        guard inverse.count>=2,inverse.allSatisfy({$0.isFinite}),depth.isFinite,depth>0,
              pixel.x.isFinite,pixel.y.isFinite,center.x.isFinite,center.y.isFinite,
              referenceSize.x.isFinite,referenceSize.y.isFinite,referenceSize.x>0,referenceSize.y>0,
              abs(simd_determinant(K))>0.000001 else {throw CameraLabError.message("Missing calibration for the 3D reference")}
        let far=simd_max(center,referenceSize-center),radius=simd_length(far)
        let delta=pixel-center,r=simd_length(delta)
        let index=min(Float(inverse.count-1),max(0,r/radius*Float(inverse.count-1)))
        let lo=min(inverse.count-2,Int(index)),a=index-Float(lo)
        let magnification=inverse[lo]*(1-a)+inverse[lo+1]*a
        let p=center+delta*(1+magnification)
        var ray=simd_inverse(K)*SIMD3(p.x,p.y,1);ray/=ray.z
        let point=ray*depth
        guard point.x.isFinite,point.y.isFinite,point.z.isFinite else {throw CameraLabError.message("Invalid rectified reference ray")}
        return point
    }
    static func stableDepth(_ values:[Float]) -> (median:Float,mad:Float)? {
        let a=values.filter{$0.isFinite && $0>0}.sorted()
        guard a.count>=max(6,values.count*3/4) else {return nil}
        let z=a[a.count/2],dev=a.map{abs($0-z)}.sorted(),mad=dev[dev.count/2]
        guard mad<=max(0.003,z*0.01) else {return nil}
        return (z,mad)
    }
    static func depthPlane(_ entry:[String:Any],root:URL) throws -> (values:[Float],width:Int,height:Int) {
        guard let d=entry["depth"] as? [String:Any],let p=(d["planes"] as? [[String:Any]])?.first,
              let name=p["file"] as? String,let w=p["width"] as? Int,let h=p["height"] as? Int,
              let stride=p["row_bytes"] as? Int,let code=d["pixel_format"] as? UInt32,
              w>0,h>0,w<=4096,h<=4096,w*h<=2_000_000,[kCVPixelFormatType_DepthFloat16,kCVPixelFormatType_DepthFloat32].contains(code) else {throw CameraLabError.message("Invalid original depth plane")}
        let url=try safeAsset(name,root:root),data=try Data(contentsOf:url),bytes=code==kCVPixelFormatType_DepthFloat32 ? 4:2
        guard stride>=w*bytes,stride<=65536,data.count==stride*h else {throw CameraLabError.message("Depth plane bytes do not match metadata")}
        let values:[Float]=data.withUnsafeBytes { b in (0..<w*h).map {i in
            let offset=(i/w)*stride+(i%w)*bytes
            return bytes==4 ? b.loadUnaligned(fromByteOffset:offset,as:Float.self):Float(Float16(bitPattern:b.loadUnaligned(fromByteOffset:offset,as:UInt16.self)))
        }}
        return (values,w,h)
    }
    static func safeAsset(_ name:String,root:URL) throws -> URL {
        let file=root.appendingPathComponent(name).standardizedFileURL
        guard !name.hasPrefix("/"),!name.split(separator:"/").contains(".."),file.path.hasPrefix(root.standardizedFileURL.path+"/") else {throw CameraLabError.message("Unsafe reference asset path")}
        return file
    }
    static func build(dataset root:URL) throws -> Self {
        guard let session=try JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("session.json"))) as? [String:Any],
              session["complete"] as? Bool==true,let frames=session["frames"] as? [[String:Any]],let entries=session["av_depth"] as? [[String:Any]],entries.count>=6 else {throw CameraLabError.message("A complete TrueDepth burst is required")}
        let middle=entries[entries.count/2]
        guard let frameID=middle["rgb_frame"] as? String,let frame=frames.first(where:{$0["id"] as? String==frameID}),
              frame["camera"] as? String=="front",frame["mirrored"] as? Bool==false,frame["rotation_degrees"] as? Int==0,
              let rgb=frame["rgb"] as? String,
              let rgbW=frame["width"] as? Int,let rgbH=frame["height"] as? Int,
              let settings=frame["settings"] as? [String:Any],settings["zoom_factor"] as? Double==1,
              settings["video_scale_and_crop_factor"] as? Double==1,settings["geometric_correction_enabled"] as? Bool==false else {throw CameraLabError.message("Missing calibration or unsupported image transformation; no guessed 3D surface")}
        let reference=try TrueDepthFrameCalibration.load(middle,root:root)
        for frame in frames {
            guard frame["camera"] as? String == "front",frame["rotation_degrees"] as? Int == 0,frame["mirrored"] as? Bool == false,
                  frame["width"] as? Int == rgbW,frame["height"] as? Int == rgbH,
                  let settings=frame["settings"] as? [String:Any],settings["zoom_factor"] as? Double == 1,
                  settings["video_scale_and_crop_factor"] as? Double == 1,settings["geometric_correction_enabled"] as? Bool == false else {
                throw CameraLabError.message("Frame transform changed; no guessed crop or alignment")
            }
            if let aperture=frame["clean_aperture"] as? [Double] {
                guard aperture.count==4,abs(aperture[0])<0.01,abs(aperture[1])<0.01,abs(aperture[2]-Double(rgbW))<0.01,abs(aperture[3]-Double(rgbH))<0.01 else {throw CameraLabError.message("Cropped clean aperture is not supported for metric validation")}
            }
        }
        let calibrations=try entries.enumerated().map {index,entry -> TrueDepthFrameCalibration in
            guard entry["sensor"] as? String == "front_TrueDepth" else {throw CameraLabError.message("Frame \(index+1) is not front TrueDepth")}
            guard entry["is_filtered"] as? Bool == false else {throw CameraLabError.message("Frame \(index+1) depth is filtered")}
            guard entry["accuracy"] as? Int == AVDepthData.Accuracy.absolute.rawValue else {throw CameraLabError.message("Frame \(index+1) depth is relative, not metric")}
            guard let frameID=entry["rgb_frame"] as? String,frames.contains(where:{$0["id"] as? String == frameID}) else {throw CameraLabError.message("Frame \(index+1) has no synchronized color sample")}
            return try TrueDepthFrameCalibration.load(entry,root:root)
        }
        let depth=try entries.map {try depthPlane($0,root:root)}
        let w=depth[entries.count/2].width,h=depth[entries.count/2].height
        for (d,c) in zip(depth,calibrations) {
            guard abs(Float(d.width)/Float(d.height)-c.size.x/c.size.y)<0.001,
                  abs(Float(rgbW)/Float(rgbH)-c.size.x/c.size.y)<0.001 else {throw CameraLabError.message("Reference crop registration is unknown")}
        }
        let sameGrid=zip(calibrations,depth).map {c,d in
            c.K == reference.K && c.size == reference.size && c.center == reference.center && c.inverse == reference.inverse && d.width == w && d.height == h
        }
        var med=[Float](repeating:.nan,count:w*h),mad=med
        // Align samples by camera ray into the middle frame, using each frame's
        // own calibration. No RGB/depth holes are interpolated or filled.
        for y in 0..<h {for x in 0..<w {
            let ray=reference.ray(at:SIMD2(Float(x)/Float(w)*reference.size.x,Float(y)/Float(h)*reference.size.y))
            var values=[Float]()
            for (index,pair) in zip(calibrations,depth).enumerated() {
                let (c,d)=pair
                if sameGrid[index] {values.append(d.values[y*w+x]);continue}
                let p=c.observedPixel(for:ray)
                guard p.x.isFinite,p.y.isFinite else {values.append(.nan);continue}
                let fx=p.x/c.size.x*Float(d.width),fy=p.y/c.size.y*Float(d.height)
                guard fx >= -0.0001,fy >= -0.0001,fx<Float(d.width)-0.5,fy<Float(d.height)-0.5 else {values.append(.nan);continue}
                let dx=max(0,Int(fx.rounded())),dy=max(0,Int(fy.rounded()))
                values.append(d.values[dy*d.width+dx])
            }
            if let stats=stableDepth(values) {med[y*w+x]=stats.median;mad[y*w+x]=stats.mad}
        }}
        guard let image=UIImage(contentsOfFile:try safeAsset(rgb,root:root).path)?.cgImage else {throw CameraLabError.message("Missing reference colour image")}
        guard image.width==rgbW,image.height==rgbH else {throw CameraLabError.message("Colour image dimensions do not match calibration metadata")}
        var rgba=[UInt8](repeating:0,count:rgbW*rgbH*4)
        let rendered=rgba.withUnsafeMutableBytes {b -> Bool in
            guard let ctx=CGContext(data:b.baseAddress,width:rgbW,height:rgbH,bitsPerComponent:8,bytesPerRow:rgbW*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue) else {return false}
            ctx.draw(image,in:CGRect(x:0,y:0,width:rgbW,height:rgbH));return true
        }
        guard rendered else {throw CameraLabError.message("Colour decoding unavailable")}
        let temporalVariation=mad.filter{$0.isFinite}.sorted()
        let temporalSupported=med.filter{$0.isFinite}.count
        var vertices=[TrueDepthVertex](),map=[Int32](repeating:-1,count:w*h),edges=0
        func populateVertices() {
            vertices=[];map=[Int32](repeating:-1,count:w*h);edges=0
        for y in 1..<h-1 {for x in 1..<w-1 {
            let i=y*w+x,z=med[i];guard z.isFinite,z>0 else {continue}
            var local=[Float]();for dy in -1...1 {for dx in -1...1 {local.append(med[(y+dy)*w+x+dx])}}
            guard local.allSatisfy({$0.isFinite && $0>0}),let lo=local.min(),let hi=local.max(),hi-lo<=max(0.006,0.02*z) else {edges+=1;continue}
            let uv=SIMD2(Float(x)/Float(w),Float(y)/Float(h))
            let xyz=reference.ray(at:uv*reference.size)*z
            let px=min(rgbW-1,max(0,Int((uv.x*Float(rgbW)).rounded()))),py=min(rgbH-1,max(0,Int((uv.y*Float(rgbH)).rounded()))),colorIndex=(py*rgbW+px)*4
            map[i]=Int32(vertices.count)
            vertices.append(TrueDepthVertex(position:xyz,color:SIMD4(Float(rgba[colorIndex])/255,Float(rgba[colorIndex+1])/255,Float(rgba[colorIndex+2])/255,1),imagePoint:uv,depthPixel:SIMD2(x,y),sigmaZ:max(0.003,max(z*0.01,1.4826*mad[i]))))
        }}
        }
        populateVertices()
        var singleFrameFallback=false
        if vertices.count<30 {
            // Keep an inspectable native frame when the burst is not repeatable.
            // This is explicitly not a stable temporal reference or filled depth.
            med=depth[entries.count/2].values
            mad=[Float](repeating:0,count:w*h)
            populateVertices();singleFrameFallback=true
        }
        guard vertices.count>=30 else {throw CameraLabError.message("No usable native depth surface in this capture. Original data is saved.")}
        var triangles=[UInt32]()
        for y in 0..<h-1 {for x in 0..<w-1 {
            let quad=[map[y*w+x],map[y*w+x+1],map[(y+1)*w+x],map[(y+1)*w+x+1]]
            for t in [[quad[0],quad[1],quad[2]],[quad[1],quad[3],quad[2]]] where t.allSatisfy({$0>=0}) {
                let zs=t.map{vertices[Int($0)].position.z}
                if let lo=zs.min(),let hi=zs.max(),hi-lo<=max(0.006,lo*0.02) {triangles += t.map{UInt32($0)}}
            }
        }}
        var summary:[String:Double]=["frames_with_per_frame_calibration":Double(calibrations.count),"accepted_points":Double(vertices.count),
            "rejected_edge_or_ambiguous_samples":Double(edges),"surface_triangles":Double(triangles.count/3),"valid_fraction":Double(vertices.count)/Double(w*h),
            "temporal_supported_fraction":Double(temporalSupported)/Double(w*h),"single_frame_fallback":singleFrameFallback ? 1:0]
        if !temporalVariation.isEmpty {summary["median_temporal_mad_mm"]=Double(temporalVariation[temporalVariation.count/2])*1000}
        return Self(vertices:vertices,triangles:triangles,pixelToVertex:map,width:w,height:h,frameID:frameID,colorPath:rgb,originalCount:w*h,summary:summary)
    }
    func indices(in rect:[Double]?) -> [Int] {
        guard let r=rect,r.count==4 else {return Array(vertices.indices)}
        return vertices.indices.filter {i in let p=vertices[i].imagePoint;return Double(p.x)>=r[0] && Double(p.x)<=r[2] && Double(p.y)>=r[1] && Double(p.y)<=r[3]}
    }
    func sample(at normalized:[Double]) -> Int? {
        guard normalized.count==2,normalized.allSatisfy({$0.isFinite && (0...1).contains($0)}) else {return nil}
        let x=min(width-1,Int((normalized[0]*Double(width)).rounded())),y=min(height-1,Int((normalized[1]*Double(height)).rounded())),index=pixelToVertex[y*width+x]
        return index<0 ? nil:Int(index)
    }
    func measurement(_ a:Int,_ b:Int) -> [String:Any] {
        let first=vertices[a],second=vertices[b]
        let sigma=sqrt(first.sigmaZ*first.sigmaZ+second.sigmaZ*second.sigmaZ)
        return ["distance_mm":Double(simd_distance(first.position,second.position)*1000),"endpoints_optical_m":[[first.position.x,first.position.y,first.position.z],[second.position.x,second.position.y,second.position.z]],
                "normalized_image_points":[[first.imagePoint.x,first.imagePoint.y],[second.imagePoint.x,second.imagePoint.y]],"sampling":"two direct supported depth pixels; no edge extrapolation","frame_id":frameID,
                "depth_uncertainty_proxy_mm":Double(sigma*1000),"uncertainty_scope":"Assumed depth noise floor and temporal variation only; not a calibrated error bar. Shared systematic bias is unmeasured.","purpose":"inspection_only; this distance is not a calibration target"]
    }
    func export(to root:URL,region:[Double]?=nil,measurements:[[String:Any]]=[]) throws {
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let selected=indices(in:region),set=Set(selected)
        var ply="ply\nformat ascii 1.0\ncomment optical camera coordinates in metres; measured visible surface, not complete object\nelement vertex \(selected.count)\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
        var obj="# Derived supported surface in metres. No hole filling or occluded surfaces.\n",remap=[Int:Int]()
        for (j,i) in selected.enumerated() {
            let v=vertices[i],p=v.position,c=v.color;remap[i]=j+1
            ply += "\(p.x) \(p.y) \(p.z) \(Int(c.x*255)) \(Int(c.y*255)) \(Int(c.z*255))\n"
            obj += "v \(p.x) \(p.y) \(p.z)\n"
        }
        for i in stride(from:0,to:triangles.count,by:3) {
            let a=Int(triangles[i]),b=Int(triangles[i+1]),c=Int(triangles[i+2])
            if set.contains(a),set.contains(b),set.contains(c),let ra=remap[a],let rb=remap[b],let rc=remap[c] {obj += "f \(ra) \(rb) \(rc)\n"}
        }
        try ply.write(to:root.appendingPathComponent("points.ply"),atomically:true,encoding:.utf8)
        try obj.write(to:root.appendingPathComponent("surface.obj"),atomically:true,encoding:.utf8)
        try cameraJSONWrite(["schema":"truedepth-visible-surface/1","source_frame":frameID,"units":"m","coordinate_convention":"optical x right, y down, z forward","summary":summary,
            "preview_region":region as Any? ?? NSNull(),"selected_points":selected.count,"measurements":measurements,"triangles":"derived interpolation between accepted neighboring depth samples; no invented hidden surfaces",
            "accuracy":"TrueDepth measured reference with unknown systematic error; not certified ground truth","crop_affects_calibration":false],root.appendingPathComponent("inspection.json"))
    }
}

#if DEBUG
extension TrueDepthReconstruction {
    static func uiTestFixture() -> TrueDepthReconstruction {
        let w=32,h=24
        let vertices=(0..<w*h).map {i -> TrueDepthVertex in
            let x=Float(i%w)/Float(w),y=Float(i/w)/Float(h)
            return TrueDepthVertex(position:SIMD3((x-0.5)*0.24,(y-0.5)*0.18,0.5),color:SIMD4(0.8,0.55+0.3*x,0.25,1),imagePoint:SIMD2(x,y),depthPixel:SIMD2(i%w,i/w),sigmaZ:0.005)
        }
        var triangles=[UInt32]()
        for y in 0..<h-1 {for x in 0..<w-1 {let a=UInt32(y*w+x);triangles += [a,a+1,a+UInt32(w),a+1,a+UInt32(w)+1,a+UInt32(w)]}}
        return Self(vertices:vertices,triangles:triangles,pixelToVertex:(0..<w*h).map{Int32($0)},width:w,height:h,frameID:"SIMULATED-UI-FIXTURE",colorPath:"",originalCount:w*h,summary:["accepted_points":Double(w*h)])
    }
}
#endif
