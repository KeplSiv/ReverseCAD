import SceneKit
import AVFoundation
import CryptoKit
import PhotosUI
import SwiftUI
import UIKit

private struct CubeFinding {
    let row: Int
    let column: Int
    let type: String
    let confidence: String
    let polygon: [CGPoint]
    let evidence: String
    let analysis: [String: Any]

    init?(_ json: [String: Any]) {
        guard let cell = json["missing_cell"] as? [String: Any],
              let row = cell["row"] as? Int,
              let column = cell["column"] as? Int,
              let type = cell["type"] as? String,
              let confidence = json["confidence"] as? String,
              let points = json["missing_polygon"] as? [[Double]],
              points.count == 4, points.allSatisfy({ $0.count == 2 }) else { return nil }
        analysis = json
        self.row = row
        self.column = column
        self.type = type
        self.confidence = confidence
        polygon = points.map { CGPoint(x: $0[0], y: $0[1]) }
        evidence = json["evidence"] as? String ?? ""
    }
}

struct CubeDemoView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var photo: UIImage?
    @State private var corners: [CGPoint] = []
    @State private var finding: CubeFinding?
    @State private var showLibrary = false
    @State private var showSettings = false
    @State private var manualCorners = false
    @State private var status = ""
    @State private var busy = false
    @State private var error: String?
    @State private var faceWidthText = ""
    private var faceWidth: Double { Double(faceWidthText.replacingOccurrences(of: ",", with: ".")) ?? 0 }
    @State private var files: [URL] = []
    @State private var showShare = false
    @State private var observedScan = false
    @State private var showCounterpart = true
    @State private var inspectFailedScan = false

    var body: some View {
        Group {
            if observedScan {
                observedResult
            } else if photo == nil && files.isEmpty {
                CubeScanCapture(onFinish: { url in
                    model.didCapture(url)
                    observedScan = true
                    model.uploadAndReconstruct()
                }, onLibrary: { showLibrary = true }, onSettings: { showSettings = true }, onLastModel: {
                    if let project = model.projects.first(where: { FileManager.default.fileExists(atPath: model.directory($0.id).appendingPathComponent("scan/manifest.json").path) }) {
                        model.select(project); observedScan = true; if model.scanMesh == nil { model.progress = "Your saved scan is ready to process." }
                    } else { restoreLastModel() }
                })
            } else {
                NavigationStack {
                    ScrollView {
                        VStack(spacing: 18) {
                            if let stl = files.first(where: { $0.pathExtension == "stl" }) {
                                CubeModelPreview(url: stl).frame(height: 370)
                                    .clipShape(RoundedRectangle(cornerRadius: 22))
                                Text("Your exterior model").font(.title2.bold())
                                Text("Drag to rotate · Pinch to zoom").font(.caption).foregroundStyle(.secondary)
                                Text("Exterior prototype. Fine edge details are estimates; physical fit is untested.")
                                    .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                                Button { showShare = true } label: {
                                    Label("Export model", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity)
                                }.buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("exportCube")
                                if finding != nil { Button("Adjust size") { files = [] } }
                            } else if let photo {
                                CubePhotoCanvas(photo: photo, corners: manualCorners ? corners : [], missing: finding?.polygon) { point in
                                    guard manualCorners, !busy, corners.count < 4 else { return }
                                    corners.append(point); finding = nil
                                }.frame(height: 320).clipShape(RoundedRectangle(cornerRadius: 22))
                                    .accessibilityIdentifier("cubePhoto")
                                if busy {
                                    ProgressView(status).padding()
                                } else if manualCorners {
                                    Text("Tap four face corners clockwise, starting at upper left.").font(.subheadline)
                                    Button("Analyze marked face") { Task { await analyze() } }
                                        .buttonStyle(.borderedProminent).disabled(corners.count != 4)
                                    Button("Reset corners") { corners = []; finding = nil }
                                }
                                if let finding, !busy {
                                    Text(finding.confidence == "needs_review" ? "Check the highlighted gap" : "Missing \(finding.type) found")
                                        .font(.title2.bold())
                                    Text("How wide is the whole cube?").font(.subheadline)
                                    HStack {
                                        TextField("e.g. 57", text: $faceWidthText)
                                            .keyboardType(.decimalPad).font(.largeTitle.bold()).multilineTextAlignment(.center)
                                            .accessibilityIdentifier("cubeWidth")
                                        Text("mm").foregroundStyle(.secondary)
                                    }.padding().background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14))
                                    if !faceWidthText.isEmpty && (faceWidth < 30 || faceWidth > 120) {
                                        Text("Enter 30–120 mm. For a 5.4 cm cube, enter 54.").font(.caption).foregroundStyle(.orange)
                                    }
                                    Button { Task { await generate() } } label: {
                                        Text("Create model").frame(maxWidth: .infinity)
                                    }.buttonStyle(.borderedProminent).controlSize(.large)
                                        .disabled(finding.confidence == "needs_review" || faceWidth < 30 || faceWidth > 120)
                                        .accessibilityIdentifier("generateCube")
                                } else if !busy && !manualCorners {
                                    Text(status).font(.subheadline).foregroundStyle(.secondary)
                                    Button("Try another photo") { showLibrary = true }
                                }
                            }
                        }.padding(20)
                    }.background(Color(.systemGroupedBackground))
                        .navigationTitle(files.isEmpty ? "Your scan" : "Your model")
                        .navigationBarTitleDisplayMode(.inline)
                        .toolbar {
                            ToolbarItem(placement: .topBarLeading) {
                                Button { resetScan() } label: { Image(systemName: "camera") }.disabled(busy).accessibilityLabel("New scan")
                            }
                            ToolbarItem(placement: .topBarTrailing) {
                                Menu {
                                    Button("Connection") { showSettings = true }
                                    Button("Adjust face manually") { manualCorners = true; corners = []; finding = nil; files = [] }
                                    Button("Detect automatically") { manualCorners = false; Task { await analyze() } }
                                } label: { Image(systemName: "ellipsis.circle") }.disabled(busy)
                            }
                            ToolbarItemGroup(placement: .keyboard) {
                                Spacer()
                                Button("Done") { UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil) }
                            }
                        }
                }
            }
        }
        .photosPicker(isPresented: $showLibrary, selection: $selectedPhoto, matching: .images)
        .onChange(of: selectedPhoto) { _, item in
            Task {
                guard !busy, let data = try? await item?.loadTransferable(type: Data.self), let image = UIImage(data: data) else { return }
                observedScan = false; photo = normalized(image); corners = []; finding = nil; files = []; manualCorners = false
                await analyze()
            }
        }
        .sheet(isPresented: $showSettings) { SettingsView().environmentObject(model) }
        .sheet(isPresented: $showShare) { ShareSheet(urls: files) }
        .alert("Couldn’t create model", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK") { error = nil }
        } message: { Text(error ?? "") }
    }

    private var observedResult: some View {
        NavigationStack {
            VStack(spacing: 18) {
                if model.busy {
                    Spacer(); ProgressView(model.progress).multilineTextAlignment(.center); Spacer()
                } else if let mesh = model.scanMesh, !mesh.vertices.isEmpty {
                    if !model.scanNeedsRescan || inspectFailedScan {
                        GeometryPreview(scan: model.counterpartPrintable && showCounterpart ? nil : mesh, part: showCounterpart ? model.counterpartMesh : nil, selectionMode: "none")
                            .frame(maxHeight: .infinity).clipShape(RoundedRectangle(cornerRadius: 22))
                    } else {
                        Spacer()
                        Image(systemName: "viewfinder.trianglebadge.exclamationmark").font(.system(size: 70)).foregroundStyle(.orange)
                    }
                    Text(model.scanNeedsRescan ? model.scanFailureTitle : (model.exteriorEstimated ? "Estimated replacement" : (model.counterpartPrintable ? "Replacement exterior ready" : "Captured surface"))).font(.title2.bold())
                    if !model.repairMessage.isEmpty && !model.exteriorEstimated { Text(model.repairMessage).font(.subheadline).multilineTextAlignment(.center) }
                    if !model.scanNeedsRescan { Text(model.exteriorEstimated ? "Exterior estimated from photos. Fine details, internal parts and fit are unverified. Cube context is inferred." : showCounterpart ? (model.counterpartPrintable ? "Orange: closed exterior prototype. Unseen sides use flat closures; internal locking geometry and fit are untested." : "Orange: proposed exterior copied from an intact edge. More views are needed before it can be closed.") : "LiDAR anchors the shape. Overlapping photos add detail where matching succeeds.")
                        .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center) }
                    if model.counterpartMesh != nil {
                        Toggle("Show replacement piece", isOn: $showCounterpart)
                    }
                    if !model.photoDetailStatus.isEmpty && !model.exteriorEstimated {
                        Text(model.photoDetailStatus).font(.caption).foregroundStyle(.secondary)
                    }
                    if !model.warnings.isEmpty {
                        DisclosureGroup("Scan quality") {
                            ScrollView { Text(model.warnings.joined(separator: "\n")).font(.caption) }.frame(maxHeight: 140)
                        }
                    }
                    if model.scanNeedsRescan {
                        Button("Scan again") { resetScan() }.buttonStyle(.borderedProminent).controlSize(.large)
                        Button(inspectFailedScan ? "Hide failed scan" : "Inspect failed scan") { inspectFailedScan.toggle() }
                        Spacer()
                    } else { Button(model.counterpartPrintable ? "Export printable piece" : (model.counterpartMesh == nil ? "Export scanned surface" : "Export scan + proposal")) { model.exportObservedSurface(printableOnly: model.counterpartPrintable) }
                        .buttonStyle(.borderedProminent).controlSize(.large).disabled(model.busy) }
                } else {
                    Spacer()
                    Text(model.error ?? model.progress).multilineTextAlignment(.center)
                    Button("Retry reconstruction") { model.uploadAndReconstruct() }.buttonStyle(.borderedProminent)
                    Spacer()
                }
            }.padding(20).navigationTitle("Your 3D scan").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button { resetScan() } label: { Image(systemName: "camera") }.disabled(model.busy).accessibilityLabel("New scan")
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button("Reprocess saved scan") { model.uploadAndReconstruct() }.disabled(model.busy)
                            Button("Connection settings") { showSettings = true }
                        } label: { Image(systemName: "ellipsis.circle") }
                    }
                }
        }.sheet(isPresented: $model.showingShare) { ShareSheet(urls: model.shareURLs) }
            .alert("Scan needs attention", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
                Button("OK") { model.error = nil }
            } message: { Text(model.error ?? "") }
    }

    private func resetScan() {
        observedScan = false; showCounterpart = true; inspectFailedScan = false
        photo = nil; finding = nil; corners = []; files = []; status = ""; manualCorners = false; selectedPhoto = nil
    }

    private func normalized(_ image: UIImage) -> UIImage {
        let scale = min(1, 1200 / max(image.size.width, image.size.height))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
    }

    private func restoreLastModel() {
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("CubeModels", isDirectory: true)
        let folders = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.creationDateKey])) ?? []
        guard let latest = folders.max(by: {
            ((try? $0.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? .distantPast) <
            ((try? $1.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? .distantPast)
        }) else { return }
        let names = ["measurements.json", "outer_cubie.py", "outer_cubie.step", "outer_cubie.stl"]
        let restored = names.map { latest.appendingPathComponent($0) }
        if restored.allSatisfy({ FileManager.default.fileExists(atPath: $0.path) }) {
            let plan = latest.appendingPathComponent("repair_plan.json")
            files = restored + (FileManager.default.fileExists(atPath: plan.path) ? [plan] : [])
        }
    }

    private func detect(_ image: UIImage, marked: [CGPoint] = []) async throws -> (CubeFinding, [CGPoint], Double) {
        guard let data = normalized(image).jpegData(compressionQuality: 0.55), data.count <= 700_000 else {
            throw ServiceFailure(message: "Photo is too large. Move closer and try again.")
        }
        var body: [String: Any] = ["photo_base64": data.base64EncodedString()]
        if !marked.isEmpty { body["corners"] = marked.map { [Double($0.x), Double($0.y)] } }
        let response = try await model.object("v1/cube/analyze", method: "POST", json: body)
        guard let result = CubeFinding(response), let face = response["face_corners"] as? [[Double]],
              face.count == 4, face.allSatisfy({ $0.count == 2 }) else {
            throw ServiceFailure(message: "The Mac did not return a valid cube result.")
        }
        return (result, face.map { CGPoint(x: $0[0], y: $0[1]) }, response["score_margin"] as? Double ?? 0)
    }

    private func analyze() async {
        guard let photo, !busy else { return }
        busy = true; status = "Finding the face and missing piece…"; files = []; finding = nil
        defer { busy = false }
        do {
            let result = try await detect(photo, marked: manualCorners ? corners : [])
            finding = result.0; corners = result.1; manualCorners = false
            status = "Found the gap. Enter the full cube width below."
        } catch { status = error.localizedDescription }
    }

    private func generate() async {
        busy = true
        defer { busy = false }
        do {
            let response = try await model.object("v1/cube/exterior", method: "POST", json: [
                "face_width_mm": faceWidth,
                                "analysis": finding?.analysis ?? [:],
            ])
            guard response["scope"] as? String == "exterior_envelope_only",
                  let artifacts = response["artifacts"] as? [[String: Any]] else {
                throw ServiceFailure(message: "The Mac did not return an exterior-only model.")
            }
            let directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("CubeModels", isDirectory: true)
                .appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            var saved: [URL] = []
            for artifact in artifacts {
                guard let name = artifact["name"] as? String,
                      ["outer_cubie.py", "outer_cubie.step", "outer_cubie.stl", "measurements.json", "repair_plan.json"].contains(name),
                      let encoded = artifact["base64"] as? String,
                      let data = Data(base64Encoded: encoded),
                      let expected = artifact["sha256"] as? String,
                      SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == expected else {
                    throw ServiceFailure(message: "A cube model file failed its checksum.")
                }
                let url = directory.appendingPathComponent(name)
                try data.write(to: url, options: .atomic)
                saved.append(url)
            }
            guard Set(saved.map(\.lastPathComponent)) == Set(["outer_cubie.py", "outer_cubie.step", "outer_cubie.stl", "measurements.json", "repair_plan.json"]) else { throw ServiceFailure(message: "The cube model is incomplete.") }
            files = saved.sorted { $0.lastPathComponent < $1.lastPathComponent }
        } catch { self.error = error.localizedDescription }
    }
}

