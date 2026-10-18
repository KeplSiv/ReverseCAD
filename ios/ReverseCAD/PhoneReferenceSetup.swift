import SwiftUI
import AVFoundation
import ReverseCADCore

/// Public-API capture only. A saved reference is evidence, not a fitted camera profile.
final class PhoneReferenceCapture: NSObject, ObservableObject, AVCaptureDataOutputSynchronizerDelegate {
    @Published var running = false
    @Published var saving = false
    @Published var canSave = false
    @Published var message = "Frame the object and nearby texture, hold still, then press Save scan."
    @Published var saved: URL?
    @Published var originalArchive: URL?
    @Published var originalDirectory: URL?
    private let queue = DispatchQueue(label: "reversecad.phone-reference")
    let session = AVCaptureSession()
    private let video = AVCaptureVideoDataOutput()
    private let depth = AVCaptureDepthDataOutput()
    private var synchronizer: AVCaptureDataOutputSynchronizer?
    private var writer: ExperimentWriter?
    private var device: AVCaptureDevice?
    private var lastTime = -Double.infinity
    private var configured = false
    private var finishing = false
    private var captureID = UUID()
    private var exposureReady = false
    private var baselineExposure = 0.0
    private struct Sample {
        let colour: CMSampleBuffer
        let depth: AVDepthData
        let time: Double
        let depthTime: Double
        let settings: [String: Any]
    }
    private var samples = [Sample]()
    private var lastSaveTrigger="none"

