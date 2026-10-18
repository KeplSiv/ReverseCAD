import SwiftUI
import ARKit
import RealityKit
import AVFoundation
import ReverseCADCore
import CoreImage

/// Both providers commit the same portable CaptureFrame records. Replay never constructs an ARFrame.
protocol CaptureProvider: AnyObject {
    var onFrame: ((CaptureFrame) -> Void)? { get set }
    var onProgress: ((CaptureProgress) -> Void)? { get set }
    func finish() async throws -> URL
}

struct CaptureProgress: Sendable {
    var accepted = 0
    var rejected = 0
    var dropped = 0
    var bytes = 0
    var guidance = "Move slowly around the stationary object."
    var coverageViews = 0
    var finished = false
    var geometryHint: String?
}

enum CaptureFailure: LocalizedError {
    case unavailable(String), write(String)
    var errorDescription: String? {
        switch self { case .unavailable(let message), .write(let message): return message }
    }
}

@MainActor final class CaptureController: ObservableObject {
    @Published private(set) var status = "Ready"
    @Published private(set) var frameCount = 0
    @Published private(set) var rejectedFrames = 0
    @Published private(set) var droppedFrames = 0
    @Published private(set) var bytesWritten = 0
    @Published private(set) var coverageViews = 0
    @Published private(set) var isCapturing = false
    @Published private(set) var packageURL: URL?
    @Published private(set) var savedRevision = 0
    @Published private(set) var previewImage: UIImage?
    @Published private(set) var guidance = "Keep the object stationary. Use a textured surface and diffuse light."
    @Published private(set) var ghost = GhostLifecycle()
    @Published private(set) var liveSurfaceMesh: MeshPreview?
    private var surfaceAccumulator = ObservedSurfaceAccumulator()
    private var surfaceEpoch = ""
    @Published private(set) var ghostMessage = "Ghost appears when repeated or symmetric geometry supports a proposal."
    var predictGhost: ((LiveGeometrySnapshot) async throws -> LiveGhostResponse)?
    private var ghostTask: Task<Void,Never>?
    private var expiryTask: Task<Void,Never>?
    let hasAR = ARWorldTrackingConfiguration.isSupported
    let hasLiDAR = ARWorldTrackingConfiguration.isSupported && ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
    let session = ARSession()
    @Published private(set) var cameraReady=false
    @Published private(set) var multiCameraPreview: AVCaptureVideoPreviewLayer?
    private var multiCamera: MultiCameraSession?
    private let useMultiCamera: Bool
    private var previewGeneration=UUID()
    private var captureRegion = CGRect(x:1.0/3,y:1.0/3,width:1.0/3,height:1.0/3)
    private var captureRotation = 90
    func pausePreview(completion: (() -> Void)? = nil) {
        previewGeneration=UUID();cameraReady=false
        session.pause()
        let camera = multiCamera
        multiCamera=nil;multiCameraPreview=nil
        if let camera { camera.stop { DispatchQueue.main.async { completion?() } } }
        else { completion?() }
    }
    func selectionImage(rect: CGRect, viewport: CGSize, orientation: UIInterfaceOrientation) throws -> (jpeg: Data, box: CGRect) {
        if useMultiCamera {
            guard let camera=multiCamera,let image=camera.latest(),let layer=multiCameraPreview else {throw CaptureFailure.unavailable("Wait for all cameras to be ready.")}
            let raw=try camera.videoRegion(fromMetadata:layer.metadataOutputRectConverted(fromLayerRect:rect)).intersection(CGRect(x:0,y:0,width:1,height:1))
            guard !raw.isNull,raw.width>0,raw.height>0 else {throw CaptureFailure.unavailable("Place the box inside the camera preview.")}
            guard let jpeg=CIContext().jpegRepresentation(of:CIImage(cvPixelBuffer:image.pixel),colorSpace:CGColorSpaceCreateDeviceRGB(),options:[kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption:0.97]) else {throw CaptureFailure.write("Could not save the selected view.")}
            captureRegion=raw
            captureRotation=orientation == .landscapeLeft ? 0 : orientation == .landscapeRight ? 180 : orientation == .portraitUpsideDown ? 270 : 90
            return (jpeg,raw)
        }
        guard let frame=session.currentFrame else {throw CaptureFailure.unavailable("Wait for a clear camera image.")}
        return (try BoxObjectIdentifier.fullImage(frame),CaptureFraming.rawRegion(rect:rect,viewport:viewport,displayTransform:frame.displayTransform(for:orientation,viewportSize:viewport)))
    }
    private var provider: CaptureProvider?
    private var confirmedTarget: CGRect?
    func setConfirmedTarget(_ box: CGRect) { confirmedTarget = box; selectedObjectPoint = CGPoint(x: box.midX, y: box.midY) }
    private var selectedObjectPoint = CGPoint(x: 0.5, y: 0.5)
    private var guideLayout: (CGRect, CGSize, UIInterfaceOrientation)?
    private var backgroundObserver: NSObjectProtocol?