private struct CubePhotoCanvas: View {
    let photo: UIImage
    let corners: [CGPoint]
    let missing: [CGPoint]?
    let onTap: (CGPoint) -> Void

    var body: some View {
        GeometryReader { geometry in
            let scale = min(geometry.size.width / photo.size.width, geometry.size.height / photo.size.height)
            let size = CGSize(width: photo.size.width * scale, height: photo.size.height * scale)
            let origin = CGPoint(x: (geometry.size.width - size.width) / 2, y: (geometry.size.height - size.height) / 2)
            ZStack(alignment: .topLeading) {
                Image(uiImage: photo).resizable().frame(width: size.width, height: size.height)
                    .position(x: origin.x + size.width / 2, y: origin.y + size.height / 2)
                if let missing, missing.count == 4 {
                    Path { path in
                        path.move(to: display(missing[0], origin, size))
                        for point in missing.dropFirst() { path.addLine(to: display(point, origin, size)) }
                        path.closeSubpath()
                    }
                    .fill(.orange.opacity(0.5))
                }
                ForEach(Array(corners.enumerated()), id: \.offset) { index, point in
                    let shown = display(point, origin, size)
                    Text("\(index + 1)")
                        .font(.caption.bold())
                        .foregroundStyle(.white)
                        .frame(width: 25, height: 25)
                        .background(.teal, in: Circle())
                        .position(shown)
                }
                Color.clear.contentShape(Rectangle()).gesture(SpatialTapGesture().onEnded { tap in
                    let x = (tap.location.x - origin.x) / size.width
                    let y = (tap.location.y - origin.y) / size.height
                    if (0...1).contains(x) && (0...1).contains(y) { onTap(CGPoint(x: x, y: y)) }
                })
            }
        }
        .background(.black)
    }