    func start() {
        guard !running else { return }
        running = true; saving = false; canSave = false
        saved = nil; originalArchive = nil; originalDirectory = nil
        message = "Starting front camera…"
        let requestID = UUID()
        queue.async {
            self.captureID=requestID;self.writer=nil;self.finishing=false;self.samples=[];self.exposureReady=false
            self.lastSaveTrigger="none"
        }
        AVCaptureDevice.requestAccess(for: .video) { allowed in
            self.queue.async {
                guard self.captureID == requestID else { return }
                do {
                    guard allowed else { throw CameraLabError.message("Allow camera access in Settings.") }
                    if !self.configured { try self.configure() }
                    self.lastTime = -.infinity; self.finishing = false
                    try self.device?.lockForConfiguration()
                    if self.device?.isExposureModeSupported(.continuousAutoExposure) == true {self.device?.exposureMode = .continuousAutoExposure}
                    self.device?.unlockForConfiguration()
                    self.session.startRunning()
                    self.queue.asyncAfter(deadline:.now()+1.5) {self.setShortExposure(requestID:requestID,attempt:0)}
                    DispatchQueue.main.async { self.message = "Frame the object and nearby texture. The camera stays open until you press Save scan." }
                } catch { self.fail(error) }
            }
        }
    }
    private func configure() throws {
        guard let device = AVCaptureDevice.default(.builtInTrueDepthCamera, for: .video, position: .front) else { throw CameraLabError.message("This device cannot perform the required front TrueDepth reference. Use a phone with a TrueDepth camera.") }
        let formats = device.formats.filter { $0.supportedDepthDataFormats.contains { [kCVPixelFormatType_DepthFloat16, kCVPixelFormatType_DepthFloat32].contains(CMFormatDescriptionGetMediaSubType($0.formatDescription)) } }
        guard let format = formats.max(by: {a,b in
                  let x=CMVideoFormatDescriptionGetDimensions(a.formatDescription),y=CMVideoFormatDescriptionGetDimensions(b.formatDescription)
                  return Int(x.width)*Int(x.height)<Int(y.width)*Int(y.height)
              }),
              let depthFormat = format.supportedDepthDataFormats.filter({ [kCVPixelFormatType_DepthFloat16,kCVPixelFormatType_DepthFloat32].contains(CMFormatDescriptionGetMediaSubType($0.formatDescription)) }).max(by: { CMVideoFormatDescriptionGetDimensions($0.formatDescription).width < CMVideoFormatDescriptionGetDimensions($1.formatDescription).width }) else { throw CameraLabError.message("No supported numerical TrueDepth format is available.") }
        session.beginConfiguration()
        defer {
            if !configured {
                for input in session.inputs { session.removeInput(input) }
                for output in session.outputs { session.removeOutput(output) }
            }
            session.commitConfiguration()
        }
        session.sessionPreset = .inputPriority
        let input = try AVCaptureDeviceInput(device: device)
        guard session.canAddInput(input), session.canAddOutput(video), session.canAddOutput(depth) else { throw CameraLabError.message("Synchronized front colour and depth capture is unavailable.") }
        session.addInput(input); session.addOutput(video); session.addOutput(depth)
        try device.lockForConfiguration(); defer { device.unlockForConfiguration() }
        device.activeFormat = format; device.activeDepthDataFormat = depthFormat
        let maximum=format.videoSupportedFrameRateRanges.map(\.maxFrameRate).max() ?? 30
        let fps=Int32(min(30,maximum))
        device.activeVideoMinFrameDuration=CMTime(value:1,timescale:fps)
        device.activeVideoMaxFrameDuration=CMTime(value:1,timescale:fps)
        device.videoZoomFactor = 1
        if device.isGeometricDistortionCorrectionSupported { device.isGeometricDistortionCorrectionEnabled = false }
        video.alwaysDiscardsLateVideoFrames = true
        video.automaticallyConfiguresOutputBufferDimensions=false
        video.deliversPreviewSizedOutputBuffers=false
        video.videoSettings=[kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_420YpCbCr8BiPlanarFullRange]
        depth.isFilteringEnabled = false
        for output in [video as AVCaptureOutput, depth as AVCaptureOutput] {
            for connection in output.connections {
                if connection.isVideoMirroringSupported { connection.automaticallyAdjustsVideoMirroring = false; connection.isVideoMirrored = false }
                if connection.isVideoRotationAngleSupported(0) { connection.videoRotationAngle = 0 }
                if connection.isVideoStabilizationSupported { connection.preferredVideoStabilizationMode = .off }
            }
        }
        self.device = device
        synchronizer = AVCaptureDataOutputSynchronizer(dataOutputs: [video, depth])
        synchronizer?.setDelegate(self, queue: queue)
        configured = true
    }
    private func setShortExposure(requestID:UUID,attempt:Int) {
        guard captureID==requestID,session.isRunning,let device else{return}
        if device.isAdjustingExposure,attempt<8 {
            queue.asyncAfter(deadline:.now()+0.3) {self.setShortExposure(requestID:requestID,attempt:attempt+1)}
            return
        }
        do {
            guard device.isExposureModeSupported(.custom) else{throw CameraLabError.message("Short-exposure reference capture is unavailable on this camera.")}
            try device.lockForConfiguration();defer{device.unlockForConfiguration()}
            baselineExposure=CMTimeGetSeconds(device.exposureDuration)
            guard baselineExposure.isFinite,baselineExposure>0 else {throw CameraLabError.message("The camera has not settled its exposure. Reopen the reference camera.")}
            let duration=FrontReferencePolicy.shutterDuration(baseline:baselineExposure,minimum:CMTimeGetSeconds(device.activeFormat.minExposureDuration))
            let iso=min(device.activeFormat.maxISO,max(device.activeFormat.minISO,device.iso*Float(baselineExposure/duration)))
            device.setExposureModeCustom(duration:CMTime(seconds:duration,preferredTimescale:1_000_000_000),iso:iso) {_ in
                self.queue.async {
                    guard self.captureID==requestID else{return}
                    self.samples=[];self.exposureReady=true
                    DispatchQueue.main.async {self.message="Hold still. Save scan or press a volume button when the image is clear."}
                }
            }
        } catch {fail(error)}
    }
    func dataOutputSynchronizer(_ synchronizer: AVCaptureDataOutputSynchronizer, didOutput collection: AVCaptureSynchronizedDataCollection) {
        guard !finishing,exposureReady else { return }
        guard let colour = collection.synchronizedData(for: video) as? AVCaptureSynchronizedSampleBufferData,
              let sample = collection.synchronizedData(for: depth) as? AVCaptureSynchronizedDepthData,
              !colour.sampleBufferWasDropped, !sample.depthDataWasDropped else { return }
        let time = CMTimeGetSeconds(colour.timestamp), depthTime = CMTimeGetSeconds(sample.timestamp)
        guard time.isFinite,depthTime.isFinite,abs(time-depthTime)<=1.0/30,time-lastTime>=FrontReferencePolicy.sampleInterval,
              let image=CMSampleBufferGetImageBuffer(colour.sampleBuffer) else{return}
        lastTime=time
        let blur=ARKitCaptureProvider.blurScore(image,region:[0,0,1,1])
        guard blur>=7 else {
            samples=[]
            DispatchQueue.main.async {self.canSave=false;self.message="The image is blurred. Hold still or add light before saving."}
            return
        }
        let connection=video.connection(with:.video)
        let settings:[String:Any]=["zoom_factor":device?.videoZoomFactor ?? 1,"lens_position":device?.lensPosition ?? 0,"video_scale_and_crop_factor":connection?.videoScaleAndCropFactor ?? 1,"geometric_correction_enabled":device?.isGeometricDistortionCorrectionEnabled ?? false,"video_rotation_degrees":connection?.videoRotationAngle ?? 0,"mirrored":connection?.isVideoMirrored ?? false,"stabilization_mode":connection?.activeVideoStabilizationMode.rawValue ?? 0,"exposure_duration_s":device.map{CMTimeGetSeconds($0.exposureDuration)} ?? 0,"auto_exposure_baseline_s":baselineExposure,"requested_shutter_ratio":0.5,"iso":device?.iso ?? 0,"sharpness":blur]
        do {
            let copied=try ReferenceBufferCopy.sample(colour.sampleBuffer)
            let depth=try sample.depthData.replacingDepthDataMap(with:ReferenceBufferCopy.pixel(sample.depthData.depthDataMap))
            samples.append(Sample(colour:copied,depth:depth,time:time,depthTime:depthTime,settings:settings))
        } catch {fail(error);return}
        samples=Array(samples.filter{time-$0.time<=FrontReferencePolicy.maximumWindow}.suffix(FrontReferencePolicy.sampleCount))
        let ready=FrontReferencePolicy.ready(timestamps:samples.map(\.time),now:time)
        DispatchQueue.main.async {self.canSave=ready;self.message=ready ? "Ready. Save scan or press a volume button." : "Hold still while the sharp reference frames settle."}
    }
    func saveScan(trigger:String = "button") {
        guard running,!saving else{return}
        queue.async {
            self.lastSaveTrigger=trigger
            guard !self.finishing,FrontReferencePolicy.ready(timestamps:self.samples.map(\.time),now:ProcessInfo.processInfo.systemUptime) else{
                DispatchQueue.main.async{self.message="Wait for a clear, steady image before saving."};return
            }
            self.finishing=true
            let burst=self.samples;self.samples=[]
            DispatchQueue.main.async{self.saving=true;self.canSave=false;self.message="Saving your chosen reference…"}
            do {
                let writer=try ExperimentWriter(source:"ReverseCAD user-selected front TrueDepth reference")
                writer.experimentContext=["user_requested":true,"capture_trigger":self.lastSaveTrigger,"capture_id":self.captureID.uuidString]
                self.writer=writer
                for sample in burst {try self.write(sample,to:writer)}
                self.finish()
            } catch {self.fail(error)}
        }
    }
    private func write(_ selected:Sample,to writer:ExperimentWriter)throws {
        do {
            let id = try writer.save(selected.colour, camera: "front", settings: selected.settings)
            let data = selected.depth, stem = "lidar/av-\(writer.directDepth.count)"
            var record: [String:Any] = ["rgb_frame": id, "sensor":"front_TrueDepth", "timestamp_s":selected.depthTime, "rgb_depth_offset_s":selected.depthTime-selected.time, "is_filtered":data.isDepthDataFiltered, "accuracy":data.depthDataAccuracy.rawValue, "quality":data.depthDataQuality.rawValue, "depth":try writer.original(data.depthDataMap, stem:stem), "depth_kind":"optical_axis_z", "units":"m", "preview_mirrored":false, "coordinate_convention":"x right, y down, z forward; unmirrored rotation zero", "registration":"No front-to-rear transform has been estimated"]
            if let calibration = data.cameraCalibrationData {
                var c: [String:Any] = ["intrinsics":cameraRows(calibration.intrinsicMatrix), "reference_size":[calibration.intrinsicMatrixReferenceDimensions.width,calibration.intrinsicMatrixReferenceDimensions.height], "distortion_center":[calibration.lensDistortionCenter.x,calibration.lensDistortionCenter.y], "extrinsics_3x4":(0..<3).map { r in (0..<4).map { col in Double(calibration.extrinsicMatrix[col][r]) } }, "extrinsic_translation_units":"mm"]
                for (name, table) in [("distortion",calibration.lensDistortionLookupTable),("inverse_distortion",calibration.inverseLensDistortionLookupTable)] {
                    if let table { let file = stem+"-\(name).bin"; try table.write(to:writer.url.appendingPathComponent(file),options:.atomic); c[name+"_float32_table"] = file }
                }
                record["calibration"] = c
            }
            writer.directDepth.append(record)
        }
    }
    func stop() {
        queue.async {
            self.captureID = UUID()
            self.samples=[];self.exposureReady=false;self.session.stopRunning()
            DispatchQueue.main.async {self.running=false;self.saving=false;self.canSave=false}
        }
    }
    private func finish() {
        guard let writer else { return }
        do {
            try writer.checkpoint(["device_id":device?.uniqueID ?? "unknown"], complete:true)
            let reference = try TrueDepthReconstruction.build(dataset:writer.url)
            try reference.export(to:writer.url.appendingPathComponent("derived"))
            _ = try FrontReferenceEvidence.prepare(root:writer.url)
            try writer.checkpoint(["device_id":device?.uniqueID ?? "unknown"], complete:true)
            let archive = try writer.archive()
            session.stopRunning()
            DispatchQueue.main.async {
                self.running = false;self.saving=false;self.saved=archive;self.originalArchive=archive;self.originalDirectory=writer.url
                self.message = "Front depth saved. Checking that the first object and its surroundings are suitable."
            }
        } catch {
            try? writer.checkpoint(["device_id":device?.uniqueID ?? "unknown"],complete:true)
            let archive=try? writer.archive()
            self.writer=nil;self.finishing=false;self.samples=[]
            DispatchQueue.main.async {
                self.saving=false;self.canSave=false;self.originalArchive=archive
                self.message=error.localizedDescription+" The camera is still open. Hold steady and press Save scan again."
            }
        }
    }
    private func fail(_ error: Error) {
        session.stopRunning(); finishing = true
        try? writer?.checkpoint(["device_id":device?.uniqueID ?? "unknown"])
        let archive = try? writer?.archive()
        DispatchQueue.main.async {
            self.running = false;self.saving=false;self.canSave=false;self.originalArchive = archive
            self.message = error.localizedDescription + " Original samples remain saved."
        }
    }

}

