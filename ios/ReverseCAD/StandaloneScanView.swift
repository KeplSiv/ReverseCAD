import SwiftUI
import ARKit
import CoreImage
import CryptoKit
import simd

/// The standalone entry point has no repair-generation action.
struct StandaloneScanView: View {
    @EnvironmentObject private var model: AppModel
    @State private var description = ""
    @State private var camera = false
    @State private var settings = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    if let project = model.project {
                        Text(project.name).font(.largeTitle.bold())
                        if model.busy { ProgressView(model.progress).frame(maxWidth: .infinity) }
                        if let mesh = model.scanMesh, !mesh.vertices.isEmpty {
                            GeometryPreview(scan: mesh, part: nil, showPart: false).frame(height: 350)
                            Text("Your observed shape").font(.title2.bold())
                            Text("Drag to rotate. Pinch to zoom. Open areas were not captured.").foregroundStyle(.secondary)
                            ForEach(Array(model.measurements.enumerated()), id: \.offset) { _, measurement in
                                if let name = measurement["name"] as? String, let value = measurement["value"] as? Double {
                                    HStack { Text(name); Spacer(); Text(String(format: "%.2f mm", value)).monospacedDigit() }
                                }
                            }
                            Button("Export 3D scan + measurements") { model.exportStandaloneScan() }.buttonStyle(.borderedProminent).disabled(model.busy)
                            Text("STEP is a faceted surface for CAD. STL and PLY keep the observed shape; this is not a completed or fitted replacement part.").font(.caption).foregroundStyle(.secondary)
                            if !model.warnings.isEmpty { DisclosureGroup("Capture details") { ForEach(model.warnings, id: \.self) { Text($0).font(.caption) } } }
                        } else {
                            Image(systemName: "cube.transparent").font(.system(size: 70)).frame(maxWidth: .infinity).padding(30)
                            Text(project.stage).font(.headline)
                            Text("Your capture is saved on this phone. Reconstruct it on the paired Mac to see the measured shape.").foregroundStyle(.secondary)
                        }
                        if project.scanID != nil {
                            Button(model.scanMesh == nil ? "Build my 3D scan" : "Reprocess scan") { model.uploadAndReconstruct() }.buttonStyle(.bordered).disabled(model.busy)
                            Button("Export original capture") { model.exportScan() }.disabled(model.busy)
                        }
                        if project.jobID != nil { Button("Resume processing") { model.resumeJob() }.disabled(model.busy) }
                        Button("Back to scans") { model.selectedID = nil }.disabled(model.busy)
                    } else {
                        Image(systemName: "viewfinder").font(.system(size: 40)).foregroundStyle(.teal)
                        Text("What are you about to scan?").font(.largeTitle.bold())
                        Text("Describe one object. Confirm its box, move around it, then export its measured 3D shape.").foregroundStyle(.secondary)
                        TextField("For example: the black camera bracket", text: $description, axis: .vertical).textFieldStyle(.roundedBorder).lineLimit(2...4).accessibilityIdentifier("scanObjectDescription")
                        Button { camera = true } label: { Label("Find my object", systemImage: "camera").frame(maxWidth: .infinity) }.buttonStyle(.borderedProminent).controlSize(.large).disabled(description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityIdentifier("findScanObject")
                        if !model.projects.filter({ $0.repairScope == "standalone_scan" }).isEmpty { Text("Saved scans").font(.title2.bold()) }
                        ForEach(model.projects.filter { $0.repairScope == "standalone_scan" }) { project in
                            Button { model.select(project) } label: { HStack { VStack(alignment: .leading) { Text(project.name).font(.headline); Text(project.stage).font(.caption) }; Spacer(); Image(systemName: "chevron.right") } }.buttonStyle(.plain)
                        }
                    }
                    Text("TestFlight capture: Apple processed depth + camera. Dimensions are estimates pending independent checks. The private sparse sensor experiment remains a separate development build.").font(.caption).foregroundStyle(.secondary)
                }.padding(22)
            }.navigationTitle("Prelude").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { settings = true } label: { Image(systemName: "network") }.accessibilityLabel("Connection").disabled(model.busy || model.captureActive) } }
                .sheet(isPresented: $settings) { SettingsView() }
                .fullScreenCover(isPresented: $camera) { StandaloneCameraView(objectDescription: description) }
                .sheet(isPresented: $model.showingShare) { ShareSheet(urls: model.shareURLs) }
                .alert("Needs attention", isPresented: Binding(get: { model.error != nil && !camera && !settings }, set: { if !$0 { model.error = nil } })) { Button("OK") { model.error = nil } } message: { Text(model.error ?? "") }
        }
    }
}

