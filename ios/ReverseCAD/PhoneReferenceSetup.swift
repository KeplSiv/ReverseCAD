import SwiftUI
import AVFoundation
import ReverseCADCore

/// Public-API capture only. A saved reference is evidence, not a fitted camera profile.
final class PhoneReferenceCapture: NSObject, ObservableObject, AVCaptureDataOutputSynchronizerDelegate {
    @Published var running = false
    @Published var message = "Keep the same object and surrounding features still. Capture a short front reference, then turn the phone for the rear scan."
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
    private var recordAfter = Double.infinity
    private var captureID = UUID()

    func start() {
        guard !running else { return }
        running = true; saved = nil; originalArchive = nil; originalDirectory = nil
        message = "Starting front camera…"
        let requestID = UUID()
        queue.async { self.captureID = requestID; self.writer = nil; self.finishing = false }
        AVCaptureDevice.requestAccess(for: .video) { allowed in
            self.queue.async {
                guard self.captureID == requestID else { return }
                do {
                    guard allowed else { throw CameraLabError.message("Allow camera access in Settings.") }
                    if !self.configured { try self.configure() }
                    self.writer = try ExperimentWriter(source: "ReverseCAD front TrueDepth reference")
                    let directory = self.writer?.url
                    DispatchQueue.main.async { self.originalDirectory = directory }
                    self.lastTime = -.infinity; self.finishing = false
                    self.recordAfter = ProcessInfo.processInfo.systemUptime + 4
                    let captureID = requestID
                    try self.writer?.checkpoint(["device_id": self.device?.uniqueID ?? "unknown"])
                    self.session.startRunning()
                    self.queue.asyncAfter(deadline:.now()+20) { if self.captureID == captureID { self.finish() } }
                    DispatchQueue.main.async { self.message = "Use the selfie camera to frame the object and nearby features. Hold the phone steady for this reference burst." }
                } catch { self.fail(error) }
            }
        }
    }
    private func configure() throws {
        guard let device = AVCaptureDevice.default(.builtInTrueDepthCamera, for: .video, position: .front) else { throw CameraLabError.message("This device cannot perform the required front TrueDepth reference. Use a phone with a TrueDepth camera.") }
        let formats = device.formats.filter { $0.supportedDepthDataFormats.contains { [kCVPixelFormatType_DepthFloat16, kCVPixelFormatType_DepthFloat32].contains(CMFormatDescriptionGetMediaSubType($0.formatDescription)) } }
        guard let format = formats.min(by: { CMVideoFormatDescriptionGetDimensions($0.formatDescription).width < CMVideoFormatDescriptionGetDimensions($1.formatDescription).width }),
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
        device.videoZoomFactor = 1
        if device.isGeometricDistortionCorrectionSupported { device.isGeometricDistortionCorrectionEnabled = false }
        video.alwaysDiscardsLateVideoFrames = true
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
    func dataOutputSynchronizer(_ synchronizer: AVCaptureDataOutputSynchronizer, didOutput collection: AVCaptureSynchronizedDataCollection) {
        guard !finishing, let writer else { return }
        guard ProcessInfo.processInfo.systemUptime >= recordAfter else { return }
        guard let colour = collection.synchronizedData(for: video) as? AVCaptureSynchronizedSampleBufferData,
              let sample = collection.synchronizedData(for: depth) as? AVCaptureSynchronizedDepthData,
              !colour.sampleBufferWasDropped, !sample.depthDataWasDropped else { writer.event("synchronized_sample_missing_or_dropped"); return }
        let time = CMTimeGetSeconds(colour.timestamp), depthTime = CMTimeGetSeconds(sample.timestamp)
        guard time.isFinite, depthTime.isFinite else { writer.event("invalid_timestamp"); return }
        guard abs(time-depthTime) <= 1.0/30 else {
            writer.event("timestamp_offset_rejected",["rgb_depth_offset_s":depthTime-time]); return
        }
        guard time-lastTime >= 0.25 else { return }
        do {
            let connection = video.connection(with: .video)
            let settings: [String:Any] = ["zoom_factor": device?.videoZoomFactor ?? 1, "lens_position": device?.lensPosition ?? 0, "video_scale_and_crop_factor": connection?.videoScaleAndCropFactor ?? 1, "geometric_correction_enabled": device?.isGeometricDistortionCorrectionEnabled ?? false, "video_rotation_degrees": connection?.videoRotationAngle ?? 0, "mirrored": connection?.isVideoMirrored ?? false, "stabilization_mode": connection?.activeVideoStabilizationMode.rawValue ?? 0, "exposure_duration_s": device.map { CMTimeGetSeconds($0.exposureDuration) } ?? 0, "iso": device?.iso ?? 0]
            let id = try writer.save(colour.sampleBuffer, camera: "front", settings: settings)
            let data = sample.depthData, stem = "lidar/av-\(writer.directDepth.count)"
            var record: [String:Any] = ["rgb_frame": id, "sensor":"front_TrueDepth", "timestamp_s":depthTime, "rgb_depth_offset_s":depthTime-time, "is_filtered":data.isDepthDataFiltered, "accuracy":data.depthDataAccuracy.rawValue, "quality":data.depthDataQuality.rawValue, "depth":try writer.original(data.depthDataMap, stem:stem), "depth_kind":"optical_axis_z", "units":"m", "preview_mirrored":false, "coordinate_convention":"x right, y down, z forward; unmirrored rotation zero", "registration":"No front-to-rear transform has been estimated"]
            if let calibration = data.cameraCalibrationData {
                var c: [String:Any] = ["intrinsics":cameraRows(calibration.intrinsicMatrix), "reference_size":[calibration.intrinsicMatrixReferenceDimensions.width,calibration.intrinsicMatrixReferenceDimensions.height], "distortion_center":[calibration.lensDistortionCenter.x,calibration.lensDistortionCenter.y], "extrinsics_3x4":(0..<3).map { r in (0..<4).map { col in Double(calibration.extrinsicMatrix[col][r]) } }, "extrinsic_translation_units":"mm"]
                for (name, table) in [("distortion",calibration.lensDistortionLookupTable),("inverse_distortion",calibration.inverseLensDistortionLookupTable)] {
                    if let table { let file = stem+"-\(name).bin"; try table.write(to:writer.url.appendingPathComponent(file),options:.atomic); c[name+"_float32_table"] = file }
                }
                record["calibration"] = c
            }
            writer.directDepth.append(record); lastTime = time
            try writer.checkpoint(["device_id":device?.uniqueID ?? "unknown"])
            let count = writer.frames.count
            DispatchQueue.main.async { self.message = "Saved \(count) synchronized reference views. Keep the object still." }
            if count >= 8 { finish() }
        } catch { fail(error) }
    }
    func stop() {
        queue.async {
            // Invalidate a pending permission/configuration callback as well as the timeout.
            self.captureID = UUID()
            guard self.writer != nil, !self.finishing else {
                DispatchQueue.main.async { self.running = false }
                return
            }
            self.finish()
        }
    }
    private func finish() {
        guard !finishing, let writer else { return }
        finishing = true; session.stopRunning()
        do {
            try writer.checkpoint(["device_id":device?.uniqueID ?? "unknown"], complete:true)
            var derivationError: Error?
            do {
                let reference = try TrueDepthReconstruction.build(dataset:writer.url)
                try reference.export(to:writer.url.appendingPathComponent("derived"))
            } catch { derivationError = error }
            try writer.checkpoint(["device_id":device?.uniqueID ?? "unknown"], complete:true)
            let archive = try writer.archive()
            if let derivationError {
                DispatchQueue.main.async {
                    self.running = false; self.originalArchive = archive
                    self.message = "Original reference saved. No usable inspection surface: " + derivationError.localizedDescription + " Rear cameras still use factory calibration."
                }
                return
            }
            let profile = try PhoneCalibrationProfile(referenceArchiveSHA256:CaptureIO.sha256(file:archive))
            let profiles = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("PhoneCalibrationProfiles")
            try profile.save(directory:profiles)
            DispatchQueue.main.async {
                self.running = false; self.saved = archive; self.originalArchive = archive
                self.message = "Reference saved. Factory rear calibration remains active. Front-to-rear fitting and independent validation are still required."
            }
        } catch { fail(error) }
    }
    private func fail(_ error: Error) {
        session.stopRunning(); finishing = true
        try? writer?.checkpoint(["device_id":device?.uniqueID ?? "unknown"])
        let archive = try? writer?.archive()
        DispatchQueue.main.async {
            self.running = false; self.originalArchive = archive
            self.message = error.localizedDescription + " Original samples remain saved."
        }
    }

}

struct PhoneReferenceSetup: View {
    /// Attach this immutable archive to a subsequent rear scan as reference evidence only.
    var onSaved: ((URL) -> Void)? = nil
    static let archivePreferenceKey = "reversecad.referenceArchive.v1"
    @StateObject private var capture = PhoneReferenceCapture()
    @AppStorage("reversecad.referenceArchive.v1") private var referenceArchive = ""
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment:.leading, spacing:20) {
                    Text("Front depth reference").font(.largeTitle.bold())
                    Text("Save front-camera color and TrueDepth samples for inspection. This does not calibrate the rear cameras or align the front and rear views.")
                    Text(capture.message).foregroundStyle(RepairStyle.secondary)
                    if capture.running {
                        ReferenceCameraPreview(session:capture.session).frame(height:260).clipped().clipShape(RoundedRectangle(cornerRadius:22))
                        ProgressView().tint(RepairStyle.accent)
                        Button("Save and stop") { capture.stop() }.buttonStyle(RepairButtonStyle(secondary:true))
                    } else {
                        if let archive = capture.originalArchive {
                            ShareLink("Export original reference", item:archive).buttonStyle(RepairButtonStyle(secondary:true))
                        }
                        if let archive = capture.saved {
                            Button("Use reference and continue") {
                                referenceArchive = archive.path; onSaved?(archive); dismiss()
                            }.buttonStyle(RepairButtonStyle())
                        } else {
                            Button("Capture front reference") { capture.start() }.buttonStyle(RepairButtonStyle())
                        }
                    }
                    Text("Hold the selfie camera steady, facing the object and nearby features. Keep the scene unchanged when turning to the rear camera.").font(.footnote).foregroundStyle(RepairStyle.secondary)
                    Text("Provisional reference only · No fitted rear-camera correction · Physical accuracy unverified")
                        .font(.caption).foregroundStyle(RepairStyle.secondary)
                }.padding(20).foregroundStyle(RepairStyle.text)
            }.background(RepairStyle.background.ignoresSafeArea())
                .navigationTitle("ReverseCAD").navigationBarTitleDisplayMode(.inline)
                .toolbarBackground(RepairStyle.background, for:.navigationBar)
                .toolbarBackground(.visible, for:.navigationBar)
                .toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { capture.stop(); dismiss() } } }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent).interactiveDismissDisabled(capture.running)
            .onDisappear { capture.stop() }
            .onAppear {
                if referenceArchive.isEmpty, let legacy = UserDefaults.standard.string(forKey:"prelude.referenceArchive.v1") {
                    referenceArchive = legacy
                }
            }
    }
}

private struct ReferenceCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    final class Preview: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    }
    func makeUIView(context:Context) -> Preview {
        let view = Preview()
        let layer = view.layer as! AVCaptureVideoPreviewLayer
        layer.session = session; layer.videoGravity = .resizeAspect
        return view
    }
    func updateUIView(_ view:Preview, context:Context) {
        if let connection = (view.layer as? AVCaptureVideoPreviewLayer)?.connection,
           connection.isVideoMirroringSupported {
            connection.automaticallyAdjustsVideoMirroring = false
            connection.isVideoMirrored = false
        }
    }
}
