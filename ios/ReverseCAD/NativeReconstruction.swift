import Foundation
import ImageIO
import simd
import ReverseCADCore

/// Complete local reconstruction. There is deliberately no URLSession,
/// service client, network address or credential in this computation.
enum NativeReconstruction {
    struct Result {let directory:URL;let infos:[ArtifactInfo];let report:[String:Any]}
    static func run(capture:URL,project:URL,target:[String:Any],repair:Bool,thicknessMM:Double?,progress:@escaping @Sendable (String)->Void) throws -> Result {
        try Task.checkCancellation()
        progress("Checking the saved capture on this iPhone…")
        let manifest=try ScanPackageWriter.validate(directory:capture)
        guard target["confirmed"] as? Bool==true,let records=target["frames"] as? [String:[String:Any]] else {throw ServiceFailure(message:"Identify the saved object before building its model.")}
        let frames=try CaptureIO.readFrames(directory:capture)
        var observations=[NativeScanObservation]()
        for frame in frames where frame.quality.accepted && frame.trackingState=="normal" {
            guard let record=records[frame.frameID],let path=record["mask_path"] as? String,let hash=record["mask_sha256"] as? String,
                  record["rgb_sha256"] as? String == (try CaptureIO.sha256(file:CaptureIO.safeURL(directory:capture,path:frame.rgbPath))) else{continue}
            let data=try Data(contentsOf:CaptureIO.safeURL(directory:capture,path:path))
            guard CaptureIO.sha256(data)==hash else{throw ServiceFailure(message:"The saved object mask changed. Identify this capture again.")}
            observations.append(try NativeScanObservation(root:capture,frame:frame,mask:data))
        }
        guard observations.count>=3,RepresentativeViews.select(observations.map(\.frame)).count>=3 else {throw ServiceFailure(message:"Add sharp views from at least three different sides. This capture has too few separated, identified object views; it is saved for recovery.")}
        let stage=project.appendingPathComponent(".building-"+UUID().uuidString)
        try FileManager.default.createDirectory(at:stage,withIntermediateDirectories:true)
        defer {try? FileManager.default.removeItem(at:stage)}
        progress("Refining camera alignment on this iPhone…")
        let registration=try refine(&observations)
        var earlier=try earlierPass(capture:capture)
        // Rear reconstruction never consults selfie/TrueDepth setup, including
        // references attached to older saved scans. Keep those originals intact.
        let calibration: [String:Any] = ["status":"uncalibrated_sensor_scale","reference_registered":false,
            "correction_applied":false,"correction":[0.0,0.0,0.0],"physical_accuracy_validated":false,
            "reason":"Selfie calibration is not used. Dimensions use recorded rear sensor scale."]
        try cameraJSONWrite(calibration,stage.appendingPathComponent("phone-calibration.json"))
        var warnings=["Approximate model using recorded rear sensor scale. Physical dimensional accuracy has not been independently validated.","Unobserved surfaces and genuine holes remain open. This model is not automatically made watertight."]
        var crossPass:[String:Any]=["status":"single_saved_pass"]
        if !earlier.isEmpty {
            progress("Registering both saved passes…")
            if let fit=try register(earlier:&earlier,detail:&observations) {
                for i in earlier.indices {earlier[i].opticalWorld=fit.pose*earlier[i].opticalWorld}
                crossPass=["status":"registered","inliers":fit.inliers.count,"held_out_rmse_m":fit.heldOutRMSE,"first_to_detail":ARKitCaptureProvider.columnMajor(fit.pose)]
            } else {
                crossPass=["status":"identity_reference_only","reason":"Insufficient shared textured features for a measured cross-pass transform."]
                warnings.append("The first pass supplied object identity. Its geometry could not be aligned reliably and was excluded; the detail pass supplies this surface.")
                earlier=[]
            }
        }
        progress("Refining observed details from all three rear cameras…")
        var stereo=["ultra":0,"tele":0]
        var trajectories=[String:[NativeAuxiliaryStereo.Pose]]()
        for i in observations.indices {
            try Task.checkCancellation()
            let path=observations[i].root.path
            if trajectories[path]==nil {trajectories[path]=NativeAuxiliaryStereo.trajectory(observations[i].root)}
            if i%max(1,observations.count/12)==0 {
                let counts=try NativeAuxiliaryStereo.run(&observations[i],poses:trajectories[path] ?? [])
                for (name,count) in counts {stereo[name,default:0]+=count}
            }
        }
        if stereo.values.reduce(0,+)==0 {warnings.append("Auxiliary-camera matches did not pass the metric consistency checks. This surface uses the supported wide-camera and LiDAR observations.")}
        let all=observations+earlier
        var fusion=NativeSurfaceFusion()
        var used=0
        for (i,observation) in all.enumerated() {
            try Task.checkCancellation()
            progress("Combining observed object surfaces… \(i+1) of \(all.count)")
            let origin=observation.opticalWorld.columns.3
            let neighboring=all.indices.filter{$0 != i}.sorted {simd_distance_squared(all[$0].opticalWorld.columns.3,origin)<simd_distance_squared(all[$1].opticalWorld.columns.3,origin)}.prefix(5).map{all[$0]}
            let surface=try observation.surface(comparing:neighboring)
            if !surface.faces.isEmpty {try fusion.add(surface);used+=1}
        }
        guard used>=3 else{throw ServiceFailure(message:"The selected object has too few consistent surfaces. Add closer views above and around its sides. Your complete capture is preserved.")}
        let mesh=try fusion.finish()
        guard mesh.faces.count>=100 else{throw ServiceFailure(message:"The object surface is too sparse for a usable model. Add closer, sharper views of its missing areas.")}
        progress("Saving the finished model and exports on this iPhone…")
        let files=try NativeMeshExport.write(mesh,to:stage,stem:"observed_object")
        try CaptureIO.atomicWrite(mesh.preview,to:stage.appendingPathComponent("scan_preview.json"))
        let low=mesh.vertices.reduce(SIMD3<Float>(repeating:.infinity)){simd_min($0,$1)},high=mesh.vertices.reduce(SIMD3<Float>(repeating:-.infinity)){simd_max($0,$1)}
        func mm(_ p:SIMD3<Float>)->[Double] {[Double(p.x)*1000,Double(p.y)*1000,Double(p.z)*1000]}
        let bounds:[String:Any]=["min":mm(low),"max":mm(high),"size":mm(high-low)]
        let measurements=(0..<3).map {axis -> [String:Any] in ["name":["Observed width","Observed height","Observed depth"][axis],"value":Double((high-low)[axis])*1000,"unit":"mm","source":"observed_surface_extent","accuracy":"not_independently_validated","complete_object_dimension":false]}
        let scanID=manifest.scanID
        var report:[String:Any]=["schema_version":1,"scan_id":scanID,"status":"ready","processing_location":"iPhone","network_requests":0,"implementation":"native-rgbd-surface-v1","bounds_mm":bounds,"measurements":measurements,"warnings":warnings,
            "surface":["kind":"observed_depth_cells","vertices":mesh.vertices.count,"triangles":mesh.faces.count,"boundary_edges":mesh.boundaryEdges,"hole_filling":false],
            "registration":registration,"cross_pass":crossPass,"three_camera_stereo_refined_samples":stereo,"accepted_object_views":used,"phone_calibration":calibration,
            "photo_detail":["status":stereo.values.reduce(0,+)>0 ? "photo_detail_integrated":"insufficient_evidence"]]
        if repair {
            progress("Checking supported damage and repair geometry on this iPhone…")
            let proposed=try NativeRepair.build(mesh:mesh,thicknessMM:thicknessMM,directory:stage)
            report["automatic_route"]=["family":"rectangular_planar","reason":proposed.reason]
            if proposed.preview != nil {report["planar_repair"]=proposed.report}
            report["counterpart"]=["watertight_replacement":proposed.printable,"reason":proposed.reason,"geometry_is_estimated":true]
            if let preview=proposed.preview {try CaptureIO.atomicWrite(preview.preview,to:stage.appendingPathComponent("counterpart_preview.json"))}
        }
        try cameraJSONWrite(report,stage.appendingPathComponent("reconstruction.json"))
        try cameraJSONWrite(["scan_id":scanID,"unit":"mm","bounds_mm":bounds,"measurements":measurements,"physical_accuracy":"not_independently_validated"],stage.appendingPathComponent("measurements.json"))
        try cameraJSONWrite(["schema_version":1,"scan_id":scanID,"status":"ready","unit":"mm","files":files+["measurements.json"],"processing_location":"iPhone","cad_kind":"faceted observed surface","boundary_edges":mesh.boundaryEdges,"hidden_surfaces":"unknown; no hole filling","dimensional_accuracy":"not_independently_validated"],stage.appendingPathComponent("scan_export.json"))
        try cameraJSONWrite(["schema_version":1,"scan_id":scanID,"source_frames_sha256":CaptureIO.sha256(file:capture.appendingPathComponent("frames.jsonl")),"processing_location":"iPhone","capture_source":manifest.source,"calibration_scale":"recorded metric depth; no category scale","raw_capture_exported":false],stage.appendingPathComponent("input_provenance.json"))
        try Task.checkCancellation()
        let published=try VerifiedArtifactStore.publishLocal(stage:stage,baseDirectory:project.appendingPathComponent("revisions"),revisionKey:"local-"+UUID().uuidString)
        return Result(directory:published.0,infos:published.1,report:report)
    }
    static func refine(_ observations:inout [NativeScanObservation]) throws -> [String:Any] {
        var corrected=0
        for i in observations.indices {
            try Task.checkCancellation();try observations[i].loadFeatures()
            guard i>0 else{continue}
            if let fit=NativeRegistration.fit(NativeScanObservation.matches(observations[i],observations[i-1])) {
                let delta=fit.pose,t=SIMD3(delta.columns.3.x,delta.columns.3.y,delta.columns.3.z)
                let angle=2*acos(min(1,abs(simd_quatf(delta).real)))
                if simd_length(t)<0.03,angle<0.08 {
                    for j in i..<observations.count {observations[j].opticalWorld=delta*observations[j].opticalWorld}
                    corrected+=1
                }
            }
        }
        return ["method":"full_scene_rgbd_tracking_plus_rigid_feature_refinement","refined_keyframes":corrected,"scale_fitted":false]
    }
    static func earlierPass(capture:URL) throws -> [NativeScanObservation] {
        let root=capture.appendingPathComponent("identification-pass"),path=capture.appendingPathComponent("identification-identity.json")
        guard FileManager.default.fileExists(atPath:path.path) else{return []}
        let identity=try JSONDecoder().decode(SavedObjectIdentity.self,from:Data(contentsOf:path))
        guard identity.sourceFramesSHA256 == (try CaptureIO.sha256(file:root.appendingPathComponent("frames.jsonl"))) else {throw ServiceFailure(message:"The first-pass identity does not match its captured views.")}
        let frames=try CaptureIO.readFrames(directory:root)
        var result=[NativeScanObservation]()
        for i in identity.confirmedIndices {
            try Task.checkCancellation()
            guard identity.frameIDs.indices.contains(i),identity.detections.indices.contains(i),let box=identity.detections[i].box,
                  let frame=frames.first(where:{$0.frameID==identity.frameIDs[i]}),let src=CGImageSourceCreateWithURL(try CaptureIO.safeURL(directory:root,path:frame.rgbPath) as CFURL,nil),let image=CGImageSourceCreateImageAtIndex(src,0,nil),
                  let mask=try SavedObjectMasks.mask(image:image,box:CGRect(x:box.left,y:box.top,width:box.right-box.left,height:box.bottom-box.top),width:frame.depthWidth,height:frame.depthHeight) else{continue}
            result.append(try NativeScanObservation(root:root,frame:frame,mask:mask))
        }
        return result
    }
    static func register(earlier:inout [NativeScanObservation],detail:inout [NativeScanObservation]) throws -> NativeRegistration.Fit? {
        var best:NativeRegistration.Fit?
        let detailIndices=Array(stride(from:0,to:detail.count,by:max(1,detail.count/3)).prefix(3))
        for i in earlier.indices.prefix(10) {
            try earlier[i].loadFeatures()
            for j in detailIndices {
                try Task.checkCancellation();try detail[j].loadFeatures()
                if let fit=NativeRegistration.fit(NativeScanObservation.matches(earlier[i],detail[j])),fit.inliers.count>(best?.inliers.count ?? 0) {best=fit}
            }
        }
        return best
    }
}
