import Foundation
import simd
import ReverseCADCore

struct NativeScanObservation {
    let root:URL
    var frame:CaptureFrame
    var depth:[Float]
    var mask:[UInt8]
    let confidence:[UInt8]
    var opticalWorld:simd_float4x4
    let k:simd_float3x3
    var correction=SIMD3<Float>.zero // log focal multiplier, k1, k2
    var image:NativeImage?
    var features:[NativeImage.Feature]?
    init(root:URL,frame:CaptureFrame,mask:Data?=nil) throws {
        self.root=root;self.frame=frame
        guard let path=frame.depthPath else{throw ServiceFailure(message:"This view has no saved depth.")}
        let d=try Data(contentsOf:CaptureIO.safeURL(directory:root,path:path))
        guard d.count==frame.depthWidth*frame.depthHeight*4 else {throw ServiceFailure(message:"A saved depth plane is incomplete.")}
        depth=d.withUnsafeBytes {b in (0..<d.count/4).map{b.loadUnaligned(fromByteOffset:$0*4,as:Float.self)}}
        if let path=frame.confidencePath {confidence=Array(try Data(contentsOf:CaptureIO.safeURL(directory:root,path:path)))}
        else {confidence=depth.map{$0.isFinite && $0>0 ? 1:0}}
        self.mask=mask.map(Array.init) ?? [UInt8](repeating:255,count:depth.count)
        guard confidence.count==depth.count,self.mask.count==depth.count else {throw ServiceFailure(message:"A saved selection or confidence plane is incomplete.")}
        let values=try Geometry.scaledIntrinsics(frame.intrinsics,fromWidth:frame.intrinsicsWidth,fromHeight:frame.intrinsicsHeight,toWidth:frame.depthWidth,toHeight:frame.depthHeight,mode:frame.depthCalibrationMode ?? "pixel_center").map{Float($0)}
        k=simd_float3x3(columns:(SIMD3(values[0],values[1],values[2]),SIMD3(values[3],values[4],values[5]),SIMD3(values[6],values[7],values[8])))
        opticalWorld=NativeRegistration.matrix(frame.worldCamera)*NativeRegistration.opticalAxes
    }
    mutating func loadFeatures() throws {
        if features != nil {return}
        let decoded=try NativeImage.read(CaptureIO.safeURL(directory:root,path:frame.rgbPath))
        image=decoded;features=decoded.features()
    }
    func cameraPoint(_ pixel:SIMD2<Float>,imageWidth:Int,imageHeight:Int,requireMask:Bool=false)->SIMD3<Float>? {
        let x=(pixel.x+0.5)*Float(frame.depthWidth)/Float(imageWidth)-0.5,y=(pixel.y+0.5)*Float(frame.depthHeight)/Float(imageHeight)-0.5
        let u=Int(x.rounded()),v=Int(y.rounded()),w=frame.depthWidth,h=frame.depthHeight
        guard u>0,v>0,u<w-1,v<h-1 else{return nil}
        let i=v*w+u,z=depth[i]
        guard z.isFinite,z>0.12,z<3,confidence[i]>=1,(!requireMask || mask[i]>0),
              [i-1,i+1,i-w,i+w].allSatisfy({depth[$0].isFinite && abs(depth[$0]-z)<max(0.012,z*0.025)}) else{return nil}
        var ray=simd_inverse(k)*SIMD3(x,y,1)
        let r2=ray.x*ray.x+ray.y*ray.y,factor=exp(correction.x)*(1+correction.y*r2+correction.z*r2*r2)
        ray.x/=factor;ray.y/=factor;return ray*z
    }
    func worldPoint(_ pixel:SIMD2<Float>,imageWidth:Int,imageHeight:Int,requireMask:Bool=false)->SIMD3<Float>? {
        cameraPoint(pixel,imageWidth:imageWidth,imageHeight:imageHeight,requireMask:requireMask).map{NativeRegistration.point($0,opticalWorld)}
    }
    func project(_ world:SIMD3<Float>)->(pixel:SIMD2<Float>,z:Float)? {
        let p=NativeRegistration.point(world,simd_inverse(opticalWorld))
        guard p.z>0.12,p.z<3 else{return nil}
        var ray=SIMD3(p.x/p.z,p.y/p.z,1),r2=(p.x*p.x+p.y*p.y)/(p.z*p.z)
        let factor=exp(correction.x)*(1+correction.y*r2+correction.z*r2*r2)
        ray.x*=factor;ray.y*=factor
        let uv=k*ray
        return (SIMD2(uv.x,uv.y),p.z)
    }
    static func matches(_ a:NativeScanObservation,_ b:NativeScanObservation)->[NativeRegistration.Match] {
        guard let ia=a.image,let ib=b.image,let fa=a.features,let fb=b.features else{return []}
        return NativeImage.matches(fa,fb).compactMap {i,j in
            guard let source=a.worldPoint(fa[i].point,imageWidth:ia.width,imageHeight:ia.height),let target=b.worldPoint(fb[j].point,imageWidth:ib.width,imageHeight:ib.height) else{return nil}
            return NativeRegistration.Match(source:source,target:target)
        }
    }
    func surface(comparing others:[NativeScanObservation],step:Int=2) throws -> NativeMesh {
        let w=frame.depthWidth,h=frame.depthHeight
        var points=[SIMD3<Float>](),map=[Int](repeating:-1,count:w*h)
        for y in stride(from:1,to:h-1,by:step) {for x in stride(from:1,to:w-1,by:step) {
            let i=y*w+x
            guard let p=worldPoint(SIMD2(Float(x),Float(y)),imageWidth:w,imageHeight:h,requireMask:true) else{continue}
            var agrees=0,conflicts=0
            for other in others {
                guard let q=other.project(p) else{continue}
                let u=Int(q.pixel.x.rounded()),v=Int(q.pixel.y.rounded()),ow=other.frame.depthWidth
                guard u>0,v>0,u<ow-1,v<other.frame.depthHeight-1 else{continue}
                let j=v*ow+u,z=other.depth[j]
                guard z.isFinite,z>0.12,other.confidence[j]>=1 else{continue}
                let tolerance=max(0.012,z*0.025)
                // A point in front of another observed surface contradicts free space.
                // Points behind another surface are occluded, not contradicted.
                if q.z<z-tolerance || (abs(q.z-z)<tolerance && other.mask[j]==0) {conflicts+=1}
                else if abs(q.z-z)<tolerance && other.mask[j]>0 {agrees+=1}
            }
            guard conflicts<=agrees || conflicts<2 else{continue}
            map[i]=points.count;points.append(p)
        }}
        var faces=[[Int]]()
        for y in stride(from:1,to:h-1-step,by:step) {for x in stride(from:1,to:w-1-step,by:step) {
            // Reuse the existing observed-depth meshing rule: every pixel in a
            // coarse cell must be observed. Even a one-pixel hole stays open.
            var complete=true,low=Float.infinity,high:Float=0
            for dy in 0...step {for dx in 0...step {
                let i=(y+dy)*w+x+dx,z=depth[i]
                if mask[i]==0 || confidence[i]<1 || !z.isFinite || z<0.12 || z>3 {complete=false}
                else {low=min(low,z);high=max(high,z)}
            }}
            guard complete,high-low<max(0.008,low*0.03) else{continue}
            let a=y*w+x,b=a+step,c=a+step*w,d=c+step
            for f in [[a,c,b],[b,c,d]] where f.allSatisfy({map[$0]>=0}) {faces.append(f.map{map[$0]})}
        }}
        return NativeMesh(vertices:points,faces:faces)
    }
}
