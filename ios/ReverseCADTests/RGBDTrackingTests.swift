import XCTest
import UIKit
import CoreImage
import simd
@testable import ReverseCAD

final class RGBDTrackingTests:XCTestCase {
    func testRigidFitRejectsOutliersWithoutChangingScale() throws {
        let points=(0..<150).map {i in SIMD3<Float>(Float(i%13)*0.017,Float(i%7)*0.029,0.45+Float(i%11)*0.013)}
        let r=simd_float3x3(simd_quatf(angle:0.08,axis:simd_normalize(SIMD3<Float>(0.3,0.9,-0.2)))),t=SIMD3<Float>(0.015,-0.007,0.004)
        var expected=points.map{r*$0+t}
        for i in 0..<25 {expected[i] += SIMD3(0.3,0.2,-0.1)}
        let result=try XCTUnwrap(RGBDRigidAlignment.robust(points,expected))
        XCTAssertGreaterThanOrEqual(result.inliers,125);XCTAssertLessThan(result.rmse,0.00001)
        XCTAssertLessThan(simd_distance(SIMD3(result.transform.columns.3.x,result.transform.columns.3.y,result.transform.columns.3.z),t),0.00001)
        for i in 0..<3 {XCTAssertLessThan(simd_distance(SIMD3(result.transform[i].x,result.transform[i].y,result.transform[i].z),r[i]),0.00001)}
        XCTAssertNil(RGBDRigidAlignment.robust(points,points.map{$0*2}))
    }
    func testOpticalFlowDirectionAndMetricTranslation() throws {
        let w=320,h=240,format=UIGraphicsImageRendererFormat();format.scale=1
        let image=UIGraphicsImageRenderer(size:CGSize(width:w,height:h),format:format).image {ctx in
            for y in 0..<60 {for x in 0..<80 {let seed=(x*73856093) ^ (y*19349663);UIColor(white:CGFloat(seed%251)/250,alpha:1).setFill();ctx.fill(CGRect(x:x*4,y:y*4,width:4,height:4))}}
        }
        let moved=UIGraphicsImageRenderer(size:CGSize(width:w,height:h),format:format).image {_ in image.draw(at:CGPoint(x:6,y:0))}
        let a=try CalibratedRaster.buffer(w,h),b=try CalibratedRaster.buffer(w,h),context=CIContext()
        context.render(CIImage(cgImage:try XCTUnwrap(image.cgImage)),to:a);context.render(CIImage(cgImage:try XCTUnwrap(moved.cgImage)),to:b)
        let k=simd_float3x3(columns:(SIMD3(300,0,0),SIMD3(0,300,0),SIMD3(160,120,1))),depth=[Float](repeating:0.5,count:w*h)
        let tracker=RGBDTracking();XCTAssertNotNil(tracker.update(.init(image:a,depth:depth,width:w,height:h,k:k,time:0)))
        let result=try XCTUnwrap(tracker.update(.init(image:b,depth:depth,width:w,height:h,k:k,time:0.2)),tracker.failure+tracker.diagnostic)
        XCTAssertEqual(result.columns.3.x,-0.01,accuracy:0.002)
        XCTAssertEqual(result.columns.3.y,0,accuracy:0.002)
        XCTAssertGreaterThan(tracker.inliers,50)
    }
}
