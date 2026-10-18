import SwiftUI
import Foundation
import CryptoKit
import Security
import ReverseCADCore

struct PatternRepairOption: Codable, Identifiable {
    struct Validation: Codable {
        var status: String
        var watertight: Bool
        var reason: String?
        var closure: String?
        var files: [String]
    }
    var id: String
    var preview: String
    var print_preview: String?
    var pattern_kind: String
    var validation: Validation
    var title: String { pattern_kind.capitalized + " proposal " + id.replacingOccurrences(of: "pattern_", with: "") }
}

struct ManualDimension: Codable, Identifiable, Equatable {
    var id = UUID().uuidString
    var name: String
    var value: Double
    var uncertainty: Double = 0.1
    var confirmed = true
    var critical = true
}
struct ContactMark: Codable, Identifiable, Equatable {
    var id = UUID().uuidString
    var point: [Double]
    var normal: [Double]
    var radius: Double = 8
    var normalSource: String?
    var normalConfirmed: Bool?
}
struct TrialRecord: Codable {
    var revisionKey: String?
    var revision: Int
    var fit: String
    var feedback: String
    var printer: String
    var iterations: Int
}
struct RepairProject: Codable, Identifiable {
    var id = UUID().uuidString
    var name: String
    var created = Date()
    var family = "bridge_handle"
    var source = "synthetic"
    var repairScope: String?
    var scanTarget: Data?
    var planarThicknessMM: Double?
    var stage = "Ready to capture"
    var scanID: String?
    var jobID: String?
    var jobKind: String?
    var repairID: String?
    var revision = 0
    var attachment = "screws"
    var evidence = "missing_part"
    var intent = "Replace the missing handle while preserving the surviving mounting geometry."
    var mode = "manual"
    var acknowledged = false
    var parameters: [String: Double] = FamilySpec.defaults("bridge_handle")
    var dimensions: [ManualDimension] = []
    var contacts: [ContactMark] = []
    var damage: [[Double]] = []
    var cropEnabled = false
    var cropMin: [Double] = [-150, -150, -150]
    var cropMax: [Double] = [150, 150, 150]
    var scaleMeasured = 0.0
    var scaleObserved = 0.0
    var scaleUncertainty = 0.1
    var symmetryConfirmed = false
    var symmetryAxis = "x"
    var feedback = ""
    var printer = ""
    var material = "PLA"
    var nozzle = 0.4
    var layerHeight = 0.2
    var printIterations = 0
    var physicalFit = "Not tested"
    var exportedRevision = 0
    var exportFolder: String?
    var verifiedArtifacts: [ArtifactInfo]?
    var pendingRepairRoute: String?
    var pendingReconstructionID: String?
    var pendingReconstructionFingerprint: String?
    var fragmentPoints: [[Double]]?
    var symmetryOffset: Double?
    var buildVolume: [Double]?
    var minimumWall: Double?
    var saddleApproved: Bool?
    var pendingRepairBody: Data?
    var pendingRepairFingerprint: String?
    var trialHistory: [TrialRecord]?
    var counterpartPoints: [[Double]]?
    var candidateID: String?
    var candidateProvenance: [String: String]?
}

enum FamilySpec {
    static let all = ["bridge_handle", "cup_handle", "bracket"]
    static func title(_ family: String) -> String {
        ["bridge_handle": "Bridge handle", "cup_handle": "Cup handle", "bracket": "Repair bracket"][family] ?? family
    }
    static func defaults(_ family: String) -> [String: Double] {
        switch family {
        case "cup_handle": return ["cup_radius":40,"cup_radius_top":40,"contact_spacing":60,"standoff":35,"grip_width":12,"grip_depth":10,"pad_height":16,"pad_thickness":4,"contact_gap":0.5]
        case "bracket": return ["width":30,"length":60,"thickness":4,"leg_height":25,"hole_diameter":4,"hole_spacing":35]
        default: return ["span":80,"standoff":30,"grip_width":12,"grip_depth":10,"pad_width":22,"pad_length":22,"pad_thickness":5,"hole_diameter":4]
        }
    }
    static func label(_ key: String) -> String { key.replacingOccurrences(of: "_", with: " ").capitalized }
}

struct ArtifactInfo: Codable, Identifiable {
    let id: String
    let name: String
    let sha256: String
    let size: Int
}

struct ServiceFailure: LocalizedError {
    var message: String
    var errorDescription: String? { message }
}

