# Implementation integration contract (v1)

All agents must read the entire specification and phone test plan. This contract coordinates modules; mandatory specification requirements still apply.

Python package: backend/reversecad. Tests: backend/tests. Python 3.11. snake_case JSON. Millimeters in CAD, meters in capture/point clouds. Matrices are 16 column-major values; T_a_b maps b to a. AR camera to CV uses diag(1,-1,-1,1). Intrinsics 9 column-major; scale using pixel centers. image orientation describes raw pixels, never a screen rotation.

Capture package directory: manifest.json {schema_version:1,scan_id:string,source:"synthetic"|"arkit"|"camera_manual",device:string,created_at:string,complete:bool,segments:[{segment_id:string,T_object_world:[16],registered:bool}],frame_count:int}, frames.jsonl, rgb/<id>.jpg, depth/<id>.f32, confidence/<id>.u8, masks/<id>.u8 optional, checksums.json {relativePath:sha256}. Optional video/review.mov, motion.jsonl, annotations.json. CaptureFrame: schema_version,scan_id,segment_id,frame_id,timestamp_s,rgb_path,rgb_width,rgb_height,orientation ("up" raw),depth_path nullable,depth_width,depth_height,depth_row_bytes,depth_byte_order:"little",confidence_path nullable,mask_path nullable,intrinsics:[9],intrinsics_width,intrinsics_height,T_world_camera:[16],tracking_state:"normal"|"limited"|"unavailable",quality:{blur_score:number,accepted:bool,reasons:[string]}. f32 files tightly packed after copying CV stride; row_bytes supports padded import. Missing depth explicit. RGB is calibrated full raw resolution. Every asset hash in checksums.

Annotations: {crop_min_m:[3]?,crop_max_m:[3]?,contacts:[{id,point_m:[3],normal:[3],radius_mm:number}],damage_points_m:[[3]],measurements:[{id,name,value,unit:"mm",source:"manual"|"depth_fit"|"design_inference",confirmed:bool,critical:bool,uncertainty_mm:number|null,observation_ids:[string]}],attachment_method:string,scale_reference:{measured_mm,observed_mm,uncertainty_mm}?,evidence_state:"missing_part"|"fragment"|"matching_part"}. Preserve user evidence and critical dimensions.

Reconstruction callable: reconstruct(scan_dir: Path, output_dir: Path, annotations: dict|None=None) -> dict; writes scan_preview.json and reconstruction.json. Result contains status (ready|needs_input), measurements, warnings, bounds_mm, point_count, primitives, metrics. scan_preview.json {vertices:[[x,y,z]...],triangles:[[i,j,k]...],colors:[[r,g,b]...]?,normals:[],unit:"mm"}; point cloud allowed empty triangles. Returned measurements follow annotations contract. Reject unregistered segments.

Sparse research extension: optional manifest `sparse_capture` version 1 with mode
`sparse_range_rgb`, explicit status, and checksummed packet/event/calibration paths;
per-frame `sensor_observation` carries physical camera identity, absolute source
clock, nullable arrival time and original image planes. The outer schema stays
at version 1. See [the extension contract](sparse-reconstruction/schema.md) and
[full specification](SPARSE_RECONSTRUCTION_SPEC.md). The normal `rgb_assisted`
stage dispatches this extension before automatic shape routing; `raw_depth_pose`
remains a separate baseline. Its first-registered-camera CV object frame uses m
for `points_measurement.npz` and camera poses, and mm for previews/measurements.
Measurements may use source `multiview`; support and sparse scale artifacts are
linked explicitly. `observations.accepted_frames` supplies existing candidate
evidence. Display mesh triangles do not replace observed points in CAD checks.

CAD callable: generate(family:str, parameters:dict, output_dir:Path, context:dict|None=None)->dict; generates all part artifacts, coupon, validation.json, manifest.json; throws actionable ValueError for invalid params. Families: bridge_handle,cup_handle,bracket. All use mm. Bridge params span,standoff,grip_width,grip_depth,pad_width,pad_length,pad_thickness,hole_diameter (0=no holes). Cup params cup_radius,contact_spacing,standoff,grip_width,grip_depth,pad_height,pad_thickness,contact_gap; attachment saddle requires explicit approval. Bracket params width,length,thickness,leg_height (0=flat),hole_diameter,hole_spacing. CAD agent publishes defaults/bounds and preview mesh schema matching scan preview. context includes contacts, observed points, manufacturing, scan revision.

API v1 uses Bearer pairing token. Public GET /v1/health. GET /v1/capabilities. POST /v1/scans {scan_id?,source,project_id?}-> {scan_id,assets:[]}; GET /v1/scans/{id} -> assets [{path,sha256,size}], committed, reconstruction optional. PUT /v1/scans/{id}/assets/{path:path} raw body with X-Content-SHA256. POST /v1/scans/{id}/commit validates files. POST /v1/scans/{id}/reconstruction -> job. PUT /v1/scans/{id}/annotations dict. POST /v1/repairs {scan_id,family,parameters,attachment_method,mode:"manual"|"fixture"|"live",acknowledge_uncertainty:bool,request_id?}-> job. POST /v1/repairs/{id}/revisions same fields -> job. GET /v1/jobs/{id} -> {job_id,state,progress,message,result?,error?}, result for repair {repair_id,revision,validation,artifacts:[{id,name,sha256,size}],parameters,family}; reconstruction result includes artifacts for preview. POST /v1/jobs/{id}/cancel. GET /v1/artifacts/{id}. DELETE /v1/projects/{id}. State queued,validating_input,reconstructing,needs_input,planning,generating_cad,validating_cad,complete,cancelled,failed.

Provider module reasoning.py: propose(scan_dir:Path,reconstruction:dict,request:dict)->dict with validated family,parameters,measurement_refs,attachment_method,questions,explanation,provider_status. Implemented by root. Manual uses typed request, fixture clearly labeled, live Responses adapter. Backend owner may start manual route independently. Never execute provider code.

Swift package ReverseCADCore owns Codable capture types, geometry, persistence and ServiceClient. Swift UI imports it. Capture owner implements ios/ReverseCAD/Capture*.swift plus replay/package writer; UI owner owns remaining app and Xcode project. Coordinate directly on interface. Service default http://127.0.0.1:8767 in Simulator; phone requires Mac LAN address and token in Keychain. App bundle com.pranav.ReverseCAD, scheme ReverseCAD, iOS 17.