    init(useMultiCamera: Bool = false) {
        self.useMultiCamera=useMultiCamera
        backgroundObserver = NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isCapturing else { return }
                self.guidance = "Capture ended when the app entered the background. Committed frames are preserved."
                do { _ = try await self.stop() } catch { self.status = error.localizedDescription }
            }
        }
    }

    deinit { if let backgroundObserver { NotificationCenter.default.removeObserver(backgroundObserver) } }

    func startPreview() async throws {
        let epoch=UUID();previewGeneration=epoch;cameraReady=false
        guard hasAR else { throw CaptureFailure.unavailable("This device does not support camera world tracking.") }
        guard await AVCaptureDevice.requestAccess(for: .video) else {
            throw CaptureFailure.unavailable("Allow camera access in Settings to scan.")
        }
        guard !isCapturing else { return }
        if useMultiCamera {
            session.pause()
            guard epoch==previewGeneration else {throw CancellationError()}
            let camera=multiCamera ?? MultiCameraSession()
            multiCamera=camera
            do {try await camera.start { [weak self] layer in
                Task { @MainActor in
                    guard let self,epoch==self.previewGeneration else{return}
                    self.multiCameraPreview=layer
                }
            }}
            catch {if epoch==previewGeneration {multiCamera=nil;multiCameraPreview=nil};camera.stop();throw error}
            guard epoch==previewGeneration else {camera.stop();throw CancellationError()}
            multiCameraPreview=camera.preview;cameraReady=true
            return
        }
        let configuration = ARWorldTrackingConfiguration()
        if let detailFormat = ARWorldTrackingConfiguration.recommendedVideoFormatFor4KResolution {
            configuration.videoFormat = detailFormat
        }
        #if REVERSECAD_SCANNER
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats.filter({ $0.captureDeviceType == .builtInWideAngleCamera && $0.captureDevicePosition == .back && $0.framesPerSecond == 30 }).min(by: { abs($0.imageResolution.width-1280) < abs($1.imageResolution.width-1280) }) { configuration.videoFormat = format }
        #endif
        if hasLiDAR { configuration.frameSemantics.insert(.sceneDepth) }
        session.run(configuration)
    }

    func start(directory: URL, scanID: String, motionDiagnostics: Bool = false) async throws {
        guard hasAR else { throw CaptureFailure.unavailable("This device has no AR world tracking. Use Synthetic sample or import a recorded package; no live LiDAR is simulated.") }
        let allowed = await AVCaptureDevice.requestAccess(for: .video)
        guard allowed else { throw CaptureFailure.unavailable("Camera permission is required. Enable ReverseCAD in Settings → Privacy & Security → Camera.") }
        guard !isCapturing else { return }
        guard let (rect, size, orientation) = guideLayout else { throw CaptureFailure.unavailable("Wait for the camera guide to appear, then capture.") }
        if useMultiCamera {
            guard let camera=multiCamera else {throw CaptureFailure.unavailable("Wait for the rear cameras to start.")}
            let capture=try MultiCameraCaptureProvider(camera:camera,directory:directory,scanID:scanID,region:captureRegion,confirmed:confirmedTarget != nil,displayRotation:captureRotation)
            capture.onObservedSurface = { [weak self] surface,epoch in
                Task { @MainActor in self?.addObservedSurface(surface,epoch:epoch) }
            }
            connect(capture);provider=capture
            frameCount=0;rejectedFrames=0;droppedFrames=0;bytesWritten=0;coverageViews=0
            liveSurfaceMesh=nil;surfaceAccumulator=ObservedSurfaceAccumulator();surfaceEpoch=""
            packageURL=directory;isCapturing=true;status="Three rear cameras + LiDAR"
            capture.start();return
        }
        let capture = try ARKitCaptureProvider(session: session, directory: directory, scanID: scanID, useDepth: hasLiDAR, motionDiagnostics: motionDiagnostics)
        capture.setGuide(rect: rect, viewport: size, orientation: orientation)
        capture.onLiveGeometry = { [weak self] snapshot in
            Task { @MainActor in self?.receiveLiveGeometry(snapshot) }
        }
        capture.onObservedSurface = { [weak self] surface, epoch in
            Task { @MainActor in
                guard let self,self.isCapturing else{return}
                if self.surfaceEpoch != epoch {self.surfaceEpoch=epoch;self.surfaceAccumulator=ObservedSurfaceAccumulator()}
                self.surfaceAccumulator.add(surface)
                self.liveSurfaceMesh=MeshPreview(vertices:self.surfaceAccumulator.vertices.map{$0.map{$0*1000}},triangles:self.surfaceAccumulator.triangles)
            }
        }
        capture.selectObject(point: selectedObjectPoint)
        if let confirmedTarget { capture.setConfirmedTarget(confirmedTarget) }
        connect(capture)
        provider = capture
        frameCount = 0; rejectedFrames = 0; droppedFrames = 0; bytesWritten = 0; coverageViews = 0
        liveSurfaceMesh=nil;surfaceAccumulator=ObservedSurfaceAccumulator();surfaceEpoch=""
        packageURL = directory
        isCapturing = true
        status = hasLiDAR ? "Live LiDAR + RGB + visual-inertial pose" : "Limited camera/manual capture — no metric depth"
        try capture.start()
    }

    private func addObservedSurface(_ surface:ObservedSurface,epoch:String) {
        guard isCapturing else{return}
        if surfaceEpoch != epoch {surfaceEpoch=epoch;surfaceAccumulator=ObservedSurfaceAccumulator()}
        surfaceAccumulator.add(surface)
        liveSurfaceMesh=MeshPreview(vertices:surfaceAccumulator.vertices.map{$0.map{$0*1000}},triangles:surfaceAccumulator.triangles)
    }

    func selectObject(normalizedRawImagePoint: CGPoint) {
        selectedObjectPoint = normalizedRawImagePoint
        (provider as? ARKitCaptureProvider)?.selectObject(point: normalizedRawImagePoint)
        guidance = "Scan center selected. Keep this object still and move the phone."
    }

    func updateGuide(rect: CGRect, viewport: CGSize, orientation: UIInterfaceOrientation) {
        guideLayout = (rect, viewport, orientation)
        (provider as? ARKitCaptureProvider)?.setGuide(rect: rect, viewport: viewport, orientation: orientation)
    }

    func stop() async throws -> URL {
        guard let provider else { throw CaptureFailure.unavailable("No capture is active.") }
        clearGhost()
        let url = try await provider.finish()
        isCapturing = false;cameraReady=false
        packageURL = url
        status = "Saved locally — \(frameCount) accepted frames"
        savedRevision += 1
        return url
    }

    func clearGhost() {
        ghostTask?.cancel(); ghostTask = nil; expiryTask?.cancel(); expiryTask = nil
        ghost.reset()
    }
    func nextGhost() { ghost.next() }
    private func receiveLiveGeometry(_ snapshot: LiveGeometrySnapshot?) {
        guard isCapturing, let snapshot else {
            clearGhost(); ghostMessage = "Finding a stable view for the ghost…"; return
        }
        if snapshot.session_id != ghost.sessionID {
            clearGhost(); ghost.sessionID = snapshot.session_id
        }
        guard ghostTask == nil, let predictGhost else { return }
        let sentAt = Date(); let epoch = ghost.sessionID
        ghostMessage = "Checking geometric patterns…"
        ghostTask = Task { [weak self] in
            guard let self else { return }
            defer { if self.ghost.sessionID == epoch { self.ghostTask = nil } }
            do {
                let response = try await predictGhost(snapshot)
                guard !Task.isCancelled, self.isCapturing, self.ghost.sessionID == epoch else { return }
                if self.ghost.accept(response, now: Date(), sentAt: sentAt) {
                    self.ghostMessage = response.message
                    self.expiryTask?.cancel()
                    self.expiryTask = Task { [weak self] in
                        try? await Task.sleep(for: .seconds(16))
                        guard !Task.isCancelled, let self, self.ghost.sessionID == epoch else { return }
                        self.ghost.expire(at: Date())
                        self.ghostMessage = "Show an intact feature and the opening from another side."
                    }
                }
            } catch {
                guard !Task.isCancelled, self.ghost.sessionID == epoch else { return }
                self.ghostMessage = "Ghost paused: " + error.localizedDescription + " Your scan is still being saved."
            }
        }
    }

    func replay(from source: URL, into directory: URL) async throws -> URL {
        guard !isCapturing else { throw CaptureFailure.unavailable("Finish the current capture first.") }
        let replay = ReplayCaptureProvider(source: source, destination: directory)
        connect(replay)
        provider = replay
        isCapturing = true
        status = "Replaying recorded CaptureFrame data"
        do {
            let url = try await replay.finish()
            packageURL = url
            if let first = try CaptureIO.readFrames(directory: url).first {
                previewImage = UIImage(contentsOfFile: url.appendingPathComponent(first.rgbPath).path)
            }
            isCapturing = false
            let manifest = try ScanPackageWriter.validate(directory: url)
            status = manifest.source == "synthetic" ? "Synthetic sample saved — not a phone measurement" : "Imported recorded scan saved"
            return url
        } catch { isCapturing = false; status = error.localizedDescription; throw error }
    }

    private func connect(_ provider: CaptureProvider) {
        provider.onProgress = { [weak self] progress in
            Task { @MainActor in
                guard let self else { return }
                self.frameCount = progress.accepted
                self.rejectedFrames = progress.rejected
                self.droppedFrames = progress.dropped
                self.bytesWritten = progress.bytes
                self.coverageViews = progress.coverageViews
                self.guidance = progress.guidance
                if self.ghost.selected == nil, self.ghostTask == nil, let hint = progress.geometryHint { self.ghostMessage = hint }
                if progress.finished && self.isCapturing {
                    do { _ = try await self.stop() } catch { self.status = error.localizedDescription }
                }
            }
        }
    }
}

