import XCTest
import CoreImage
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
