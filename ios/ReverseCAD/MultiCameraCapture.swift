import Foundation
import AVFoundation
import CoreImage
import Vision
import UIKit
import ReverseCADCore

/// RGB-D poses use the full scene. Only object geometry receives a foreground mask.
final class MultiCameraCaptureProvider: CaptureProvider, @unchecked Sendable {
    var onFrame: ((CaptureFrame) -> Void)?
    var onProgress: ((CaptureProgress) -> Void)?
    var onObservedSurface: ((ObservedSurface, String) -> Void)?
    private let camera: MultiCameraSession
    private let directory: URL
    private let scanID: String
    private let segment = UUID().uuidString
    private let queue = DispatchQueue(label: "reversecad.multicam-processing", qos: .userInitiated)
    private let slot = DispatchSemaphore(value: 1)
    private let ci = CIContext(options: [.cacheIntermediates: false])
    private let tracker = RGBDTracking()
    private var writer: ScanPackageWriter!
    private var stats = CaptureProgress()
    private var origin: Double?
    private var lastSavedTime = -Double.infinity
    private var lastPose: simd_float4x4?
    private var lastDirection: SIMD3<Float>?
    private var byteCeiling=480*1024*1024
    private var guide = ScanGuidance()
    private var target: SIMD3<Float>?
    private let rawRegion: CGRect
    private let confirmed: Bool
    private var objectTracker: VNTrackObjectRequest?
    private let objectSequence = VNSequenceRequestHandler()
    private var stopped = false
    private var finishTask: Task<URL, Error>?
    private var firstError: String?
    private var diagnosticFrames = [[String: Any]]()
    private let displayRotation: Int