struct StandaloneCameraView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var capture = CaptureController()
    let objectDescription: String
    @State private var still: UIImage?
    @State private var originalJPEG: Data?
    @State private var snapshotPose: simd_float4x4?
    @State private var box: CGRect?
    @State private var target: [String: Any]?
    @State private var pending = false
    @State private var failure: String?
    @State private var delivered = false
    @State private var requestID: String?
    @State private var snapshotTime = Date.distantPast
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                ZStack {
                    CapturePreview(session: capture.session, onGuide: { rect, size, orientation in capture.updateGuide(rect: rect, viewport: size, orientation: orientation) })
                    if let still { TargetStillView(image: still, box: box, onDraw: target?["selection_method"] as? String == "manual_box" ? { self.box = $0 } : nil) }
                }.frame(maxWidth: .infinity, maxHeight: .infinity).clipped()
                VStack(spacing: 14) {
                    Text(objectDescription).font(.headline)
                    if pending { ProgressView("Jev is finding your object…") }
                    if let failure { Text(failure).font(.subheadline).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true) }
                    if capture.isCapturing {
                        Text(capture.guidance).font(.subheadline).multilineTextAlignment(.center)
                        Text("\(capture.frameCount) saved views").font(.caption)
                        Button("Finish scan") { Task { await finish() } }.buttonStyle(.borderedProminent)
                    } else if box != nil {
                        Text(target?["selection_method"] as? String == "manual_box" ? "Drag across the image to box the whole object. Keep the phone still, then confirm." : "Is this the whole object? Keep the phone in this position, then confirm.").font(.subheadline).multilineTextAlignment(.center)
                        Button("Yes, scan this object") { Task { await begin() } }.buttonStyle(.borderedProminent).disabled(pending)
                        Button("Try another view") { clearTarget() }.disabled(pending)
                    } else {
                        Text("Keep one whole object in view. Jev checks its category and bounding box.").font(.subheadline).multilineTextAlignment(.center)
                        Button("Identify with Jev") { Task { await identify() } }.buttonStyle(.borderedProminent).disabled(pending)
                        Button("Choose the box myself") { Task { await identify(manual: true) } }.disabled(pending)
                        Text("Jev sends this camera image to TypeSafe through your paired Mac. Manual selection stays on this phone.").font(.caption).foregroundStyle(.secondary)
                        if still != nil { Button("Retake view") { clearTarget() }.disabled(pending) }
                    }
                }.padding(.horizontal, 20).padding(.bottom, 16)
            }.navigationTitle("Scan object").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarLeading) { Button(capture.isCapturing ? "Save & close" : "Close") { Task { if capture.isCapturing { await finish() } else { dismiss() } } }.disabled(pending) } }
                .task { do { try await capture.startPreview() } catch { failure = error.localizedDescription } }
                .onChange(of: capture.savedRevision) { _, _ in deliver() }
                .onDisappear { requestID = nil; capture.session.pause() }
        }.interactiveDismissDisabled(capture.isCapturing || pending)
    }
    private func clearTarget() { still = nil; originalJPEG = nil; box = nil; target = nil; failure = nil; requestID = nil }
    private func identify(manual: Bool = false) async {
        guard !pending, let frame = capture.session.currentFrame else { failure = "Wait for the camera to be ready."; return }
        pending = true; failure = nil
        defer { pending = false }
        let id = UUID().uuidString; requestID = id; snapshotPose = frame.camera.transform; snapshotTime = Date()
        do {
            let original = CIImage(cvPixelBuffer: frame.capturedImage).oriented(.right)
            let scale = min(1, 1280 / max(original.extent.width, original.extent.height))
            let image = original.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            let context = CIContext()
            guard let cg = context.createCGImage(image, from: image.extent), let jpg = UIImage(cgImage: cg).jpegData(compressionQuality: 0.9) else { throw ServiceFailure(message: "Could not read the camera image.") }
            still = UIImage(data: jpg); originalJPEG = jpg
            if manual {
                box = CGRect(x: 0.15, y: 0.15, width: 0.7, height: 0.7)
                target = ["selection_method": "manual_box", "description": objectDescription, "metric_evidence": false,
                          "image_sha256": SHA256.hash(data: jpg).map { String(format: "%02x", $0) }.joined()]
                return
            }
            let result = try await model.object("v1/objects/identify", method: "POST", json: ["description": objectDescription, "image_base64": jpg.base64EncodedString(), "request_id": id])
            guard requestID == id, result["request_id"] as? String == id, result["image_sha256"] as? String == SHA256.hash(data: jpg).map({ String(format: "%02x", $0) }).joined() else { return }
            guard result["status"] as? String == "confirm_target", let edges = result["box"] as? [String: Double], let top = edges["top"], let bottom = edges["bottom"], let left = edges["left"], let right = edges["right"], [top,bottom,left,right].allSatisfy({ $0.isFinite && (0...1).contains($0) }), bottom > top, right > left else { throw ServiceFailure(message: result["message"] as? String ?? "The object could not be selected.") }
            box = CGRect(x: left, y: top, width: right-left, height: bottom-top); target = result
        } catch { failure = error.localizedDescription }
    }
    private func begin() async {
        guard let box, let snapshotPose, let current = capture.session.currentFrame, var target else { return }
        let distance = simd_distance(snapshotPose.columns.3, current.camera.transform.columns.3)
        let old = snapshotPose.columns.2, new = current.camera.transform.columns.2
        let cosine = simd_dot(simd_normalize(SIMD3(old.x, old.y, old.z)), simd_normalize(SIMD3(new.x, new.y, new.z)))
        guard Date().timeIntervalSince(snapshotTime) <= 60, distance < 0.025, cosine > 0.99 else { clearTarget(); failure = "The camera moved since identification. Identify this view again so the box stays on the right object."; return }
        pending = true; defer { pending = false }
        do {
            model.create(name: objectDescription, synthetic: false)
            target["user_confirmed"] = true; target["image_orientation"] = "portrait_clockwise_from_raw"; if target["selection_method"] == nil { target["selection_method"] = "jev_box_then_user_confirmation" }
            target["confirmed_box"] = ["left": box.minX, "right": box.maxX, "top": box.minY, "bottom": box.maxY]
            let rawBox = CGRect(x: box.minY, y: 1-box.maxX, width: box.height, height: box.width)
            model.update { $0.repairScope = "standalone_scan"; $0.scanTarget = try? JSONSerialization.data(withJSONObject: target) }
            guard let directory = model.scanDirectory else { return }
            if let projectDirectory = model.projectDirectory, let jpg = originalJPEG { try jpg.write(to: projectDirectory.appendingPathComponent("target-preview.jpg")) }
            capture.setConfirmedTarget(rawBox)
            try await capture.start(directory: directory, scanID: UUID().uuidString)
            model.captureActive = true; still = nil; self.box = nil
        } catch { failure = error.localizedDescription; model.captureActive = false }
    }
    private func finish() async {
        pending = true; defer { pending = false }
        do { _ = try await capture.stop(); deliver() } catch { failure = error.localizedDescription }
    }
    private func deliver() {
        guard !delivered, let url = capture.packageURL, capture.savedRevision > 0 else { return }
        delivered = true; model.captureActive = false; model.didCapture(url); dismiss()
    }
}

