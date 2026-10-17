import SwiftUI
import ARKit
import RealityKit
import AVFoundation
import ReverseCADCore

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
    @Published private(set) var ghostMessage = "Ghost appears when repeated or symmetric geometry supports a proposal."
    var predictGhost: ((LiveGeometrySnapshot) async throws -> LiveGhostResponse)?
    private var ghostTask: Task<Void,Never>?
    private var expiryTask: Task<Void,Never>?
    let hasAR = ARWorldTrackingConfiguration.isSupported
    let hasLiDAR = ARWorldTrackingConfiguration.isSupported && ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
    let session = ARSession()
    private var provider: CaptureProvider?
    private var selectedObjectPoint = CGPoint(x: 0.5, y: 0.5)
    private var backgroundObserver: NSObjectProtocol?

    init() {
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
        guard hasLiDAR else { throw CaptureFailure.unavailable("3D scanning needs a LiDAR iPhone or iPad. You can still import a photo for a simple cube prototype.") }
        guard await AVCaptureDevice.requestAccess(for: .video) else {
            throw CaptureFailure.unavailable("Allow camera access in Settings to scan.")
        }
        guard !isCapturing else { return }
        let configuration = ARWorldTrackingConfiguration()
        if let detailFormat = ARWorldTrackingConfiguration.recommendedVideoFormatFor4KResolution {
            configuration.videoFormat = detailFormat
        }
        configuration.frameSemantics.insert(.sceneDepth)
        session.run(configuration)
    }

    func start(directory: URL, scanID: String, motionDiagnostics: Bool = false) async throws {
        guard hasAR else { throw CaptureFailure.unavailable("This device has no AR world tracking. Use Synthetic sample or import a recorded package; no live LiDAR is simulated.") }
        let allowed = await AVCaptureDevice.requestAccess(for: .video)
        guard allowed else { throw CaptureFailure.unavailable("Camera permission is required. Enable Reverse CAD in Settings → Privacy & Security → Camera.") }
        guard !isCapturing else { return }
        let capture = try ARKitCaptureProvider(session: session, directory: directory, scanID: scanID, useDepth: hasLiDAR, motionDiagnostics: motionDiagnostics)
        capture.onLiveGeometry = { [weak self] snapshot in
            Task { @MainActor in self?.receiveLiveGeometry(snapshot) }
        }
        capture.selectObject(point: selectedObjectPoint)
        connect(capture)
        provider = capture
        frameCount = 0; rejectedFrames = 0; droppedFrames = 0; bytesWritten = 0; coverageViews = 0
        packageURL = directory
        isCapturing = true
        status = hasLiDAR ? "Live LiDAR + RGB + visual-inertial pose" : "Limited camera/manual capture — no metric depth"
        try capture.start()
    }

    func selectObject(normalizedRawImagePoint: CGPoint) {
        selectedObjectPoint = normalizedRawImagePoint
        (provider as? ARKitCaptureProvider)?.selectObject(point: normalizedRawImagePoint)
        guidance = "Scan center selected. Keep this object still and move the phone."
    }

    func stop() async throws -> URL {
        guard let provider else { throw CaptureFailure.unavailable("No capture is active.") }
        isCapturing = false
        clearGhost()
        let url = try await provider.finish()
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
    var onSelect: ((CGPoint) -> Void)? = nil
    var ghost: LiveGhostResponse.Candidate? = nil
    func makeCoordinator() -> Coordinator { Coordinator(session: session, onSelect: onSelect) }
    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        view.session = session
        view.addGestureRecognizer(UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tapped(_:))))
        view.accessibilityLabel = "Live camera. Tap the stationary object to select its foreground region."
        return view
    }
    func updateUIView(_ view: ARView, context: Context) {
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
            let normalized = CGPoint(x: position.x / view.bounds.width, y: position.y / view.bounds.height)
            let orientation = view.window?.windowScene?.interfaceOrientation ?? .portrait
            // Inverse display transform maps portrait screen coordinates back to raw calibrated image coordinates.
            let image = normalized.applying(frame.displayTransform(for: orientation, viewportSize: view.bounds.size).inverted())
            onSelect?(CGPoint(x: min(1, max(0, image.x)), y: min(1, max(0, image.y))))
        }
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
