import AVFoundation
import CoreImage
import simd

/// Uses Apple's delivered per-frame LUTs once. Originals are retained separately.
struct CalibratedRaster {
    let image:CVPixelBuffer
    let trackingImage:CVPixelBuffer
    let depth:[Float]
    let width:Int
    let height:Int
    let imageK:simd_float3x3
    let depthK:simd_float3x3
    let calibration:TrueDepthFrameCalibration
    static func buffer(_ w:Int,_ h:Int)throws->CVPixelBuffer {
        var result:CVPixelBuffer?
        guard CVPixelBufferCreate(kCFAllocatorDefault,w,h,kCVPixelFormatType_32BGRA,[kCVPixelBufferIOSurfacePropertiesKey:[:]] as CFDictionary,&result)==kCVReturnSuccess,let result else{throw CaptureFailure.write("Could not allocate the camera image.")}
        return result
    }
    static func make(rgb:CVPixelBuffer,depth source:AVDepthData,context:CIContext)throws->Self {
        guard let c=source.cameraCalibrationData,let inverse=c.inverseLensDistortionLookupTable else{throw CaptureFailure.unavailable("LiDAR calibration is missing for this view.")}
        func table(_ data:Data)->[Float] {data.withUnsafeBytes{b in (0..<data.count/4).map{b.loadUnaligned(fromByteOffset:$0*4,as:Float.self)}}}
        let cal=TrueDepthFrameCalibration(K:c.intrinsicMatrix,inverseK:simd_inverse(c.intrinsicMatrix),size:SIMD2(Float(c.intrinsicMatrixReferenceDimensions.width),Float(c.intrinsicMatrixReferenceDimensions.height)),center:SIMD2(Float(c.lensDistortionCenter.x),Float(c.lensDistortionCenter.y)),inverse:table(inverse),forward:c.lensDistortionLookupTable.map(table))
        guard cal.inverse.count>=2,cal.inverse.allSatisfy(\.isFinite) else{throw CaptureFailure.unavailable("LiDAR distortion calibration is invalid.")}
        let metric=source.converting(toDepthDataType:kCVPixelFormatType_DepthFloat32).depthDataMap
        let dw=CVPixelBufferGetWidth(metric),dh=CVPixelBufferGetHeight(metric),rw=CVPixelBufferGetWidth(rgb),rh=CVPixelBufferGetHeight(rgb)
        let iw=min(640,rw),ih=max(1,Int(round(Double(rh)*Double(iw)/Double(rw))))
        let raw=try buffer(rw,rh),image=try buffer(iw,ih)
        context.render(CIImage(cvPixelBuffer:rgb),to:raw)
        CVPixelBufferLockBaseAddress(metric,.readOnly);CVPixelBufferLockBaseAddress(raw,.readOnly);CVPixelBufferLockBaseAddress(image,[])
        defer {CVPixelBufferUnlockBaseAddress(metric,.readOnly);CVPixelBufferUnlockBaseAddress(raw,.readOnly);CVPixelBufferUnlockBaseAddress(image,[])}
        guard let depthBase=CVPixelBufferGetBaseAddress(metric),let pixels=CVPixelBufferGetBaseAddress(raw),let dest=CVPixelBufferGetBaseAddress(image) else{throw CaptureFailure.write("Camera image is inaccessible.")}
        func sample(_ x:Int,_ y:Int,_ w:Int,_ h:Int)->SIMD2<Float> {
            let ideal=SIMD2((Float(x)+0.5)*cal.size.x/Float(w)-0.5,(Float(y)+0.5)*cal.size.y/Float(h)-0.5)
            return cal.observedPixel(for:cal.inverseK*SIMD3(ideal.x,ideal.y,1))
        }
        var result=[Float](repeating:.nan,count:dw*dh)
        for y in 0..<dh {for x in 0..<dw {
            let p=sample(x,y,dw,dh),u=Int(((p.x+0.5)*Float(dw)/cal.size.x-0.5).rounded()),v=Int(((p.y+0.5)*Float(dh)/cal.size.y-0.5).rounded())
            if u>=0,u<dw,v>=0,v<dh {let z=depthBase.loadUnaligned(fromByteOffset:v*CVPixelBufferGetBytesPerRow(metric)+u*4,as:Float.self);if z.isFinite,z>0 {result[y*dw+x]=z}}
        }}
        for y in 0..<ih {for x in 0..<iw {
            let p=sample(x,y,iw,ih),u=(p.x+0.5)*Float(rw)/cal.size.x-0.5,v=(p.y+0.5)*Float(rh)/cal.size.y-0.5
            let a=Int(floor(u)),b=Int(floor(v)),fx=u-Float(a),fy=v-Float(b),o=y*CVPixelBufferGetBytesPerRow(image)+x*4
            for channel in 0..<4 {
                var value:Float=channel==3 ? 255:0
                if a>=0,a+1<rw,b>=0,b+1<rh {
                    func at(_ xx:Int,_ yy:Int)->Float {Float(pixels.load(fromByteOffset:yy*CVPixelBufferGetBytesPerRow(raw)+xx*4+channel,as:UInt8.self))}
                    value=(at(a,b)*(1-fx)+at(a+1,b)*fx)*(1-fy)+(at(a,b+1)*(1-fx)+at(a+1,b+1)*fx)*fy
                }
                dest.storeBytes(of:UInt8(max(0,min(255,value.rounded()))),toByteOffset:o+channel,as:UInt8.self)
            }
        }}
        func scaled(_ w:Int,_ h:Int)->simd_float3x3 {
            var k=cal.K;let sx=Float(w)/cal.size.x,sy=Float(h)/cal.size.y
            k[0][0]*=sx;k[1][1]*=sy;k[2][0]=(k[2][0]+0.5)*sx-0.5;k[2][1]=(k[2][1]+0.5)*sy-0.5;return k
        }
        let tracking=try buffer(dw,dh)
        context.render(CIImage(cvPixelBuffer:image).transformed(by:CGAffineTransform(scaleX:CGFloat(dw)/CGFloat(iw),y:CGFloat(dh)/CGFloat(ih))),to:tracking)
        return Self(image:image,trackingImage:tracking,depth:result,width:dw,height:dh,imageK:scaled(iw,ih),depthK:scaled(dw,dh),calibration:cal)
    }
}