final class TokenStore {
    static let service = "com.pranav.ReverseCAD.pairing"
    static func load() -> String {
        let q: [String: Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecReturnData as String:true,kSecMatchLimit as String:kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary,&result) == errSecSuccess, let data = result as? Data else { return "" }
        return String(data:data,encoding:.utf8) ?? ""
    }
    static func save(_ token: String) {
        let q: [String: Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service]
        SecItemDelete(q as CFDictionary)
        var add = q
        add[kSecValueData as String] = Data(token.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary,nil)
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var projects: [RepairProject] = []
    @Published var selectedID: String?
    @Published var serverURL: String
    @Published var token: String
    @Published var connection = "Not checked"
    @Published var busy = false
    @Published var sparseReport: [String: Any]?
    @Published var captureActive = false
    @Published var candidates: [[String: Any]] = []
    @Published var candidateQuestions: [String] = []
    @Published var candidateNotes: [String] = []
    @Published var progress = ""
    @Published var error: String?
    @Published var scanMesh: MeshPreview?
    @Published var counterpartMesh: MeshPreview?
    @Published var comparison: ComparisonReport?
    @Published var selectedComparisonID: String?
    @Published var comparisonScan: MeshPreview?
    @Published var comparisonPart: MeshPreview?
    @Published var comparisonReviewed = false
    var selectedComparison: ComparisonVariant? { comparison?.variants.first { $0.id == selectedComparisonID } }
    @Published var patternRepairs: [PatternRepairOption] = []
    @Published var selectedPatternID: String?
    @Published var patternMesh: MeshPreview?
    @Published var patternReviewed = false
    var selectedPattern: PatternRepairOption? { patternRepairs.first { $0.id == selectedPatternID } }
    @Published var counterpartPrintable = false
    @Published var faceRepair: [String: Any]?
    @Published var reconstructionNeedsUpdate = false
    @Published var automaticRoute: [String: Any]?
    @Published var planarRepair: [String: Any]?
    @Published var scanNeedsRescan = false
    @Published var scanFailureTitle = "Scan didn’t line up"
    @Published var exteriorEstimated = false
    @Published var repairMessage = ""
    @Published var photoDetailStatus = ""
    @Published var partMesh: MeshPreview?
    @Published var measurements: [[String: Any]] = []
    @Published var warnings: [String] = []
    @Published var validation: [String: Any] = [:]
    @Published var artifacts: [ArtifactInfo] = []
    @Published var shareURLs: [URL] = []
    @Published var showingShare = false
    private var activeTask: Task<Void,Never>?
    private var cancelRequested = false
    let root: URL

    init(rootURL: URL? = nil) {
        root = rootURL ?? FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("Projects",isDirectory:true)
        let args = ProcessInfo.processInfo.arguments
        func arg(_ key:String)->String? { guard let i=args.firstIndex(of:key),args.count>i+1 else{return nil};return args[i+1] }
        #if targetEnvironment(simulator)
        let initial = "http://127.0.0.1:8767"
        #else
        let initial = ""
        #endif
        serverURL = arg("-serviceURL") ?? ProcessInfo.processInfo.environment["REVERSECAD_TEST_URL"] ?? UserDefaults.standard.string(forKey:"serverURL") ?? initial
        token = arg("-pairingToken") ?? ProcessInfo.processInfo.environment["REVERSECAD_TEST_TOKEN"] ?? TokenStore.load()
        try? FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        #if DEBUG
        if ProcessInfo.processInfo.environment["REVERSECAD_CLEAR_CAPTURE_DIAGNOSTICS"] == "1" {
            do { print("Removed \(try Self.removeSavedCaptureDiagnostics(root: root)) saved capture diagnostics") }
            catch { print("Capture diagnostics cleanup failed: \(error.localizedDescription)") }
        }
        #endif
        reload()
        #if DEBUG
        if let scanID = ProcessInfo.processInfo.environment["REVERSECAD_REPLAY_SCAN"],
           let jobID = ProcessInfo.processInfo.environment["REVERSECAD_REPLAY_JOB"],
           let saved = projects.first(where: { $0.scanID == scanID }) {
            select(saved)
            update { $0.repairScope = "cube_exterior"; $0.jobID = jobID; $0.jobKind = "reconstruction" }
            perform { try await self.runJob(["job_id":jobID], kind: "reconstruction") }
        }
        #endif
        if arg("-serviceURL") != nil || ProcessInfo.processInfo.environment["REVERSECAD_TEST_URL"] != nil {
            saveSettings()
            checkConnection()
        }
    }
    var project: RepairProject? { projects.first{$0.id == selectedID} }
    /// Explicit maintenance action only. Preserve scans and their integrity manifests.
    static func removeSavedCaptureDiagnostics(root: URL) throws -> Int {
        let manager = FileManager.default
        var removed = 0
        for project in try manager.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isSymbolicLinkKey]) {
            if try project.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink == true { continue }
            let scan = project.appendingPathComponent("scan", isDirectory: true)
            let diagnostic = scan.appendingPathComponent("capture_diagnostics.json")
            guard manager.fileExists(atPath: diagnostic.path) else { continue }
            let checksum = scan.appendingPathComponent("checksums.json")
            let original = try Data(contentsOf: checksum)
            var hashes = try JSONDecoder().decode([String:String].self, from: original)
            hashes.removeValue(forKey: "capture_diagnostics.json")
            try JSONEncoder().encode(hashes).write(to: checksum, options: .atomic)
            do { try manager.removeItem(at: diagnostic); removed += 1 }
            catch { try original.write(to: checksum, options: .atomic); throw error }
        }
        return removed
    }
    func directory(_ id: String) -> URL { root.appendingPathComponent(id,isDirectory:true) }
    var projectDirectory: URL? { selectedID.map(directory) }
    var scanDirectory: URL? { projectDirectory?.appendingPathComponent("scan",isDirectory:true) }
    func reload() {
        let urls = (try? FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil)) ?? []
        projects = urls.compactMap { try? JSONDecoder().decode(RepairProject.self,from:Data(contentsOf:$0.appendingPathComponent("project.json"))) }.sorted{$0.created>$1.created}
    }
    func create(name:String,synthetic:Bool) {
        guard !busy && !captureActive else { return }
        var p=RepairProject(name:name.isEmpty ? "Untitled repair":name)
        p.source=synthetic ? "synthetic":"arkit"
        projects.insert(p,at:0);selectedID=p.id;save();loadDerived()
    }
    func select(_ p:RepairProject) {
        guard !busy && !captureActive else{return}
        selectedID=p.id;loadDerived()
        guard let dir=scanDirectory,FileManager.default.fileExists(atPath:dir.appendingPathComponent("manifest.json").path) else{return}
        do {
            let manifest=try JSONDecoder().decode(CaptureManifest.self,from:Data(contentsOf:dir.appendingPathComponent("manifest.json")))
            if !manifest.complete {
                perform {
                    try await Task.detached {
                        do {_ = try ScanPackageWriter.validate(directory:dir,allowIncomplete:true)}
                        catch {let writer=try ScanPackageWriter.recover(directory:dir);_ = try writer.finish(complete:false)}
                    }.value
                    self.didCapture(dir)
                    self.update{$0.stage="Interrupted scan recovered"}
                    self.progress="Committed frames recovered. Review coverage and incomplete video before processing. Start a new project for a new coordinate origin."
                }
            }
        } catch {self.error="Recovery needs attention: \(error.localizedDescription)"}
    }
    func update(_ change:(inout RepairProject)->Void) {
        guard let i=projects.firstIndex(where:{$0.id==selectedID}) else{return}
        let old=projects[i]
        change(&projects[i])
        let new=projects[i]
        if old.family != new.family || old.attachment != new.attachment || old.evidence != new.evidence || old.dimensions != new.dimensions || old.contacts != new.contacts || old.cropMin != new.cropMin || old.cropMax != new.cropMax || old.cropEnabled != new.cropEnabled || old.scaleObserved != new.scaleObserved || old.scaleMeasured != new.scaleMeasured || old.scaleUncertainty != new.scaleUncertainty || old.damage != new.damage || old.fragmentPoints != new.fragmentPoints || old.counterpartPoints != new.counterpartPoints || old.symmetryConfirmed != new.symmetryConfirmed || old.symmetryAxis != new.symmetryAxis || old.symmetryOffset != new.symmetryOffset {
            projects[i].candidateID=nil;projects[i].candidateProvenance=nil
            candidates=[];candidateQuestions=[];candidateNotes=[]
        }
        save()
    }
    func save() {
        guard let p=project else{return}
        do {try FileManager.default.createDirectory(at:directory(p.id),withIntermediateDirectories:true)
            let encoder=JSONEncoder();encoder.outputFormatting=[.prettyPrinted,.sortedKeys]
            try encoder.encode(p).write(to:directory(p.id).appendingPathComponent("project.json"),options:.atomic)
        } catch {self.error="Could not save project: \(error.localizedDescription)"}
    }
    func saveSettings() {UserDefaults.standard.set(serverURL,forKey:"serverURL");TokenStore.save(token)}
    func loadDerived() {
        reconstructionNeedsUpdate = false
        sparseReport = nil
        comparison=nil;selectedComparisonID=nil;comparisonScan=nil;comparisonPart=nil;comparisonReviewed=false
        patternRepairs=[];selectedPatternID=nil;patternMesh=nil;patternReviewed=false
        automaticRoute=nil;planarRepair=nil;faceRepair=nil;counterpartMesh=nil;counterpartPrintable=false;scanNeedsRescan=false;exteriorEstimated=false;repairMessage="";photoDetailStatus="";scanMesh=nil;partMesh=nil;measurements=[];warnings=[];validation=[:];artifacts=[];candidates=[];candidateQuestions=[];candidateNotes=[]
        guard let dir=projectDirectory else{return}
        if let data=try? Data(contentsOf:dir.appendingPathComponent("reconstruction.json")),let info=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {
            guard ReconstructionIdentity.matches(info, scanID: savedScanID) else {
                reconstructionNeedsUpdate = true
                repairMessage = "This saved result belongs to another scan. Update this scan to create its own preview."
                return
            }
            sparseReport = info["sparse_reconstruction"] as? [String: Any]
            updatePhotoDetail(info)
            let hasFaceWorkflow = faceRepair != nil || (info["surface"] as? [String: Any])?["kind"] as? String == "tracked_face_outlines"
            let oldFaceGeometry = faceRepair != nil && (faceRepair?["geometry_version"] as? Int ?? 1) < 2
            reconstructionNeedsUpdate = project?.repairScope == "cube_exterior" && (!hasFaceWorkflow || oldFaceGeometry)
        } else { reconstructionNeedsUpdate = project?.repairScope == "cube_exterior" }
        counterpartMesh=try? JSONDecoder().decode(MeshPreview.self,from:Data(contentsOf:dir.appendingPathComponent("counterpart_preview.json")))
        scanMesh=try? JSONDecoder().decode(MeshPreview.self,from:Data(contentsOf:dir.appendingPathComponent("scan_preview.json")))
        partMesh=try? JSONDecoder().decode(MeshPreview.self,from:Data(contentsOf:dir.appendingPathComponent("part_preview.json")))
        if let data=try? Data(contentsOf:dir.appendingPathComponent("reconstruction.json")),let d=try? JSONSerialization.jsonObject(with:data) as? [String:Any] { measurements=d["measurements"] as? [[String:Any]] ?? [];warnings=d["warnings"] as? [String] ?? [] }
        if let data=try? Data(contentsOf:dir.appendingPathComponent("validation.json")),let d=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {validation=d}
        if let data=try? Data(contentsOf:dir.appendingPathComponent("artifacts.json")) {artifacts=(try? JSONDecoder().decode([ArtifactInfo].self,from:data)) ?? []}
        if let p=project,let folder=p.exportFolder,let verified=p.verifiedArtifacts {
            let revisionDir=dir.appendingPathComponent(folder);artifacts=verified
            if let data=try? Data(contentsOf:revisionDir.appendingPathComponent("validation.json")),let d=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {validation=d}
            for name in ["preview.json","part_preview.json","mesh.json"] {if let data=try? Data(contentsOf:revisionDir.appendingPathComponent(name)),let mesh=try? JSONDecoder().decode(MeshPreview.self,from:data) {partMesh=mesh;break}}
        }
    }
    func perform(_ action:@escaping () async throws -> Void) {
        guard !busy else{return};busy=true;error=nil;cancelRequested=false
        activeTask=Task {
            do {try await action()}
            catch is CancellationError {progress="Cancelled. Your saved scan is preserved."}
            catch {
                if error is URLError {
                    self.error = "Couldn’t reach \(URL(string: self.serverURL)?.host ?? self.serverURL) while \(self.progress.lowercased()). Your scan is saved. Check Connection, keep the Mac service running, and use the same reachable network."
                } else { self.error=error.localizedDescription }
                progress=error is URLError ? "Connection interrupted. Saved data is preserved; check the service address and connection before retrying." : "Action needs attention. Saved data is preserved; review the message before retrying."
            }
            busy=false;activeTask=nil
        }
    }
    // HTTP is paired and bounded. Scan package transfer uses the shared Core client.
    func request(_ path:String,method:String="GET",json:[String:Any]?=nil,raw:Data?=nil,hash:String?=nil) async throws -> Data {
        guard !serverURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              URL(string: serverURL)?.host?.lowercased() != "your-mac.local",
              !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ServiceFailure(message:"Connect this iPhone to the Mac service in Connection settings first. Your scan is saved; reopen it from Saved scans after connecting.")
        }
        guard let base=URL(string:serverURL),["http","https"].contains(base.scheme ?? ""),let host=base.host,!host.isEmpty else{throw ServiceFailure(message:"Enter the Mac service URL, including http:// or https://.")}
        #if !targetEnvironment(simulator)
        if ["localhost","127.0.0.1","::1"].contains(host) {throw ServiceFailure(message:"On iPhone use your Mac's LAN address, not localhost.")}
        #endif
        let client=ServiceClient(baseURL:base,token:token)
        let body=try json.map{try JSONSerialization.data(withJSONObject:$0)}
        return try await client.data(method,"/"+path.trimmingCharacters(in:CharacterSet(charactersIn:"/")),body:body)
    }
    func object(_ path:String,method:String="GET",json:[String:Any]?=nil) async throws -> [String:Any] {
        let d=try await request(path,method:method,json:json)
        return (try JSONSerialization.jsonObject(with:d)) as? [String:Any] ?? [:]
    }
    func checkConnection() {perform {
        self.connection="Checking connection…"
        do {let d=try await self.object("v1/health");_ = try await self.object("v1/capabilities");self.connection="Connected · \(d["status"] ?? "ready")";self.saveSettings();UserDefaults.standard.set(self.connection,forKey:"lastConnectionStatus")}
        catch {self.connection="Not connected";UserDefaults.standard.set(error.localizedDescription,forKey:"lastConnectionStatus");throw error}
    }}
    func didCapture(_ url:URL) {
        let data=try? Data(contentsOf:url.appendingPathComponent("manifest.json"))
        let manifest=data.flatMap{try? JSONSerialization.jsonObject(with:$0) as? [String:Any]}
        update{$0.scanID=manifest?["scan_id"] as? String;$0.source=manifest?["source"] as? String ?? $0.source;$0.stage=(manifest?["complete"] as? Bool)==false ? "Interrupted scan saved" : "Scan saved locally"}
    }
    func replay(_ controller:CaptureController) {perform {
        guard let dir=self.scanDirectory,let sample=Bundle.main.url(forResource:"SampleScan",withExtension:nil) else{throw ServiceFailure(message:"Bundled sample is missing. Generate fixtures and rebuild the app.")}
        self.progress="Replaying calibrated synthetic frames…"
        let result=try await controller.replay(from:sample,into:dir)
        self.didCapture(result);self.progress="Synthetic sample saved. Process it with your paired Mac."
    }}
    func annotationJSON()->[String:Any] {
        guard let p=project else{return [:]}
        var d:[String:Any]=["contacts":p.contacts.map{["id":$0.id,"point_m":$0.point,"normal":$0.normal,"radius_mm":$0.radius,"normal_source":$0.normalSource ?? "scan_patch_estimate","normal_confirmed":$0.normalConfirmed ?? false]},"damage_points_m":p.damage,"measurements":p.dimensions.map{["id":$0.id,"name":$0.name,"value":$0.value,"unit":"mm","source":"manual","confirmed":$0.confirmed,"critical":$0.critical,"uncertainty_mm":$0.uncertainty,"observation_ids":[]] as [String:Any]},"attachment_method":p.attachment,"evidence_state":p.evidence]
        d["repair_scope"] = p.repairScope ?? "general"
        if let target = p.scanTarget, let value = try? JSONSerialization.jsonObject(with: target) { d["object_target"] = value }
        if let thickness = p.planarThicknessMM { d["planar_thickness_mm"] = thickness }
        if p.cropEnabled {d["crop_min_m"]=p.cropMin.map{$0/1000};d["crop_max_m"]=p.cropMax.map{$0/1000}}
        if p.scaleMeasured>0 && p.scaleObserved>0 {d["scale_reference"]=["measured_mm":p.scaleMeasured,"observed_mm":p.scaleObserved,"uncertainty_mm":p.scaleUncertainty]}
        if p.symmetryConfirmed {d["symmetry"]=["confirmed":true,"axis":p.symmetryAxis,"counterpart_points_m":p.counterpartPoints ?? [],"offset_m":(p.symmetryOffset ?? 0)/1000,"source":"user_confirmed_counterpart"]}
        d["fragment_points_m"]=p.fragmentPoints ?? []
        return d
    }
    func reconstructAutomatically() {
        update { $0.repairScope = "automatic" }
        uploadAndReconstruct(compareMethods: false)
    }
    func reconstructRectangle(thickness: Double? = nil) {
        update { $0.repairScope = "rectangular_planar"; $0.planarThicknessMM = thickness }
        uploadAndReconstruct(compareMethods: false)
    }
    func planarImageURL(ghost: Bool) -> URL? {
        guard let (folder, infos) = try? observedArtifactLocation() else { return nil }
        let name = ghost ? "planar_overlay.jpg" : "planar_original.jpg"
        return infos.contains(where: { $0.name == name }) ? folder.appendingPathComponent(name) : nil
    }
    func cubeImageURL(ghost: Bool) -> URL? {
        guard let (folder, infos) = try? observedArtifactLocation() else { return nil }
        let name = ghost ? "cube_overlay.jpg" : "cube_original.jpg"
        return infos.contains(where: { $0.name == name }) ? folder.appendingPathComponent(name) : nil
    }
    func exportPlanar() { perform {
        guard self.counterpartPrintable, let report = self.planarRepair,
              let names = report["exports"] as? [String], !names.isEmpty else {
            throw ServiceFailure(message: "Enter measured thickness and create the solid first.")
        }
        let (folder, infos) = try self.observedArtifactLocation()
        guard names.allSatisfy({ name in infos.contains { $0.name == name } }) else {
            throw ServiceFailure(message: "Replacement files are incomplete. Rebuild the patch.")
        }
        try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: folder) }.value
        self.shareURLs = (names + ["planar_repair.json"]).map { folder.appendingPathComponent($0) }
        self.showingShare = true
    }}
    func reconstructCubeExterior() {
        update { $0.repairScope = "cube_exterior" }
        uploadAndReconstruct(compareMethods: false)
    }
    func uploadAndReconstruct(compareMethods: Bool = false) {perform {
        guard let dir=self.scanDirectory,let p=self.project else{return}
        let manifest=(try JSONSerialization.jsonObject(with:Data(contentsOf:dir.appendingPathComponent("manifest.json")))) as! [String:Any]
        let scanID=manifest["scan_id"] as? String ?? p.id
        self.progress="Connecting to your Mac…"
        _ = try await self.object("v1/health")
        if p.repairScope == "standalone_scan" {
            let capabilities = try await self.object("v1/capabilities")
            guard capabilities["capture_first_masks"] as? Bool == true else {
                throw ServiceFailure(message: "Update the Mac reconstruction service to the capture-first version on pranav-dev. This scan is saved; the older service cannot apply its object masks.")
            }
        }
        self.progress="Checking saved scan and resuming missing uploads…"
        self.update{$0.scanID=scanID;$0.stage="Uploading"}
        guard let url=URL(string:self.serverURL) else{throw ServiceFailure(message:"Invalid service address")}
        _ = try await ServiceClient(baseURL:url,token:self.token).uploadScan(directory:dir,projectID:p.id)
        _ = try await self.object("v1/scans/\(scanID)/annotations",method:"PUT",json:self.annotationJSON())
        let fingerprint=CaptureIO.sha256(try JSONSerialization.data(withJSONObject:["annotations":self.annotationJSON(),"compare_methods":compareMethods],options:.sortedKeys))
        let requestID=p.pendingReconstructionFingerprint==fingerprint ? (p.pendingReconstructionID ?? UUID().uuidString) : UUID().uuidString
        self.update{$0.pendingReconstructionID=requestID;$0.pendingReconstructionFingerprint=fingerprint}
        let job=try await self.object("v1/scans/\(scanID)/reconstruction",method:"POST",json:["request_id":requestID,"compare_methods":compareMethods])
        try await self.runJob(job,kind:"reconstruction")
    }}
    func persistAnnotations() {perform {
        guard let dir=self.projectDirectory else{return};let data=try JSONSerialization.data(withJSONObject:self.annotationJSON(),options:[.prettyPrinted,.sortedKeys]);try data.write(to:dir.appendingPathComponent("annotations.json"),options:.atomic)
        if let id=self.project?.scanID {_ = try await self.object("v1/scans/\(id)/annotations",method:"PUT",json:self.annotationJSON())}
        self.progress="Evidence saved. Reprocess scan to apply crop or scale changes."
    }}
    func generate() {perform {
        guard let p=self.project,let scanID=p.scanID else{throw ServiceFailure(message:"Capture and process a scan first.")}
        _ = try await self.object("v1/scans/\(scanID)/annotations",method:"PUT",json:self.annotationJSON())
        let buildVolume: [Double] = p.buildVolume ?? [220,220,250]
        let minimumWall: Double = p.minimumWall ?? 1.2
        let manufacturing: [String:Any] = ["nozzle_diameter_mm":p.nozzle,"layer_height_mm":p.layerHeight,"material":p.material,"build_volume_mm":buildVolume,"minimum_wall_mm":minimumWall]
        var body:[String:Any]=["scan_id":scanID,"family":p.family,"parameters":p.parameters,"attachment_method":p.attachment,"mode":p.mode,"provider_consent":p.mode=="live","acknowledge_uncertainty":p.acknowledged,"description":p.intent,"manufacturing":manufacturing]
        if let candidate=p.candidateID {body["candidate_id"]=candidate}
        let fingerprint=CaptureIO.sha256(try JSONSerialization.data(withJSONObject:["request":body,"annotations":self.annotationJSON()],options:.sortedKeys))
        var route=p.repairID.map{"v1/repairs/\($0)/revisions"} ?? "v1/repairs"
        if p.pendingRepairFingerprint==fingerprint,let frozen=p.pendingRepairBody {
            route=p.pendingRepairRoute ?? route
            body=try JSONSerialization.jsonObject(with:frozen) as! [String:Any]
        } else {
            body["request_id"]=UUID().uuidString
            let frozen=try JSONSerialization.data(withJSONObject:body,options:.sortedKeys)
            self.update{$0.pendingRepairBody=frozen;$0.pendingRepairFingerprint=fingerprint;$0.pendingRepairRoute=route}
        }
        let job=try await self.object(route,method:"POST",json:body)
        try await self.runJob(job,kind:"repair")
    }}
    func resumeJob() {guard let id=project?.jobID else{return};let kind=project?.jobKind ?? "repair";perform{try await self.runJob(["job_id":id],kind:kind)}}
    func runJob(_ initial:[String:Any],kind:String) async throws {
        guard let projectID = project?.id else { return }
        guard let id=initial["job_id"] as? String ?? initial["id"] as? String else{throw ServiceFailure(message:"Service omitted the job identifier.")}
        update{$0.jobID=id;$0.jobKind=kind;$0.stage="Processing";if kind=="repair" {$0.repairID=initial["repair_id"] as? String ?? $0.repairID}}
        for _ in 0..<1200 {
            try Task.checkCancellation()
            let job=try await object("v1/jobs/\(id)")
            guard project?.id == projectID else { throw CancellationError() }
            let state=job["state"] as? String ?? "queued"
            progress="\(state.replacingOccurrences(of:"_",with:" ").capitalized) · \(job["message"] ?? "")"
            if state=="complete" || state=="needs_input" {
                let result=job["result"] as? [String:Any] ?? [:]
                let resultArtifacts=result["artifacts"] as? [[String:Any]] ?? []
                if state=="needs_input" && (resultArtifacts.isEmpty || (kind=="repair" && !resultArtifacts.contains(where:{$0["name"] as? String=="part.step"}))) {
                    let questions=result["questions"] as? [String] ?? (result["intent"] as? [String:Any])?["questions"] as? [String] ?? []
                    warnings=questions.isEmpty ? ["More observations or confirmed critical dimensions are required."] : questions
                    candidateQuestions=warnings
                    if let dir=projectDirectory {try JSONSerialization.data(withJSONObject:result,options:.prettyPrinted).write(to:dir.appendingPathComponent("needs_input.json"),options:.atomic)}
                    progress="Needs measurements: "+warnings.joined(separator:" ")
                    update{$0.pendingRepairBody=nil;$0.pendingRepairFingerprint=nil;$0.pendingRepairRoute=nil}
                } else {try await receive(result,kind:kind)}
                guard project?.id == projectID else { throw CancellationError() }
                update{$0.jobID=nil;if kind=="reconstruction" {$0.pendingReconstructionID=nil;$0.pendingReconstructionFingerprint=nil};$0.stage=state=="needs_input" ? "Needs measurements":(kind=="repair" ? "CAD checks passed":"Scan reconstructed")}
                if state=="needs_input" {warnings.append("More views or confirmed measurements are required. Review the quality report.")}
                return
            }
            if state=="failed" || state=="cancelled" {
                update{$0.jobID=nil;$0.stage=state.capitalized;$0.pendingRepairBody=nil;$0.pendingRepairFingerprint=nil;$0.pendingRepairRoute=nil;$0.pendingReconstructionID=nil;$0.pendingReconstructionFingerprint=nil}
                if state=="cancelled" {throw CancellationError()}
                let detail=(job["error"] as? [String:Any])?["message"] as? String ?? job["error"] as? String ?? job["message"] as? String ?? "Review the input and validation report before retrying."
                throw ServiceFailure(message:detail)
            }
            try await Task.sleep(for:.seconds(1))
        }
        throw ServiceFailure(message:"Still processing. Your job is saved; use Resume job to check it later.")
    }
    func receive(_ result:[String:Any],kind:String) async throws {
        guard let dir=projectDirectory,let p=project,let url=URL(string:serverURL) else{return}
        if kind == "reconstruction" && !ReconstructionIdentity.matches(result, scanID: savedScanID) {
            throw ServiceFailure(message: "The returned result belongs to a different scan. Your saved capture is unchanged; reprocess this scan.")
        }
        let list=result["artifacts"] as? [[String:Any]] ?? []
        let decoder=JSONDecoder()
        let infos=try decoder.decode([ArtifactInfo].self,from:JSONSerialization.data(withJSONObject:list))
        let revision=result["revision"] as? Int ?? (p.revision+1)
        let key=kind=="repair" ? "repair-\(result["repair_id"] as? String ?? p.repairID ?? p.id)-r\(revision)" : "scan-\(p.jobID ?? UUID().uuidString)"
        let published=try await VerifiedArtifactStore.download(infos:infos,baseDirectory:dir.appendingPathComponent("revisions"),revisionKey:key,client:ServiceClient(baseURL:url,token:token))
        guard project?.id == p.id else { throw CancellationError() }
        if kind == "reconstruction" {
            counterpartMesh = nil
            try? FileManager.default.removeItem(at: dir.appendingPathComponent("counterpart_preview.json"))
        }
        // No observable revision state changes until the complete immutable artifact set is verified.
        for artifact in infos {
            let file=published.appendingPathComponent(artifact.name)
            if artifact.name=="counterpart_preview.json" {let data=try Data(contentsOf:file);counterpartMesh=try decoder.decode(MeshPreview.self,from:data);try data.write(to:dir.appendingPathComponent("counterpart_preview.json"),options:.atomic)}
            if artifact.name=="scan_preview.json" {let data=try Data(contentsOf:file);scanMesh=try decoder.decode(MeshPreview.self,from:data);try data.write(to:dir.appendingPathComponent("scan_preview.json"),options:.atomic)}
            if kind=="repair" && ["preview.json","part_preview.json","mesh.json"].contains(artifact.name) {let data=try Data(contentsOf:file);partMesh=try decoder.decode(MeshPreview.self,from:data);try data.write(to:dir.appendingPathComponent("part_preview.json"),options:.atomic)}
        }
        if kind=="reconstruction" {
            try JSONSerialization.data(withJSONObject: ["folder": "revisions/"+key, "artifacts": list, "scan_id": savedScanID ?? ""], options: .prettyPrinted).write(to: dir.appendingPathComponent("observed_artifacts.json"), options: .atomic)
            let reconstruction=result["reconstruction"] as? [String:Any] ?? result
            sparseReport = reconstruction["sparse_reconstruction"] as? [String: Any]
            updatePhotoDetail(reconstruction)
            reconstructionNeedsUpdate = false
            measurements=reconstruction["measurements"] as? [[String:Any]] ?? []
            if !p.cropEnabled,let bounds=reconstruction["bounds_mm"] as? [String:Any],let low=bounds["min"] as? [Double],let high=bounds["max"] as? [Double],low.count==3,high.count==3 {update{$0.cropMin=low.map{$0-1};$0.cropMax=high.map{$0+1}}}
            warnings=reconstruction["warnings"] as? [String] ?? []
            try JSONSerialization.data(withJSONObject:reconstruction,options:.prettyPrinted).write(to:dir.appendingPathComponent("reconstruction.json"),options:.atomic)
        } else {
            let newValidation=result["validation"] as? [String:Any] ?? [:]
            try JSONSerialization.data(withJSONObject:newValidation,options:.prettyPrinted).write(to:dir.appendingPathComponent("validation.json"),options:.atomic)
            try JSONEncoder().encode(infos).write(to:dir.appendingPathComponent("artifacts.json"),options:.atomic)
            artifacts=infos;validation=newValidation
            update {
                if $0.revision>0 && $0.exportFolder != "revisions/"+key {
                    let trial=TrialRecord(revisionKey:$0.exportFolder,revision:$0.revision,fit:$0.physicalFit,feedback:$0.feedback,printer:$0.printer,iterations:$0.printIterations)
                    $0.trialHistory=($0.trialHistory ?? [])+[trial]
                    $0.physicalFit="Not tested";$0.feedback="";$0.printIterations=0
                }
                $0.repairID=result["repair_id"] as? String ?? $0.repairID
                if let actualParameters=result["parameters"] as? [String:Double] {$0.parameters=actualParameters}
                if let actualFamily=result["family"] as? String {$0.family=actualFamily}
                $0.revision=revision;$0.exportFolder="revisions/"+key;$0.verifiedArtifacts=infos
                $0.pendingRepairBody=nil;$0.pendingRepairFingerprint=nil;$0.pendingRepairRoute=nil
            }
            progress="CAD artifacts downloaded and checksum verified. Physical fit remains untested for this revision."
        }
    }
    func suggestCandidates() {perform {
        guard let p=self.project,let scanID=p.scanID else{throw ServiceFailure(message:"Process a scan first.")}
        _ = try await self.object("v1/scans/\(scanID)/annotations",method:"PUT",json:self.annotationJSON())
        let response=try await self.object("v1/scans/\(scanID)/candidates",method:"POST",json:["family":p.family,"attachment_method":p.attachment])
        self.candidates=response["candidates"] as? [[String:Any]] ?? []
        self.candidateQuestions=response["questions"] as? [String] ?? []
        self.candidateNotes=response["evidence_notes"] as? [String] ?? []
        self.progress=self.candidates.isEmpty ? "More contact evidence is needed. Review the questions below." : "Evidence-linked candidates ready. Review assumptions and missing measurements."
    }}
    func applyCandidate(_ candidate:[String:Any]) {
        guard let params=candidate["parameters"] as? [String:Double] else{return}
        update {p in
            var updated=params
            for dimension in p.dimensions where dimension.confirmed && dimension.critical {if updated[dimension.name] != nil {updated[dimension.name]=dimension.value}}
            p.parameters=updated;p.candidateID=candidate["id"] as? String
            p.candidateProvenance=(candidate["provenance"] as? [String:[String:Any]])?.mapValues {value in
                let source=value["source"] as? String ?? "design_inference"
                if source=="design_inference" {return "Proposed design dimension — not observed"}
                if value["confirmed"] as? Bool == true {return "Confirmed evidence-based constraint"}
                return "Derived from selected scan evidence — confirmation and uncertainty review required"
            }
        }
    }
    func cancel() {
        cancelRequested=true
        if let id=project?.jobID {Task {do {_ = try await object("v1/jobs/\(id)/cancel",method:"POST",json:[:]);activeTask?.cancel();update{$0.stage="Cancelled";$0.jobID=nil;$0.pendingReconstructionID=nil;$0.pendingReconstructionFingerprint=nil;$0.pendingRepairBody=nil;$0.pendingRepairFingerprint=nil;$0.pendingRepairRoute=nil}} catch {self.error=error.localizedDescription}}} else {activeTask?.cancel()}
    }
    var validForExport: Bool {
        if let valid=validation["valid"] as? Bool {return valid}
        if let passed=validation["passed"] as? Bool {return passed}
        if let status=validation["status"] as? String {return ["passed","valid","ready","ready_for_test_print"].contains(status)}
        return false
    }
    private func updatePhotoDetail(_ info: [String: Any]) {
        automaticRoute = info["automatic_route"] as? [String: Any]
        planarRepair = info["planar_repair"] as? [String: Any]
        faceRepair = info["face_repair"] as? [String: Any]
        selectedComparisonID = nil; comparisonScan = nil; comparisonPart = nil; comparisonReviewed = false
        if let value = info["comparison"], let data = try? JSONSerialization.data(withJSONObject: value) {
            comparison = try? JSONDecoder().decode(ComparisonReport.self, from: data)
        } else { comparison = nil }
        patternMesh = nil; selectedPatternID = nil; patternReviewed = false
        if let report = info["pattern_hypotheses"] as? [String: Any],
           let values = report["candidates"], let data = try? JSONSerialization.data(withJSONObject: values) {
            patternRepairs = (try? JSONDecoder().decode([PatternRepairOption].self, from: data)) ?? []
        } else { patternRepairs = [] }
        let notes = info["warnings"] as? [String] ?? []
        let counterpart = info["counterpart"] as? [String: Any] ?? [:]
        exteriorEstimated = counterpart["geometry_is_estimated"] as? Bool == true && counterpart["watertight_replacement"] as? Bool == true
        scanNeedsRescan = !exteriorEstimated && ((faceRepair != nil && info["status"] as? String == "needs_input") || notes.contains { $0.hasPrefix("cross_view_depth_inconsistency") || $0.hasPrefix("rgb_pose_inconsistency") })
        let alignment = info["photo_alignment"] as? [String: Any] ?? [:]
        let photosAligned = alignment["status"] as? String == "aligned_photos"
        let alignedCount = alignment["registered_frames"] as? Int ?? 0
        scanFailureTitle = photosAligned ? "Replacement not resolved" : "Scan didn’t line up"
        if scanNeedsRescan && photosAligned {
            repairMessage = alignment["repair_failure"] as? String ?? counterpart["reason"] as? String ?? "The photos aligned, but no supported replacement was found. Review the saved scan."
        } else if scanNeedsRescan {
            repairMessage = "The captured views could not be combined reliably. Keep the object still and take sharp, overlapping views of the intact feature and damaged opening."
        } else {
            repairMessage = patternRepairs.isEmpty ? (counterpart["reason"] as? String ?? "") : "Possible repairs found. Choose one to compare with the missing area."
        }
        counterpartPrintable = (info["counterpart"] as? [String: Any])?["watertight_replacement"] as? Bool ?? false
        let detail = info["photo_detail"] as? [String: Any] ?? [:]
        photoDetailStatus = exteriorEstimated ? "Observed donor outline · inferred side shape and depth" : scanNeedsRescan ? (photosAligned ? "\(alignedCount) photos aligned. Fine surface geometry and the missing part remain unresolved." : "Photo alignment needs more overlapping, sharp views.") : detail["status"] as? String == "photo_detail_integrated"
            ? "Photo detail matched across views · accuracy uncalibrated"
            : "Fine photo detail unresolved. Try closer, sharp overlapping views."
    }

    func selectComparison(_ id: String) {
        guard !busy else { return }
        comparisonReviewed = false; comparisonScan = nil; comparisonPart = nil; selectedComparisonID = nil
        guard let variant = comparison?.variants.first(where: { $0.id == id }) else { return }
        perform {
            let (directory, infos) = try self.observedArtifactLocation()
            try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: directory) }.value
            func mesh(_ name: String?) throws -> MeshPreview? {
                guard let name else { return nil }
                guard infos.contains(where: { $0.name == name }) else { throw ServiceFailure(message: "A comparison preview is missing. Reprocess the scan.") }
                return try JSONDecoder().decode(MeshPreview.self, from: Data(contentsOf: directory.appendingPathComponent(name)))
            }
            let scan = try mesh(variant.scan_preview), part = try mesh(variant.part_preview)
            self.comparisonScan = scan; self.comparisonPart = part; self.selectedComparisonID = id
        }
    }
    func exportComparison() { perform {
        guard self.comparisonReviewed, let variant = self.selectedComparison, variant.printable,
              variant.status == "proposal_needs_review", !variant.print_files.isEmpty,
              variant.print_files.contains(where: { $0.hasSuffix(".stl") }),
              variant.print_files.contains(where: { $0.hasSuffix(".3mf") }) else {
            throw ServiceFailure(message: "Review a closed exterior proposal before test-print export.")
        }
        let (directory, infos) = try self.observedArtifactLocation()
        let names = variant.print_files + ["comparison.json"]
        guard names.allSatisfy({ name in infos.contains { $0.name == name } }) else {
            throw ServiceFailure(message: "The comparison export is incomplete. Reprocess the scan.")
        }
        try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: directory) }.value
        self.shareURLs = names.map { directory.appendingPathComponent($0) }; self.showingShare = true
    }}

    func selectPattern(_ id: String) {
        patternReviewed = false; patternMesh = nil; selectedPatternID = nil
        guard let option = patternRepairs.first(where: { $0.id == id }) else { return }
        perform {
            let (directory, infos) = try self.observedArtifactLocation()
            try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: directory) }.value
            let name = option.print_preview ?? option.preview
            guard infos.contains(where: { $0.name == name }) else { throw ServiceFailure(message: "Proposal preview is missing. Reprocess this scan.") }
            let mesh = try JSONDecoder().decode(MeshPreview.self, from: Data(contentsOf: directory.appendingPathComponent(name)))
            self.patternMesh = mesh; self.selectedPatternID = id
        }
    }

    private var savedScanID: String? {
        if let dir = scanDirectory,
           let data = try? Data(contentsOf: dir.appendingPathComponent("manifest.json")),
           let manifest = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let id = manifest["scan_id"] as? String { return id }
        return project?.scanID
    }

    private func observedArtifactLocation() throws -> (URL, [ArtifactInfo]) {
        guard let dir = projectDirectory else { throw ServiceFailure(message: "Open a saved scan first.") }
        let reconstruction = try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("reconstruction.json"))) as? [String: Any] ?? [:]
        guard ReconstructionIdentity.matches(reconstruction, scanID: savedScanID) else {
            throw ServiceFailure(message: "The saved result belongs to another scan. Reprocess this scan before opening or exporting its result.")
        }
        let record = try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("observed_artifacts.json"))) as? [String: Any]
        guard let folder = record?["folder"] as? String, folder.hasPrefix("revisions/"), !folder.contains(".."),
              let list = record?["artifacts"] as? [[String: Any]] else { throw ServiceFailure(message: "The scan's verified files are unavailable. Reprocess the scan.") }
        if let id = record?["scan_id"] as? String, id != savedScanID {
            throw ServiceFailure(message: "The saved files belong to another scan. Reprocess this scan.")
        }
        let provenanceURL = dir.appendingPathComponent(folder).appendingPathComponent("input_provenance.json")
        if FileManager.default.fileExists(atPath: provenanceURL.path) {
            let provenance = try JSONSerialization.jsonObject(with: Data(contentsOf: provenanceURL)) as? [String: Any] ?? [:]
            guard ReconstructionIdentity.matches(provenance, scanID: savedScanID) else {
                throw ServiceFailure(message: "The saved files do not match this capture. Reprocess this scan.")
            }
        }
        let infos = try JSONDecoder().decode([ArtifactInfo].self, from: JSONSerialization.data(withJSONObject: list))
        return (dir.appendingPathComponent(folder), infos)
    }

    var standaloneExportFormats: [String] {
        guard let (directory, _) = try? observedArtifactLocation(),
              let data = try? Data(contentsOf: directory.appendingPathComponent("scan_export.json")),
              let report = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              report["status"] as? String == "ready", let files = report["files"] as? [String] else { return [] }
        return ["STL", "PLY", "STEP", "Measurements"].filter { format in
            files.contains { format == "Measurements" ? $0 == "measurements.json" : $0.lowercased().hasSuffix("." + format.lowercased()) }
        }
    }

    func exportStandaloneScan(format: String? = nil) { perform {
        let (directory, infos) = try self.observedArtifactLocation()
        let report = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("scan_export.json"))) as? [String: Any]
        guard report?["status"] as? String == "ready", let names = report?["files"] as? [String],
              !names.isEmpty, names.allSatisfy({ name in infos.contains { $0.name == name } }) else {
            throw ServiceFailure(message: "This scan needs more usable views before measured export. The original capture is still available.")
        }
        try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: directory) }.value
        let selectedNames = names.filter { name in
            guard let format else { return true }
            return format == "Measurements" ? name == "measurements.json" : name.lowercased().hasSuffix("." + format.lowercased())
        }
        guard !selectedNames.isEmpty else { throw ServiceFailure(message: "This reconstruction cannot export \(format ?? "that format"). Other supported formats and the original capture remain available.") }
        self.shareURLs = (selectedNames + ["scan_export.json", "input_provenance.json"]).filter { name in infos.contains { $0.name == name } }.map { directory.appendingPathComponent($0) }
        self.showingShare = true
    }}

    func exportPattern() { perform {
        guard !self.scanNeedsRescan, self.patternReviewed, let option = self.selectedPattern,
              option.validation.watertight else { throw ServiceFailure(message: "Review a closed proposal before exporting a test print.") }
        let (directory, infos) = try self.observedArtifactLocation()
        let names = option.validation.files + [option.id + "_validation.json", "pattern_hypotheses.json"]
        guard !option.validation.files.isEmpty, names.allSatisfy({ name in infos.contains { $0.name == name } }) else {
            throw ServiceFailure(message: "The validated print files are incomplete. Reprocess this scan.")
        }
        try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: directory) }.value
        self.shareURLs = names.map { directory.appendingPathComponent($0) }
        self.showingShare = true
    }}

    func exportObservedSurface(printableOnly: Bool = false) { perform {
        guard !self.scanNeedsRescan else { throw ServiceFailure(message: self.repairMessage) }
        if self.exteriorEstimated && !printableOnly { throw ServiceFailure(message: "Only the estimated replacement is exportable; the original scan did not align.") }
        let (directory, infos) = try self.observedArtifactLocation()
        guard infos.contains(where: { $0.name == (printableOnly ? "printable_edge.stl" : "observed_surface.stl") }) else {
            throw ServiceFailure(message: "No surface mesh was reconstructed. Capture more views and try again.")
        }
        try await Task.detached { try VerifiedArtifactStore.verify(infos: infos, directory: directory) }.value
        if printableOnly && !infos.contains(where: { $0.name == "printable_edge.stl" }) {
            throw ServiceFailure(message: "No validated closed piece is available. Scan both sides of the intact edge again.")
        }
        let names = printableOnly
            ? try ExteriorPrintFiles.names(report: self.faceRepair, available: Set(infos.map(\.name)))
            : ["observed_surface.stl", "observed_surface_mm.ply", "reconstruction.json", "input_provenance.json", "photo_detail.json", "counterpart.json", "counterpart_surface.stl"].filter { name in infos.contains { $0.name == name } }
        self.shareURLs = names.map { directory.appendingPathComponent($0) }
        self.showingShare = true
    }}

    func exportArtifacts() {
        guard validForExport,let p=project,let dir=projectDirectory else{error="Export requires a valid CAD solid and verified mesh.";return}
        if !p.acknowledged {error="Acknowledge unresolved fit before prototype export.";return}
        guard let folder=p.exportFolder else{error="No complete revision is available.";return}
        let artifactDirectory=dir.appendingPathComponent(folder)
        perform {
            let infos=self.artifacts
            try await Task.detached {try VerifiedArtifactStore.verify(infos:infos,directory:artifactDirectory)}.value
            self.shareURLs=self.artifacts.map{artifactDirectory.appendingPathComponent($0.name)}
            guard !self.shareURLs.isEmpty else{throw ServiceFailure(message:"No verified artifacts are available.")}
            self.update{$0.exportedRevision=$0.revision};self.showingShare=true
        }
    }
    func exportScan() {
        guard let dir=scanDirectory,FileManager.default.fileExists(atPath:dir.path) else{error="Capture a scan first.";return}
        perform {
            let archive=try await CaptureExport.archive(directory:dir)
            guard let projectDirectory=self.projectDirectory else{return}
            let evidence=projectDirectory.appendingPathComponent("annotations.json")
            try JSONSerialization.data(withJSONObject:self.annotationJSON(),options:[.prettyPrinted,.sortedKeys]).write(to:evidence,options:.atomic)
            self.shareURLs=[archive,evidence];self.showingShare=true
        }
    }
    func importScan(_ source:URL) {
        perform {
            guard let dest=self.scanDirectory else{return}
            let access=source.startAccessingSecurityScopedResource();defer{if access{source.stopAccessingSecurityScopedResource()}}
            guard FileManager.default.fileExists(atPath:source.appendingPathComponent("manifest.json").path) else{throw ServiceFailure(message:"Select the scan package folder containing manifest.json.")}
            if FileManager.default.fileExists(atPath:dest.path) {throw ServiceFailure(message:"This project already has a scan. Create a new project to import without overwriting observations.")}
            _ = try await Task.detached {try CaptureIO.importPackage(from:source,to:dest)}.value;self.didCapture(dest);self.progress="Imported scan saved locally. Service validation runs before processing."
        }
    }
    func deleteProject(server:Bool) {perform {
        guard let p=self.project else{return}
        if server {_ = try await self.object("v1/projects/\(p.id)",method:"DELETE")}
        try FileManager.default.removeItem(at:self.directory(p.id));self.selectedID=nil;self.reload()
    }}
}
