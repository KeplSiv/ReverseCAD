import XCTest
import CoreImage
import AVFoundation
import ReverseCADCore
@testable import ReverseCAD

final class CameraPreviewTests:XCTestCase {
    func testReferenceCopiesOriginalPlanesWithoutRetainingCameraPoolMemory() throws {
        var source:CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault,64,48,kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,[kCVPixelBufferIOSurfacePropertiesKey:[:]] as CFDictionary,&source),kCVReturnSuccess)
        let original=try XCTUnwrap(source)
        CVPixelBufferLockBaseAddress(original,[])
        for plane in 0..<CVPixelBufferGetPlaneCount(original) {
            memset(try XCTUnwrap(CVPixelBufferGetBaseAddressOfPlane(original,plane)),33+Int32(plane),CVPixelBufferGetBytesPerRowOfPlane(original,plane)*CVPixelBufferGetHeightOfPlane(original,plane))
        }
        CVPixelBufferUnlockBaseAddress(original,[])
        let copy=try ReferenceBufferCopy.pixel(original)
        let context=CIContext(options:[.cacheIntermediates:false])
        func decoded(_ buffer:CVPixelBuffer)->[UInt8] {
            var bytes=[UInt8](repeating:0,count:64*48*4)
            context.render(CIImage(cvPixelBuffer:buffer),toBitmap:&bytes,rowBytes:64*4,bounds:CGRect(x:0,y:0,width:64,height:48),format:.RGBA8,colorSpace:CGColorSpaceCreateDeviceRGB())
            return bytes
        }
        XCTAssertEqual(decoded(original),decoded(copy))
        CVPixelBufferLockBaseAddress(original,[])
        CVPixelBufferGetBaseAddressOfPlane(original,0)!.storeBytes(of:UInt8(99),as:UInt8.self)
        CVPixelBufferUnlockBaseAddress(original,[])
        CVPixelBufferLockBaseAddress(copy,.readOnly);defer{CVPixelBufferUnlockBaseAddress(copy,.readOnly)}
        for plane in 0..<CVPixelBufferGetPlaneCount(copy) {
            XCTAssertEqual(CVPixelBufferGetBytesPerRowOfPlane(copy,plane),CVPixelBufferGetBytesPerRowOfPlane(original,plane))
            XCTAssertEqual(CVPixelBufferGetBaseAddressOfPlane(copy,plane)!.load(as:UInt8.self),UInt8(33+plane))
        }
    }
    func testCopiedNV12SampleReconcilesStorageLayoutAndPreservesMetadata() throws {
        var buffer:CVPixelBuffer?
        let attributes:[CFString:Any]=[kCVPixelBufferIOSurfacePropertiesKey:[:],kCVPixelBufferBytesPerRowAlignmentKey:256]
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault,64,48,kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,attributes as CFDictionary,&buffer),kCVReturnSuccess)
        let original=try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(original,[])
        for plane in 0..<CVPixelBufferGetPlaneCount(original) {
            memset(try XCTUnwrap(CVPixelBufferGetBaseAddressOfPlane(original,plane)),32+Int32(plane)*96,
                   CVPixelBufferGetBytesPerRowOfPlane(original,plane)*CVPixelBufferGetHeightOfPlane(original,plane))
        }
        CVPixelBufferUnlockBaseAddress(original,[])
        CVBufferSetAttachment(original,kCVImageBufferColorPrimariesKey,kCVImageBufferColorPrimaries_ITU_R_709_2,.shouldPropagate)
        CVBufferSetAttachment(original,"PreservedPixelMetadata" as CFString,"pixel-value" as CFString,.shouldNotPropagate)
        var generated:CMVideoFormatDescription?
        XCTAssertEqual(CMVideoFormatDescriptionCreateForImageBuffer(allocator:kCFAllocatorDefault,imageBuffer:original,formatDescriptionOut:&generated),noErr)
        let base=try XCTUnwrap(generated)
        var extensions=try XCTUnwrap(CMFormatDescriptionGetExtensions(base) as? [String:Any])
        extensions["PreservedFormatMetadata"]="format-value"
        var originalFormat:CMVideoFormatDescription?
        XCTAssertEqual(CMVideoFormatDescriptionCreate(allocator:kCFAllocatorDefault,codecType:CVPixelBufferGetPixelFormatType(original),width:64,height:48,
            extensions:extensions as CFDictionary,formatDescriptionOut:&originalFormat),noErr)
        let format=try XCTUnwrap(originalFormat)
        var timing=CMSampleTimingInfo(duration:CMTime(value:1001,timescale:30000),
            presentationTimeStamp:CMTime(value:123456,timescale:600,flags:.valid,epoch:42),
            decodeTimeStamp:CMTime(value:123455,timescale:600,flags:.valid,epoch:42))
        var source:CMSampleBuffer?
        XCTAssertEqual(CMSampleBufferCreateReadyWithImageBuffer(allocator:kCFAllocatorDefault,imageBuffer:original,formatDescription:format,sampleTiming:&timing,sampleBufferOut:&source),noErr)
        let sample=try XCTUnwrap(source)
        let intrinsics=Data((0..<48).map(UInt8.init))
        CMSetAttachment(sample,key:kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix,value:intrinsics as CFData,attachmentMode:kCMAttachmentMode_ShouldPropagate)
        CMSetAttachment(sample,key:"PreservedSampleMetadata" as CFString,value:"sample-value" as CFString,attachmentMode:kCMAttachmentMode_ShouldNotPropagate)
        let sourceAttachments=try XCTUnwrap(CMSampleBufferGetSampleAttachmentsArray(sample,createIfNecessary:true) as? [NSMutableDictionary])
        sourceAttachments[0][kCMSampleAttachmentKey_NotSync as String]=true
        let outputTime=CMTime(value:123499,timescale:600,flags:.valid,epoch:42)
        XCTAssertEqual(CMSampleBufferSetOutputPresentationTimeStamp(sample,newValue:outputTime),noErr)

        let copy=try ReferenceBufferCopy.sample(sample)
        let image=try XCTUnwrap(CMSampleBufferGetImageBuffer(copy)),copiedFormat=try XCTUnwrap(CMSampleBufferGetFormatDescription(copy))
        XCTAssertNotEqual(CVPixelBufferGetBytesPerRow(original),CVPixelBufferGetBytesPerRow(image))
        var oldAttempt:CMSampleBuffer?
        XCTAssertEqual(CMSampleBufferCreateReadyWithImageBuffer(allocator:kCFAllocatorDefault,imageBuffer:image,formatDescription:format,sampleTiming:&timing,sampleBufferOut:&oldAttempt),kCMSampleBufferError_InvalidMediaFormat)
        XCTAssertTrue(CMVideoFormatDescriptionMatchesImageBuffer(copiedFormat,imageBuffer:image))
        var copiedExtensions=try XCTUnwrap(CMFormatDescriptionGetExtensions(copiedFormat) as? [String:Any])
        XCTAssertEqual(copiedExtensions[kCMFormatDescriptionExtension_BytesPerRow as String] as? Int,CVPixelBufferGetBytesPerRow(image))
        extensions.removeValue(forKey:kCMFormatDescriptionExtension_BytesPerRow as String)
        copiedExtensions.removeValue(forKey:kCMFormatDescriptionExtension_BytesPerRow as String)
        XCTAssertEqual(copiedExtensions as NSDictionary,extensions as NSDictionary)
        var copiedTiming=CMSampleTimingInfo()
        XCTAssertEqual(CMSampleBufferGetSampleTimingInfo(copy,at:0,timingInfoOut:&copiedTiming),noErr)
        XCTAssertEqual(copiedTiming.duration,timing.duration)
        XCTAssertEqual(copiedTiming.presentationTimeStamp,timing.presentationTimeStamp)
        XCTAssertEqual(copiedTiming.decodeTimeStamp,timing.decodeTimeStamp)
        XCTAssertEqual(CMSampleBufferGetOutputPresentationTimeStamp(copy),outputTime)
        XCTAssertEqual(CMGetAttachment(copy,key:kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix,attachmentModeOut:nil) as? Data,intrinsics)
        XCTAssertEqual(CMGetAttachment(copy,key:"PreservedSampleMetadata" as CFString,attachmentModeOut:nil) as? String,"sample-value")
        XCTAssertEqual((CMSampleBufferGetSampleAttachmentsArray(copy,createIfNecessary:false) as? [[String:Any]])?.first?[kCMSampleAttachmentKey_NotSync as String] as? Bool,true)
        XCTAssertEqual(CVBufferCopyAttachment(image,"PreservedPixelMetadata" as CFString,nil) as? String,"pixel-value")
        CVPixelBufferLockBaseAddress(original,.readOnly);CVPixelBufferLockBaseAddress(image,.readOnly)
        for plane in 0..<CVPixelBufferGetPlaneCount(original) {
            let stride=CVPixelBufferGetBytesPerRowOfPlane(original,plane),height=CVPixelBufferGetHeightOfPlane(original,plane)
            XCTAssertEqual(CVPixelBufferGetBytesPerRowOfPlane(image,plane),stride)
            XCTAssertEqual(Data(bytes:try XCTUnwrap(CVPixelBufferGetBaseAddressOfPlane(original,plane)),count:stride*height),
                Data(bytes:try XCTUnwrap(CVPixelBufferGetBaseAddressOfPlane(image,plane)),count:stride*height))
        }
        CVPixelBufferUnlockBaseAddress(image,.readOnly);CVPixelBufferUnlockBaseAddress(original,.readOnly)
        let writer=try ExperimentWriter(source:"synthetic owned-NV12 sample regression")
        defer {try? FileManager.default.removeItem(at:writer.url)}
        let frame=try writer.save(copy,camera:"front",settings:[:])
        XCTAssertTrue(FileManager.default.fileExists(atPath:writer.url.appendingPathComponent("frames/\(frame).png").path))
        XCTAssertEqual(writer.frames.first?["timestamp_s"] as? Double,CMTimeGetSeconds(timing.presentationTimeStamp))
        XCTAssertEqual(writer.frames.first?["width"] as? Int,64)
        XCTAssertEqual(writer.frames.first?["height"] as? Int,48)
    }

    func testReferenceWindowAcceptsSlowerSynchronizedCadencesWithoutStarvation() {
        for rate in [5.0, 7.0, 10.0, 15.0, 30.0] {
            var window = [Double]()
            for index in 0..<20 {
                let now = 100 + Double(index) / rate
                window = FrontReferencePolicy.recent(window + [now], now: now, timestamp: { $0 })
                XCTAssertLessThanOrEqual(window.count, FrontReferencePolicy.sampleCount)
                if index >= 7 { XCTAssertTrue(FrontReferencePolicy.ready(timestamps: window, now: now), "Cadence \(rate) Hz starved at sample \(index)") }
            }
            XCTAssertFalse(FrontReferencePolicy.ready(timestamps: window, now: window.last! + 0.31))
        }
        XCTAssertFalse(FrontReferencePolicy.ready(timestamps: Array(repeating: 100, count: 8), now: 100))
        XCTAssertFalse(FrontReferencePolicy.ready(timestamps: (0..<8).map { 100 + Double($0) / 10 }, now: 99))
    }
    func testReferenceUsesFreshSharpWindowAndHalfShutter() {
        let times=(0..<8).map{100+Double($0)*0.133}
        XCTAssertTrue(FrontReferencePolicy.ready(timestamps:times,now:101))
        XCTAssertFalse(FrontReferencePolicy.ready(timestamps:times,now:102))
        XCTAssertFalse(FrontReferencePolicy.ready(timestamps:Array(times.dropFirst()),now:101))
        XCTAssertFalse(FrontReferencePolicy.ready(timestamps:[.nan]+Array(times.dropFirst()),now:101))
        XCTAssertEqual(FrontReferencePolicy.shutterDuration(baseline:1.0/30,minimum:1.0/10000),1.0/60,accuracy:1e-8)
        XCTAssertEqual(FrontReferencePolicy.shutterDuration(baseline:1.0/10000,minimum:1.0/10000),1.0/10000,accuracy:1e-8)
    }

}
