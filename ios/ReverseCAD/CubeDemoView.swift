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

    var body: some View {
        Group {
            if photo == nil && files.isEmpty {
                CubeScanCapture(onFinish: { frames in
                    photo = frames.last
                    Task { await analyzeFrames(frames) }
                }, onLibrary: { showLibrary = true }, onSettings: { showSettings = true }, onLastModel: { restoreLastModel() })
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
                photo = normalized(image); corners = []; finding = nil; files = []; manualCorners = false
                await analyze()
            }
        }
        .sheet(isPresented: $showSettings) { SettingsView().environmentObject(model) }
        .sheet(isPresented: $showShare) { ShareSheet(urls: files) }
        .alert("Couldn’t create model", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK") { error = nil }
        } message: { Text(error ?? "") }
    }

    private func resetScan() {
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

    private func analyzeFrames(_ frames: [UIImage]) async {
        guard !frames.isEmpty, !busy else { return }
        busy = true; files = []; finding = nil; corners = []; manualCorners = false
        photo = frames.last
        defer { busy = false }
        var best: (UIImage, CubeFinding, [CGPoint], Double)?
        var lastError = "Keep a mostly same-colored face and its missing edge visible, then scan again."
        for (index, frame) in frames.enumerated() {
            status = "Analyzing view \(index + 1) of \(frames.count)…"
            do {
                let result = try await detect(frame)
                if result.2 > (best?.3 ?? -1) { best = (frame, result.0, result.1, result.2) }
            } catch { lastError = error.localizedDescription }
        }
        if let best {
            photo = best.0; finding = best.1; corners = best.2
            status = "Best view selected. Enter the full cube width below."
        } else { status = lastError }
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

/// Silent camera sampling: image frames only, with no microphone or movie file.
private final class CubeScanCamera: NSObject, ObservableObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "reversecad.cube-camera")
    private let context = CIContext()
    private var frames: [UIImage] = []
    private var lastTime = -Double.infinity
    private var stopped = false
    private var sampling = false
    @Published var count = 0
    @Published var failure: String?

    func start() {
        AVCaptureDevice.requestAccess(for: .video) { granted in
            guard granted else {
                DispatchQueue.main.async { self.failure = "Allow camera access in Settings to scan, or choose a saved photo." }
                return
            }
            self.queue.async {
                guard !self.stopped else { return }
                do {
                    self.session.beginConfiguration()
                    self.session.sessionPreset = .hd1280x720
                    guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                        throw ServiceFailure(message: "This device has no rear camera.")
                    }
                    let input = try AVCaptureDeviceInput(device: camera)
                    guard self.session.canAddInput(input) else { throw ServiceFailure(message: "Camera is unavailable.") }
                    self.session.addInput(input)
                    let output = AVCaptureVideoDataOutput()
                    output.alwaysDiscardsLateVideoFrames = true
                    output.setSampleBufferDelegate(self, queue: self.queue)
                    guard self.session.canAddOutput(output) else { throw ServiceFailure(message: "Camera frames are unavailable.") }
                    self.session.addOutput(output)
                    if let connection = output.connection(with: .video), connection.isVideoRotationAngleSupported(90) {
                        connection.videoRotationAngle = 90
                    }
                    self.session.commitConfiguration()
                    self.session.startRunning()
                } catch {
                    self.session.commitConfiguration()
                    DispatchQueue.main.async { self.failure = error.localizedDescription }
                }
            }
        }
    }

    func beginSampling() { queue.async { self.frames = []; self.lastTime = -Double.infinity; self.sampling = true } }

    func stop() { queue.async { self.stopped = true; self.session.stopRunning() } }

    func finish(_ completion: @escaping ([UIImage]) -> Void) {
        queue.async {
            self.stopped = true
            self.session.stopRunning()
            let captured = self.frames
            DispatchQueue.main.async { completion(captured) }
        }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard !stopped, sampling, frames.count < 8 else { return }
        let time = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
        guard time - lastTime >= 1, let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastTime = time
        let source = CIImage(cvPixelBuffer: buffer)
        guard let cg = context.createCGImage(source, from: source.extent) else { return }
        frames.append(UIImage(cgImage: cg))
        let capturedCount = frames.count
        DispatchQueue.main.async { self.count = capturedCount }
    }
}

private final class CubePreviewUIView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
}

private struct CubeScanPreview: UIViewRepresentable {
    let session: AVCaptureSession
    func makeUIView(context: Context) -> CubePreviewUIView {
        let view = CubePreviewUIView()
        view.preview.session = session
        view.preview.videoGravity = .resizeAspectFill
        return view
    }
    func updateUIView(_ view: CubePreviewUIView, context: Context) {
        if let connection = view.preview.connection, connection.isVideoRotationAngleSupported(90) {
            connection.videoRotationAngle = 90
        }
    }
}

private struct CubeScanCapture: View {
    let onFinish: ([UIImage]) -> Void
    let onLibrary: () -> Void
    let onSettings: () -> Void
    let onLastModel: () -> Void
    @StateObject private var camera = CubeScanCamera()
    @State private var finishing = false
    @State private var scanning = false
    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CubeScanPreview(session: camera.session).ignoresSafeArea()
            VStack {
                HStack {
                    Text("ReverseCAD").font(.headline)
                    Spacer()
                    Menu {
                        Button("Connection", action: onSettings)
                        Button("Last model", action: onLastModel)
                    } label: { Image(systemName: "ellipsis.circle").font(.title2) }.disabled(scanning)
                }.padding().background(.black.opacity(0.35))
                Spacer()
                RoundedRectangle(cornerRadius: 28).stroke(.white.opacity(0.7), style: StrokeStyle(lineWidth: 1, dash: [12, 8]))
                    .frame(width: 260, height: 300).allowsHitTesting(false)
                Spacer()
                VStack(spacing: 20) {
                    Text(camera.failure ?? (scanning ? "Move slowly. Keep the missing edge visible." : "Show the cube’s missing edge"))
                        .font(.subheadline).multilineTextAlignment(.center)
                    if scanning { ProgressView(value: Double(camera.count), total: 8).tint(.white) }
                    HStack {
                        Button(action: onLibrary) { Image(systemName: "photo.on.rectangle").font(.title2).frame(width: 52) }
                            .disabled(scanning).accessibilityLabel("Choose photo")
                        Spacer()
                        Button {
                            if scanning { finish() } else { scanning = true; camera.beginSampling() }
                        } label: {
                            ZStack {
                                Circle().stroke(.white, lineWidth: 4).frame(width: 78, height: 78)
                                if scanning { RoundedRectangle(cornerRadius: 7).fill(.red).frame(width: 30, height: 30) }
                                else { Circle().fill(.white).frame(width: 64, height: 64) }
                            }
                        }.disabled(finishing || camera.failure != nil || (scanning && camera.count < 2))
                            .accessibilityLabel(scanning ? "Finish scan" : "Start scan").accessibilityIdentifier("startCubeScan")
                        Spacer()
                        Color.clear.frame(width: 52, height: 30)
                    }
                    Text(scanning ? "\(camera.count) / 8 views" : "Start scan").font(.caption.bold())
                }.padding(24).background(.black.opacity(0.55))
            }.foregroundStyle(.white)
        }.onAppear { camera.start() }.onDisappear { camera.stop() }
            .onChange(of: camera.count) { _, count in if count == 8 { finish() } }
    }
    private func finish() {
        guard !finishing else { return }
        finishing = true
        camera.finish(onFinish)
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
