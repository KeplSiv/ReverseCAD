import AVFoundation
import UIKit
import simd

/// One session owns all rear cameras. ARKit must be stopped before starting it.
final class MultiCameraSession: NSObject, AVCaptureDataOutputSynchronizerDelegate, @unchecked Sendable {
    struct Video {
        let pixel: CVPixelBuffer
        let time: Double
        let intrinsics: simd_float3x3
    }
    struct Packet {
        let videos: [String: Video]
        let depth: AVDepthData
        let time: Double
    }
    let session = AVCaptureMultiCamSession()
    let queue = DispatchQueue(label: "reversecad.multicam", qos: .userInitiated)
    private(set) var preview: AVCaptureVideoPreviewLayer!
    private(set) var calibration = [String: Any]()
    private var outputs = [String: AVCaptureVideoDataOutput]()
    private var depthOutput: AVCaptureDepthDataOutput!
    private var synchronizer: AVCaptureDataOutputSynchronizer?
    private var videos = [String: [Video]]()
    private var depths = [(Double, AVDepthData)]()
    private var reference: Video?
    private var referenceDate=Date.distantPast
    private var configured=false
    private var joinedCount=0
    private let lock = NSLock()
    var onPacket: ((Packet) -> Void)?
    var onFailure: ((String) -> Void)?
    private var observers = [NSObjectProtocol]()
    private(set) var delivered = [String: Int]()
    static let maximumOffset = 0.045