/// Live display uses the same ARSession as acquisition; no competing camera session.
struct CapturePreview: UIViewRepresentable {
    let session: ARSession
    var showsGuide = true
    var onSelect: ((CGPoint) -> Void)? = nil
    var ghost: LiveGhostResponse.Candidate? = nil
    var onGuide: ((CGRect, CGSize, UIInterfaceOrientation) -> Void)? = nil
    func makeCoordinator() -> Coordinator { Coordinator(session: session, onSelect: onSelect) }
    func makeUIView(context: Context) -> ARView {
        let view = GuidedARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        view.showsGuide = showsGuide
        view.onGuide = onGuide
        view.session = session
        view.addGestureRecognizer(UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tapped(_:))))
        view.accessibilityLabel = "Live camera. Tap the stationary object to select its foreground region."
        return view
    }
    func updateUIView(_ view: ARView, context: Context) {
        (view as? GuidedARView)?.showsGuide = showsGuide
        (view as? GuidedARView)?.onGuide = onGuide
        view.setNeedsLayout()
        context.coordinator.onSelect = onSelect
        context.coordinator.updateGhost(ghost, in: view)
    }
    final class Coordinator: NSObject {
        let session: ARSession
        var onSelect: ((CGPoint) -> Void)?
        private var lastGhost: LiveGhostResponse.Candidate?
        private var ghostAnchor: AnchorEntity?
        func updateGhost(_ candidate: LiveGhostResponse.Candidate?, in view: ARView) {
            guard candidate != lastGhost else { return }
            lastGhost = candidate; ghostAnchor?.removeFromParent(); ghostAnchor = nil
            guard let candidate else { return }
            let mesh = candidate.mesh
            var descriptor = MeshDescriptor(name: "Provisional repair")
            descriptor.positions = MeshBuffers.Positions(candidate.worldPositions)
            descriptor.primitives = .triangles(mesh.triangles.flatMap { $0.map { UInt32($0) } })
            guard let resource = try? MeshResource.generate(from: [descriptor]) else { return }
            var material = SimpleMaterial(color: UIColor.systemOrange.withAlphaComponent(0.4), isMetallic: false)
            if #available(iOS 18.0, *) { material.faceCulling = .none; material.writesDepth = false }
            let entity = ModelEntity(mesh: resource, materials: [material])
            let anchor = AnchorEntity(world: SIMD3<Float>.zero)
            anchor.addChild(entity); view.scene.addAnchor(anchor); ghostAnchor = anchor
        }
        init(session: ARSession, onSelect: ((CGPoint) -> Void)?) { self.session = session; self.onSelect = onSelect }
        @objc func tapped(_ recognizer: UITapGestureRecognizer) {
            guard let view = recognizer.view, let frame = session.currentFrame, view.bounds.width > 0, view.bounds.height > 0 else { return }
            let position = recognizer.location(in: view)
            if let guided = view as? GuidedARView, guided.onGuide != nil,
               !GuidedARView.guideRect(in: view.bounds).contains(position) { return }
            let normalized = CGPoint(x: position.x / view.bounds.width, y: position.y / view.bounds.height)
            let orientation = view.window?.windowScene?.interfaceOrientation ?? .portrait
            // Inverse display transform maps portrait screen coordinates back to raw calibrated image coordinates.
            let image = normalized.applying(frame.displayTransform(for: orientation, viewportSize: view.bounds.size).inverted())
            onSelect?(CGPoint(x: min(1, max(0, image.x)), y: min(1, max(0, image.y))))
        }
    }
}

