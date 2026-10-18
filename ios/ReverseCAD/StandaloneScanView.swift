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
                        Text("Describe one object. Jev outlines it live; tap Scan, move around it, then export its measured 3D shape.").foregroundStyle(.secondary)
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
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var capture = CaptureController()
    @StateObject private var live = LiveObjectIdentifier()
    let objectDescription: String
    @State private var manualSnapshot: ObjectCameraSnapshot?
    @State private var manualBox: CGRect?
    @State private var manualMode = false
    @State private var pending = false
    @State private var failure: String?
    @State private var delivered = false
    @State private var visible = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                ZStack {
                    CapturePreview(session: capture.session, showsGuide: false, onGuide: { rect, size, orientation in capture.updateGuide(rect: rect, viewport: size, orientation: orientation) })
                    if let manualSnapshot, let image = UIImage(data: manualSnapshot.jpeg) {
                        TargetStillView(image: image, box: manualBox, onDraw: { manualBox = $0 })
                    } else {
                        LiveObjectOverlay(identifier: live, session: capture.session)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity).clipped()
                VStack(spacing: 12) {
                    Text(objectDescription).font(.headline)
                    if let failure { Text(failure).font(.subheadline).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true) }
                    if capture.isCapturing {
                        Text(capture.guidance).font(.subheadline).multilineTextAlignment(.center)
                        Text("\(capture.frameCount) saved views").font(.caption)
                        Button("Finish scan") { Task { await finish() } }.buttonStyle(.borderedProminent).disabled(pending)
                    } else if manualSnapshot != nil {
                        Text("Drag a box around the whole object. Keep the phone still, then scan.").font(.subheadline).multilineTextAlignment(.center)
                        Button("Scan this object") { Task { await begin() } }.buttonStyle(.borderedProminent).disabled(pending)
                        Button("Use live Jev detection") { resumeLive() }.disabled(pending)
                    } else {
                        Label(live.message, systemImage: "viewfinder").font(.subheadline).multilineTextAlignment(.center)
                        Button("Scan outlined object") { Task { await begin() } }.buttonStyle(.borderedProminent)
                            .disabled(pending || live.candidate == nil).accessibilityIdentifier("scanLiveObject")
                        Text("Jev checks the camera about five times a second. Tap Scan when the outline covers your object.").font(.caption).foregroundStyle(.secondary)
                        Button("Choose the box myself") { chooseManualBox() }.font(.subheadline).disabled(pending)
                        Text("Live camera images go to TypeSafe through your paired Mac while this screen is open.").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.horizontal, 20).padding(.bottom, 16)
            }.navigationTitle("Scan object").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarLeading) { Button(capture.isCapturing ? "Save & close" : "Close") { Task { if capture.isCapturing { await finish() } else { live.stop(); dismiss() } } }.disabled(pending) } }
                .onAppear { visible = true }
                .task {
                    do { try await capture.startPreview(); if visible && scenePhase == .active { resumeLive() } }
                    catch { failure = error.localizedDescription }
                }
                .onChange(of: capture.savedRevision) { _, _ in deliver() }
                .onChange(of: scenePhase) { _, phase in
                    if phase != .active { live.stop() }
                    else if visible && !manualMode && !delivered { live.start(session: capture.session, description: objectDescription, model: model) }
                }
                .onDisappear { visible = false; live.stop(); capture.session.pause() }
        }.interactiveDismissDisabled(capture.isCapturing || pending)
    }

    private func resumeLive() {
        manualSnapshot = nil; manualBox = nil; manualMode = false; failure = nil
        live.start(session: capture.session, description: objectDescription, model: model)
    }

    private func chooseManualBox() {
        guard let frame = capture.session.currentFrame else { failure = "Wait for the camera to be ready."; return }
        do {
            let photo = try live.snapshot(frame)
            live.stop(); manualMode = true; failure = nil; manualSnapshot = photo
            manualBox = CGRect(x: 0.15, y: 0.15, width: 0.7, height: 0.7)
        } catch { failure = error.localizedDescription }
    }

    private func begin() async {
        guard !pending, let current = capture.session.currentFrame else { return }
        let photo: ObjectCameraSnapshot
        let box: CGRect
        var target: [String: Any]
        if let manualSnapshot, let manualBox {
            guard manualSnapshot.matches(current, maximumAge: 60) else {
                failure = "The camera moved. Choose the box again on the current view."; chooseManualBox(); return
            }
            photo = manualSnapshot; box = manualBox
            target = ["selection_method": "manual_box", "description": objectDescription, "metric_evidence": false, "image_sha256": photo.hash]
        } else if let candidate = live.currentCandidate(session: capture.session) {
            photo = candidate.snapshot; box = candidate.box; target = candidate.response
            target["selection_method"] = "live_jev_box_then_user_confirmation"
            target["requested_interval_ms"] = 200
        } else {
            failure = "Wait for Jev's fresh outline, then tap Scan."; return
        }
        pending = true; failure = nil; defer { pending = false }
        do {
            model.create(name: objectDescription, synthetic: false)
            target["user_confirmed"] = true; target["image_orientation"] = "portrait_clockwise_from_raw"
            target["source_frame_timestamp"] = photo.frameTimestamp
            target["confirmed_box"] = ["left": box.minX, "right": box.maxX, "top": box.minY, "bottom": box.maxY]
            let rawBox = CGRect(x: box.minY, y: 1-box.maxX, width: box.height, height: box.width)
            model.update { $0.repairScope = "standalone_scan"; $0.scanTarget = try? JSONSerialization.data(withJSONObject: target) }
            guard let directory = model.scanDirectory else { return }
            if let projectDirectory = model.projectDirectory { try photo.jpeg.write(to: projectDirectory.appendingPathComponent("target-preview.jpg")) }
            capture.setConfirmedTarget(rawBox)
            try await capture.start(directory: directory, scanID: UUID().uuidString)
            model.captureActive = true; manualSnapshot = nil; manualBox = nil
        } catch { failure = error.localizedDescription; model.captureActive = false }
    }

    private func finish() async {
        live.stop(); pending = true; defer { pending = false }
        do { _ = try await capture.stop(); deliver() } catch { failure = error.localizedDescription }
    }
    private func deliver() {
        guard !delivered, let url = capture.packageURL, capture.savedRevision > 0 else { return }
        delivered = true; live.stop(); model.captureActive = false; model.didCapture(url); dismiss()
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
