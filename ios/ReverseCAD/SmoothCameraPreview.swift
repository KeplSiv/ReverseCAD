import CoreImage
import MetalKit
import Vision
import UIKit

/// Display-only interpolation. These images never enter capture, tracking,
/// calibration, segmentation, measurements or exported geometry.
enum PreviewFrameBlender {
    private static let warp = CIKernel(source: """
    kernel vec4 previewWarp(sampler picture, sampler motion, float phase, vec2 scale) {
        vec2 p = destCoord();
        vec2 f = sample(motion, samplerTransform(motion, p / scale)).rg;
        return sample(picture, samplerTransform(picture, p - phase * f * scale));
    }
    """)
    static func image(previous:CIImage,current:CIImage,flow:CIImage?,phase:Double)->CIImage {
        let t=max(0,min(1,phase))
        guard t>0 else{return previous}
        guard t<1 else{return current}
        var a=previous,b=current
        if let flow,let warp {
            let scale=CIVector(x:current.extent.width/flow.extent.width,y:current.extent.height/flow.extent.height)
            a=warp.apply(extent:previous.extent,roiCallback:{_,_ in previous.extent},arguments:[previous,flow,t,scale]) ?? previous
            b=warp.apply(extent:current.extent,roiCallback:{_,_ in current.extent},arguments:[current,flow,t-1,scale]) ?? current
        }
        return a.applyingFilter("CIDissolveTransition",parameters:[kCIInputTargetImageKey:b,kCIInputTimeKey:t]).cropped(to:current.extent)
    }
}

final class SmoothCameraRenderer:NSObject,MTKViewDelegate {
    typealias Source = () -> (pixel:CVPixelBuffer,time:Double)?
    var source:Source?
    var orientation:UIInterfaceOrientation = .portrait
    private let context:CIContext
    private let commands:MTLCommandQueue
    private let worker=DispatchQueue(label:"reversecad.preview-only",qos:.userInteractive)
    private let slot=DispatchSemaphore(value:1),lock=NSLock()
    private var submitted = -Double.infinity
    private var previous:(CIImage,CVPixelBuffer,Double)?
    private struct Pair {let first:CIImage;let last:CIImage;let flow:CIImage?;let arrived:Double;let duration:Double}
    private var pair:Pair?
    private(set) var renderedFrames=0
    private var sourceFrames=0
    private var started:Double?

