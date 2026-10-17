"""Bounded COLMAP alignment with automatic metric scale and explicit uncertainty.

The input capture is immutable. Native depth is used only as scale evidence;
failed depth surfaces are never silently fused into the photo reconstruction.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from .geometry import transform_points


def robust_scale(samples, minimum=30):
    values = np.asarray(samples, dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if len(values) < minimum:
        raise ValueError('Too few metric depth correspondences for automatic scale')
    median = float(np.median(values))
    mad = float(np.median(abs(values-median)))
    keep = abs(values-median) <= max(3*1.4826*mad, median*.015)
    values = values[keep]
    if len(values) < minimum:
        raise ValueError('Metric scale has insufficient consistent support')
    median = float(np.median(values))
    spread = float((np.percentile(values, 90)-np.percentile(values, 10))/(2*median))
    if spread > .15:
        raise ValueError('Depth scale varies too much between matched observations')
    return median, {'samples': int(len(values)), 'relative_p10_p90_half_range': spread,
                    'accuracy_calibrated': False, 'source': 'robust_native_depth_to_triangulated_photo_depth_ratio'}


def align_photos(scan_dir, frames, capture_frames, output_dir):
    import pycolmap as pc
    report = {'method': 'COLMAP_SIFT_bundle_adjustment', 'status': 'insufficient_photo_evidence',
              'input_frames': len(frames), 'native_capture_modified': False}
    if len(frames) < 4:
        return [], report
    # Bounded CPU and image count for the companion worker. Preserve temporal coverage.
    chosen = [frames[i] for i in np.unique(np.linspace(0, len(frames)-1, min(32,len(frames)), dtype=int))]
    metadata = {f['frame_id']: f for f in capture_frames}
    with TemporaryDirectory(prefix='reversecad-colmap-') as temporary:
        root = Path(temporary)
        import shutil
        images = root/'images'; images.mkdir()
        # A tracking-limited RGB photo can still constrain COLMAP; its ARKit pose
        # and depth never become accepted native measurement frames.
        photos=[f for f in capture_frames if float(f.get('quality',{}).get('blur_score',0))>=8]
        photos=[photos[i] for i in np.unique(np.linspace(0,len(photos)-1,min(32,len(photos)),dtype=int))]
        for f in photos:
            shutil.copyfile(scan_dir/f['rgb_path'], images/(f['frame_id']+'.jpg'))
        k = chosen[0]['image_k']
        params = ','.join(str(float(v)) for v in [k[0,0], k[1,1], k[0,2], k[1,2]])
        database = root/'database.db'
        pc.extract_features(database, images, camera_mode=pc.CameraMode.SINGLE,
            reader_options={'camera_model':'PINHOLE','camera_params':params},
            extraction_options={'num_threads':2,'max_image_size':1920}, device=pc.Device.cpu)
        pc.match_exhaustive(database, matching_options={'num_threads':2}, device=pc.Device.cpu)
        models = pc.incremental_mapping(database, images, root/'models', options={
            'num_threads':2, 'random_seed':0, 'max_num_models':2, 'max_runtime_seconds':65,
            'ba_refine_focal_length':False, 'ba_refine_principal_point':False,
            'ba_refine_extra_params':False,
            'mapper':{'abs_pose_refine_focal_length':False,'abs_pose_refine_extra_params':False}})
        if not models:
            return [], {**report, 'reason':'Photos could not be registered into a shared model.'}
        model = max(models.values(), key=lambda r:r.num_reg_images())
        poses = {im.name:np.linalg.inv(np.vstack([im.cam_from_world().matrix(),[0,0,0,1]]))
                 for im in model.images.values() if im.has_pose}
        selected = [f for f in chosen if f['frame_id']+'.jpg' in poses]
        report.update(registered_frames=len(selected), sparse_points=model.num_points3D(),
                      mean_reprojection_error_px=model.compute_mean_reprojection_error())
        if len(selected) < 4 or model.compute_mean_reprojection_error() > 2.5:
            return [], {**report,'reason':'Too few reliably aligned photos.'}
        lookup={f['frame_id']+'.jpg':f for f in selected}
        background, foreground, by_frame = [], [], {}
        for im in model.images.values():
            f=lookup.get(im.name)
            if f is None: continue
            meta=metadata[f['frame_id']]
            depth=np.fromfile(scan_dir/meta['depth_path'],dtype='<f4').reshape(f['depth'].shape)
            confidence=np.fromfile(scan_dir/meta['confidence_path'],dtype=np.uint8).reshape(depth.shape) if meta.get('confidence_path') else np.ones(depth.shape)
            samples=[]
            for p in im.points2D:
                if not p.has_point3D():continue
                x,y=np.rint(p.xy/np.array(f['image_size'])*np.array(depth.shape[::-1])).astype(int)
                if not (1<=x<depth.shape[1]-1 and 1<=y<depth.shape[0]-1):continue
                patch=depth[y-1:y+2,x-1:x+2]
                d=float(depth[y,x]); z=float((im.cam_from_world()*model.points3D[p.point3D_id].xyz)[2])
                if not (.08<d<3 and z>0 and confidence[y,x]>=1 and np.isfinite(patch).all()):continue
                # Discontinuities and high-variance depth are unreliable metric anchors.
                if np.ptp(patch) > max(.004,d*.025):continue
                value=d/z
                (background if f['depth'][y,x]==0 else foreground).append(value)
                samples.append(value)
            if samples:by_frame[f['frame_id']]=float(np.median(samples))
        try:
            scale,scale_report=robust_scale(background if len(background)>=30 else foreground)
        except ValueError as exc:
            return [], {**report,'reason':str(exc)}
        scale_report['region']='background' if len(background)>=30 else 'object'
        scale_report['per_frame_medians']=by_frame
        # Keep the first aligned camera in its recorded world frame; scale only translation.
        first=selected[0];original=first['pose'];sfm=poses[first['frame_id']+'.jpg']
        rotation=original[:3,:3]@sfm[:3,:3].T
        translation=original[:3,3]-scale*rotation@sfm[:3,3]
        corrected=[]
        for f in selected:
            p=poses[f['frame_id']+'.jpg'].copy()
            p[:3,3]=scale*rotation@p[:3,3]+translation;p[:3,:3]=rotation@p[:3,:3]
            change=p@np.linalg.inv(f['pose'])
            corrected.append({**f,'pose':p,'points':transform_points(f['points'],change),
                              'raw_points':transform_points(f['raw_points'],change)})
        report.update(status='aligned_photos',scale=scale_report, similarity_scale_m=scale,
                      frame_ids=[f['frame_id'] for f in corrected])
        # Small auditable artifact; databases and source-image copies stay temporary.
        import json
        (output_dir/'photo_camera_poses.json').write_text(json.dumps({
            'unit':'m','method':report['method'],'scale':scale_report,
            'poses':{f['frame_id']:f['pose'].tolist() for f in corrected}},indent=2))
        return corrected,report
