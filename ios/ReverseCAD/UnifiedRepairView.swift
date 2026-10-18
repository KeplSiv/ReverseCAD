import SwiftUI
import UIKit

/// Palette supplied by the user. Semantic roles keep contrast consistent.
enum RepairStyle {
    static let background = Color(red: 26/255, green: 20/255, blue: 35/255)
    static let surface = Color(red: 61/255, green: 49/255, blue: 74/255)
    static let selected = Color(red: 104/255, green: 71/255, blue: 86/255)
    static let copper = Color(red: 150/255, green: 112/255, blue: 91/255)
    static let accent = Color(red: 171/255, green: 132/255, blue: 118/255)
    static let text = Color.white
    static let secondary = Color.white.opacity(0.72)
}

struct RepairButtonStyle: ButtonStyle {
    var secondary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body.weight(.semibold))
            .frame(maxWidth: .infinity).padding(.horizontal, 18).padding(.vertical, 16)
            .foregroundStyle(secondary ? RepairStyle.text : RepairStyle.background)
            .background(secondary ? RepairStyle.surface : RepairStyle.accent, in: RoundedRectangle(cornerRadius: 18))
            .opacity(enabled ? (configuration.isPressed ? 0.75 : 1) : 0.45)
    }
}

struct UnifiedRepairView: View {
    var savedScanMode = false
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel
    @State private var result = false
    @State private var repairWorkflow = false
    @State private var library = false
    @State private var cameraGeneration = 0
    @State private var help = false
    @State private var display = "Repair"
    @State private var reviewed = false
    @State private var thickness = ""
    private var isFlat: Bool { model.planarRepair != nil }
    private var report: [String: Any]? { model.planarRepair ?? model.faceRepair }
    private var count: Int { report?["piece_count"] as? Int ?? (model.counterpartMesh == nil ? 0 : 1) }
    private var thicknessMM: Double? { Double(thickness.replacingOccurrences(of: ",", with: ".")) }
    private var hasResult: Bool { report != nil }
    private var needsChoice: Bool { model.automaticRoute?["needs_choice"] as? Bool == true }

