import SwiftUI
import UniformTypeIdentifiers
import ImageIO

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @State private var settings = false
    @State private var newProject = false
    @State private var name = ""
    var body: some View {
        NavigationStack {
            Group {
                if let p=model.project {
                    ProjectView(project:p)
                } else {
                    ScrollView {
                        VStack(alignment:.leading,spacing:22) {
                            VStack(alignment:.leading,spacing:10) {
                                Image(systemName:"cube.transparent.fill").font(.system(size:42)).foregroundStyle(.teal)
                                Text("Measure what remains.\nDesign what’s missing.").font(.largeTitle.bold())
                                Text("Capture a stationary object, confirm its interfaces, and make an editable repair.").foregroundStyle(.secondary)
                            }.padding(.vertical)
                            Button {newProject=true} label:{Label("New repair project",systemImage:"plus.circle.fill").frame(maxWidth:.infinity)}.buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("newProject")
                            Button {model.create(name:"Synthetic sample",synthetic:true)} label:{Label("Explore synthetic sample",systemImage:"cube.transparent").frame(maxWidth:.infinity)}.buttonStyle(.bordered).accessibilityIdentifier("sampleProject")
                            if !model.projects.isEmpty {Text("Your projects").font(.title2.bold())}
                            ForEach(model.projects) {p in
                                Button {model.select(p)} label:{
                                    HStack(spacing:16) {
                                        ProjectThumbnail(directory:model.directory(p.id).appendingPathComponent("scan/rgb"),family:p.family)
                                        VStack(alignment:.leading,spacing:5) {Text(p.name).font(.headline);Text("\(FamilySpec.title(p.family)) · \(p.created.formatted(date:.abbreviated,time:.omitted))").font(.caption);Text(p.stage).font(.caption.bold());if p.exportedRevision>0 {Text("Last exported revision \(p.exportedRevision)").font(.caption)}}
                                        Spacer();Image(systemName:"chevron.right")
                                    }.foregroundStyle(.primary).padding().background(.regularMaterial,in:RoundedRectangle(cornerRadius:16))
                                }.buttonStyle(.plain)
                            }
                            Label("Software checks and physical fit are separate results.",systemImage:"ruler").font(.footnote).foregroundStyle(.secondary)
                        }.padding(22)
                    }.background(Color(.systemGroupedBackground))
                }
            }
            .navigationTitle(model.project?.name ?? "Reverse CAD").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement:.topBarLeading) {if model.project != nil {Button {model.selectedID=nil} label:{Label("Projects",systemImage:"chevron.left")}.accessibilityIdentifier("backProjects").disabled(model.busy || model.captureActive)}}
                ToolbarItem(placement:.topBarTrailing) {Button {settings=true} label:{Image(systemName:"network")}.accessibilityLabel("Service settings").accessibilityIdentifier("serviceSettings").disabled(model.busy || model.captureActive)}
            }
            .toolbar {ToolbarItemGroup(placement:.keyboard){Spacer();Button("Done"){UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder),to:nil,from:nil,for:nil)}.accessibilityIdentifier("keyboardDone")}}
            .sheet(isPresented:$settings) {SettingsView()}
            .sheet(isPresented:$newProject) {NavigationStack {Form {TextField("Object name",text:$name).accessibilityIdentifier("projectName");Text("Your scan stays on this phone until you choose Process scan.").font(.footnote)}.navigationTitle("New repair").toolbar {ToolbarItem(placement:.confirmationAction){Button("Create"){model.create(name:name,synthetic:false);name="";newProject=false}.accessibilityIdentifier("createProject")};ToolbarItem(placement:.cancellationAction){Button("Cancel"){newProject=false}}}}}
            .sheet(isPresented:$model.showingShare) {ShareSheet(urls:model.shareURLs)}
            .alert("Action needs attention",isPresented:Binding(get:{model.error != nil && !settings},set:{if !$0 && !settings {model.error=nil}})) {Button("OK",role:.cancel){model.error=nil}} message:{Text(model.error ?? "")}
        }
    }
}