    init?(view:MTKView) {
        guard let device=MTLCreateSystemDefaultDevice(),let commands=device.makeCommandQueue() else{return nil}
        self.commands=commands;context=CIContext(mtlDevice:device,options:[.cacheIntermediates:false])
        super.init()
        view.device=device;view.framebufferOnly=false;view.preferredFramesPerSecond=60
        view.enableSetNeedsDisplay=false;view.isPaused=false;view.autoResizeDrawable=false
        view.colorPixelFormat = .bgra8Unorm;view.isOpaque=true;view.delegate=self
    }
    func mtkView(_ view:MTKView,drawableSizeWillChange size:CGSize) {}
    func draw(in view:MTKView) {
        if let frame=source?(),frame.time != submitted,slot.wait(timeout:.now()) == .success {
            submitted=frame.time
            sourceFrames+=1
            worker.async {[self] in defer{slot.signal()};autoreleasepool{prepare(frame)}}
        }
        lock.lock();let p=pair;lock.unlock()
        guard let p,CACurrentMediaTime()-p.arrived<0.6,let drawable=view.currentDrawable,let command=commands.makeCommandBuffer() else{return}
        let t=(CACurrentMediaTime()-p.arrived)/p.duration
        var image=PreviewFrameBlender.image(previous:p.first,current:p.last,flow:p.flow,phase:t)
        switch orientation {
        case .portrait:image=image.oriented(.right)
        case .portraitUpsideDown:image=image.oriented(.left)
        case .landscapeRight:image=image.oriented(.down)
        default:break
        }
        let size=view.drawableSize,s=max(size.width/image.extent.width,size.height/image.extent.height)
        image=image.transformed(by:CGAffineTransform(translationX:-image.extent.minX,y:-image.extent.minY)).transformed(by:CGAffineTransform(scaleX:s,y:s))
        image=image.transformed(by:CGAffineTransform(translationX:(size.width-image.extent.width)/2,y:(size.height-image.extent.height)/2))
        context.render(image,to:drawable.texture,commandBuffer:command,bounds:CGRect(origin:.zero,size:size),colorSpace:CGColorSpaceCreateDeviceRGB())
        command.present(drawable);command.commit();renderedFrames+=1
        started=started ?? CACurrentMediaTime()
        #if DEBUG
        if renderedFrames%120==0,ProcessInfo.processInfo.arguments.contains(where:{$0 == "-multiCameraCheck" || $0 == "-frontReferenceCheck"}) {
            let elapsed=CACurrentMediaTime()-(started ?? CACurrentMediaTime())
            try? cameraJSONWrite(["rendered_frames":renderedFrames,"source_frames":sourceFrames,"elapsed_s":elapsed,"render_fps":Double(renderedFrames-1)/max(elapsed,0.001),"drawable_width":size.width,"drawable_height":size.height,"mode":"display-only interpolation; source capture unchanged"],FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("preview-render-stats.json"))
        }
        #endif
    }
    private func prepare(_ frame:(pixel:CVPixelBuffer,time:Double)) {
        let sourceImage=CIImage(cvPixelBuffer:frame.pixel)
        let previewWidth=min(1920,Int(sourceImage.extent.width))
        let previewHeight=max(1,Int(sourceImage.extent.height*CGFloat(previewWidth)/sourceImage.extent.width))
        var owned:CVPixelBuffer?
        guard CVPixelBufferCreate(kCFAllocatorDefault,previewWidth,previewHeight,kCVPixelFormatType_32BGRA,[kCVPixelBufferIOSurfacePropertiesKey:[:]] as CFDictionary,&owned)==kCVReturnSuccess,let owned else{return}
        context.render(sourceImage.transformed(by:CGAffineTransform(scaleX:CGFloat(previewWidth)/sourceImage.extent.width,y:CGFloat(previewHeight)/sourceImage.extent.height)),to:owned)
        let image=CIImage(cvPixelBuffer:owned)
        let width=240,height=max(1,Int(image.extent.height*CGFloat(width)/image.extent.width))
        var buffer:CVPixelBuffer?
        guard CVPixelBufferCreate(kCFAllocatorDefault,width,height,kCVPixelFormatType_32BGRA,[kCVPixelBufferIOSurfacePropertiesKey:[:]] as CFDictionary,&buffer)==kCVReturnSuccess,let buffer else{return}
        context.render(image.transformed(by:CGAffineTransform(scaleX:CGFloat(width)/image.extent.width,y:CGFloat(height)/image.extent.height)),to:buffer)
        defer {previous=(image,buffer,frame.time)}
        guard let previous,previous.0.extent==image.extent,frame.time>previous.2,frame.time-previous.2<0.4 else {
            lock.lock();pair=Pair(first:image,last:image,flow:nil,arrived:CACurrentMediaTime(),duration:1.0/60);lock.unlock();return
        }
        let request=VNGenerateOpticalFlowRequest(targetedCVPixelBuffer:buffer)
        request.revision=VNGenerateOpticalFlowRequestRevision1
        request.computationAccuracy = .low;request.outputPixelFormat=kCVPixelFormatType_TwoComponent32Float
        let flow:CIImage?
        do {try VNImageRequestHandler(cvPixelBuffer:previous.1).perform([request]);flow=request.results?.first.map{CIImage(cvPixelBuffer:$0.pixelBuffer)}}
        catch {flow=nil}
        lock.lock();pair=Pair(first:previous.0,last:image,flow:flow,arrived:CACurrentMediaTime(),duration:frame.time-previous.2);lock.unlock()
    }
}