    var body: some View {
        NavigationStack {
            Group {
                if result || savedScanMode { resultScreen }
                else {
                    RepairCamera(onFinish: { url in
                        model.didCapture(url); reviewed = false; display = "Repair"; thickness = ""; result = true
                        model.reconstructAutomatically()
                    }, onReset: { cameraGeneration += 1 }, onLibrary: { library = true }).id(cameraGeneration)
                }
            }
            .background(RepairStyle.background.ignoresSafeArea())
            .navigationTitle(result ? "Your repair" : "ReverseCAD")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(RepairStyle.background, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { help = true } label: { Image(systemName: "questionmark.circle").frame(width: 44, height: 44) }
                        .accessibilityLabel("Scanning tips")
                        .disabled(model.captureActive)
                }
                if result {
                    ToolbarItem(placement: .topBarTrailing) { cameraHomeButton }
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer(); Button("Done") { UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil) }
                }
            }
        }
        .preferredColorScheme(.dark).tint(RepairStyle.accent)
        .sheet(isPresented: $repairWorkflow) {
            if let project = model.project {
                NavigationStack { ProjectView(project: project).toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { repairWorkflow = false } }
                }}
            }
        }
        .sheet(isPresented: $library) { savedScans }
        .sheet(isPresented: $help) { scanHelp }
        .sheet(isPresented: $model.showingShare) { ShareSheet(urls: model.shareURLs) }
        .alert("Couldn’t finish this repair", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
        .onChange(of: model.counterpartMesh) { _, _ in reviewed = false }
        .onAppear {
            if savedScanMode { result = true }
            #if DEBUG
            if ProcessInfo.processInfo.environment["REVERSECAD_REPLAY_SCAN"] != nil { result = true }
            if ProcessInfo.processInfo.arguments.contains("-unifiedPreview") {
                if let project = model.projects.first { model.select(project); thickness = project.planarThicknessMM.map { String($0) } ?? "" }
                result = true
            }
            #endif
        }
    }

    private var resultScreen: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                if model.busy {
                    VStack(spacing: 20) {
                        ProgressView().controlSize(.large).tint(RepairStyle.accent)
                        Text("Finding what’s missing").font(.title2.bold())
                        Text(model.progress).font(.subheadline).foregroundStyle(RepairStyle.secondary).multilineTextAlignment(.center)
                        Button("Cancel") { model.cancel() }.buttonStyle(RepairButtonStyle(secondary: true))
                    }.frame(maxWidth: .infinity).padding(.vertical, 80)
                } else if let report = model.sparseReport {
                    Text("Review your scan").font(.title2.bold())
                    if let mesh = model.scanMesh, !mesh.vertices.isEmpty {
                        GeometryPreview(scan: mesh, part: nil).frame(height: 340)
                        Text("Rotate and zoom to check that the shape shows your object. Unseen surfaces remain unknown.")
                            .font(.subheadline).foregroundStyle(RepairStyle.secondary)
                    }
                    Text(report["reason"] as? String ?? "The observed shape is ready for repair planning. Dimensions and physical fit still need checking.")
                        .font(.subheadline)
                    ForEach(Array(model.warnings.enumerated()), id: \.offset) { _, warning in
                        Text(warning).font(.footnote).foregroundStyle(RepairStyle.secondary)
                    }
                    Toggle("The preview shows my object and relevant surfaces", isOn: $reviewed)
                        .disabled(report["status"] as? String != "ready")
                    Button("Continue to repair") { model.update { $0.repairScope = "general" }; repairWorkflow = true }
                        .buttonStyle(RepairButtonStyle()).disabled(report["status"] as? String != "ready" || !reviewed)
                    DisclosureGroup("Capture and measurement details") {
                        if report["capture_is_synthetic"] as? Bool == true { Text("Synthetic test fixture; not a device scan.") }
                        Text("Source: physical rear 1× images + sparse range observations. Camera motion is recovered from image correspondences.")
                        Text("\(report["view_count"] as? Int ?? 0) registered views · \(report["scale_support"] as? Int ?? 0) scale observations")
                        Text("Public processed depth and ARKit poses remain separately labeled diagnostics. Calibration accuracy is unverified.")
                        Button("Export original scan") { model.exportScan() }
                    }.font(.footnote)
                    Button("Take another scan") { result = false }.buttonStyle(RepairButtonStyle(secondary: true))
                } else if hasResult {
                    previewTabs
                    preview
                    VStack(alignment: .leading, spacing: 6) {
                        Text(count > 0 ? "\(count) proposed \(count == 1 ? "piece" : "pieces")" : "No missing region found")
                            .font(.title2.bold())
                        Text(isFlat ? "Assuming a flat rectangular part" : "Assuming a repeating 3×3 cube")
                            .font(.subheadline).foregroundStyle(RepairStyle.secondary)
                    }
                    if count > 0 {
                        Text(model.counterpartPrintable ? "Check each highlighted piece. Fit is untested." : "Review the highlighted outline before making a solid.")
                            .font(.subheadline).foregroundStyle(RepairStyle.secondary)
                        Toggle("The repair matches the missing area", isOn: $reviewed)
                            .font(.subheadline).tint(RepairStyle.copper)
                        if isFlat { thicknessInput }
                        if isFlat && (!model.counterpartPrintable || thicknessMM != model.project?.planarThicknessMM) {
                            Button { model.reconstructRectangle(thickness: thicknessMM); display = "Pieces" } label: {
                                Label("Create printable piece", systemImage: "cube")
                            }.buttonStyle(RepairButtonStyle())
                                .disabled(!reviewed || thicknessMM == nil || (thicknessMM ?? 0) <= 0 || (thicknessMM ?? 0) > 100)
                        } else {
                            Button { if isFlat { model.exportPlanar() } else { model.exportObservedSurface(printableOnly: true) } } label: {
                                Label(count > 1 ? "Export \(count) pieces" : "Export piece", systemImage: "square.and.arrow.up")
                            }.buttonStyle(RepairButtonStyle()).disabled(!reviewed || !model.counterpartPrintable)
                        }
                    }
                    DisclosureGroup("Details") {
                        VStack(alignment: .leading, spacing: 12) {
                            if let route = model.automaticRoute, let reason = route["reason"] as? String { Text(reason) }
                            if !model.repairMessage.isEmpty { Text(model.repairMessage) }
                            if !isFlat {
                                Text(model.faceRepair?["reference_prototype"] != nil
                                     ? "Connector and recess dimensions are estimated from reference photos. The ghost shows the front outline; the 3D piece includes inferred surfaces."
                                     : "The ghost shows the front outline. Side depth and hidden surfaces are inferred; internal connectors are unresolved.")
                            }
                            Text("Check dimensions and fit before using a printed replacement.")
                            ForEach(Array(model.warnings.enumerated()), id: \.offset) { _, text in Text(text) }
                            Button("Analyze again", systemImage: "arrow.clockwise") {
                                reviewed = false; model.reconstructAutomatically()
                            }.buttonStyle(RepairButtonStyle(secondary: true))
                            Menu("Correct detected shape") {
                                Button("Flat rectangular part") { reviewed = false; model.reconstructRectangle(thickness: thicknessMM) }
                                Button("3×3 cube") { reviewed = false; model.reconstructCubeExterior() }
                            }.foregroundStyle(RepairStyle.accent)

                        }.font(.footnote).foregroundStyle(RepairStyle.secondary).padding(.top, 12)
                    }.tint(RepairStyle.text).padding(16).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 18))
                } else {
                    Image(systemName: needsChoice ? "square.on.circle" : "viewfinder")
                        .font(.system(size: 42, weight: .light)).foregroundStyle(RepairStyle.accent).padding(.top, 36)
                    Text(needsChoice ? "Which shape are we repairing?" : "Let’s take another look").font(.title2.bold())
                    Text(needsChoice ? "The scan is saved. Choose the closest shape so we can continue." : (model.repairMessage.isEmpty ? "Your scan is saved and ready to analyze." : model.repairMessage))
                        .foregroundStyle(RepairStyle.secondary)
                    if needsChoice {
                        Button("Flat rectangular part") { model.reconstructRectangle() }.buttonStyle(RepairButtonStyle())
                        Button("3×3 cube") { model.reconstructCubeExterior() }.buttonStyle(RepairButtonStyle(secondary: true))
                    } else {
                        Button("Analyze saved scan") { model.reconstructAutomatically() }.buttonStyle(RepairButtonStyle())
                    }
                    Button("Back to object scan") { if savedScanMode { dismiss() } else { result = false } }.buttonStyle(RepairButtonStyle(secondary: true))
                }
            }.padding(20).foregroundStyle(RepairStyle.text)
        }
    }

    private var previewTabs: some View {
        HStack(spacing: 4) {
            ForEach(model.counterpartMesh == nil ? ["Original", "Repair"] : ["Original", "Repair", "Pieces"], id: \.self) { tab in
                Button { display = tab } label: {
                    Text(tab).font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).padding(.vertical, 13)
                        .background(display == tab ? RepairStyle.selected : Color.clear, in: RoundedRectangle(cornerRadius: 13))
                }.buttonStyle(.plain).accessibilityAddTraits(display == tab ? [.isSelected] : [])
            }
        }.padding(4).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 17))
    }

    @ViewBuilder private var preview: some View {
        if display == "Pieces", let mesh = model.counterpartMesh {
            GeometryPreview(scan: nil, part: mesh, backgroundColor: UIColor(RepairStyle.surface), selectionMode: "none").frame(height: 360)
                .clipShape(RoundedRectangle(cornerRadius: 22))
                .accessibilityLabel("Proposed pieces. Drag to rotate and pinch to zoom.")
            Text("Drag to rotate · Pinch to zoom").font(.caption).foregroundStyle(RepairStyle.secondary)
        } else if let url = isFlat ? model.planarImageURL(ghost: display != "Original") : model.cubeImageURL(ghost: display != "Original"),
                  let image = UIImage(contentsOfFile: url.path) {
            Image(uiImage: image).resizable().scaledToFit().frame(maxWidth: .infinity)
                .clipShape(RoundedRectangle(cornerRadius: 22))
                .accessibilityLabel(display == "Original" ? "Original capture" : "Proposed repair over the original capture")
        }
    }

    private var thicknessInput: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Part thickness").font(.subheadline.weight(.medium))
                Spacer()
                TextField("0.0", text: $thickness).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                    .frame(width: 72).accessibilityLabel("Measured thickness in millimeters")
                Text("mm").foregroundStyle(RepairStyle.secondary)
            }
            Text("Measure the sheet or board; phone depth cannot resolve thin material reliably.")
                .font(.caption).foregroundStyle(RepairStyle.secondary)
        }.padding(16).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 18))
    }

    private var cameraHomeButton: some View {
        Button {
            if savedScanMode { dismiss(); return }
            library = false; help = false; result = false
        } label: {
            Image(systemName: "camera").frame(width: 44, height: 44)
        }
        .accessibilityLabel("Back to camera")
        .accessibilityIdentifier("backToCamera")
        .disabled(model.busy)
    }

    private var savedScans: some View {
        NavigationStack {
            List {
                if model.projects.isEmpty { Text("Your saved scans will appear here.").foregroundStyle(.secondary) }
                ForEach(model.projects) { project in
                    Button {
                        model.select(project); reviewed = false; display = "Repair"
                        thickness = project.planarThicknessMM.map { String($0) } ?? ""
                        result = true; library = false
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
                .navigationTitle("Saved scans").toolbar {
                    ToolbarItem(placement: .topBarLeading) { Button("Done") { library = false } }
                    ToolbarItem(placement: .topBarTrailing) { cameraHomeButton }
                }
        }.tint(RepairStyle.accent)
    }

    private var scanHelp: some View {
        NavigationStack {
            List {
                Label("Keep the whole object inside the box, with space around its edges.", systemImage: "viewfinder")
                #if SPARSE_RESEARCH
                Label("Keep the object still. Move sideways slowly to show the front and another side, keeping nearby views overlapping.", systemImage: "move.3d")
                Label("Use diffuse light and a matte, textured object. The scan saves after about 18 seconds.", systemImage: "camera")
                Text("Review the observed shape before continuing to a repair. Unseen surfaces and hidden dimensions remain unknown.").font(.footnote)
                #else
                Label("Start with a sharp front view. For a flat part, point the camera straight down.", systemImage: "camera")
                Label("Keep the object still. Move the phone slowly to show depth and matching intact features.", systemImage: "move.3d")
                Label("Tap Finish when the damaged area and intact features are clear. Flat parts only need a short, steady capture.", systemImage: "checkmark.circle")
                Text("Automatic selection currently supports flat rectangular parts and damaged 3×3 cubes. Always review the inferred shape and every proposed piece.").font(.footnote)
                #endif
            }.navigationTitle("A better scan").toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Done") { help = false } }
                ToolbarItem(placement: .topBarTrailing) { cameraHomeButton }
            }
        }.tint(RepairStyle.accent)
    }
}

private struct RepairCamera: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var camera = CaptureController()
    let onFinish: (URL) -> Void
    let onReset: () -> Void
    let onLibrary: () -> Void
    @State private var transition = false
    @State private var delivered = false
    @State private var failure: String?
    var body: some View {
        VStack(spacing: 0) {
            CapturePreview(session: camera.session, onSelect: { camera.selectObject(normalizedRawImagePoint: $0) }, ghost: camera.ghost.selected,
                           onGuide: { rect, size, orientation in camera.updateGuide(rect: rect, viewport: size, orientation: orientation) })
                .frame(maxWidth: .infinity, maxHeight: .infinity).clipped()
                .overlay(alignment: .top) {
                    Text(camera.isCapturing ? "SCANNING" : "FRAME YOUR OBJECT")
                        .font(.caption2.weight(.semibold)).tracking(2).padding(.horizontal, 16).padding(.vertical, 10)
                        .background(RepairStyle.background.opacity(0.9), in: Capsule()).padding(.top, 16).allowsHitTesting(false)
                }
            VStack(spacing: 16) {
                Text(camera.isCapturing ? (camera.frameCount < 4 ? "Hold still for a sharp first view" : camera.guidance) : "Keep the whole object inside the box")
                    .font(.subheadline).multilineTextAlignment(.center).foregroundStyle(RepairStyle.text)
                    .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("scanGuidance")
                HStack {
                    Button(action: onLibrary) {
                        Image(systemName: "square.stack").font(.title3.weight(.medium))
                            .frame(width: 52, height: 52).background(RepairStyle.surface, in: Circle())
                    }.accessibilityLabel("Saved scans").accessibilityIdentifier("openSavedScans")
                        .disabled(camera.isCapturing || transition || model.busy)
                    Spacer()
                    Button { Task { await toggle() } } label: {
                        ZStack {
                            Circle().stroke(RepairStyle.accent, lineWidth: 3).frame(width: 80, height: 80)
                            Circle().fill(RepairStyle.accent).frame(width: 66, height: 66)
                            if transition { ProgressView().tint(RepairStyle.background) }
                            else { Image(systemName: camera.isCapturing ? "checkmark" : "viewfinder").font(.system(size: 27, weight: .semibold)).foregroundStyle(RepairStyle.background) }
                        }
                    }.buttonStyle(.plain).disabled(transition || failure != nil || model.busy)
                        .accessibilityLabel(camera.isCapturing ? "Finish scan" : "Start scan").accessibilityIdentifier("startUnifiedScan")
                    Spacer()
                    Button { Task { await reset() } } label: {
                        Image(systemName: "arrow.counterclockwise").font(.title3.weight(.medium))
                            .frame(width: 52, height: 52).background(RepairStyle.surface, in: Circle())
                    }.accessibilityLabel("Reset camera").accessibilityIdentifier("resetCapture")
                        .accessibilityHint(failure ?? "Save the current capture and start with a fresh camera view.")
                        .disabled(transition || model.busy)
                }
                Text(camera.isCapturing ? "\(camera.frameCount) views · Tap to finish" : (failure == nil ? "Start scan" : "Camera unavailable")).font(.caption.weight(.medium)).foregroundStyle(RepairStyle.secondary)
            }.padding(.horizontal, 28).padding(.vertical, 20).background(RepairStyle.background)
        }.foregroundStyle(RepairStyle.text)
            .task {
                #if !SPARSE_RESEARCH
                camera.predictGhost = { snapshot in
                    let payload = try JSONSerialization.jsonObject(with: JSONEncoder().encode(snapshot)) as! [String: Any]
                    let data = try await model.request("v1/geometry/live", method: "POST", json: payload)
                    return try JSONDecoder().decode(LiveGhostResponse.self, from: data)
                }
                #endif
                await preview()
            }
            .onChange(of: camera.savedRevision) { _, _ in deliver() }
            .onDisappear { camera.clearGhost(); camera.session.pause() }
    }
    private func preview() async {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-cameraLayoutPreview") { return }
        #endif
        guard camera.hasAR else { failure = "Live scanning needs a LiDAR iPhone or iPad."; return }
        do { try await camera.startPreview() } catch { failure = error.localizedDescription }
    }
    private func reset() async {
        guard !transition && !model.busy else { return }
        transition = true
        // Stop saves the existing package. Suppress its normal processing callback
        // so resetting never uploads it or discards the user's captured frames.
        delivered = true
        do {
            if camera.isCapturing || (camera.packageURL != nil && camera.savedRevision == 0) {
                let url = try await camera.stop(); model.didCapture(url)
            }
            camera.clearGhost(); camera.session.pause(); model.captureActive = false
            onReset()
        } catch {
            failure = error.localizedDescription; transition = false
            model.captureActive = camera.isCapturing
            // A failed save stays on this screen and can be retried with reset.
        }
    }
    private func toggle() async {
        guard !transition && !model.busy else { return }
        transition = true
        defer { transition = false }
        do {
            if camera.isCapturing { _ = try await camera.stop(); deliver() }
            else {
                model.create(name: "Scan \(Date().formatted(date: .omitted, time: .shortened))", synthetic: false)
                guard let dir = model.scanDirectory else { return }
                try await camera.start(directory: dir, scanID: UUID().uuidString)
                model.captureActive = true
            }
        } catch { failure = error.localizedDescription; model.captureActive = false }
    }
    private func deliver() {
        guard !delivered, camera.savedRevision > 0, let url = camera.packageURL else { return }
        delivered = true; model.captureActive = false; onFinish(url)
    }
}