struct SettingsView:View {
    @EnvironmentObject var model:AppModel
    @Environment(\.dismiss) var dismiss
    var body:some View {NavigationStack {Form {
        Section("Paired Mac service") {
            TextField("http://your-mac.local:8767",text:$model.serverURL).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL).accessibilityIdentifier("serviceURL")
            SecureField("Pairing token",text:$model.token).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("pairingToken")
            Text("Use the Mac’s reachable LAN address on iPhone. Simulator can use 127.0.0.1. Read the private pairing-token file shown by the Mac startup script and enter its contents here.").font(.footnote).foregroundStyle(.secondary)
            Button("Check connection"){model.checkConnection()}.disabled(model.busy).accessibilityIdentifier("checkConnection")
            Label(model.connection,systemImage:model.connection.hasPrefix("Connected") ? "checkmark.circle":"network")
        }
        Section("Data and reasoning") {
            Text("Scans stay in your project until processing is requested. The paired service reconstructs and generates CAD on your Mac. Live AI mode sends selected object images and the evidence table to the configured provider. Manual and fixture modes do not call a model.")
            Text("Only this service pairing token is stored on iPhone, in Keychain. The model API key belongs on the Mac.").font(.footnote).foregroundStyle(.secondary)
        }
        Section("Validation status") {Text("Simulator uses synthetic RGB-D replay. Live sensing, dimensional accuracy, and printed fit need separate phone trials.")}
    }.navigationTitle("Connection")
    .alert("Action needs attention",isPresented:Binding(get:{model.error != nil},set:{if !$0 {model.error=nil}})){Button("OK",role:.cancel){model.error=nil}} message:{Text(model.error ?? "")}
    .toolbar {ToolbarItem(placement:.confirmationAction){Button("Done"){model.saveSettings();dismiss()}}}}}
}

struct ProjectView:View {
    @EnvironmentObject var model:AppModel
    @StateObject private var capture=CaptureController()
    let project:RepairProject
    @State private var tab=0
    @State private var importing=false
    @State private var deleteConfirm=false
    @State private var motionDiagnostics=false
    var body:some View {
        VStack(spacing:0) {
            HStack {Text(project.source=="synthetic" ? "SYNTHETIC SAMPLE":"LOCAL SCAN").font(.caption2.bold()).padding(6).background(.teal.opacity(0.12),in:Capsule());Spacer();Text(project.stage).font(.caption).foregroundStyle(.secondary)}.padding(.horizontal).padding(.top,8)
            Picker("Workflow",selection:$tab) {Text("Capture").tag(0);Text("Evidence").tag(1);Text("Design").tag(2);Text("Results").tag(3)}.pickerStyle(.segmented).padding().accessibilityIdentifier("workflowTabs")
            if model.busy || !model.progress.isEmpty {
                HStack(alignment:.top) {if model.busy {ProgressView()};Text(model.progress).font(.caption);Spacer();if model.busy {Button("Cancel"){model.cancel()}.font(.caption).accessibilityIdentifier("cancelJob")}}
                    .padding(12).background(.teal.opacity(0.08)).accessibilityElement(children:.contain)
            }
            ScrollView {
                VStack(alignment:.leading,spacing:18) {
                    switch tab {
                    case 0: captureTab
                    case 1: EvidenceView(project:project)
                    case 2: DesignView(project:project)
                    default: ResultsView(project:project)
                    }
                    if let _=project.jobID,!model.busy {Button("Resume saved job"){model.resumeJob()}.buttonStyle(.borderedProminent).accessibilityIdentifier("resumeJob")}
                }.padding(18).disabled(model.busy)
            }.id(tab).background(Color(.systemGroupedBackground))
        }
        .onChange(of:capture.isCapturing) { _,active in model.captureActive=active }
        .onChange(of:capture.savedRevision) { _,_ in if let url=capture.packageURL {model.didCapture(url)} }
        .fileImporter(isPresented:$importing,allowedContentTypes:[.folder]) {result in if case .success(let url)=result {model.importScan(url)}}
        .confirmationDialog("Delete project data?",isPresented:$deleteConfirm,titleVisibility:.visible) {Button("Delete local project",role:.destructive){model.deleteProject(server:false)};Button("Delete local and paired server data",role:.destructive){model.deleteProject(server:true)}}
    }
    var captureTab:some View {
        VStack(alignment:.leading,spacing:18) {
            VStack(alignment:.leading,spacing:10) {
                Label(capture.hasLiDAR ? "Live LiDAR available":capture.hasAR ? "Camera / manual capture":"Replay and manual workflow",systemImage:capture.hasLiDAR ? "viewfinder":"play.rectangle")
                    .font(.headline)
                Text(capture.hasLiDAR ? "Native depth + RGB + ARKit visual-inertial pose":"Live LiDAR is unavailable here. Synthetic replay is labeled; camera-only capture cannot establish depth measurements.").font(.footnote).foregroundStyle(.secondary)
            }.card()
            if capture.isCapturing {
                CapturePreview(session:capture.session,onSelect:{capture.selectObject(normalizedRawImagePoint:$0)}).frame(height:280).clipShape(RoundedRectangle(cornerRadius:18)).overlay(alignment:.center){Image(systemName:"scope").font(.system(size:70,weight:.ultraLight)).foregroundStyle(.white).allowsHitTesting(false)}
                Text(capture.guidance).font(.headline)
                Text("\(capture.status) · \(capture.coverageViews) view bins · \(capture.rejectedFrames) rejected").font(.caption)
                HStack {metric("Frames",String(capture.frameCount));metric("Dropped",String(capture.droppedFrames));metric("MiB",String(format:"%.1f",Double(capture.bytesWritten)/1048576))}
                Button("Finish and save scan") {Task {do {let url=try await capture.stop();model.didCapture(url)} catch {model.error=error.localizedDescription}}}.buttonStyle(.borderedProminent).accessibilityIdentifier("finishScan")
            } else {
                if let mesh=model.scanMesh {GeometryPreview(scan:mesh,part:nil,selectionMode:"none").frame(height:250).clipShape(RoundedRectangle(cornerRadius:16))}
                VStack(alignment:.leading,spacing:12) {
                    Text("Keep the object still").font(.title3.bold())
                    instruction("1","Use diffuse light and a textured support.")
                    instruction("2","Center the object. Move the phone around it with overlapping views at different heights.")
                    instruction("3","Capture the attachment regions and include a measured reference.")
                }.card()
                if capture.hasAR {Toggle("Optional motion diagnostics",isOn:$motionDiagnostics).font(.caption);Button {Task {do {guard let dir=model.scanDirectory else{return};try await capture.start(directory:dir,scanID:UUID().uuidString,motionDiagnostics:motionDiagnostics)} catch {model.error=error.localizedDescription}}} label:{Label("Start live capture",systemImage:"camera.fill").frame(maxWidth:.infinity)}.buttonStyle(.borderedProminent).controlSize(.large).disabled(project.scanID != nil).accessibilityIdentifier("startCapture")}
                Button {model.replay(capture)} label:{Label("Load synthetic replay",systemImage:"play.rectangle.fill").frame(maxWidth:.infinity)}.buttonStyle(.bordered).disabled(model.busy || project.scanID != nil).accessibilityIdentifier("loadReplay")
                Text("Replay follows the same CaptureFrame contract. It tests software, not iPhone sensor accuracy.").font(.caption).foregroundStyle(.secondary)
                if project.scanID != nil {
                    Label("Scan saved on device",systemImage:"checkmark.circle.fill").foregroundStyle(.teal).accessibilityIdentifier("scanSaved")
                    Button {model.uploadAndReconstruct()} label:{Label("Process scan",systemImage:"arrow.up.doc").frame(maxWidth:.infinity)}.buttonStyle(.borderedProminent).controlSize(.large).disabled(model.busy).accessibilityIdentifier("processScan")
                    Text("Uploads this scan to your paired Mac. A lost connection preserves local data; retry sends only missing files.").font(.caption).foregroundStyle(.secondary)
                    Button("Export scan package"){model.exportScan()}.accessibilityIdentifier("exportScan")
                }
                Button("Import scan folder"){importing=true}.disabled(project.scanID != nil)
                DisclosureGroup("Project data") {Button("Delete project…",role:.destructive){deleteConfirm=true}}
            }
        }
    }
    func metric(_ name:String,_ value:String)->some View {VStack {Text(value).font(.title3.monospacedDigit().bold());Text(name).font(.caption)}.frame(maxWidth:.infinity).card()}
    func instruction(_ n:String,_ text:String)->some View {HStack(alignment:.top){Text(n).font(.headline).foregroundStyle(.teal);Text(text).font(.subheadline)}}
}

