import Foundation
import ReverseCADCore

/// Separate captures retain their own poses. First-pass geometry is not silently fused across a new AR origin.
struct TwoPassScan: Codable {
    var stage: String
    var firstScanID: String
    var displayBox: [Double]? = nil
    static func load(_ project: URL) -> Self? {
        guard let data=try? Data(contentsOf:project.appendingPathComponent("two-pass.json")) else{return nil}
        return try? JSONDecoder().decode(Self.self,from:data)
    }
    func save(_ project: URL) throws { try CaptureIO.atomicWrite(self,to:project.appendingPathComponent("two-pass.json")) }
    static func prepareDetail(project: URL,capture: URL) throws {
        guard var state=load(project) else {throw ServiceFailure(message:"The identification pass is missing. Your saved capture is preserved.")}
        if state.stage == "detail_capturing" { return }
        guard state.stage == "identification_captured",let selected=try ObjectSelectionReference.load(project:project,capture:capture),selected.detection != nil else {throw ServiceFailure(message:"Identify the saved first pass before starting the detail pass.")}
        _=try ScanPackageWriter.validate(directory:capture)
        let original=project.appendingPathComponent("identification-pass",isDirectory:true)
        guard !FileManager.default.fileExists(atPath:original.path) else {throw ServiceFailure(message:"The first pass is already preserved. Reopen this saved scan to continue.")}
        // The untouched first pass remains recoverable even if second-pass preparation fails.
        try FileManager.default.moveItem(at:capture,to:original)
        do {
            try FileManager.default.createDirectory(at:capture,withIntermediateDirectories:true)
            try FileManager.default.copyItem(at:original,to:capture.appendingPathComponent("identification-pass",isDirectory:true))
            var reference=selected;reference.imagePath="identification-pass/"+selected.imagePath
            try CaptureIO.atomicWrite(reference,to:project.appendingPathComponent("object-selection.json"))
            let old=project.appendingPathComponent("object-identity.json")
            if FileManager.default.fileExists(atPath:old.path) {
                try FileManager.default.copyItem(at:old,to:project.appendingPathComponent("identification-object-identity.json"))
                try FileManager.default.copyItem(at:old,to:capture.appendingPathComponent("identification-identity.json"))
                try FileManager.default.removeItem(at:old)
            }
            state.stage="detail_capturing";try state.save(project)
        } catch {
            try? FileManager.default.removeItem(at:capture)
            try? FileManager.default.moveItem(at:original,to:capture)
            try? CaptureIO.atomicWrite(selected,to:project.appendingPathComponent("object-selection.json"))
            throw error
        }
    }
}
