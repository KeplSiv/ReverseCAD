import SwiftUI
import ARKit
import ReverseCADCore

struct StandaloneScanView: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var workflow = CapturedObjectWorkflow()
    @State private var description = ""
    @State private var camera = false
    @State private var settings = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let project = model.project {
                        Text(project.name).font(.largeTitle.bold())
                        if model.busy || workflow.working {
                            ProgressView(workflow.working ? workflow.message : "Building your 3D model…\n" + model.progress)
                            Button("Cancel") { workflow.cancel(); if model.busy { model.cancel() } }
                        }
                        if let failure = workflow.failure { Text(failure).foregroundStyle(.orange) }
                        if let mesh = model.scanMesh, !mesh.vertices.isEmpty {
                            Text("Preview and export").font(.title2.bold())
                            GeometryPreview(scan: mesh, part: nil, showPart: false).frame(height: 350)
                            Text("Drag to rotate. Pinch to zoom. Holes and unseen surfaces remain open.").foregroundStyle(.secondary)
                            ForEach(Array(model.measurements.enumerated()), id: \.offset) { _, measurement in
                                if let name = measurement["name"] as? String, let value = measurement["value"] as? Double {
                                    HStack { Text(name); Spacer(); Text(String(format: "%.2f mm", value)).monospacedDigit() }
                                }
                            }
                            if let dimensions = meshDimensions(mesh) { Text(dimensions).font(.headline) }
                            ForEach(model.standaloneExportFormats, id: \.self) { format in
                                Button("Export " + format) { model.exportStandaloneScan(format: format) }.buttonStyle(.bordered).disabled(model.busy || workflow.working)
                            }
                            if !model.standaloneExportFormats.contains("STEP") { Text("STEP is unavailable for this reconstruction. The supported exports appear above.").font(.caption).foregroundStyle(.secondary) }
                            Text("STEP, when available, is a faceted observed surface. Dimensions are estimates, not independently validated measurements.").font(.caption).foregroundStyle(.secondary)
                        } else if workflow.phase == "ambiguous", let image = workflow.referenceImage {
                            Text("Identify object").font(.title2.bold())
                            Text(workflow.message)
                            CapturedTargetImage(image: image) { point in identify(point: point) }.frame(height: 370)
                        } else if workflow.phase == "identified" {
                            Text("Build 3D model").font(.title2.bold())
                            Text("Identified: \(workflow.identity?.category.replacingOccurrences(of: "_", with: " ") ?? "object")")
                        } else if !workflow.working {
                            Text(workflow.message.isEmpty ? "Your scan is saved on this phone." : workflow.message)
                            Button("Find object in saved scan") { identify() }.buttonStyle(.borderedProminent)
                        }
                        if workflow.identity?.confirmedIndices.isEmpty == false && !workflow.working {
                            Text("Reconstruction runs on your Mac. Connect to the Mac service in Connection settings before building. Capture and identification work without it.").font(.subheadline).foregroundStyle(.secondary)
                            Button(model.scanMesh == nil ? "Build 3D model" : "Rebuild from saved scan") { build() }.buttonStyle(.borderedProminent).disabled(model.busy)
                            Button("Choose a different object") { workflow.phase = "ambiguous"; workflow.message = "Tap the intended object in the saved image." }.disabled(model.busy)
                        }
                        if !model.warnings.isEmpty { DisclosureGroup("Capture quality and missing views") { ForEach(model.warnings, id: \.self) { Text($0).font(.caption) } } }
                        if project.jobID != nil { Button("Resume processing") { model.resumeJob() }.disabled(model.busy) }
                        Button("Export original capture") { model.exportScan() }.disabled(model.busy || workflow.working)
                        Button("Back to scans") { workflow.cancel(); model.selectedID = nil }.disabled(model.busy)
                    } else {
                        Text("Frame object").font(.largeTitle.bold())
                        Text("Place one object inside the box.").font(.title3)
                        TextField("Description (optional)", text: $description, axis: .vertical).textFieldStyle(.roundedBorder).lineLimit(1...3).accessibilityIdentifier("scanObjectDescription")
                        Button { camera = true } label: { Label("Open camera", systemImage: "camera").frame(maxWidth: .infinity) }.buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("findScanObject")
                        Text("Frame object → Scan around it → Identify object → Build 3D model → Preview and export").font(.caption).foregroundStyle(.secondary)
                        if !model.projects.filter({ $0.repairScope == "standalone_scan" }).isEmpty { Text("Saved scans").font(.title2.bold()) }
                        ForEach(model.projects.filter { $0.repairScope == "standalone_scan" }) { project in
                            Button { model.select(project) } label: { HStack { VStack(alignment: .leading) { Text(project.name).font(.headline); Text(project.stage).font(.caption) }; Spacer(); Image(systemName: "chevron.right") } }.buttonStyle(.plain)
                        }
                    }
                }.padding(22)
            }.navigationTitle("Prelude").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { settings = true } label: { Image(systemName: "network") }.accessibilityLabel("Connection").disabled(model.busy || model.captureActive || workflow.working) } }
                .sheet(isPresented: $settings) { SettingsView() }
                .fullScreenCover(isPresented: $camera, onDismiss: { resumeSaved() }) { StandaloneCameraView(objectDescription: description) }
                .sheet(isPresented: $model.showingShare) { ShareSheet(urls: model.shareURLs) }
                .task(id: model.selectedID) { if !camera { resumeSaved() } }
                .alert("Needs attention", isPresented: Binding(get: { model.error != nil && !camera && !settings }, set: { if !$0 { model.error = nil } })) { Button("OK") { model.error = nil } } message: { Text(model.error ?? "") }
        }
    }
    private func resumeSaved() {
        guard let project = model.projectDirectory, let capture = model.scanDirectory, model.project?.scanID != nil else { return }
        workflow.load(project: project, capture: capture)
        if workflow.identity == nil { identify() }
    }
    private func identify(point: CGPoint? = nil) {
        guard let project = model.projectDirectory, let capture = model.scanDirectory else { return }
        workflow.find(project: project, capture: capture, description: model.project?.intent ?? description, point: point)
    }
    private func build() {
        guard let project = model.projectDirectory, let capture = model.scanDirectory else { return }
        workflow.build(project: project, capture: capture) { target in
            model.update { $0.scanTarget = try? JSONSerialization.data(withJSONObject: target); $0.stage = "Building your 3D model" }
            model.uploadAndReconstruct()
        }
    }
    private func meshDimensions(_ mesh: MeshPreview) -> String? {
        guard !mesh.vertices.isEmpty else { return nil }
        let bounds = (0..<3).map { axis in (mesh.vertices.map { $0[axis] }.max() ?? 0) - (mesh.vertices.map { $0[axis] }.min() ?? 0) }
        return String(format: "Observed bounds: %.1f × %.1f × %.1f mm", bounds[0], bounds[1], bounds[2])
    }
}

