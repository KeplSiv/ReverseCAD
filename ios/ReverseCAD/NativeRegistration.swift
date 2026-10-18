import Foundation
import CoreGraphics
import ImageIO
import simd

/// Rotation-aware binary image features. Used only to propose correspondences;
/// metric depth and held-out residuals must validate every accepted registration.
struct NativeImage {
    let width:Int, height:Int
    let gray:[UInt8]
    struct Feature {let point:SIMD2<Float>;let words:[UInt64]}
    static func read(_ url:URL, maximum:Int=640) throws -> Self {
        guard let src=CGImageSourceCreateWithURL(url as CFURL,nil),let image=CGImageSourceCreateThumbnailAtIndex(src,0,[kCGImageSourceCreateThumbnailFromImageAlways:true,kCGImageSourceThumbnailMaxPixelSize:maximum,kCGImageSourceCreateThumbnailWithTransform:false] as CFDictionary) else {throw ServiceFailure(message:"A saved camera image is unreadable.")}
        var pixels=[UInt8](repeating:0,count:image.width*image.height)
        let ok=pixels.withUnsafeMutableBytes {bytes -> Bool in
            guard let ctx=CGContext(data:bytes.baseAddress,width:image.width,height:image.height,bitsPerComponent:8,bytesPerRow:image.width,space:CGColorSpaceCreateDeviceGray(),bitmapInfo:0) else{return false}
            ctx.draw(image,in:CGRect(x:0,y:0,width:image.width,height:image.height));return true
        }
        guard ok else {throw ServiceFailure(message:"Could not decode the saved camera image.")}
        return Self(width:image.width,height:image.height,gray:pixels)
    }
    func features() -> [Feature] {
        var result=[Feature]()
        var seed:UInt64=1969
        func random()->Float {seed=seed &* 6364136223846793005 &+ 1;return Float((seed>>32)%2001)/100-10}
        let pattern=(0..<256).map{_ in (SIMD2(random(),random()),SIMD2(random(),random()))}
        for scale:Float in [1,0.7,0.5] {
            let w=Int(Float(width)*scale),h=Int(Float(height)*scale)
            guard w>40,h>40 else{continue}
            var a=[Float](repeating:0,count:w*h)
            for y in 0..<h {for x in 0..<w {a[y*w+x]=Float(gray[min(height-1,Int(Float(y)/scale))*width+min(width-1,Int(Float(x)/scale))])}}
            var candidates=[(Float,Int,Int)]()
            for y in stride(from:16,to:h-16,by:2) {for x in stride(from:16,to:w-16,by:2) {
                var xx:Float=0,xy:Float=0,yy:Float=0
                for j in -1...1 {for i in -1...1 {
                    let p=(y+j)*w+x+i,gx=a[p+1]-a[p-1],gy=a[p+w]-a[p-w]
                    xx+=gx*gx;xy+=gx*gy;yy+=gy*gy
                }}
                let score=xx*yy-xy*xy-0.04*(xx+yy)*(xx+yy)
                if score>1_000_000 {candidates.append((score,x,y))}
            }}
            candidates.sort{$0.0>$1.0}
            var chosen=[SIMD2<Float>]()
            for (_,x,y) in candidates {
                let p=SIMD2(Float(x),Float(y))
                if chosen.contains(where:{simd_distance_squared($0,p)<64}) {continue}
                chosen.append(p)
                var mx:Float=0,my:Float=0
                for j in -7...7 {for i in -7...7 {let value=a[(y+j)*w+x+i];mx+=Float(i)*value;my+=Float(j)*value}}
                let angle=atan2(my,mx),c=cos(angle),s=sin(angle)
                func sample(_ q:SIMD2<Float>)->Float {let u=x+Int((q.x*c-q.y*s).rounded()),v=y+Int((q.x*s+q.y*c).rounded());return a[v*w+u]}
                var words=[UInt64](repeating:0,count:4)
                for (i,pair) in pattern.enumerated() {if sample(pair.0)<sample(pair.1) {words[i/64] |= UInt64(1) << (i%64)}}
                result.append(Feature(point:SIMD2((Float(x)+0.5)/scale-0.5,(Float(y)+0.5)/scale-0.5),words:words))
                if chosen.count>=350 {break}
            }
        }
        return result
    }
    static func matches(_ a:[Feature],_ b:[Feature])->[(Int,Int)] {
        guard a.count>=2,b.count>=2 else{return []}
        var reverse=[Int](repeating:-1,count:b.count),reverseDistance=[Int](repeating:257,count:b.count)
        var proposals=[(Int,Int)]()
        for (i,f) in a.enumerated() {
            var best=257,second=257,jBest = -1
            for (j,g) in b.enumerated() {
                let distance=(0..<4).reduce(0){$0+(f.words[$1]^g.words[$1]).nonzeroBitCount}
                if distance<reverseDistance[j] {reverseDistance[j]=distance;reverse[j]=i}
                if distance<best {second=best;best=distance;jBest=j} else if distance<second {second=distance}
            }
            if best<72,Float(best)<Float(second)*0.78 {proposals.append((i,jBest))}
        }
        return proposals.filter{reverse[$0.1] == $0.0}
    }
}