/// Draw and measure the guide in the same view that displays the AR image.
final class GuidedARView: ARView {
    var showsGuide = true
    var onGuide: ((CGRect, CGSize, UIInterfaceOrientation) -> Void)?
    private let guide = CAShapeLayer()
    static func guideRect(in bounds: CGRect) -> CGRect {
        CaptureFraming.centerCell(in: bounds)
    }
    override func layoutSubviews() {
        super.layoutSubviews()
        guard let onGuide, bounds.width > 0, bounds.height > 0 else { guide.removeFromSuperlayer(); return }
        let rect = Self.guideRect(in: bounds)
        if showsGuide && guide.superlayer == nil { layer.addSublayer(guide) }
        if !showsGuide { guide.removeFromSuperlayer() }
        guide.path = UIBezierPath(rect: rect).cgPath
        guide.fillColor = UIColor.clear.cgColor; guide.strokeColor = UIColor.white.withAlphaComponent(0.85).cgColor
        guide.lineWidth = 2; guide.lineDashPattern = [18, 8]
        onGuide(rect, bounds.size, window?.windowScene?.interfaceOrientation ?? .portrait)
    }
}

final class ReplayCaptureProvider: CaptureProvider, @unchecked Sendable {
    var onFrame: ((CaptureFrame) -> Void)?
    var onProgress: ((CaptureProgress) -> Void)?
    private let source: URL
    private let destination: URL
    private var completed: URL?
    init(source: URL, destination: URL) { self.source = source; self.destination = destination }