    private func display(_ point: CGPoint, _ origin: CGPoint, _ size: CGSize) -> CGPoint {
        CGPoint(x: origin.x + point.x * size.width, y: origin.y + point.y * size.height)
    }
}

/// Calibrated RGB, depth and camera poses from the same AR session.
private struct CubeScanCapture: View {
    @EnvironmentObject private var model: AppModel
    let onFinish: (URL) -> Void
    let onLibrary: () -> Void
    let onSettings: () -> Void
    let onLastModel: () -> Void
    @StateObject private var camera = CaptureController()
    @State private var transitioning = false
    @State private var delivered = false
    @State private var failure: String?
    @State private var showScanHelp = false
    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CapturePreview(session: camera.session, onSelect: { camera.selectObject(normalizedRawImagePoint: $0) }).ignoresSafeArea()
            VStack {
                HStack {
                    Text("ReverseCAD").font(.headline)
                    Spacer()
                    Menu {
                        Button("How to capture detail") { showScanHelp = true }
                        Button("Connection", action: onSettings)
                        Button("Last scan or model", action: onLastModel)
                    } label: { Image(systemName: "ellipsis.circle").font(.title2) }
                        .disabled(camera.isCapturing || transitioning)
                }.padding().background(.black.opacity(0.35))
                Spacer()
                RoundedRectangle(cornerRadius: 28)
                    .stroke(.white.opacity(0.85), style: StrokeStyle(lineWidth: 2, dash: [18, 8]))
                    .frame(width: 270, height: 300)
                    .overlay(alignment: .bottom) {
                        Text("Keep the whole object inside").font(.caption)
                            .padding(8).background(.black.opacity(0.45), in: Capsule()).offset(y: 38)
                    }.allowsHitTesting(false)
                Spacer()
                VStack(spacing: 20) {
                    Text(failure ?? (camera.isCapturing ? camera.guidance : "Keep the object still. Tap it to set the scan center. Move the phone, not the object."))
                        .font(.subheadline).multilineTextAlignment(.center)
                    HStack {
                        Button(action: onLibrary) { Image(systemName: "photo.on.rectangle").font(.title2).frame(width: 52) }
                            .disabled(camera.isCapturing || transitioning).accessibilityLabel("Photo prototype")
                        Spacer()
                        Button { Task { await toggle() } } label: {
                            ZStack {
                                Circle().stroke(.white, lineWidth: 4).frame(width: 78, height: 78)
                                if transitioning { ProgressView().tint(.white) }
                                else if camera.isCapturing { RoundedRectangle(cornerRadius: 7).fill(.red).frame(width: 30, height: 30) }
                                else { Circle().fill(.white).frame(width: 64, height: 64) }
                            }
                        }.disabled(transitioning || failure != nil)
                            .accessibilityLabel(camera.isCapturing ? "Finish scan" : "Start scan").accessibilityIdentifier("startCubeScan")
                        Spacer()
                        Color.clear.frame(width: 52, height: 30)
                    }
                    Text(camera.isCapturing ? "\(camera.frameCount) views saved · Tap to finish" : "Start 3D scan").font(.caption.bold())
                }.padding(24).background(.black.opacity(0.55))
            }.foregroundStyle(.white)
        }.task {
            do { try await camera.startPreview() } catch { failure = error.localizedDescription }
        }.sheet(isPresented: $showScanHelp) {
            NavigationStack {
                List {
                    Section("1 · Keep it fixed") {
                        Text("Use diffuse light and a textured, matte background. Keep the object stationary for the entire scan. Move your phone around it; keep fingers out of the view.")
                    }
                    Section("2 · Overlap your views") {
                        Text("Begin about 25–35 cm away. Move slowly in small steps, keeping most of the previous view visible. Follow the live prompt, then make another pass from higher and lower angles.")
                    }
                    Section("3 · Capture ridges and openings") {
                        Text("Move closer only while edges stay sharp. View each ridge, intact reference feature and visible recess from several angles. Aim into the damaged opening from both sides; shadows and glare can hide its shape.")
                    }
                    Section("4 · Expose the underside") {
                        Text("An assembled object can reveal surfaces inside an opening, but not surfaces hidden behind solid material. If accessible, scan a removed intact part separately, including its connector. Finish before repositioning it; separate orientations still need registration before they can be combined.")
                    }
                    Section("What the guide measures") {
                        Text("Prompts check camera tracking, local sharpness, distance, framing and viewing direction. They do not certify minute detail or complete coverage. LiDAR provides coarse depth; photographs must resolve small features.")
                    }
                }.navigationTitle("Capture detail")
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showScanHelp = false } } }
            }
        }.onDisappear { camera.session.pause() }
            .onChange(of: camera.savedRevision) { _, _ in deliver() }
    }
    private func toggle() async {
        guard !transitioning else { return }
        transitioning = true
        defer { transitioning = false }
        do {
            if camera.isCapturing {
                _ = try await camera.stop()
                deliver()
            } else {
                model.create(name: "3D scan", synthetic: false)
                guard let directory = model.scanDirectory else { return }
                try await camera.start(directory: directory, scanID: UUID().uuidString)
                model.captureActive = true
            }
        } catch { failure = error.localizedDescription; model.captureActive = false }
    }
    private func deliver() {
        guard !delivered, let url = camera.packageURL, camera.savedRevision > 0 else { return }
        delivered = true; model.captureActive = false
        onFinish(url)
    }
}