    override init() { super.init() }
    deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }

    func start(onPreview: ((AVCaptureVideoPreviewLayer)->Void)? = nil) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                do {
                    if self.session.isRunning {if let preview=self.preview {onPreview?(preview)};continuation.resume();return}
                    self.videos=[:];self.depths=[];self.delivered=[:];self.joinedCount=0
                    self.lock.lock();self.reference=nil;self.referenceDate = .distantPast;self.lock.unlock()
                    if !self.configured {
                        do {try self.configure();self.configured=true}
                        catch {self.rollbackConfiguration();throw error}
                    }
                    if let preview=self.preview {onPreview?(preview)}
                    self.session.startRunning()
                    guard self.session.isRunning else { throw CaptureFailure.unavailable("The rear cameras could not start. Close other camera apps and try again.") }
                    self.queue.asyncAfter(deadline:.now()+3) {
                        if self.session.isRunning && self.joinedCount>0 {continuation.resume()}
                        else {self.session.stopRunning();continuation.resume(throwing:CaptureFailure.unavailable("All three cameras and LiDAR must deliver fresh frames. Reset the camera and try again."))}
                    }
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
    func stop(completion: (() -> Void)? = nil) {
        queue.async {
            self.onPacket = nil; self.session.stopRunning(); self.videos = [:]; self.depths = []
            self.lock.lock(); self.reference = nil; self.referenceDate = .distantPast; self.lock.unlock()
            completion?()
        }
    }
    func latest() -> Video? { lock.lock(); defer { lock.unlock() }; return Date().timeIntervalSince(referenceDate)<1.5 ? reference : nil }

    func videoRegion(fromMetadata rect:CGRect) throws -> CGRect {
        guard configured,let output=outputs["wide"],let video=latest() else {throw CaptureFailure.unavailable("The camera mapping is not ready.")}
        let pixels=output.outputRectConverted(fromMetadataOutputRect:rect)
        // AVCaptureOutput converts to pixel coordinates, not normalized output.
        let w=CGFloat(CVPixelBufferGetWidth(video.pixel)),h=CGFloat(CVPixelBufferGetHeight(video.pixel))
        return CGRect(x:pixels.minX/w,y:pixels.minY/h,width:pixels.width/w,height:pixels.height/h)
    }
    func metadataRegion(fromVideo rect:CGRect) throws -> CGRect {
        guard configured,let output=outputs["wide"],let video=latest() else {throw CaptureFailure.unavailable("The camera mapping is not ready.")}
        let w=CGFloat(CVPixelBufferGetWidth(video.pixel)),h=CGFloat(CVPixelBufferGetHeight(video.pixel))
        return output.metadataOutputRectConverted(fromOutputRect:CGRect(x:rect.minX*w,y:rect.minY*h,width:rect.width*w,height:rect.height*h))
    }
    private func rollbackConfiguration() {
        session.beginConfiguration()
        for connection in session.connections {session.removeConnection(connection)}
        for output in session.outputs {session.removeOutput(output)}
        for input in session.inputs {session.removeInput(input)}
        session.commitConfiguration()
        outputs=[:];depthOutput=nil;preview=nil;synchronizer=nil;calibration=[:];configured=false
        for observer in observers {NotificationCenter.default.removeObserver(observer)}
        observers=[]
    }
    private func configure() throws {
        guard AVCaptureMultiCamSession.isMultiCamSupported else { throw CaptureFailure.unavailable("This scan requires simultaneous rear cameras and LiDAR. This phone does not support MultiCam.") }
        let types: [String: AVCaptureDevice.DeviceType] = ["wide": .builtInLiDARDepthCamera, "ultra": .builtInUltraWideCamera, "tele": .builtInTelephotoCamera]
        var devices = [String: AVCaptureDevice]()
        session.beginConfiguration()
        defer { session.commitConfiguration() }
        for name in ["wide", "ultra", "tele"] {
            guard let device = AVCaptureDevice.default(types[name]!, for: .video, position: .back) else {
                throw CaptureFailure.unavailable("This scan requires wide, ultra-wide and telephoto cameras plus LiDAR. The \(name) camera is unavailable.")
            }
            devices[name] = device
            let input = try AVCaptureDeviceInput(device: device)
            guard session.canAddInput(input) else { throw CaptureFailure.unavailable("The \(name) camera cannot run with the other sensors on this phone.") }
            session.addInputWithNoConnections(input)
            let formats = device.formats.filter { f in
                f.isMultiCamSupported && (name != "wide" || !f.supportedDepthDataFormats.isEmpty) && f.videoSupportedFrameRateRanges.contains { $0.minFrameRate <= 15 && $0.maxFrameRate >= 15 }
            }
            guard let format = formats.min(by: { a, b in
                let x = CMVideoFormatDescriptionGetDimensions(a.formatDescription), y = CMVideoFormatDescriptionGetDimensions(b.formatDescription)
                return abs(Int(x.width)-1280)*10000+Int(x.height) < abs(Int(y.width)-1280)*10000+Int(y.height)
            }) else { throw CaptureFailure.unavailable("No compatible \(name) camera format is available.") }
            try device.lockForConfiguration()
            device.activeFormat = format
            device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 15)
            device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 15)
            if name == "wide" { device.activeDepthDataFormat = format.supportedDepthDataFormats.last }
            // The primary image and depth are rectified together from delivered LUTs.
            // Auxiliary streams use the system's geometric correction, when available.
            if device.isGeometricDistortionCorrectionSupported { device.isGeometricDistortionCorrectionEnabled = name != "wide" }
            device.unlockForConfiguration()
            let output = AVCaptureVideoDataOutput()
            output.alwaysDiscardsLateVideoFrames = true
            output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange]
            guard session.canAddOutput(output), let port = input.ports.first(where: { $0.mediaType == .video }) else { throw CaptureFailure.unavailable("Cannot read \(name) camera images.") }
            session.addOutputWithNoConnections(output)
            let connection = AVCaptureConnection(inputPorts: [port], output: output)
            guard session.canAddConnection(connection) else { throw CaptureFailure.unavailable("Cannot connect \(name) camera images.") }
            session.addConnection(connection)
            connection.preferredVideoStabilizationMode = .off
            if connection.isVideoRotationAngleSupported(0) {connection.videoRotationAngle=0}
            if connection.isVideoMirroringSupported {connection.automaticallyAdjustsVideoMirroring=false;connection.isVideoMirrored=false}
            guard connection.isCameraIntrinsicMatrixDeliverySupported else { throw CaptureFailure.unavailable("The \(name) camera did not provide calibrated intrinsics.") }
            connection.isCameraIntrinsicMatrixDeliveryEnabled = true
            outputs[name] = output
            let dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            calibration[name] = ["device_type": device.deviceType.rawValue, "width": dimensions.width, "height": dimensions.height,
                "stabilization": "off", "system_distortion_correction": device.isGeometricDistortionCorrectionEnabled]
            if name == "wide" {
                let depth = AVCaptureDepthDataOutput(); depth.isFilteringEnabled = false
                guard session.canAddOutput(depth), let depthPort = input.ports.first(where: { $0.mediaType == .depthData }) else { throw CaptureFailure.unavailable("LiDAR is unavailable with the rear cameras.") }
                session.addOutputWithNoConnections(depth)
                let depthConnection = AVCaptureConnection(inputPorts: [depthPort], output: depth)
                guard session.canAddConnection(depthConnection) else { throw CaptureFailure.unavailable("The LiDAR connection could not be created.") }
                session.addConnection(depthConnection); depthOutput = depth
                preview = AVCaptureVideoPreviewLayer(sessionWithNoConnection: session)
                preview.videoGravity = .resizeAspectFill
                let display = AVCaptureConnection(inputPort: port, videoPreviewLayer: preview)
                guard session.canAddConnection(display) else { throw CaptureFailure.unavailable("The camera preview could not be connected.") }
                session.addConnection(display)
                if display.isVideoRotationAngleSupported(90) { display.videoRotationAngle = 90 }
            }
        }
        guard session.hardwareCost <= 1 else { throw CaptureFailure.unavailable("The simultaneous camera configuration exceeds this phone's hardware capacity.") }
        guard let physicalWide = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else { throw CaptureFailure.unavailable("Wide-camera factory calibration is missing.") }
        for name in ["ultra", "tele"] {
            guard let target = devices[name], let data = AVCaptureDevice.extrinsicMatrix(from: physicalWide, to: target), data.count == MemoryLayout<simd_float4x3>.size else {
                throw CaptureFailure.unavailable("The \(name) camera is missing its factory alignment. This scan cannot combine uncalibrated cameras.")
            }
            let matrix = data.withUnsafeBytes { $0.loadUnaligned(as: simd_float4x3.self) }
            var row = calibration[name] as! [String: Any]
            row["from_wide_extrinsics_column_major_mm"] = (0..<4).flatMap { c in (0..<3).map { r in Double(matrix[c][r]) } }
            calibration[name] = row
        }
        calibration["hardware_cost"] = session.hardwareCost
        calibration["pressure_cost"] = session.systemPressureCost
        calibration["timestamp_tolerance_s"] = Self.maximumOffset
        synchronizer = AVCaptureDataOutputSynchronizer(dataOutputs: [outputs["wide"]!, depthOutput!, outputs["ultra"]!, outputs["tele"]!])
        synchronizer?.setDelegate(self, queue: queue)
        observers.append(NotificationCenter.default.addObserver(forName: .AVCaptureSessionWasInterrupted, object: session, queue: nil) { [weak self] _ in
            self?.onFailure?("Capture was interrupted. Saved views are preserved. Finish this pass and retry when the cameras are available.")
        })
        observers.append(NotificationCenter.default.addObserver(forName: .AVCaptureSessionRuntimeError, object: session, queue: nil) { [weak self] _ in
            self?.onFailure?("The camera session stopped. Saved views are preserved. Let the phone cool, then retry.")
        })
    }

    func dataOutputSynchronizer(_ synchronizer: AVCaptureDataOutputSynchronizer, didOutput collection: AVCaptureSynchronizedDataCollection) {
        for (name, output) in outputs {
            guard let sample = collection.synchronizedData(for: output) as? AVCaptureSynchronizedSampleBufferData, !sample.sampleBufferWasDropped,
                  let pixel = CMSampleBufferGetImageBuffer(sample.sampleBuffer),
                  let data = CMGetAttachment(sample.sampleBuffer, key: kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix, attachmentModeOut: nil) as? Data,
                  data.count == MemoryLayout<simd_float3x3>.size else { continue }
            let video = Video(pixel: pixel, time: CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample.sampleBuffer)), intrinsics: data.withUnsafeBytes { $0.loadUnaligned(as: simd_float3x3.self) })
            delivered[name, default: 0] += 1
            videos[name, default: []].append(video); videos[name] = Array(videos[name]!.suffix(4))
            if name == "wide" { lock.lock(); reference = video; referenceDate=Date(); lock.unlock() }
        }
        if let sample = collection.synchronizedData(for: depthOutput) as? AVCaptureSynchronizedDepthData, !sample.depthDataWasDropped {
            delivered["lidar", default: 0] += 1
            depths.append((CMTimeGetSeconds(sample.timestamp), sample.depthData)); depths = Array(depths.suffix(4))
        }
        // Sensors have different exposure phases; a synchronizer callback is not
        // guaranteed to contain all outputs. Join only measured nearby timestamps.
        guard let wide = videos["wide"]?.first,
              let d = depths.min(by: { abs($0.0-wide.time) < abs($1.0-wide.time) }), abs(d.0-wide.time) < 0.002 else { trim(); return }
        var selected = ["wide": wide]
        for name in ["ultra", "tele"] {
            guard let match = videos[name]?.min(by: { abs($0.time-wide.time) < abs($1.time-wide.time) }), abs(match.time-wide.time) <= Self.maximumOffset else { trim(); return }
            selected[name] = match
        }
        joinedCount += 1
        onPacket?(Packet(videos: selected, depth: d.1, time: wide.time))
        for (name, selected) in selected { videos[name]?.removeAll { $0.time <= selected.time } }
        depths.removeAll { $0.0 <= d.0 }
    }
    private func trim() {
        let latest = videos.values.compactMap { $0.last?.time }.max() ?? 0
        for name in Array(videos.keys) { videos[name]?.removeAll { $0.time < latest-0.15 } }
        depths.removeAll { $0.0 < latest-0.15 }
    }
}
