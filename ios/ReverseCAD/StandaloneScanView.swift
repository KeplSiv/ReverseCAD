import SwiftUI
import ARKit
import ReverseCADCore

struct StandaloneScanView: View {
    var flow: ObjectFlow = .scan
    var cameraFirst = false
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel
    @StateObject private var workflow = CapturedObjectWorkflow()
    @State private var selectedFlow: ObjectFlow = .scan
    @State private var cameraHomeActive = true
    @State private var detailMode = false
    @State private var cameraControlsBusy = false
    @State private var library = false
    @State private var help = false
    private var activeFlow: ObjectFlow { cameraFirst ? selectedFlow : flow }
    private var showsCameraHome: Bool { cameraFirst && cameraHomeActive }
    @State private var description = ""
    @State private var camera = false
    @State private var settings = false
    @State private var repairPresented = false
    @State private var repairStartedFor: String?
    @State private var automaticBuildAttempt: String?
    @State private var cancelledProcessing: String?
    private var processingIdentity: String? {
        guard let project = model.project, let scan = project.scanID else { return nil }
        return project.id + ":" + scan
    }
    var body: some View {
        NavigationStack {
            Group {
                if showsCameraHome { cameraHome }
                else { ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let project = model.project {
                        Text(project.name).font(.largeTitle.bold())
                        if activeFlow == .repair, project.repairScope != "standalone_scan" {
                            Button("Review repair") { repairPresented=true }.buttonStyle(RepairButtonStyle())
                        }
                        if model.busy || workflow.working {
                            VStack(spacing: 16) {
                                ProgressView().controlSize(.large).tint(RepairStyle.accent)
                                Text(workflow.phase == "finding" ? "Finding your object…" : "Building your 3D model…").font(.title2.bold())
                                Text(workflow.working ? workflow.message : model.progress)
                                    .font(.subheadline).foregroundStyle(RepairStyle.secondary).multilineTextAlignment(.center)
                                Button("Cancel") { cancelProcessing() }
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
                                Button("Save or share " + format) { model.exportStandaloneScan(format: format) }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy || workflow.working)
                            }
                            if !model.standaloneExportFormats.contains("STEP") { Text("STEP is unavailable for this reconstruction. The supported exports appear above.").font(.caption).foregroundStyle(RepairStyle.secondary) }
                            Text("STEP, when available, is a faceted observed surface. Dimensions are estimates, not independently validated measurements.").font(.caption).foregroundStyle(RepairStyle.secondary)
                        } else if workflow.phase == "ambiguous", let image = workflow.referenceImage {
                            Text("Identify object").font(.title2.bold())
                            Text(workflow.message)
                            CapturedTargetImage(image: image) { point in identify(point: point) }.frame(height: 370)
                        } else if workflow.phase == "identified" {
                            Text(model.projectDirectory.flatMap { TwoPassScan.load($0) }?.stage == "identification_captured" ? "First pass identified" : "Build 3D model").font(.title2.bold())
                            Text("Identified: \(workflow.identity?.category.replacingOccurrences(of: "_", with: " ") ?? "object")")
                        } else if !workflow.working {
                            Text(workflow.message.isEmpty ? "Your scan is saved on this phone." : workflow.message)
                            Button("Find object in saved scan") { identify() }.buttonStyle(RepairButtonStyle())
                        }
                        if workflow.identity?.confirmedIndices.isEmpty == false && !workflow.working {
                            Text("Your phone builds the model from the captured geometry. The original camera records stay inside ReverseCAD.").font(.subheadline).foregroundStyle(RepairStyle.secondary)
                            if let project=model.projectDirectory, TwoPassScan.load(project)?.stage == "identification_captured" {
                                Text("First pass identified. Keep the same object still, then make the second 360° pass.").font(.subheadline)
                                Button("Start second 360° pass") { detailMode=true;cameraHomeActive=true }.buttonStyle(RepairButtonStyle()).disabled(model.busy)
                            } else {
                                Button(model.scanMesh == nil ? "Build 3D model" : "Rebuild from saved scan") { build() }.buttonStyle(RepairButtonStyle()).disabled(model.busy)
                            }
                            if model.standaloneExportFormats.isEmpty {
                                Button("Choose a different object") { workflow.phase = "ambiguous"; workflow.message = "Tap the intended object in the saved image." }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy)
                            }
                        }
                        if !model.warnings.isEmpty { DisclosureGroup("Capture quality and missing views") { ForEach(model.warnings, id: \.self) { Text($0).font(.caption) } } }
                        Button("Back to scans") { workflow.cancel(); detailMode=false; cameraHomeActive = true; model.selectedID = nil }.buttonStyle(RepairButtonStyle(secondary: true)).disabled(model.busy)
                    } else {
                        Text(activeFlow.title).font(.largeTitle.bold())
                        Text("Adjust the box around one object.").font(.title3)
                        TextField("Description (optional)", text: $description, axis: .vertical).textFieldStyle(.plain).lineLimit(1...3)
                            .padding(16).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 18))
                            .accessibilityIdentifier("scanObjectDescription")
                        Button { camera = true } label: { Label("Open camera", systemImage: "camera").frame(maxWidth: .infinity) }.buttonStyle(RepairButtonStyle()).controlSize(.large).accessibilityIdentifier("findScanObject")
                        Text(activeFlow == .scan ? "Adjust box → First pass → Identify → Detail pass → Preview and export" : "Adjust box → First pass → Identify → Detail pass → Find damage → Review CAD").font(.caption).foregroundStyle(RepairStyle.secondary)
                        if !model.projects.filter({ activeFlow.includes($0) }).isEmpty { Text("Saved scans").font(.title2.bold()) }
                        ForEach(model.projects.filter { activeFlow.includes($0) }) { project in
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
            } }
            }.background(RepairStyle.background.ignoresSafeArea())
                .navigationTitle("ReverseCAD").navigationBarTitleDisplayMode(.inline)
                .toolbarBackground(RepairStyle.background, for: .navigationBar)
                .toolbarBackground(.visible, for: .navigationBar)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        if showsCameraHome {
                            Button { help = true } label: { Image(systemName: "questionmark.circle").frame(width: 44, height: 44) }
                                .accessibilityLabel("Scanning tips").disabled(model.captureActive)
                        } else {
                            Button("Home") { workflow.cancel(); detailMode=false; cameraHomeActive=true; model.selectedID=nil; if !cameraFirst { dismiss() } }
                                .disabled(model.busy || model.captureActive)
                        }
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { settings = true } label: { Image(systemName: "info.circle").frame(width: 44, height: 44) }
                            .accessibilityLabel("About ReverseCAD").disabled(model.busy || model.captureActive || workflow.working)
                    }
                    ToolbarItemGroup(placement: .keyboard) {
                        Spacer(); Button("Done") { UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil) }
                    }
                }
                .sheet(isPresented: $settings) { SettingsView() }
                .sheet(isPresented: $library) { savedScans }
                .sheet(isPresented: $help) { scanHelp }
                .fullScreenCover(isPresented: $camera, onDismiss: { resumeSaved() }) { StandaloneCameraView(objectDescription: description, flow: activeFlow) }
                .fullScreenCover(isPresented: $repairPresented) { UnifiedRepairView(savedScanMode: true) }
                .onChange(of: model.busy) { _, busy in if !busy { continueToRepairIfReady() } }
                .onChange(of: workflow.phase) { _, phase in
                    if phase == "identified" { buildAutomaticallyIfReady() }
                }
                .sheet(isPresented: $model.showingShare) { ShareSheet(urls: model.shareURLs) }
                .task(id: model.selectedID) { if !camera && !showsCameraHome { resumeSaved() } }
                .alert("Needs attention", isPresented: Binding(get: { model.error != nil && !camera && !settings }, set: { if !$0 { model.error = nil } })) { Button("OK") { model.error = nil } } message: { Text(model.error ?? "") }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent)
    }
    private var cameraHome: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                ObjectFlowPicker(selection: $selectedFlow).disabled(model.captureActive || cameraControlsBusy)
                TextField("Description (optional)", text: $description)
                    .font(.subheadline).textFieldStyle(.plain).padding(.horizontal, 14).padding(.vertical, 10)
                    .background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 13))
                    .accessibilityIdentifier("scanObjectDescription").disabled(model.captureActive || cameraControlsBusy)
            }.padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 12)
            StandaloneCameraView(objectDescription: description, flow: activeFlow, embedded: true, detailPass: detailMode,
                                 onLibrary: { library = true }, onComplete: { cameraHomeActive = false; resumeSaved() },
                                 onBusyChanged: { cameraControlsBusy = $0 })
                .id(selectedFlow.rawValue + (detailMode ? "detail" : "identify"))
        }
    }
    private var savedScans: some View {
        NavigationStack {
            List {
                if model.projects.filter({ activeFlow.includes($0) }).isEmpty {
                    Text("Your saved scans will appear here.").foregroundStyle(RepairStyle.secondary)
                }
                ForEach(model.projects.filter { activeFlow.includes($0) }) { project in
                    Button {
                        cameraHomeActive = false; model.select(project); library = false
                    } label: {
                        HStack(spacing: 14) {
                            ProjectThumbnail(directory: model.directory(project.id).appendingPathComponent("scan/rgb"), family: project.family)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(project.name).font(.headline).foregroundStyle(RepairStyle.text)
                                Text(project.created.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(RepairStyle.secondary)
                            }
                            Spacer(); Image(systemName: "chevron.right").font(.caption)
                        }.padding(.vertical, 6)
                    }.disabled(model.busy).listRowBackground(RepairStyle.surface).accessibilityIdentifier("savedScan_\(project.id)")
                }
            }.scrollContentBackground(.hidden).background(RepairStyle.background)
                .navigationTitle("Saved scans").toolbar { ToolbarItem(placement: .topBarLeading) { Button("Done") { library = false } } }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent)
    }
    private var scanHelp: some View {
        NavigationStack {
            List {
                Label("Adjust the box around one object, then make the first 360° pass. Jev identifies it afterward.", systemImage: "viewfinder")
                Label("Keep the object still. Walk slowly around it and keep it inside the box.", systemImage: "move.3d")
                Label("After identification, make a second pass. The small live preview shows only observed object depth; both passes stay saved.", systemImage: "checkmark.circle")
                Text(activeFlow == .scan ? "Preview and save the captured shape. Holes and unseen surfaces remain open." : "After scanning, review a proposed repair for a flat rectangular part. Other shapes remain available as scanned geometry.")
                Text("Both flows build on this phone. Internet is needed for Jev identification. Save or share finished models and CAD files; the original camera records remain inside the app.").font(.footnote)
            }.navigationTitle("A better scan").toolbar { ToolbarItem(placement: .topBarLeading) { Button("Done") { help = false } } }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent)
    }
    private func resumeSaved() {
        guard let project = model.projectDirectory, let capture = model.scanDirectory else { return }
        if var state=TwoPassScan.load(project),state.stage=="detail_capturing" {
            if let frames=try? CaptureIO.readFrames(directory:capture),!frames.isEmpty {
                let projectID = model.project?.id
                Task {
                    do {
                        _=try await Task.detached {try ScanPackageWriter.recover(directory:capture).finish(complete:false)}.value
                        state.stage="detail_captured";try state.save(project)
                        guard model.project?.id == projectID else { return }
                        model.didCapture(capture);workflow.load(project:project,capture:capture);identify()
                    } catch {
                        if model.project?.id == projectID { model.error=error.localizedDescription }
                    }
                }
            } else {detailMode=true;cameraHomeActive=true}
            return
        }
        guard model.project?.scanID != nil else{return}
        workflow.load(project: project, capture: capture)
        if activeFlow == .repair, model.project?.repairScope != "standalone_scan" { repairPresented=true;return }
        if workflow.identity == nil { identify() }
        else { buildAutomaticallyIfReady(); continueToRepairIfReady() }
    }
    private func cancelProcessing() {
        cancelledProcessing = processingIdentity
        automaticBuildAttempt = processingIdentity
        workflow.cancel()
        if model.busy { model.cancel() }
    }
    private func buildAutomaticallyIfReady() {
        guard let token = processingIdentity, token != automaticBuildAttempt, token != cancelledProcessing,
              !model.busy, workflow.failure == nil, workflow.phase == "identified",
              workflow.identity?.confirmedIndices.isEmpty == false, model.project?.scanTarget == nil,
              let project = model.projectDirectory, TwoPassScan.load(project)?.stage == "detail_captured" else { return }
        automaticBuildAttempt = token
        build(userInitiated: false)
    }
    private func continueToRepairIfReady() {
        guard activeFlow == .repair, !model.busy, model.error == nil, processingIdentity != cancelledProcessing,
              model.project?.repairScope == "standalone_scan",
              !model.standaloneExportFormats.isEmpty, let id=model.project?.scanID, repairStartedFor != id else{return}
        repairStartedFor=id;repairPresented=true;model.analyzeCapturedDamage()
    }
    private func identify(point: CGPoint? = nil) {
        cancelledProcessing = nil
        automaticBuildAttempt = nil
        guard let project = model.projectDirectory, let capture = model.scanDirectory else { return }
        workflow.find(project: project, capture: capture, description: model.project?.intent ?? description, point: point)
    }
    private func build(userInitiated: Bool = true) {
        guard let project = model.projectDirectory, let capture = model.scanDirectory, !model.busy else { return }
        if userInitiated { cancelledProcessing = nil; automaticBuildAttempt = processingIdentity }
        workflow.build(project: project, capture: capture) { target in
            guard model.projectDirectory == project, model.scanDirectory == capture else { return }
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
    @StateObject private var capture = CaptureController(useMultiCamera: true)
    let objectDescription: String
    var flow: ObjectFlow = .scan
    var embedded = false
    var detailPass = false
    @AppStorage("reversecad.referenceArchive.v1") private var referenceArchive = ""
    @State private var referenceSetup = false
    @State private var referenceOpening = false
    @State private var referenceOpeningID: UUID?
    @State private var cameraVisible = false
    @State private var phoneSetup: PhoneSetupRecord?
    @State private var setupLoaded = false
    var onLibrary: (() -> Void)? = nil
    var onComplete: (() -> Void)? = nil
    var onBusyChanged: ((Bool) -> Void)? = nil
    @StateObject private var identifier = BoxObjectIdentifier()
    @State private var box = SelectionBox.initial
    @State private var viewport = CGSize.zero
    @State private var orientation = UIInterfaceOrientation.portrait
    @State private var pending = false
    @State private var failure: String?
    @State private var delivered = false
    var body: some View {
        Group {
            if embedded { cameraContent }
            else { NavigationStack { cameraContent } }
        }.preferredColorScheme(.dark).tint(RepairStyle.accent)
            .cameraCaptureButton(enabled:!referenceSetup && !referenceOpening && !pending && !identifier.running && capture.cameraReady && phoneSetup != nil) {
                Task {if capture.isCapturing {await finish()} else {await begin()}}
            }
            .interactiveDismissDisabled(capture.isCapturing || pending)
            .sheet(isPresented:$referenceSetup,onDismiss:{ Task { await refreshSetupAndPreview() } }) { PhoneReferenceSetup() }
            .onAppear {
                if detailPass,let project=model.projectDirectory,let saved=TwoPassScan.load(project)?.displayBox,saved.count==4,saved.allSatisfy(\.isFinite) {
                    let previous=CGRect(x:saved[0],y:saved[1],width:saved[2],height:saved[3]).intersection(CGRect(x:0,y:0,width:1,height:1))
                    if !previous.isNull,previous.width>=0.08,previous.height>=0.08 {box=previous}
                }
            }
    }
    private var cameraContent: some View {
            VStack(spacing: 0) {
                ZStack {
                    Group {
                    if let layer=capture.multiCameraPreview {
                        MultiCameraPreview(layer:layer) { size,value in
                            if viewport != size {viewport=size}
                            if orientation != value {orientation=value}
                            capture.updateGuide(rect:CGRect(x:box.minX*size.width,y:box.minY*size.height,width:box.width*size.width,height:box.height*size.height),viewport:size,orientation:value)
                        }
                    } else {
                        RepairStyle.background.overlay {ProgressView("Opening camera…").tint(RepairStyle.accent)}
                    }
                    }
                    AdjustableObjectBox(box:$box,editable:!capture.isCapturing && !identifier.running)
                }.frame(maxWidth: .infinity, maxHeight: .infinity).clipped()
                    .overlay(alignment: .top) {
                        VStack(spacing: 8) {
                            Text(capture.isCapturing ? "SCANNING" : (identifier.running ? "IDENTIFYING" : "FRAME YOUR OBJECT"))
                                .font(.caption2.weight(.semibold)).tracking(2)
                                .padding(.horizontal, 16).padding(.vertical, 10)
                                .background(RepairStyle.background.opacity(0.9), in: Capsule())
                            if setupLoaded && phoneSetup == nil {
                                Text("Set up the selfie camera before your first scan.")
                                    .font(.subheadline.weight(.medium)).multilineTextAlignment(.center)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .padding(.horizontal, 14).padding(.vertical, 10)
                                    .background(RepairStyle.background.opacity(0.95), in: RoundedRectangle(cornerRadius: 12))
                                    .accessibilityIdentifier("selfieSetupHint")
                            }
                        }.padding(.horizontal, 16).padding(.top, 16).allowsHitTesting(false)
                    }
                    .overlay(alignment:.topTrailing) {
                        if detailPass {
                            VStack(spacing:4) {
                                if let mesh=capture.liveSurfaceMesh {
                                    GeometryPreview(scan:mesh,part:nil,showPart:false,backgroundColor:.clear)
                                        .frame(width:140,height:140).opacity(0.65).allowsHitTesting(false)
                                    Text("\(mesh.vertices.count) observed points").font(.caption2)
                                } else { Text("Waiting for object depth…").font(.caption).frame(width:140,height:100) }
                                Text("Live observed surface").font(.caption2)
                            }.padding(8).background(RepairStyle.background.opacity(0.7),in:RoundedRectangle(cornerRadius:16)).padding(12)
                                .accessibilityIdentifier("liveObjectPreview")
                        }
                    }
                    .onChange(of:box) { _, _ in identifier.cancel(clear:true) }
                VStack(spacing: 14) {
                    Text(capture.isCapturing ? "Keep the object still. Walk slowly around it, keeping it inside the box." : "Place one object inside the box.")
                        .font(.subheadline).multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("scanGuidance")
                    if let failure { Text(failure).font(.footnote).foregroundStyle(.orange) }
                    if let failure=identifier.failure { Text(failure).font(.footnote).foregroundStyle(.orange) }
                    if capture.isCapturing {
                        Text(capture.guidance).font(.subheadline).multilineTextAlignment(.center).foregroundStyle(RepairStyle.secondary)
                        cameraControls { cameraAction(detailPass ? "Finish detail pass" : "Finish first pass", icon: "checkmark", accessibilityID: "finishObjectScan") { Task { await finish() } } }
                        Text("\(capture.frameCount) accepted views · \(capture.coverageViews) observed directions")
                            .font(.caption).foregroundStyle(RepairStyle.secondary)
                    } else if phoneSetup == nil {
                        cameraControls { cameraAction("Set up this phone",icon:"camera",accessibilityID:"setupPhone") { openReference() } }
                        Text("For your first object, capture its selfie-camera and infrared depth reference. Jev checks the scene before you turn the phone for the rear scan.").font(.caption).foregroundStyle(RepairStyle.secondary)
                    } else {
                        cameraControls { cameraAction(detailPass ? "Start second 360° pass" : "Start first 360° pass", icon:"viewfinder",accessibilityID:"startObjectScan") { Task { await begin() } }.disabled(!capture.cameraReady) }
                        Text(detailPass ? "Use the same object and starting view. Your phone builds the live preview and final model." : "Drag the box around one object. Jev identifies it automatically after this first pass.")
                            .font(.caption).foregroundStyle(RepairStyle.secondary).multilineTextAlignment(.center)
                        if !detailPass {Button("Update phone setup") {openReference()}.font(.caption).disabled(pending)}
                    }
                }.padding(.horizontal, 24).padding(.vertical, 20).background(RepairStyle.background)
            }.foregroundStyle(RepairStyle.text)
                .background(RepairStyle.background.ignoresSafeArea())
                .navigationTitle(embedded ? "ReverseCAD" : (capture.isCapturing ? "Scan around it" : "Frame object")).navigationBarTitleDisplayMode(.inline)
                .toolbarBackground(RepairStyle.background, for: .navigationBar)
                .toolbarBackground(.visible, for: .navigationBar)
                .toolbar {
                    if !embedded { ToolbarItem(placement: .topBarLeading) { Button(capture.isCapturing ? "Save & close" : "Close") { Task { if capture.isCapturing { await finish() } else { identifier.cancel();dismiss() } } }.disabled(pending) } }
                }
                .task {
                    guard !Task.isCancelled else { return }
                    cameraVisible = true
                    await refreshSetupAndPreview()
                }
                .onChange(of: capture.savedRevision) { _, _ in deliver() }
                .onChange(of: identifier.running) { _, running in onBusyChanged?(running || pending) }
                .onDisappear {
                    cameraVisible = false; referenceOpening = false; referenceOpeningID = nil
                    identifier.cancel(); capture.pausePreview(); onBusyChanged?(false)
                }
    }
    private func cameraControls<Primary: View>(@ViewBuilder primary: () -> Primary) -> some View {
        HStack {
            if let onLibrary {
                Button(action: onLibrary) { Image(systemName: "square.stack").font(.title3.weight(.medium)).frame(width: 52, height: 52).background(RepairStyle.surface, in: Circle()) }
                    .accessibilityLabel("Saved scans").accessibilityIdentifier("openSavedScans").disabled(capture.isCapturing || pending)
            }
            Spacer(minLength: 0)
            primary()
            Spacer(minLength: 0)
            Button { Task { await resetCamera() } } label: {
                Image(systemName: "arrow.counterclockwise").font(.title3.weight(.medium)).frame(width: 52, height: 52).background(RepairStyle.surface, in: Circle())
            }.accessibilityLabel("Reset camera").accessibilityIdentifier("resetCapture").disabled(pending)
        }
    }
    private func resetCamera() async {
        if capture.isCapturing { await finish(); return }
        identifier.cancel(clear: true); box = SelectionBox.initial; failure = nil
        await startCameraPreview()
    }
    private func openReference() {
        guard cameraVisible, !referenceOpening, !referenceSetup else { return }
        let requestID = UUID()
        referenceOpening = true; referenceOpeningID = requestID
        capture.pausePreview {
            guard cameraVisible, referenceOpeningID == requestID else { return }
            referenceSetup = true
            referenceOpening = false; referenceOpeningID = nil
        }
    }
    private func refreshSetupAndPreview() async {
        let device=PhoneSetupStore.deviceIdentity
        phoneSetup=await Task.detached {PhoneSetupStore.load(deviceIdentity:device)}.value
        guard !Task.isCancelled else{return}
        setupLoaded=true
        await startCameraPreview()
    }
    private func startCameraPreview() async {
        guard cameraVisible, !referenceOpening, !referenceSetup, !Task.isCancelled else { return }
        do {try await capture.startPreview();failure=nil}
        catch is CancellationError {}
        catch {failure=error.localizedDescription}
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
        guard viewport.width>0,viewport.height>0 else {failure="Wait for the camera to be ready.";return}
        do {
            let rect=CGRect(x:box.minX*viewport.width,y:box.minY*viewport.height,width:box.width*viewport.width,height:box.height*viewport.height)
            let selection=try capture.selectionImage(rect:rect,viewport:viewport,orientation:orientation)
            failure=nil;identifier.identify(jpeg:selection.jpeg,rawBox:selection.box,description:objectDescription)
        } catch {failure=error.localizedDescription}
    }
    private func begin() async {
        guard !pending, !capture.isCapturing, phoneSetup != nil else { return }
        pending = true; onBusyChanged?(true); defer { pending = false; onBusyChanged?(false) }
        do {
            let device=PhoneSetupStore.deviceIdentity
            guard let setup=await Task.detached(operation:{PhoneSetupStore.load(deviceIdentity:device)}).value else {
                phoneSetup=nil;throw ServiceFailure(message:"The saved phone setup changed. Set up this phone again.")
            }
            let name = objectDescription.trimmingCharacters(in: .whitespacesAndNewlines)
            if !detailPass {
                model.create(name:name.isEmpty ? "Object scan" : String(name.prefix(80)),synthetic:false)
                model.update { $0.repairScope="standalone_scan";$0.scanPurpose=flow.rawValue;$0.intent=String(name.prefix(240)) }
            }
            guard let directory=model.scanDirectory,let project=model.projectDirectory else { throw ServiceFailure(message:"Wait for a clear camera image.") }
            let rect=CGRect(x:box.minX*viewport.width,y:box.minY*viewport.height,width:box.width*viewport.width,height:box.height*viewport.height)
            let selection=try capture.selectionImage(rect:rect,viewport:viewport,orientation:orientation)
            let raw=selection.box
            if detailPass {
                try await Task.detached {try TwoPassScan.prepareDetail(project:project,capture:directory)}.value
                model.update { $0.scanID=nil;$0.scanTarget=nil }
                capture.setConfirmedTarget(raw)
            } else {
                let jpeg=selection.jpeg
                let reference=ObjectSelectionReference(imageSHA256:CaptureIO.sha256(jpeg),rawBox:[raw.minX,raw.minY,raw.width,raw.height],detection:nil)
                let image=try CaptureIO.safeURL(directory:directory,path:reference.imagePath)
                try FileManager.default.createDirectory(at:image.deletingLastPathComponent(),withIntermediateDirectories:true)
                try jpeg.write(to:image,options:.atomic)
                try CaptureIO.atomicWrite(reference,to:project.appendingPathComponent("object-selection.json"))
            }
            capture.selectObject(normalizedRawImagePoint:CGPoint(x:raw.midX,y:raw.midY))
            let profileURL=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("PhoneCalibrationProfiles/current.json")
            if let profile=try? Data(contentsOf:profileURL) { try profile.write(to:directory.appendingPathComponent("phone-reference-profile.json"),options:.atomic) }
            try CaptureHardware.preserveReference(setup.archive,in:directory)
            try PhoneSetupStore.attach(to:directory)
            let provenance: [String:Any] = ["schema_version":1,"pass":detailPass ? "detail" : "identification","prior_pass_path":detailPass ? "identification-pass" : "","cross_pass_geometry_registered":false,"prior_information":"selected reference image, object identity and measured front reference; cross-pass geometry requires registration"]
            try JSONSerialization.data(withJSONObject:provenance,options:[.sortedKeys]).write(to:directory.appendingPathComponent("pass-provenance.json"),options:.atomic)
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
        delivered = true; model.captureActive = false
        if let project=model.projectDirectory,let manifest=try? ScanPackageWriter.validate(directory:url) {
            let record=TwoPassScan(stage:detailPass ? "detail_captured" : "identification_captured",firstScanID:TwoPassScan.load(project)?.firstScanID ?? manifest.scanID,displayBox:detailPass ? TwoPassScan.load(project)?.displayBox : [box.minX,box.minY,box.width,box.height])
            try? record.save(project)
        }
        model.didCapture(url)
        if let onComplete { onComplete() } else { dismiss() }
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