struct PhoneReferenceSetup: View {
    var onSaved: ((URL) -> Void)? = nil
    static let archivePreferenceKey = "reversecad.referenceArchive.v1"
    @StateObject private var capture = PhoneReferenceCapture()
    @StateObject private var review = FrontReferenceReviewModel()
    @State private var box = SelectionBox.initial
    @State private var saveError: String?
    @State private var previewReady = false
    @AppStorage("reversecad.referenceArchive.v1") private var referenceArchive = ""
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            VStack(spacing:12) {
                primaryAction
                Text("Keep the object still on a textured surface. Tap Save scan or press a volume button.")
                    .font(.subheadline).foregroundStyle(RepairStyle.secondary)
                    .fixedSize(horizontal:false,vertical:true)
                    .accessibilityIdentifier("frontReferenceInstructions")
                ZStack {
                    if capture.running {
                        ReferenceCameraPreview(session:capture.session,ready:$previewReady)
                        if !previewReady { openingCamera }
                    } else if let image=review.image {
                        Image(uiImage:image).resizable().scaledToFit()
                            .overlay {AdjustableObjectBox(box:$box,editable:!review.working)}
                            .onChange(of:box) {_,_ in review.review=nil}
                    } else {
                        openingCamera
                    }
                    if capture.saving {ProgressView("Saving reference…").padding().background(.regularMaterial,in:RoundedRectangle(cornerRadius:12))}
                }
                .frame(maxWidth:.infinity,maxHeight:.infinity)
                .background(.black).clipShape(RoundedRectangle(cornerRadius:20))
                .accessibilityIdentifier("frontReferencePreview")
                Text(statusText).font(.footnote).foregroundStyle(RepairStyle.secondary)
                    .lineLimit(3).frame(maxWidth:.infinity,alignment:.leading)
                    .accessibilityLabel(statusText).accessibilityIdentifier("frontReferenceStatus")
                if !capture.running,capture.saved != nil {
                    Button("Retake reference") {restart()}
                        .buttonStyle(RepairButtonStyle(secondary:true)).disabled(review.working)
                }
            }
            .padding(16).foregroundStyle(RepairStyle.text)
            .background(RepairStyle.background.ignoresSafeArea())
            .navigationTitle("Front reference").navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(RepairStyle.background,for:.navigationBar)
            .toolbarBackground(.visible,for:.navigationBar)
            .toolbar {ToolbarItem(placement:.cancellationAction) {Button("Close") {review.cancel();capture.stop();dismiss()}}}
            .alert("Reference needs attention",isPresented:Binding(get:{saveError != nil},set:{if !$0 {saveError=nil}})) {
                Button("OK",role:.cancel) {saveError=nil}
            } message:{Text(saveError ?? "")}
        }
        .preferredColorScheme(.dark).tint(RepairStyle.accent)
        .interactiveDismissDisabled(capture.running || review.working)
        .cameraCaptureButton(enabled:capture.running && !capture.saving) {capture.saveScan(trigger:"volume")}
        .onAppear {capture.start()}
        .onDisappear {review.cancel();capture.stop()}
        .onChange(of:capture.running) {_,running in if !running {previewReady=false}}
        .onChange(of:capture.saved) {_,saved in
            if saved != nil,let root=capture.originalDirectory {review.check(root:root,box:box)}
        }
    }
    private var openingCamera:some View {
        RepairStyle.background.overlay {
            ProgressView("Opening selfie camera…")
                .tint(RepairStyle.accent)
                .accessibilityIdentifier("frontCameraOpening")
        }
    }
    private var statusText:String {
        if capture.running {return capture.message}
        return review.message.isEmpty ? capture.message:review.message
    }
    @ViewBuilder private var primaryAction:some View {
        if capture.running {
            Button("Save scan",systemImage:"checkmark") {capture.saveScan()}
                .buttonStyle(RepairButtonStyle()).disabled(capture.saving)
                .accessibilityIdentifier("saveFrontReference")
        } else if review.working {
            Button("Cancel check") {review.cancel()}.buttonStyle(RepairButtonStyle(secondary:true))
        } else if review.review?.accepted == true {
            Button("Use reference — turn phone") {useReference()}
                .buttonStyle(RepairButtonStyle()).accessibilityIdentifier("useFrontReference")
        } else if let root=capture.originalDirectory,capture.saved != nil {
            Button("Check reference") {review.check(root:root,box:box)}.buttonStyle(RepairButtonStyle())
        } else {
            Button("Open selfie camera") {restart()}.buttonStyle(RepairButtonStyle())
        }
    }
    private func restart() {
        review.cancel();review.review=nil;saveError=nil;capture.start()
    }
    private func useReference() {
        guard let root=capture.originalDirectory,let archive=capture.saved,let verdict=review.review else{return}
        do {
            try PhoneSetupStore.save(root:root,archive:archive,review:verdict)
            referenceArchive=archive.path;onSaved?(archive);dismiss()
        } catch {saveError=error.localizedDescription}
    }
}

