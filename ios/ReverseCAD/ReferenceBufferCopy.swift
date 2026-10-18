import AVFoundation

/// Own the rolling reference samples without retaining the camera's finite
/// buffer pool. Plane bytes, padding, dimensions, timing and attachments survive.
enum ReferenceBufferCopy {
    static func pixel(_ source:CVPixelBuffer)throws->CVPixelBuffer {
        CVPixelBufferLockBaseAddress(source,.readOnly)
        defer{CVPixelBufferUnlockBaseAddress(source,.readOnly)}
        let width=CVPixelBufferGetWidth(source),height=CVPixelBufferGetHeight(source)
        let format=CVPixelBufferGetPixelFormatType(source),planes=CVPixelBufferGetPlaneCount(source)
        var result:CVPixelBuffer?
        let status:CVReturn
        if planes==0 {
            let stride=CVPixelBufferGetBytesPerRow(source),size=stride*height
            guard let sourceBytes=CVPixelBufferGetBaseAddress(source),let bytes=malloc(size) else{throw CameraLabError.message("Not enough memory for the front reference.")}
            memcpy(bytes,sourceBytes,size)
            status=CVPixelBufferCreateWithBytes(kCFAllocatorDefault,width,height,format,bytes,stride,{_,data in free(UnsafeMutableRawPointer(mutating:data))},nil,nil,&result)
            if status != kCVReturnSuccess {free(bytes)}
        } else {
            var widths=(0..<planes).map{CVPixelBufferGetWidthOfPlane(source,$0)}
            var heights=(0..<planes).map{CVPixelBufferGetHeightOfPlane(source,$0)}
            var strides=(0..<planes).map{CVPixelBufferGetBytesPerRowOfPlane(source,$0)}
            let size=zip(heights,strides).reduce(0){$0+$1.0*$1.1}
            guard let bytes=malloc(size) else{throw CameraLabError.message("Not enough memory for the front reference.")}
            var addresses=[UnsafeMutableRawPointer?](),offset=0
            for i in 0..<planes {
                guard let sourceBytes=CVPixelBufferGetBaseAddressOfPlane(source,i) else{free(bytes);throw CameraLabError.message("A reference image plane is unavailable.")}
                let count=heights[i]*strides[i],destination=bytes.advanced(by:offset)
                memcpy(destination,sourceBytes,count);addresses.append(destination);offset+=count
            }
            status=CVPixelBufferCreateWithPlanarBytes(kCFAllocatorDefault,width,height,format,bytes,size,planes,&addresses,&widths,&heights,&strides,{_,data,_,_,_ in free(UnsafeMutableRawPointer(mutating:data))},nil,nil,&result)
            if status != kCVReturnSuccess {free(bytes)}
        }
        guard status==kCVReturnSuccess,let result else{throw CameraLabError.message("Could not preserve the front reference image.")}
        for mode in [CVAttachmentMode.shouldPropagate,.shouldNotPropagate] {
            if let attachments=CVBufferCopyAttachments(source,mode) {CVBufferSetAttachments(result,attachments,mode)}
        }
        return result
    }
    static func sample(_ source:CMSampleBuffer)throws->CMSampleBuffer {
        guard let image=CMSampleBufferGetImageBuffer(source),let format=CMSampleBufferGetFormatDescription(source) else{throw CameraLabError.message("A reference sample is incomplete.")}
        let copy=try pixel(image)
        var timing=CMSampleTimingInfo(),result:CMSampleBuffer?
        guard CMSampleBufferGetSampleTimingInfo(source,at:0,timingInfoOut:&timing)==noErr,
              CMSampleBufferCreateReadyWithImageBuffer(allocator:kCFAllocatorDefault,imageBuffer:copy,formatDescription:format,sampleTiming:&timing,sampleBufferOut:&result)==noErr,let result else{throw CameraLabError.message("Could not preserve reference timing.")}
        for mode in [kCMAttachmentMode_ShouldPropagate,kCMAttachmentMode_ShouldNotPropagate] {
            if let attachments=CMCopyDictionaryOfAttachments(allocator:kCFAllocatorDefault,target:source,attachmentMode:mode) {CMSetAttachments(result,attachments:attachments,attachmentMode:mode)}
        }
        return result
    }
}
