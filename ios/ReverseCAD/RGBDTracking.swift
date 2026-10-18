import AVFoundation
import Accelerate
import Vision
import simd

/// Rigid alignment of measured 3D correspondences. Scale is never fitted.
enum RGBDRigidAlignment {
    struct Result {let transform:simd_float4x4;let inliers:Int;let rmse:Float}
    static func fit(_ source:[SIMD3<Float>],_ target:[SIMD3<Float>]) -> simd_float4x4? {
        guard source.count==target.count,source.count>=3 else{return nil}
        let n=Float(source.count),a=source.reduce(.zero,+)/n,b=target.reduce(.zero,+)/n
        var h=simd_float3x3(0)
        for (s,t) in zip(source,target) {let x=s-a,y=t-b;h += simd_float3x3(columns:(x*y.x,x*y.y,x*y.z))}
        var values=(0..<3).flatMap{c in (0..<3).map{r in h[c][r]}}
        var singular=[Float](repeating:0,count:3),u=[Float](repeating:0,count:9),vt=u,work=[Float](repeating:0,count:64)
        var m:Int32=3,nc:Int32=3,lda:Int32=3,ldu:Int32=3,ldvt:Int32=3,lwork:Int32=64,info:Int32=0
        var jobA:Int8=65,jobB:Int8=65
        sgesvd_(&jobA,&jobB,&m,&nc,&values,&lda,&singular,&u,&ldu,&vt,&ldvt,&work,&lwork,&info)
        guard info==0,singular[1]>max(1e-9,singular[0]*0.0001) else{return nil}
        func matrix(_ x:[Float])->simd_float3x3 {simd_float3x3(columns:(SIMD3(x[0],x[1],x[2]),SIMD3(x[3],x[4],x[5]),SIMD3(x[6],x[7],x[8])))}
        let um=matrix(u);var v=matrix(vt).transpose
        if simd_determinant(v*um.transpose)<0 {v.columns.2 *= -1}
        let r=v*um.transpose,t=b-r*a
        return simd_float4x4(columns:(SIMD4(r.columns.0,0),SIMD4(r.columns.1,0),SIMD4(r.columns.2,0),SIMD4(t,1)))
    }
    static func robust(_ source:[SIMD3<Float>],_ target:[SIMD3<Float>],threshold:Float=0.012)->Result? {
        guard source.count==target.count,source.count>=50 else{return nil}
        var best=[Int](),seed:UInt64=0x72657665727365
        func indices(_ pose:simd_float4x4)->[Int] {
            source.indices.filter {i in let p=pose*SIMD4(source[i],1);return simd_distance(SIMD3(p.x,p.y,p.z),target[i])<threshold}
        }
        for _ in 0..<64 {
            var sample=Set<Int>()
            while sample.count<3 {seed=seed &* 6364136223846793005 &+ 1442695040888963407;sample.insert(Int((seed>>32)%UInt64(source.count)))}
            let ids=Array(sample).sorted()
            guard let pose=fit(ids.map{source[$0]},ids.map{target[$0]}) else{continue}
            let accepted=indices(pose);if accepted.count>best.count {best=accepted}
        }
        guard best.count>=50,Double(best.count)/Double(source.count)>=0.55 else{return nil}
        guard let pose=fit(best.map{source[$0]},best.map{target[$0]}) else{return nil}
        best=indices(pose)
        let error=best.reduce(Float(0)){sum,i in let p=pose*SIMD4(source[i],1);return sum+simd_length_squared(SIMD3(p.x,p.y,p.z)-target[i])}
        let rmse=sqrt(error/Float(max(1,best.count)))
        guard rmse<0.008,simd_length(SIMD3(pose.columns.3.x,pose.columns.3.y,pose.columns.3.z))<0.15 else{return nil}
        let angle=acos(min(1,max(-1,(pose[0][0]+pose[1][1]+pose[2][2]-1)/2)))
        guard angle<0.35 else{return nil}
        return Result(transform:pose,inliers:best.count,rmse:rmse)
    }
}