private struct TargetStillView: View {
    let image: UIImage
    let box: CGRect?
    var onDraw: ((CGRect) -> Void)? = nil
    var body: some View {
        GeometryReader { geometry in
            let scale = min(geometry.size.width / image.size.width, geometry.size.height / image.size.height)
            let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
            ZStack {
                Color.black
                Image(uiImage: image).resizable().frame(width: size.width, height: size.height)
                if let box { Rectangle().stroke(.mint, lineWidth: 3).frame(width: box.width * size.width, height: box.height * size.height).position(x: (geometry.size.width-size.width)/2 + box.midX*size.width, y: (geometry.size.height-size.height)/2 + box.midY*size.height) }
            }.frame(width: geometry.size.width, height: geometry.size.height)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 4).onChanged { value in
                    guard let onDraw else { return }
                    let origin = CGPoint(x: (geometry.size.width-size.width)/2, y: (geometry.size.height-size.height)/2)
                    let x0 = min(1, max(0, (value.startLocation.x-origin.x)/size.width))
                    let y0 = min(1, max(0, (value.startLocation.y-origin.y)/size.height))
                    let x1 = min(1, max(0, (value.location.x-origin.x)/size.width))
                    let y1 = min(1, max(0, (value.location.y-origin.y)/size.height))
                    let rect = CGRect(x: min(x0,x1), y: min(y0,y1), width: abs(x1-x0), height: abs(y1-y0))
                    if rect.width >= 0.02 && rect.height >= 0.02 { onDraw(rect) }
                })
        }
    }
}