extension View {
    func card()->some View {padding(16).frame(maxWidth:.infinity,alignment:.leading).background(Color(.secondarySystemGroupedBackground),in:RoundedRectangle(cornerRadius:16))}
}
struct ShareSheet:UIViewControllerRepresentable {
    let urls:[URL]
    func makeUIViewController(context:Context)->UIActivityViewController {UIActivityViewController(activityItems:urls,applicationActivities:nil)}
    func updateUIViewController(_ vc:UIActivityViewController,context:Context) {}
}

struct ProjectThumbnail:View {
    let directory:URL
    let family:String
    var thumbnail:UIImage? {
        guard let url=(try? FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil))?.sorted(by:{$0.path<$1.path}).first,
              let source=CGImageSourceCreateWithURL(url as CFURL,nil),
              let image=CGImageSourceCreateThumbnailAtIndex(source,0,[kCGImageSourceCreateThumbnailFromImageAlways:true,kCGImageSourceThumbnailMaxPixelSize:128,kCGImageSourceCreateThumbnailWithTransform:true] as CFDictionary) else{return nil}
        return UIImage(cgImage:image)
    }
    var body:some View {Group {if let thumbnail {Image(uiImage:thumbnail).resizable().scaledToFill()} else {Image(systemName:family=="cup_handle" ? "cup.and.saucer.fill":"cube.fill").font(.title)}}.frame(width:54,height:64).background(.teal.opacity(0.1)).clipShape(RoundedRectangle(cornerRadius:12)).accessibilityHidden(true)}
}
