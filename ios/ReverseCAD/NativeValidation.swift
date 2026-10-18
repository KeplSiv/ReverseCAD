#if DEBUG
import SwiftUI
import ReverseCADCore

/// Explicitly synthetic diagnostic. Never enters or satisfies phone calibration.
enum NativeValidation {
    static func fixture(at root:URL)throws->(capture:URL,target:[String:Any]) {
        guard let source=Bundle.main.url(forResource:"SampleScan",withExtension:nil) else{throw ServiceFailure(message:"Synthetic diagnostic fixture is missing.")}
        let capture=root.appendingPathComponent("capture")
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try FileManager.default.copyItem(at:source,to:capture)
        var records=[String:[String:Any]]()
        for f in try CaptureIO.readFrames(directory:capture) {
            guard let path=f.maskPath else{continue}
            records[f.frameID]=["mask_path":path,"mask_sha256":try CaptureIO.sha256(file:capture.appendingPathComponent(path)),"rgb_sha256":try CaptureIO.sha256(file:capture.appendingPathComponent(f.rgbPath))]
        }
        return (capture,["confirmed":true,"frames":records,"category":"synthetic_test_fixture"])
    }
    static func run(root:URL,progress:@escaping @Sendable(String)->Void)throws->NativeReconstruction.Result {
        let fixture=try fixture(at:root)
        let start=Date()
        let result=try NativeReconstruction.run(capture:fixture.capture,project:root,target:fixture.target,repair:false,thicknessMM:nil,progress:progress)
        let repairs=root.appendingPathComponent("repair-validation")
        try FileManager.default.createDirectory(at:repairs,withIntermediateDirectories:true)
        let repair=try NativeRepair.build(mesh:damagedPlate(),thicknessMM:3,directory:repairs)
        guard repair.printable,!repair.files.isEmpty else{throw ServiceFailure(message:"Synthetic local repair diagnostic failed.")}
        try cameraJSONWrite(["status":"passed","source":"synthetic_fixture_executed_on_this_device","physical_accuracy_validated":false,"elapsed_s":Date().timeIntervalSince(start),"network_requests":0,"result_directory":result.directory.lastPathComponent,"repair_files":repair.files],root.appendingPathComponent("diagnostic.json"))
        return result
    }
    static func damagedPlate()throws->NativeMesh {
        var vertices=[SIMD3<Float>](),faces=[[Int]]()
        for y in 0...35 {for x in 0...50 {vertices.append(SIMD3(Float(x)*0.002,Float(y)*0.002,0))}}
        for y in 0..<35 {for x in 0..<50 {
            if x>=35 && y>=25 {continue}
            if (20...25).contains(x) && (13...18).contains(y) {continue}
            let a=y*51+x;faces += [[a,a+1,a+52],[a,a+52,a+51]]
        }}
        var fusion=NativeSurfaceFusion(voxel:0.0001);try fusion.add(NativeMesh(vertices:vertices,faces:faces));return try fusion.finish()
    }
}
struct NativeValidationView:View {
    @State private var message="Running local reconstruction diagnostic…"
    @State private var mesh:MeshPreview?
    var body:some View {
        VStack {
            Text("ReverseCAD · local diagnostic").font(.headline)
            if let mesh {GeometryPreview(scan:mesh,part:nil).frame(maxHeight:.infinity)}
            Text(message).padding()
        }.task {
            let root=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("NativeValidation/"+UUID().uuidString)
            do {
                let worker=Task.detached {try NativeValidation.run(root:root) {_ in}}
                let result=try await worker.value
                mesh=try JSONDecoder().decode(MeshPreview.self,from:Data(contentsOf:result.directory.appendingPathComponent("scan_preview.json")))
                message="Local model and exports passed. Synthetic fixture, not physical accuracy.\n"+root.lastPathComponent
            } catch {
                message=error.localizedDescription
                try? FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
                try? message.write(to:root.appendingPathComponent("failure.txt"),atomically:true,encoding:.utf8)
            }
        }
    }
}

struct PhoneJevValidationView:View {
    @State private var message="Checking direct phone identification…"
    var body:some View {
        Text(message).padding().task {
            let documents=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
            let root=documents.appendingPathComponent("MultiCameraValidation")
            let report=documents.appendingPathComponent("phone-jev-validation.json")
            do {
                let directories=try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:[.contentModificationDateKey]).filter{FileManager.default.fileExists(atPath:$0.appendingPathComponent("frames.jsonl").path)}.sorted{((try? $0.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)>((try? $1.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)}
                guard let capture=directories.first,let frame=try CaptureIO.readFrames(directory:capture).first else{throw ServiceFailure(message:"Capture a diagnostic view first.")}
                let image=try CapturedObjectWorkflow.requestImage(capture.appendingPathComponent(frame.rgbPath))
                let detection=try await JevClient().identifySavedView(jpeg:image,reference:image,description:"the object at the centre of the selected saved camera view",anchor:CGPoint(x:0.5,y:0.5),requestID:UUID(),apiKey:ReverseCADJevConfiguration.apiKey(),referenceBox:SelectionBox.initial)
                try cameraJSONWrite(["status":"response_received_on_phone","model":detection.model,"category":detection.category,"has_box":detection.box != nil,"request_count":1,"mac_service_used":false,"scope":"one saved physical view; not a multi-view identity validation"],report)
                message="Direct Jev response received on iPhone. One saved view; full identity consistency still needs a physical orbit."
            } catch {message=error.localizedDescription;try? cameraJSONWrite(["status":"failed","error":message],report)}
        }
    }
}
#endif