    init(camera: MultiCameraSession, directory: URL, scanID: String, region: CGRect, confirmed: Bool, displayRotation: Int = 90) throws {
        self.camera=camera;self.directory=directory;self.scanID=scanID;rawRegion=region;self.confirmed=confirmed;self.displayRotation=displayRotation
        writer = try ScanPackageWriter(directory: directory, manifest: CaptureManifest(scanID: scanID, source: "multicam_rgbd", device: UIDevice.current.model, segments: [CaptureSegment(segmentID: segment)]))
        if !FileManager.default.fileExists(atPath:directory.appendingPathComponent("identification-pass").path) {byteCeiling=220*1024*1024}
        var hardware=camera.calibration
        hardware["active_path"]="avcapture_multicam_rgbd"
        hardware["configured_rear_camera_count"]=3
        hardware["private_sensor_interception_active"]=false
        hardware["pose_source"]="full_scene_rgbd_rigid_correspondences"
        hardware["confidence_source"]="finite_depth_and_local_consistency; native confidence unavailable"
        hardware["metric_accuracy_validated"]=false
        try JSONSerialization.data(withJSONObject: hardware, options: [.sortedKeys]).write(to: directory.appendingPathComponent("capture-hardware.json"), options: .atomic)
    }
    func start() {
        camera.queue.async { [self] in
            camera.onFailure = { [weak self] message in self?.queue.async { self?.stopWith(message) } }
            camera.onPacket = { [weak self] packet in
                guard let self else {return}
                guard slot.wait(timeout: .now()) == .success else {return}
                queue.async { [self] in
                    defer { self.slot.signal() }
                    guard !self.stopped else {return}
                    autoreleasepool {
                        do { try self.process(packet) }
                        catch { self.firstError=error.localizedDescription;self.stopWith(error.localizedDescription) }
                    }
                }
            }
        }
    }
    private func stopWith(_ message: String) {
        guard !stopped else {return}
        stopped=true;stats.guidance=message;stats.finished=true;onProgress?(stats)
    }
    private func process(_ packet: MultiCameraSession.Packet) throws {
        guard let primary=packet.videos["wide"] else {return}
        if origin == nil {origin=min(packet.time,packet.videos.values.map(\.time).min() ?? packet.time)}
        let time=packet.time-origin!
        if time>180 {stopWith("This pass reached its capture limit. Saved views are preserved; review coverage before processing.");return}
        let raster=try CalibratedRaster.make(rgb:primary.pixel,depth:packet.depth,context:ci)
        let pose=tracker.update(.init(image:raster.trackingImage,depth:raster.depth,width:raster.width,height:raster.height,k:raster.depthK,time:time))
        if diagnosticFrames.count<1000 {diagnosticFrames.append(["time_s":time,"tracked":pose != nil,"inliers":tracker.inliers,"residual_m":tracker.residual,"failure":tracker.failure,"detail":tracker.diagnostic,"pose":ARKitCaptureProvider.columnMajor(tracker.worldFromCamera)])}
        guard let trackedPose=pose else {
            stats.rejected += 1;stats.guidance=tracker.failure;onProgress?(stats);return
        }
        let axes=simd_float4x4(diagonal:SIMD4<Float>(1,-1,-1,1))
        let opticalPose=axes*trackedPose
        let worldCamera=opticalPose*axes
        let rawBox=rawRegion
        func ideal(_ p:CGPoint)->CGPoint {
            let pixel=SIMD2(Float(p.x)*raster.calibration.size.x,Float(p.y)*raster.calibration.size.y)
            let ray=raster.calibration.ray(at:pixel)
            let q=raster.calibration.K*ray
            return CGPoint(x:Double(q.x/q.z/raster.calibration.size.x),y:Double(q.y/q.z/raster.calibration.size.y))
        }
        let corners=[CGPoint(x:rawBox.minX,y:rawBox.minY),CGPoint(x:rawBox.maxX,y:rawBox.minY),CGPoint(x:rawBox.minX,y:rawBox.maxY),CGPoint(x:rawBox.maxX,y:rawBox.maxY)].map(ideal)
        let x0=max(0,corners.map(\.x).min()!),y0=max(0,corners.map(\.y).min()!)
        var region=CGRect(x:x0,y:y0,width:min(1,corners.map(\.x).max()!)-x0,height:min(1,corners.map(\.y).max()!)-y0)
        if confirmed {
            if objectTracker == nil {
                objectTracker=VNTrackObjectRequest(detectedObjectObservation:VNDetectedObjectObservation(boundingBox:CGRect(x:region.minX,y:1-region.maxY,width:region.width,height:region.height)))
                objectTracker?.trackingLevel = .accurate
            } else if let objectTracker {
                try objectSequence.perform([objectTracker],on:raster.image,orientation:.up)
                guard let observation=objectTracker.results?.first as? VNDetectedObjectObservation,observation.confidence>=0.6 else {
                    stats.rejected += 1;stats.guidance="Keep the same object in view. Return slowly to the last clear view.";onProgress?(stats);return
                }
                objectTracker.inputObservation=observation
                let b=observation.boundingBox
                region=CGRect(x:b.minX,y:1-b.maxY,width:b.width,height:b.height)
            }
        }
        let point=CGPoint(x:region.midX,y:region.midY)
        let blur=ARKitCaptureProvider.blurScore(primary.pixel,region:[rawBox.minX,rawBox.minY,rawBox.width,rawBox.height])
        let confidence=Self.validity(raster.depth,width:raster.width,height:raster.height)
        let validCount=confidence.filter{$0>0}.count
        guard blur>=7,validCount>raster.width*raster.height/10 else {
            stats.rejected += 1;stats.guidance=blur<7 ? "Hold still briefly for a sharp view. Add light or visible texture." : "Depth is weak. Change the angle or distance and avoid glare.";onProgress?(stats);return
        }
        if target == nil {
            let x=min(raster.width-1,max(0,Int(point.x*Double(raster.width)))),y=min(raster.height-1,max(0,Int(point.y*Double(raster.height))))
            var values=[Float]()
            for yy in max(0,y-3)...min(raster.height-1,y+3) {for xx in max(0,x-3)...min(raster.width-1,x+3) {
                let i=yy*raster.width+xx;if confidence[i]>0 {values.append(raster.depth[i])}
            }}
            if values.count>=9 {
                values.sort();let z=values[values.count/2]
                let ray=simd_inverse(raster.depthK)*SIMD3(Float(x),Float(y),1),p=opticalPose*SIMD4(ray*z,1)
                target=SIMD3(p.x,p.y,p.z)
            }
        }
        guard time-lastSavedTime>=0.45 else {return}
        if let target, let previous=lastDirection {
            let direction=simd_normalize(SIMD3(worldCamera.columns.3.x,worldCamera.columns.3.y,worldCamera.columns.3.z)-target)
            guard simd_dot(previous,direction)<cos(0.17) else {
                stats.guidance="Walk slowly to a new angle. This view is already saved.";onProgress?(stats);return
            }
        } else if let old=lastPose {
            let distance=simd_distance(worldCamera.columns.3,old.columns.3)
            let angle=acos(min(1,max(-1,simd_dot(SIMD3(worldCamera.columns.2.x,worldCamera.columns.2.y,worldCamera.columns.2.z),SIMD3(old.columns.2.x,old.columns.2.y,old.columns.2.z)))))
            guard distance>=0.02 || angle>=0.08 else {
                stats.guidance="Move slowly to another side of the object. This view is already saved.";onProgress?(stats);return
            }
        }
        let id=String(format:"%06d",stats.accepted)
        let rgbPath="rgb/\(id).jpg",depthPath="depth/\(id).f32",confidencePath="confidence/\(id).u8"
        var assets=[rgbPath:try jpeg(raster.image),depthPath:raster.depth.withUnsafeBytes{Data($0)},confidencePath:confidence]
        var maskPath:String?
        if confirmed {
            guard let image=ci.createCGImage(CIImage(cvPixelBuffer:raster.image),from:CGRect(x:0,y:0,width:CVPixelBufferGetWidth(raster.image),height:CVPixelBufferGetHeight(raster.image))),
                  let mask=try SavedObjectMasks.mask(image:image,box:region,width:raster.width,height:raster.height) else {
                stats.rejected += 1;stats.guidance="Show the object clearly against the background. Its outline is not distinct in this view.";onProgress?(stats);return
            }
            maskPath="masks/\(id).u8";assets[maskPath!]=mask
        }
        let standard=Set(assets.keys)
        var sensorRecords=[String:Any]()
        for name in ["wide","ultra","tele"] {
            guard let video=packet.videos[name] else {throw CaptureFailure.write("A required camera view is missing.")}
            let prefix="sensors/\(id)-\(name)"
            let planes=try Self.originalPlanes(video.pixel)
            var paths=[String](),layout=[[String:Int]]()
            for (index,plane) in planes.enumerated() {
                let path="\(prefix)-\(index).bin";assets[path]=plane.data;paths.append(path)
                layout.append(["row_bytes":plane.rowBytes,"width":plane.width,"height":plane.height])
            }
            let path=prefix+".jpg";assets[path]=try jpeg(video.pixel)
            sensorRecords[name]=["rgb_path":path,"original_plane_paths":paths,"plane_layout":layout,
                "width":CVPixelBufferGetWidth(video.pixel),"height":CVPixelBufferGetHeight(video.pixel),
                "pixel_format":CVPixelBufferGetPixelFormatType(video.pixel),"timestamp_s":video.time-origin!,
                "offset_from_primary_s":video.time-packet.time,"intrinsics":ARKitCaptureProvider.columnMajor(video.intrinsics)]
        }
        let originalDepth=packet.depth.converting(toDepthDataType:kCVPixelFormatType_DepthFloat32).depthDataMap
        let originalDepthPath="sensors/\(id)-lidar.f32"
        assets[originalDepthPath]=try ARKitCaptureProvider.copyRows(originalDepth,bytesPerPixel:4,expectedFormat:kCVPixelFormatType_DepthFloat32)
        let calibrationPath="sensors/\(id)-calibration.json"
        var calibration=camera.calibration
        calibration["primary_depth_intrinsics"]=ARKitCaptureProvider.columnMajor(raster.calibration.K)
        calibration["primary_reference_dimensions"]=[raster.calibration.size.x,raster.calibration.size.y]
        calibration["primary_distortion_center"]=[raster.calibration.center.x,raster.calibration.center.y]
        calibration["inverse_lens_distortion_lut"]=raster.calibration.inverse
        calibration["forward_lens_distortion_lut"]=raster.calibration.forward ?? []
        calibration["original_depth_path"]=originalDepthPath
        calibration["original_depth_size"]=[CVPixelBufferGetWidth(originalDepth),CVPixelBufferGetHeight(originalDepth)]
        calibration["primary_working_image"]="full view rectified once with factory LUT; pixel-center scaling; original NV12 retained"
        calibration["depth_confidence"]="native confidence unavailable; derived finite/local-depth validity is stored separately"
        assets[calibrationPath]=try JSONSerialization.data(withJSONObject:calibration,options:[.sortedKeys])
        var frame=CaptureFrame(scanID:scanID,segmentID:segment,frameID:id,timestampS:time,rgbPath:rgbPath,rgbWidth:CVPixelBufferGetWidth(raster.image),rgbHeight:CVPixelBufferGetHeight(raster.image),depthPath:depthPath,depthWidth:raster.width,depthHeight:raster.height,depthRowBytes:raster.width*4,confidencePath:confidencePath,maskPath:maskPath,intrinsics:ARKitCaptureProvider.columnMajor(raster.imageK),intrinsicsWidth:CVPixelBufferGetWidth(raster.image),intrinsicsHeight:CVPixelBufferGetHeight(raster.image),worldCamera:ARKitCaptureProvider.columnMajor(worldCamera),trackingState:"normal",quality:CaptureQuality(blurScore:blur,accepted:true))
        frame.captureRegion=[region.minX,region.minY,region.width,region.height];frame.displayRotationCW=displayRotation;frame.depthCalibrationMode="pixel_center"
        frame.additionalAssets=assets.keys.filter{!standard.contains($0)}.sorted()
        let observation:[String:Any]=["schema_version":1,"clock":"capture_elapsed_seconds","cameras":sensorRecords,
            "calibration_path":calibrationPath,"pose_source":"full_scene_rgbd_rigid","tracking_inliers":tracker.inliers,"tracking_residual_m":tracker.residual,
            "confidence_source":"derived_local_validity","native_confidence_available":false]
        frame.multiCamera=try JSONDecoder().decode(JSONValue.self,from:JSONSerialization.data(withJSONObject:observation,options:[.sortedKeys]))
        guard writer.bytesWritten+assets.values.reduce(0,{$0+$1.count})+65536<byteCeiling else {
            stopWith("This pass reached its storage budget. Your views are saved; review coverage before continuing.");return
        }
        try writer.append(frame:frame,assets:assets)
        stats.accepted += 1;stats.bytes=writer.bytesWritten;lastSavedTime=time;lastPose=worldCamera
        if let target {
            lastDirection=simd_normalize(SIMD3(worldCamera.columns.3.x,worldCamera.columns.3.y,worldCamera.columns.3.z)-target)
            // Normalize the selected region to the guide's coordinate system.
            let p=simd_inverse(opticalPose)*SIMD4(target,1),q=raster.imageK*SIMD3(p.x,p.y,p.z)
            let u=Double(q.x/q.z)/Double(frame.rgbWidth),v=Double(q.y/q.z)/Double(frame.rgbHeight)
            let normalized=SIMD2<Float>(Float((u-region.minX)/region.width)/3+1/3,Float((v-region.minY)/region.height)/3+1/3)
            stats.guidance=guide.update(camera:SIMD3(worldCamera.columns.3.x,worldCamera.columns.3.y,worldCamera.columns.3.z),target:target,screenPoint:normalized,sharp:true,tracking:true,reliableDepth:true,accepted:true)
            stats.coverageViews=guide.covered.count
        }
        if let maskPath,let mask=assets[maskPath],let surface=try? ObservedSurface.depth(frame:frame,depth:assets[depthPath]!,confidence:confidence,mask:mask) {onObservedSurface?(surface,segment)}
        onFrame?(frame);onProgress?(stats)
        if stats.accepted>=90 || stats.bytes>byteCeiling-8*1024*1024 {stopWith("This pass is saved. Review the covered views; add only the missing angles if needed.")}
    }
    private func jpeg(_ pixel:CVPixelBuffer)throws->Data {
        guard let bytes=ci.jpegRepresentation(of:CIImage(cvPixelBuffer:pixel),colorSpace:CGColorSpaceCreateDeviceRGB(),options:[kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption:0.97]) else {throw CaptureFailure.write("Could not save a camera image.")};return bytes
    }
    static func originalPlanes(_ pixel:CVPixelBuffer)throws->[(data:Data,rowBytes:Int,width:Int,height:Int)] {
        guard CVPixelBufferIsPlanar(pixel),CVPixelBufferGetPlaneCount(pixel)==2 else {throw CaptureFailure.write("Expected original NV12 camera planes.")}
        CVPixelBufferLockBaseAddress(pixel,.readOnly);defer {CVPixelBufferUnlockBaseAddress(pixel,.readOnly)}
        return try (0..<2).map {index in
            guard let p=CVPixelBufferGetBaseAddressOfPlane(pixel,index) else {throw CaptureFailure.write("A camera plane is unavailable.")}
            let row=CVPixelBufferGetBytesPerRowOfPlane(pixel,index),h=CVPixelBufferGetHeightOfPlane(pixel,index),w=CVPixelBufferGetWidthOfPlane(pixel,index)
            return (Data(bytes:p,count:row*h),row,w,h)
        }
    }
    static func validity(_ depth:[Float],width:Int,height:Int)->Data {
        var result=Data(repeating:0,count:depth.count)
        guard width>2,height>2,depth.count==width*height else{return result}
        for y in 1..<height-1 {for x in 1..<width-1 {
            let i=y*width+x,z=depth[i]
            if z.isFinite,z>0.12,z<3,[i-1,i+1,i-width,i+width].allSatisfy({depth[$0].isFinite && abs(depth[$0]-z)<max(0.012,z*0.025)}) {result[i]=1}
        }}
        return result
    }
    func finish() async throws -> URL {
        if let finishTask {return try await finishTask.value}
        let task=Task<URL,Error> {
            try await withCheckedThrowingContinuation {continuation in
                camera.queue.async { [self] in
                    camera.onPacket=nil;camera.onFailure=nil
                    camera.session.stopRunning()
                    queue.async { [self] in
                        stopped=true
                        do {
                            let diagnostic:[String:Any]=["schema_version":1,"delivered":camera.delivered,"accepted":stats.accepted,"rejected":stats.rejected,"tracking":diagnosticFrames,"error":firstError ?? ""]
                            try JSONSerialization.data(withJSONObject:diagnostic,options:[.sortedKeys]).write(to:directory.appendingPathComponent("capture_diagnostics.json"),options:.atomic)
                            continuation.resume(returning:try writer.finish())
                        } catch {continuation.resume(throwing:error)}
                    }
                }
            }
        }
        finishTask=task
        do {return try await task.value}
        catch {finishTask=nil;throw error}
    }
}