private struct ReferenceCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    @Binding var ready: Bool
    final class Preview: UIView {
        var readyObservation: NSKeyValueObservation?
        var readinessChanged: ((Bool)->Void)?
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        override func layoutSubviews() {
            super.layoutSubviews()
            let orientation=window?.windowScene?.interfaceOrientation ?? .portrait
            let angle:CGFloat=orientation == .landscapeLeft ? 0 : orientation == .landscapeRight ? 180 : orientation == .portraitUpsideDown ? 270 : 90
            let preview=layer as! AVCaptureVideoPreviewLayer
            if let connection=preview.connection,connection.isVideoRotationAngleSupported(angle) {connection.videoRotationAngle=angle}
        }
    }
    func makeUIView(context:Context) -> Preview {
        let view = Preview()
        let layer = view.layer as! AVCaptureVideoPreviewLayer
        layer.session = session; layer.videoGravity = .resizeAspect
        view.readinessChanged = {ready=$0}
        // Keep the native layer attached during startup. Only remove the loading
        // cover once AVFoundation confirms that it can display a live frame.
        view.readyObservation = layer.observe(\.isPreviewing,options:[.initial,.new]) { [weak view] layer,_ in
            let ready=layer.isPreviewing
            DispatchQueue.main.async {view?.readinessChanged?(ready)}
        }
        return view
    }
    func updateUIView(_ view:Preview, context:Context) {
        view.readinessChanged = {ready=$0}
        if let connection = (view.layer as? AVCaptureVideoPreviewLayer)?.connection,
           connection.isVideoMirroringSupported {
            connection.automaticallyAdjustsVideoMirroring = false
            connection.isVideoMirrored = false
        }
    }
    static func dismantleUIView(_ view:Preview,coordinator:()) {
        view.readyObservation?.invalidate()
        view.readinessChanged=nil
        (view.layer as? AVCaptureVideoPreviewLayer)?.session=nil
    }
}