    func finish() async throws -> URL {
        if let completed { return completed }
        let replayTask = Task.detached(priority: .userInitiated) { [self] () throws -> URL in
            var manifest = try ScanPackageWriter.validate(directory: source)
            let original = manifest.scanID
            manifest.scanID = UUID().uuidString.lowercased()
            manifest.complete = false
            manifest.frameCount = 0
            let writer = try ScanPackageWriter(directory: destination, manifest: manifest)
            let frames = try CaptureIO.readFrames(directory: source)
            var progress = CaptureProgress()
            for var frame in frames {
                try Task.checkCancellation()
                frame.scanID = manifest.scanID
                var assets: [String: Data] = [:]
                for path in [frame.rgbPath, frame.depthPath, frame.confidencePath, frame.maskPath].compactMap({ $0 }) {
                    assets[path] = try Data(contentsOf: source.appendingPathComponent(path), options: .mappedIfSafe)
                }
                try writer.append(frame: frame, assets: assets)
                if frame.quality.accepted { progress.accepted += 1 } else { progress.rejected += 1 }
                progress.bytes = writer.bytesWritten
                progress.guidance = "Replay \(original): \(progress.accepted) accepted calibrated frames. This is not live sensor validation."
                onFrame?(frame); onProgress?(progress)
            }
            // Copy optional original evidence after required frame assets have passed the common validator.
            for path in ["annotations.json", "motion.jsonl", "video/review.mov", "video/timestamps.jsonl", "capture_diagnostics.json"] {
                let url = source.appendingPathComponent(path)
                if FileManager.default.fileExists(atPath: url.path) {
                    let output = destination.appendingPathComponent(path)
                    try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
                    try FileManager.default.copyItem(at: url, to: output)
                }
            }
            return try writer.finish()
        }
        let result = try await withTaskCancellationHandler(operation: { try await replayTask.value }, onCancel: { replayTask.cancel() })
        completed = result
        return result
    }
}

enum CaptureExport {
    /// Apple's coordinated .forUploading snapshot archives a directory without requiring a ZIP dependency.
    /// Copy inside the accessor: Foundation unlinks its temporary snapshot when the block returns.
    static func archive(directory: URL) async throws -> URL {
        try await Task.detached(priority: .userInitiated) {
            let manifest = try ScanPackageWriter.validate(directory: directory, allowIncomplete: true)
            try Task.checkCancellation()
            let output = FileManager.default.temporaryDirectory.appendingPathComponent("ReverseCAD-\(manifest.scanID)-\(UUID().uuidString.prefix(8)).zip")
            var coordinationError: NSError?
            var copyError: Error?
            NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: directory, options: .forUploading, error: &coordinationError) { snapshot in
                do { try FileManager.default.copyItem(at: snapshot, to: output) } catch { copyError = error }
            }
            if let coordinationError { throw coordinationError }
            if let copyError { throw copyError }
            guard FileManager.default.fileExists(atPath: output.path) else { throw CaptureFailure.write("The system did not create a scan archive.") }
            return output
        }.value
    }
}