enum NativeRegistration {
    struct Match {let source:SIMD3<Float>;let target:SIMD3<Float>}
    struct Fit {let pose:simd_float4x4;let inliers:[Int];let rmse:Float;let heldOutRMSE:Float}
    static func point(_ p:SIMD3<Float>,_ pose:simd_float4x4)->SIMD3<Float> {let q=pose*SIMD4(p,1);return SIMD3(q.x,q.y,q.z)}
    static func matrix(_ values:[Double])->simd_float4x4 {let m=values.map{Float($0)};return simd_float4x4(columns:(SIMD4(m[0],m[1],m[2],m[3]),SIMD4(m[4],m[5],m[6],m[7]),SIMD4(m[8],m[9],m[10],m[11]),SIMD4(m[12],m[13],m[14],m[15])))}
    static let opticalAxes=simd_float4x4(diagonal:SIMD4(1,-1,-1,1))
    static func fit(_ matches:[Match], tolerance:Float=0.015, minimum:Int=16)->Fit? {
        guard matches.count>=minimum+6 else{return nil}
        let training=matches.indices.filter{$0%4 != 0},held=matches.indices.filter{$0%4==0}
        var best=[Int](),seed:UInt64=901
        func residual(_ i:Int,_ p:simd_float4x4)->Float {simd_distance(point(matches[i].source,p),matches[i].target)}
        for _ in 0..<256 {
            var sample=Set<Int>()
            while sample.count<3 {seed=seed &* 6364136223846793005 &+ 1;sample.insert(training[Int((seed>>32)%UInt64(training.count))])}
            let ids=sample.sorted()
            guard let pose=RGBDRigidAlignment.fit(ids.map{matches[$0].source},ids.map{matches[$0].target}) else{continue}
            let inliers=training.filter{residual($0,pose)<tolerance}
            if inliers.count>best.count {best=inliers}
        }
        guard best.count>=minimum,Double(best.count)/Double(training.count)>=0.45,
              let pose=RGBDRigidAlignment.fit(best.map{matches[$0].source},best.map{matches[$0].target}) else{return nil}
        let supportedHeld=held.filter{residual($0,pose)<tolerance}
        guard supportedHeld.count>=max(5,held.count/2) else{return nil}
        let rms=sqrt(best.reduce(Float(0)){$0+pow(residual($1,pose),2)}/Float(best.count))
        let heldRMS=sqrt(supportedHeld.reduce(Float(0)){$0+pow(residual($1,pose),2)}/Float(supportedHeld.count))
        guard rms<0.01,heldRMS<0.012 else{return nil}
        return Fit(pose:pose,inliers:matches.indices.filter{residual($0,pose)<tolerance},rmse:rms,heldOutRMSE:heldRMS)
    }
}
