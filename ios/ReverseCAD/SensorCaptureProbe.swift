#if DEBUG
import AVFoundation
import ARKit
import SwiftUI
import CoreImage
import ReverseCADCore

/// Explicit, local-only device diagnostic. Never included in a distribution build.
final class SensorCaptureProbe: NSObject, ObservableObject, AVCaptureDataOutputSynchronizerDelegate, ARSessionDelegate {
    @Published var message = "Checking camera support…"
    private let queue = DispatchQueue(label: "reversecad.sensor-probe")
    private var capture: AVCaptureMultiCamSession?
    private var synchronizer: AVCaptureDataOutputSynchronizer?
    private var outputs = [String: AVCaptureVideoDataOutput]()
    private var depth: AVCaptureDepthDataOutput?
    private var counts = [String: Int]()
    private var samples = [[String: Double]]()
    private var report = [String: Any]()
    private var trials = [[String: Any]]()
    private var current = [String: Any]()
    private var ar: ARSession?
    private var arSamples = [[String: Any]]()
    private var pending = [([String], Bool)]()
    private let directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("SensorDiagnostics", isDirectory: true)
    private let runID=UUID().uuidString

    func start() {
        AVCaptureDevice.requestAccess(for: .video) { allowed in
            self.queue.async {
                guard allowed else {self.report["error"] = "Camera permission denied"; self.save(); return}
                let discovery = Self.discovery()
                self.report = ["schema": "reversecad-device-sensors/1", "created": ISO8601DateFormatter().string(from: Date()), "system": UIDevice.current.systemVersion,
                    "run": self.runID,
                    "multicam_supported": AVCaptureMultiCamSession.isMultiCamSupported,
                    "supported_sets": discovery.supportedMultiCamDeviceSets.map {$0.map { $0.deviceType.rawValue }.sorted()},
                    "devices": discovery.devices.map { d in ["type": d.deviceType.rawValue, "virtual": d.isVirtualDevice, "formats": d.formats.enumerated().filter {$0.element.isMultiCamSupported}.map { i, f -> [String: Any] in
                        let size = CMVideoFormatDescriptionGetDimensions(f.formatDescription)
                        return ["index": i, "size": [size.width, size.height], "depth_formats": f.supportedDepthDataFormats.count, "fps": f.videoSupportedFrameRateRanges.map {[$0.minFrameRate, $0.maxFrameRate]}]
                    }] }]
                self.save()
                self.pending = [(["wide", "ultra", "tele"], true), (["wide", "ultra", "tele"], false), (["wide", "ultra"], true), (["wide", "tele"], true), (["ultra", "tele"], false)]
                self.next()
            }
        }
    }
    static func discovery() -> AVCaptureDevice.DiscoverySession {
        AVCaptureDevice.DiscoverySession(deviceTypes: [.builtInWideAngleCamera, .builtInUltraWideCamera, .builtInTelephotoCamera, .builtInLiDARDepthCamera], mediaType: .video, position: .back)
    }
    private func next() {
        guard !pending.isEmpty else {save(); DispatchQueue.main.async {self.message = "Camera check complete. Results saved on this phone."}; return}
        let (names, useDepth) = pending.removeFirst()
        if !names.contains("wide") {
            let session=ARSession();session.delegate=self;session.delegateQueue=queue;ar=session
            let config=ARWorldTrackingConfiguration();config.frameSemantics=[.sceneDepth]
            if let format=ARWorldTrackingConfiguration.supportedVideoFormats.filter({$0.captureDeviceType == .builtInWideAngleCamera && $0.framesPerSecond == 30}).min(by:{$0.imageResolution.width<$1.imageResolution.width}) {config.videoFormat=format}
            session.run(config)
            queue.asyncAfter(deadline:.now()+3) {self.startTrial(names:names,useDepth:useDepth)}
        } else {startTrial(names:names,useDepth:useDepth)}
    }
    private func startTrial(names:[String],useDepth:Bool) {
        current = ["cameras": names, "lidar": useDepth]; counts = [:]; samples = []
        current["arkit_concurrent"]=ar != nil;arSamples=[]
        do {
            let discovery = Self.discovery()
            let devices = try names.map { name -> AVCaptureDevice in
                let type: AVCaptureDevice.DeviceType = name == "wide" ? (useDepth ? .builtInLiDARDepthCamera : .builtInWideAngleCamera) : (name == "ultra" ? .builtInUltraWideCamera : .builtInTelephotoCamera)
                guard let d = discovery.devices.first(where: {$0.deviceType == type}) else {throw CaptureFailure.unavailable("Missing \(name)")}; return d
            }
            current["advertised_supported"] = discovery.supportedMultiCamDeviceSets.contains { Set(devices).isSubset(of: $0) }
            let session = AVCaptureMultiCamSession(); capture = session
            session.beginConfiguration()
            defer {session.commitConfiguration()}
            for (name, device) in zip(names, devices) {
                let input = try AVCaptureDeviceInput(device: device)
                guard session.canAddInput(input) else {throw CaptureFailure.unavailable("Cannot add \(name) input to this simultaneous combination")}
                session.addInputWithNoConnections(input)
                let needsDepth = useDepth && name == "wide"
                let formats = device.formats.filter { f in
                    f.isMultiCamSupported && (!needsDepth || !f.supportedDepthDataFormats.isEmpty) && f.videoSupportedFrameRateRanges.contains {$0.minFrameRate <= 15 && $0.maxFrameRate >= 15}
                }
                guard let format = formats.min(by: {a,b in
                    let x=CMVideoFormatDescriptionGetDimensions(a.formatDescription), y=CMVideoFormatDescriptionGetDimensions(b.formatDescription)
                    return abs(Int(x.width)-1280)*10000+Int(x.height) < abs(Int(y.width)-1280)*10000+Int(y.height)
                }) else {throw CaptureFailure.unavailable("No MultiCam format for \(name) with requested depth")}
                try device.lockForConfiguration()
                device.activeFormat = format
                device.activeVideoMinFrameDuration=CMTime(value:1,timescale:15); device.activeVideoMaxFrameDuration=CMTime(value:1,timescale:15)
                if needsDepth {device.activeDepthDataFormat = format.supportedDepthDataFormats.last}
                device.unlockForConfiguration()
                let output=AVCaptureVideoDataOutput(); output.alwaysDiscardsLateVideoFrames=true
                output.videoSettings=[kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_420YpCbCr8BiPlanarFullRange]
                guard session.canAddOutput(output) else {throw CaptureFailure.unavailable("Cannot add \(name) output")}; session.addOutputWithNoConnections(output)
                guard let port=input.ports.first(where: {$0.mediaType == .video}) else {throw CaptureFailure.unavailable("No video port")}
                let connection=AVCaptureConnection(inputPorts:[port],output:output)
                guard session.canAddConnection(connection) else {throw CaptureFailure.unavailable("Cannot connect \(name)")}; session.addConnection(connection)
                connection.preferredVideoStabilizationMode = .off
                if connection.isCameraIntrinsicMatrixDeliverySupported {connection.isCameraIntrinsicMatrixDeliveryEnabled=true}
                outputs[name]=output
                if needsDepth {
                    let d=AVCaptureDepthDataOutput();d.isFilteringEnabled=false
                    guard session.canAddOutput(d), let port=input.ports.first(where:{$0.mediaType == .depthData}) else {throw CaptureFailure.unavailable("LiDAR output unavailable")}
                    session.addOutputWithNoConnections(d)
                    let c=AVCaptureConnection(inputPorts:[port],output:d)
                    guard session.canAddConnection(c) else {throw CaptureFailure.unavailable("LiDAR connection unavailable")};session.addConnection(c);depth=d
                }
            }
            current["hardware_cost"]=session.hardwareCost;current["pressure_cost"]=session.systemPressureCost
        } catch {current["error"]=error.localizedDescription; finishTrial(); return}
        guard let capture else {return}
        if capture.hardwareCost > 1 {current["error"]="Hardware cost exceeds 1";finishTrial();return}
        var all: [AVCaptureOutput] = Array(outputs.values)
        if let depth {all.append(depth)}
        synchronizer=AVCaptureDataOutputSynchronizer(dataOutputs:all);synchronizer?.setDelegate(self,queue:queue)
        capture.startRunning()
        current["running"]=capture.isRunning
        DispatchQueue.main.async {self.message="Testing \(names.joined(separator: ", "))\(useDepth ? " + LiDAR" : "")…"}
        queue.asyncAfter(deadline:.now()+6) {self.finishTrial()}
    }
    func session(_ session: ARSession,didUpdate frame:ARFrame) {
        guard ar === session else {return}
        counts["arkit",default:0]+=1
        if frame.sceneDepth != nil {counts["arkit_lidar",default:0]+=1}
        if arSamples.count<240 {arSamples.append(["time":frame.timestamp,"depth":frame.sceneDepth != nil,"tracking":String(describing:frame.camera.trackingState)])}
    }
    func session(_ session:ARSession,didFailWithError error:Error) {current["arkit_error"]=error.localizedDescription}
    func sessionWasInterrupted(_ session:ARSession) {current["arkit_interrupted"]=true}
    func dataOutputSynchronizer(_ synchronizer: AVCaptureDataOutputSynchronizer, didOutput collection: AVCaptureSynchronizedDataCollection) {
        var row=[String:Double]()
        for (name,output) in outputs {
            if let sample=collection.synchronizedData(for:output) as? AVCaptureSynchronizedSampleBufferData, !sample.sampleBufferWasDropped {
                counts[name,default:0]+=1;row[name]=CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample.sampleBuffer))
                if let pixel=CMSampleBufferGetImageBuffer(sample.sampleBuffer), [1,60].contains(counts[name] ?? 0) {dump(pixel,name:name,count:counts[name] ?? 0)}
            }
        }
        if let depth, let sample=collection.synchronizedData(for:depth) as? AVCaptureSynchronizedDepthData, !sample.depthDataWasDropped {
            counts["lidar",default:0]+=1;row["lidar"]=CMTimeGetSeconds(sample.timestamp)
            if [1,60].contains(counts["lidar"] ?? 0) {dump(sample.depthData.converting(toDepthDataType:kCVPixelFormatType_DepthFloat32).depthDataMap,name:"lidar",count:counts["lidar"] ?? 0)}
        }
        if samples.count < 180 {samples.append(row)}
    }
    private func finishTrial() {
        synchronizer?.setDelegate(nil,queue:nil);capture?.stopRunning()
        current["delivered_frames"]=counts;current["timestamps"]=samples;current["arkit_samples"]=arSamples
        ar?.pause();ar=nil
        trials.append(current);capture=nil;synchronizer=nil;depth=nil;outputs=[:];save()
        queue.asyncAfter(deadline:.now()+0.5) {self.next()}
    }
    private func save() {
        report["trials"]=trials
        try? FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        let run=directory.appendingPathComponent(runID);try? FileManager.default.createDirectory(at:run,withIntermediateDirectories:true)
        if let data=try? JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]) {
            try? data.write(to:directory.appendingPathComponent("camera-check.json"),options:.atomic)
            try? data.write(to:run.appendingPathComponent("camera-check.json"),options:.atomic)
        }
    }
    private func dump(_ pixel:CVPixelBuffer,name:String,count:Int) {
        let stem="\(runID)/trial-\(trials.count)-\(name)-\(count)"
        CVPixelBufferLockBaseAddress(pixel,.readOnly);defer {CVPixelBufferUnlockBaseAddress(pixel,.readOnly)}
        let planes=max(1,CVPixelBufferGetPlaneCount(pixel));var records=[[String:Any]]()
        for plane in 0..<planes {
            let planar=CVPixelBufferIsPlanar(pixel)
            let base=planar ? CVPixelBufferGetBaseAddressOfPlane(pixel,plane):CVPixelBufferGetBaseAddress(pixel)
            let h=planar ? CVPixelBufferGetHeightOfPlane(pixel,plane):CVPixelBufferGetHeight(pixel)
            let stride=planar ? CVPixelBufferGetBytesPerRowOfPlane(pixel,plane):CVPixelBufferGetBytesPerRow(pixel)
            if let base {
                let data=Data(bytes:base,count:h*stride),path="\(stem)-plane\(plane).bin"
                try? data.write(to:directory.appendingPathComponent(path),options:.atomic)
                records.append(["path":path,"sha256":CaptureIO.sha256(data),"row_bytes":stride,"height":h])
            }
        }
        var snapshots=current["snapshots"] as? [[String:Any]] ?? []
        var row:[String:Any]=["camera":name,"sample":count,"width":CVPixelBufferGetWidth(pixel),"height":CVPixelBufferGetHeight(pixel),"pixel_format":CVPixelBufferGetPixelFormatType(pixel),"planes":records]
        if name=="lidar",let base=CVPixelBufferGetBaseAddress(pixel) {
            var values=[Float]()
            for y in 0..<CVPixelBufferGetHeight(pixel) {for x in 0..<CVPixelBufferGetWidth(pixel) {
                let z=base.loadUnaligned(fromByteOffset:y*CVPixelBufferGetBytesPerRow(pixel)+x*4,as:Float.self)
                if z.isFinite && z>0 {values.append(z)}
            }}
            values.sort();row["finite_positive_samples"]=values.count;row["median_depth_m"]=values.isEmpty ? 0:values[values.count/2]
        } else if let image=CIContext().pngRepresentation(of:CIImage(cvPixelBuffer:pixel),format:.RGBA8,colorSpace:CGColorSpaceCreateDeviceRGB()) {
            let path=stem+".png";try? image.write(to:directory.appendingPathComponent(path));row["preview"]=path
        }
        snapshots.append(row);current["snapshots"]=snapshots
    }
}
struct SensorCaptureProbeView: View {
    @StateObject private var probe=SensorCaptureProbe()
    var body: some View {VStack(spacing:24) {Text("ReverseCAD").font(.largeTitle);Text(probe.message);Text("Local camera diagnostic").foregroundStyle(.secondary)}.padding().task {probe.start()}}
}
#endif
