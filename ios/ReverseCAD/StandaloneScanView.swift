import SwiftUI
import ARKit
import ReverseCADCore

struct StandaloneScanView: View {
    var flow: ObjectFlow = .scan
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel
    @StateObject private var workflow = CapturedObjectWorkflow()
    @State private var description = ""
    @State private var camera = false
    @State private var settings = false
    @State private var repairPresented = false
    @State private var repairStartedFor: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let project = model.project {
                        Text(project.name).font(.largeTitle.bold())
                        if flow == .repair, project.repairScope != "standalone_scan" {
                            Button("Review repair") { repairPresented=true }.buttonStyle(RepairButtonStyle())
                        }
                        if model.busy || workflow.working {
                            VStack(spacing: 16) {
                                ProgressView().controlSize(.large).tint(RepairStyle.accent)
                                Text(workflow.phase == "finding" ? "Finding your object…" : "Building your 3D model…").font(.title2.bold())
                                Text(workflow.working ? workflow.message : model.progress)
                                    .font(.subheadline).foregroundStyle(RepairStyle.secondary).multilineTextAlignment(.center)
                                Button("Cancel") { workflow.cancel(); if model.busy { model.cancel() } }
                                    .buttonStyle(RepairButtonStyle(secondary: true))
                            }.frame(maxWidth: .infinity).padding(20)
                                .background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 22))
                        }
                        if let failure = workflow.failure { Text(failure).foregroundStyle(.orange) }
                        if let mesh = model.scanMesh, !mesh.vertices.isEmpty, workflow.phase != "ambiguous" {
                            Text("Preview and export").font(.title2.bold())
                            GeometryPreview(scan: mesh, part: nil, showPart: false, backgroundColor: UIColor(RepairStyle.surface)).frame(height: 350)
                                .clipShape(RoundedRectangle(cornerRadius: 22))
                                .accessibilityLabel("Your scanned object. Drag to rotate and pinch to zoom.")
                            Text("Drag to rotate. Pinch to zoom. Holes and unseen surfaces remain open.").foregroundStyle(RepairStyle.secondary)
                            ForEach(Array(model.measurements.enumerated()), id: \.offset) { _, measurement in
                                if let name = measurement["name"] as? String, let value = measurement["value"] as? Double {
                                    HStack { Text(name); Spacer(); Text(String(format: "%.2f mm", value)).monospacedDigit() }
                                }
                            }
                            if let dimensions = meshDimensions(mesh) { Text(dimensions).font(.headline) }
                            ForEach(model.standaloneExportFormats, id: \.self) { format in
                                Button("Export " + format) { model.exportStandaloneScan(format: format) }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy || workflow.working)
                            }
                            if !model.standaloneExportFormats.contains("STEP") { Text("STEP is unavailable for this reconstruction. The supported exports appear above.").font(.caption).foregroundStyle(RepairStyle.secondary) }
                            Text("STEP, when available, is a faceted observed surface. Dimensions are estimates, not independently validated measurements.").font(.caption).foregroundStyle(RepairStyle.secondary)
                        } else if workflow.phase == "ambiguous", let image = workflow.referenceImage {
                            Text("Identify object").font(.title2.bold())
                            Text(workflow.message)
                            CapturedTargetImage(image: image) { point in identify(point: point) }.frame(height: 370)
                        } else if workflow.phase == "identified" {
                            Text("Build 3D model").font(.title2.bold())
                            Text("Identified: \(workflow.identity?.category.replacingOccurrences(of: "_", with: " ") ?? "object")")
                        } else if !workflow.working {
                            Text(workflow.message.isEmpty ? "Your scan is saved on this phone." : workflow.message)
                            Button("Find object in saved scan") { identify() }.buttonStyle(RepairButtonStyle())
                        }
                        if workflow.identity?.confirmedIndices.isEmpty == false && !workflow.working {
                            Text("Reconstruction runs on your Mac. Connect to the Mac service in Connection settings before building. Capture and identification work without it.").font(.subheadline).foregroundStyle(RepairStyle.secondary)
                            Button(model.scanMesh == nil ? "Build 3D model" : "Rebuild from saved scan") { build() }.buttonStyle(RepairButtonStyle()).disabled(model.busy)
                            if model.standaloneExportFormats.isEmpty {
                                Button("Choose a different object") { workflow.phase = "ambiguous"; workflow.message = "Tap the intended object in the saved image." }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy)
                            }
                        }
                        if !model.warnings.isEmpty { DisclosureGroup("Capture quality and missing views") { ForEach(model.warnings, id: \.self) { Text($0).font(.caption) } } }
                        if project.jobID != nil { Button("Resume processing") { model.resumeJob() }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy) }
                        Button("Export original capture") { model.exportScan() }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy || workflow.working)
                        Button("Back to scans") { workflow.cancel(); model.selectedID = nil }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy)
                    } else {
                        Text(flow.title).font(.largeTitle.bold())
                        Text("Adjust the box around one object.").font(.title3)
                        TextField("Description (optional)", text: $description, axis: .vertical).textFieldStyle(.plain).lineLimit(1...3)
                            .padding(16).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 18))
                            .accessibilityIdentifier("scanObjectDescription")
                        Button { camera = true } label: { Label("Open camera", systemImage: "camera").frame(maxWidth: .infinity) }.buttonStyle(RepairButtonStyle()).controlSize(.large).accessibilityIdentifier("findScanObject")
                        Text(flow == .scan ? "Adjust box → Identify → Scan → Preview and export" : "Adjust box → Identify → Scan → Find damage → Review CAD").font(.caption).foregroundStyle(RepairStyle.secondary)
                        if !model.projects.filter({ flow.includes($0) }).isEmpty { Text("Saved scans").font(.title2.bold()) }
                        ForEach(model.projects.filter { flow.includes($0) }) { project in
                            Button { model.select(project) } label: {
                                HStack(spacing: 14) {
                                    ProjectThumbnail(directory: model.directory(project.id).appendingPathComponent("scan/rgb"), family: project.family)
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(project.name).font(.headline).foregroundStyle(RepairStyle.text)
                                        Text(project.stage).font(.caption).foregroundStyle(RepairStyle.secondary)
                                    }
                                    Spacer(); Image(systemName: "chevron.right").font(.caption).foregroundStyle(RepairStyle.accent)
                                }.padding(16).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 18))
                            }.buttonStyle(.plain)
                        }
                    }
                }.padding(20).foregroundStyle(RepairStyle.text)
            }.background(RepairStyle.background.ignoresSafeArea())
                .navigationTitle("Prelude").navigationBarTitleDisplayMode(.inline)
                .toolbarBackground(RepairStyle.background, for: .navigationBar)
                .toolbarBackground(.visible, for: .navigationBar)
                .toolbar { ToolbarItem(placement: .topBarLeading) { Button("Home") { workflow.cancel();model.selectedID=nil;dismiss() }.disabled(model.busy || model.captureActive) }; ToolbarItem(placement: .topBarTrailing) { Button { settings = true } label: { Image(systemName: "network") }.accessibilityLabel("Connection").disabled(model.busy || model.captureActive || workflow.working) } }
                .sheet(isPresented: $settings) { SettingsView() }
                .fullScreenCover(isPresented: $camera, onDismiss: { resumeSaved() }) { StandaloneCameraView(objectDescription: description, flow: flow) }
                .fullScreenCover(isPresented: $repairPresented) { UnifiedRepairView(savedScanMode: true) }
                .onChange(of: model.busy) { _, busy in if !busy { continueToRepairIfReady() } }
                .sheet(isPresented: $model.showingShare) { ShareSheet(urls: model.shareURLs) }
                .task(id: model.selectedID) { if !camera { resumeSaved() } }
                .alert("Needs attention", isPresented: Binding(get: { model.error != nil && !camera && !settings }, set: { if !$0 { model.error = nil } })) { Button("OK") { model.error = nil } } message: { Text(model.error ?? "") }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent)
    }
    private func resumeSaved() {
        guard let project = model.projectDirectory, let capture = model.scanDirectory, model.project?.scanID != nil else { return }
        workflow.load(project: project, capture: capture)
        if flow == .repair, model.project?.repairScope != "standalone_scan" { repairPresented=true;return }
        if workflow.identity == nil { identify() }
        else { continueToRepairIfReady() }
    }
    private func continueToRepairIfReady() {
        guard flow == .repair, !model.busy, model.error == nil, model.project?.repairScope == "standalone_scan",
              !model.standaloneExportFormats.isEmpty, let id=model.project?.scanID, repairStartedFor != id else{return}
        repairStartedFor=id;repairPresented=true;model.analyzeCapturedDamage()
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
    var flow: ObjectFlow = .scan
    @StateObject private var identifier = BoxObjectIdentifier()
    @State private var box = SelectionBox.initial
    @State private var viewport = CGSize.zero
    @State private var orientation = UIInterfaceOrientation.portrait
    @State private var pending = false
    @State private var failure: String?
    @State private var delivered = false
    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ZStack {
                    CapturePreview(session: capture.session, showsGuide: false, onGuide: { _, size, value in
                        if viewport != size { viewport=size }
                        if orientation != value { orientation=value }
                        capture.updateGuide(rect: CGRect(x:box.minX*size.width,y:box.minY*size.height,width:box.width*size.width,height:box.height*size.height),viewport:size,orientation:value)
                    })
                    AdjustableObjectBox(box:$box,editable:!capture.isCapturing && !identifier.running)
                }.frame(maxWidth: .infinity, maxHeight: .infinity).clipped()
                    .overlay(alignment: .top) {
                        Text(capture.isCapturing ? "SCANNING" : (identifier.running ? "IDENTIFYING" : "FRAME YOUR OBJECT"))
                            .font(.caption2.weight(.semibold)).tracking(2)
                            .padding(.horizontal, 16).padding(.vertical, 10)
                            .background(RepairStyle.background.opacity(0.9), in: Capsule())
                            .padding(.top, 16).allowsHitTesting(false)
                    }
                    .onChange(of:box) { _, _ in identifier.cancel(clear:true) }
                VStack(spacing: 14) {
                    Text(capture.isCapturing ? "Keep the object still. Walk slowly around it, keeping it inside the box." : "Place one object inside the box.")
                        .font(.subheadline).multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("scanGuidance")
                    if let failure { Text(failure).font(.footnote).foregroundStyle(.orange) }
                    if let failure=identifier.failure { Text(failure).font(.footnote).foregroundStyle(.orange) }
                    if identifier.running {
                        ProgressView(identifier.message).tint(RepairStyle.accent)
                        Button("Cancel identification") { identifier.cancel() }.buttonStyle(RepairButtonStyle(secondary: true))
                    } else if capture.isCapturing {
                        Text(capture.guidance).font(.subheadline).multilineTextAlignment(.center).foregroundStyle(RepairStyle.secondary)
                        cameraAction("Finish", icon: "checkmark", accessibilityID: "finishObjectScan") { Task { await finish() } }
                        Text("\(capture.frameCount) accepted views · \(capture.coverageViews) observed directions")
                            .font(.caption).foregroundStyle(RepairStyle.secondary)
                    } else {
                        if identifier.reference != nil {
                            Text(identifier.message).font(.subheadline).foregroundStyle(RepairStyle.secondary)
                            cameraAction("Start scan", icon: "viewfinder", accessibilityID: "startObjectScan") { Task { await begin() } }
                        } else {
                            cameraAction("Identify object in box", icon: "viewfinder", accessibilityID: "identifyObjectBox", action: identifyBox)
                        }
                        Text("Drag the corners to resize, or drag inside to move. Full images are retained.")
                            .font(.caption).foregroundStyle(RepairStyle.secondary).multilineTextAlignment(.center)
                    }
                }.padding(.horizontal, 24).padding(.vertical, 20).background(RepairStyle.background)
            }.foregroundStyle(RepairStyle.text)
                .background(RepairStyle.background.ignoresSafeArea())
                .navigationTitle(capture.isCapturing ? "Scan around it" : "Frame object").navigationBarTitleDisplayMode(.inline)
                .toolbarBackground(RepairStyle.background, for: .navigationBar)
                .toolbarBackground(.visible, for: .navigationBar)
                .toolbar { ToolbarItem(placement: .topBarLeading) { Button(capture.isCapturing ? "Save & close" : "Close") { Task { if capture.isCapturing { await finish() } else { identifier.cancel();dismiss() } } }.disabled(pending) } }
                .task { do { try await capture.startPreview() } catch { failure = error.localizedDescription } }
                .onChange(of: capture.savedRevision) { _, _ in deliver() }
                .onDisappear { identifier.cancel();capture.session.pause() }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent)
            .interactiveDismissDisabled(capture.isCapturing || pending)
    }
    private func cameraAction(_ title: String, icon: String, accessibilityID: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 10) {
                ZStack {
                    Circle().stroke(RepairStyle.accent, lineWidth: 3).frame(width: 80, height: 80)
                    Circle().fill(RepairStyle.accent).frame(width: 66, height: 66)
                    if pending { ProgressView().tint(RepairStyle.background) }
                    else { Image(systemName: icon).font(.system(size: 27, weight: .semibold)).foregroundStyle(RepairStyle.background) }
                }
                Text(title).font(.caption.weight(.semibold)).foregroundStyle(RepairStyle.text)
            }.frame(minWidth: 160)
        }.buttonStyle(.plain).disabled(pending || identifier.running)
            .accessibilityLabel(title).accessibilityIdentifier(accessibilityID)
    }
    private func identifyBox() {
        guard let frame=capture.session.currentFrame,viewport.width>0,viewport.height>0 else {failure="Wait for the camera to be ready.";return}
        do {
            let rect=CGRect(x:box.minX*viewport.width,y:box.minY*viewport.height,width:box.width*viewport.width,height:box.height*viewport.height)
            let raw=CaptureFraming.rawRegion(rect:rect,viewport:viewport,displayTransform:frame.displayTransform(for:orientation,viewportSize:viewport))
            failure=nil;identifier.identify(jpeg:try BoxObjectIdentifier.fullImage(frame),rawBox:raw,description:objectDescription)
        } catch {failure=error.localizedDescription}
    }
    private func begin() async {
        guard !pending, !capture.isCapturing, identifier.reference != nil else { return }
        pending = true; defer { pending = false }
        do {
            let name = objectDescription.trimmingCharacters(in: .whitespacesAndNewlines)
            model.create(name: name.isEmpty ? "Object scan" : String(name.prefix(80)), synthetic: false)
            model.update { $0.repairScope = "standalone_scan"; $0.scanPurpose = flow.rawValue; $0.intent = String(name.prefix(240)) }
            guard let directory = model.scanDirectory else { return }
            guard let project=model.projectDirectory else{return}
            try identifier.save(project:project,capture:directory)
            if let frame=capture.session.currentFrame {
                let rect=CGRect(x:box.minX*viewport.width,y:box.minY*viewport.height,width:box.width*viewport.width,height:box.height*viewport.height)
                let raw=CaptureFraming.rawRegion(rect:rect,viewport:viewport,displayTransform:frame.displayTransform(for:orientation,viewportSize:viewport))
                capture.selectObject(normalizedRawImagePoint:CGPoint(x:raw.midX,y:raw.midY))
            }
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