struct StandaloneCameraView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var capture = CaptureController()
    let objectDescription: String
    @State private var pending = false
    @State private var failure: String?
    @State private var delivered = false
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                CapturePreview(session: capture.session, onGuide: { rect, size, orientation in capture.updateGuide(rect: rect, viewport: size, orientation: orientation) })
                    .frame(maxWidth: .infinity, maxHeight: .infinity).clipped()
                VStack(spacing: 12) {
                    Text(capture.isCapturing ? "Keep the object still. Walk slowly around it, keeping it inside the box." : "Place one object inside the box.").font(.headline).multilineTextAlignment(.center)
                    if let failure { Text(failure).foregroundStyle(.orange) }
                    if capture.isCapturing {
                        Text(capture.guidance).font(.subheadline).multilineTextAlignment(.center)
                        Text("\(capture.frameCount) accepted views · \(capture.coverageViews) observed directions").font(.caption)
                        Button("Finish") { Task { await finish() } }.buttonStyle(.borderedProminent).disabled(pending)
                    } else {
                        Button("Start scan") { Task { await begin() } }.buttonStyle(.borderedProminent).disabled(pending).accessibilityIdentifier("startObjectScan")
                        Text("Full images are saved locally. The box is only a framing hint.").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.horizontal, 20).padding(.bottom, 16)
            }.navigationTitle(capture.isCapturing ? "Scan around it" : "Frame object").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarLeading) { Button(capture.isCapturing ? "Save & close" : "Close") { Task { if capture.isCapturing { await finish() } else { dismiss() } } }.disabled(pending) } }
                .task { do { try await capture.startPreview() } catch { failure = error.localizedDescription } }
                .onChange(of: capture.savedRevision) { _, _ in deliver() }
                .onDisappear { capture.session.pause() }
        }.interactiveDismissDisabled(capture.isCapturing || pending)
    }
    private func begin() async {
        guard !pending, !capture.isCapturing else { return }
        pending = true; defer { pending = false }
        do {
            let name = objectDescription.trimmingCharacters(in: .whitespacesAndNewlines)
            model.create(name: name.isEmpty ? "Object scan" : String(name.prefix(80)), synthetic: false)
            model.update { $0.repairScope = "standalone_scan"; $0.intent = String(name.prefix(240)) }
            guard let directory = model.scanDirectory else { return }
            try await capture.start(directory: directory, scanID: UUID().uuidString)
            model.captureActive = true
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

private struct CapturedTargetImage: View {
    let image: UIImage
    let onTap: (CGPoint) -> Void
    var body: some View {
        GeometryReader { geometry in
            let scale = min(geometry.size.width / image.size.width, geometry.size.height / image.size.height)
            let size = CGSize(width: image.size.width*scale, height: image.size.height*scale)
            Image(uiImage: image).resizable().frame(width: size.width, height: size.height)
                .onTapGesture(coordinateSpace: .local) { point in
                    // Gesture coordinates belong to the fitted image, not the letterboxed parent.
                    onTap(CGPoint(x: min(1,max(0,point.x/size.width)), y: min(1,max(0,point.y/size.height))))
                }.position(x: geometry.size.width/2, y: geometry.size.height/2).accessibilityLabel("Saved reference image. Tap the object you intended to scan.")
        }
    }
}