/// Render the exported STL itself, so preview and downloaded geometry agree.
private struct CubeModelPreview: UIViewRepresentable {
    let url: URL
    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.backgroundColor = .secondarySystemGroupedBackground
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.scene = scene()
        return view
    }
    func updateUIView(_ view: SCNView, context: Context) {}
    private func scene() -> SCNScene {
        let scene = SCNScene()
        guard let data = try? Data(contentsOf: url), data.count >= 84 else { return scene }
        func uint(_ offset: Int) -> UInt32 {
            data.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(fromByteOffset: offset, as: UInt32.self)) }
        }
        let count = Int(uint(80))
        guard count > 0, count < 1_000_000, data.count == 84 + count * 50 else { return scene }
        func vector(_ offset: Int) -> SCNVector3 {
            SCNVector3(Float(bitPattern: uint(offset)), Float(bitPattern: uint(offset + 4)), Float(bitPattern: uint(offset + 8)))
        }
        var vertices: [SCNVector3] = []
        var normals: [SCNVector3] = []
        for triangle in 0..<count {
            let start = 84 + triangle * 50
            let normal = vector(start)
            for corner in 0..<3 { vertices.append(vector(start + 12 + corner * 12)); normals.append(normal) }
        }
        let element = SCNGeometryElement(indices: (0..<UInt32(vertices.count)).map { $0 }, primitiveType: .triangles)
        let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices), SCNGeometrySource(normals: normals)], elements: [element])
        geometry.firstMaterial?.diffuse.contents = UIColor.systemTeal
        geometry.firstMaterial?.roughness.contents = 0.35
        geometry.firstMaterial?.lightingModel = .physicallyBased
        let node = SCNNode(geometry: geometry)
        scene.rootNode.addChildNode(node)
        let camera = SCNNode(); camera.camera = SCNCamera()
        let extent = vertices.reduce(Float(1)) { max($0, max(abs($1.x), max(abs($1.y), abs($1.z)))) }
        camera.position = SCNVector3(extent * 3.3, extent * 2.5, extent * 4)
        camera.look(at: SCNVector3Zero)
        camera.camera?.zFar = 1000
        scene.rootNode.addChildNode(camera)
        return scene
    }
}