/// Uses full-scene texture and measured depth for motion, before object masking.
final class RGBDTracking {
    struct Frame {let image:CVPixelBuffer;let depth:[Float];let width:Int;let height:Int;let k:simd_float3x3;let time:Double}
    private var previous:Frame?
    private(set) var worldFromCamera=matrix_identity_float4x4
    private(set) var failure=""
    private(set) var inliers=0
    private(set) var residual:Float=0
    private(set) var diagnostic=""
    func update(_ frame:Frame)->simd_float4x4? {
        guard let previous else{self.previous=frame;return worldFromCamera}
        guard frame.time>previous.time,frame.width==previous.width,frame.height==previous.height else {failure="Return to the last view. Tracking needs overlapping views.";return nil}
        do {
            // Handler-to-target motion is verified by the translated-image test.
            let request=VNGenerateOpticalFlowRequest(targetedCVPixelBuffer:frame.image)
            request.revision=VNGenerateOpticalFlowRequestRevision1
            request.computationAccuracy = .medium;request.outputPixelFormat=kCVPixelFormatType_TwoComponent32Float
            try VNImageRequestHandler(cvPixelBuffer:previous.image).perform([request])
            guard let flow=request.results?.first?.pixelBuffer else{return nil}
            CVPixelBufferLockBaseAddress(flow,.readOnly);defer {CVPixelBufferUnlockBaseAddress(flow,.readOnly)}
            guard let base=CVPixelBufferGetBaseAddress(flow),CVPixelBufferGetWidth(flow)==frame.width,CVPixelBufferGetHeight(flow)==frame.height else{return nil}
            let reverse=VNGenerateOpticalFlowRequest(targetedCVPixelBuffer:previous.image)
            reverse.revision=VNGenerateOpticalFlowRequestRevision1
            reverse.computationAccuracy = .medium;reverse.outputPixelFormat=kCVPixelFormatType_TwoComponent32Float
            try VNImageRequestHandler(cvPixelBuffer:frame.image).perform([reverse])
            guard let back=reverse.results?.first?.pixelBuffer else{return nil}
            CVPixelBufferLockBaseAddress(back,.readOnly);CVPixelBufferLockBaseAddress(previous.image,.readOnly)
            defer {CVPixelBufferUnlockBaseAddress(back,.readOnly);CVPixelBufferUnlockBaseAddress(previous.image,.readOnly)}
            guard let backward=CVPixelBufferGetBaseAddress(back),let texture=CVPixelBufferGetBaseAddress(previous.image) else{return nil}
            func textured(_ x:Int,_ y:Int)->Bool {
                let row=CVPixelBufferGetBytesPerRow(previous.image)
                var values=[Float]()
                for dy in -2...2 {for dx in -2...2 {
                    let p=texture.advanced(by:(y+dy)*row+(x+dx)*4).assumingMemoryBound(to:UInt8.self)
                    values.append((Float(p[0])+Float(p[1])+Float(p[2]))/3)
                }}
                let mean=values.reduce(0,+)/Float(values.count)
                return values.reduce(0){$0+($1-mean)*($1-mean)}/Float(values.count)>36
            }
            var source=[SIMD3<Float>](),target=[SIMD3<Float>](),cells=Set<Int>()
            let inversePrevious=simd_inverse(previous.k),inverseCurrent=simd_inverse(frame.k)
            func depth(_ f:Frame,_ x:Int,_ y:Int)->Float? {
                guard x>1,y>1,x<f.width-2,y<f.height-2 else{return nil}
                let z=f.depth[y*f.width+x]
                guard z.isFinite,z>0.12,z<3 else{return nil}
                for j in [x-1+y*f.width,x+1+y*f.width,x+(y-1)*f.width,x+(y+1)*f.width] {
                    let v=f.depth[j];if !v.isFinite || abs(v-z)>max(0.015,z*0.03) {return nil}
                }
                return z
            }
            for y in stride(from:4,to:frame.height-4,by:6) {for x in stride(from:4,to:frame.width-4,by:6) {
                guard textured(x,y) else{continue}
                let offset=y*CVPixelBufferGetBytesPerRow(flow)+x*8
                let dx=base.loadUnaligned(fromByteOffset:offset,as:Float.self),dy=base.loadUnaligned(fromByteOffset:offset+4,as:Float.self)
                guard dx.isFinite,dy.isFinite,abs(dx)<80,abs(dy)<80 else{continue}
                let u=Float(x)+dx,v=Float(y)+dy
                let xx=Int(u.rounded()),yy=Int(v.rounded())
                guard let before=depth(previous,x,y),let after=depth(frame,xx,yy) else{continue}
                let bo=yy*CVPixelBufferGetBytesPerRow(back)+xx*8
                let bx=backward.loadUnaligned(fromByteOffset:bo,as:Float.self),by=backward.loadUnaligned(fromByteOffset:bo+4,as:Float.self)
                guard bx.isFinite,by.isFinite,hypot(dx+bx,dy+by)<1.5 else{continue}
                cells.insert((x*4/frame.width)+(y*3/frame.height)*4)
                source.append((inverseCurrent*SIMD3(u,v,1))*after)
                target.append((inversePrevious*SIMD3(Float(x),Float(y),1))*before)
            }}
            guard cells.count>=6,let fit=RGBDRigidAlignment.robust(source,target) else{diagnostic="\(source.count) depth/flow correspondences in \(cells.count) image cells";failure="Move back slowly to the last view. Add light and visible texture.";return nil}
            worldFromCamera=worldFromCamera*fit.transform;self.previous=frame;inliers=fit.inliers;residual=fit.rmse;failure=""
            return worldFromCamera
        } catch {diagnostic=error.localizedDescription;failure="Motion tracking could not read this view. Return to the previous view.";return nil}
    }
}
