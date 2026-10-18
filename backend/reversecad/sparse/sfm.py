"""Fixed-calibration COLMAP reconstruction, reusing the existing classical path."""
from __future__ import annotations
import shutil
from pathlib import Path
import cv2
import numpy as np
from .capture import WIDE, write_json
from ..capture_region import region_mask


def reconstruct_images(scan_dir, frames, output):
    import pycolmap as pc
    output.mkdir(parents=True,exist_ok=True)
    images=output/'images'; images.mkdir()
    dbpath=output/'database.db'
    photos=[]
    for f in frames:
        s=f.get('sensor_observation',{})
        identity=s.get('physical_camera',{})
        if (identity.get('verified') is True and identity.get('device_type')==WIDE and
                identity.get('position')=='back' and identity.get('device_id') and
                float(f['quality']['blur_score'])>=7): photos.append(f)
    if len(photos)>48: photos=[photos[i] for i in np.unique(np.linspace(0,len(photos)-1,48,dtype=int))]
    if len(photos)<3: raise ValueError('Need at least three sharp images with verified physical rear 1× camera identity')
    if len({f['sensor_observation']['physical_camera']['device_id'] for f in photos})!=1:
        raise ValueError('Physical camera changed within the scan')
    mapping={}; masks={}; cameras={}; inputs={}
    with pc.Database.open(dbpath): pass
    for f in photos:
        name=f['frame_id']+Path(f['rgb_path']).suffix
        shutil.copyfile(scan_dir/f['rgb_path'],images/name)
        K=np.asarray(f['intrinsics']).reshape(3,3,order='F')
        if (f['intrinsics_width'],f['intrinsics_height'])!=(f['rgb_width'],f['rgb_height']):
            raise ValueError('RGB and recorded calibration dimensions differ; explicit working-image transform required')
        params=[K[0,0],K[1,1],K[0,2]+.5,K[1,2]+.5]
        key=(f['rgb_width'],f['rgb_height'],*params)
        if key not in cameras:
            cam=pc.Camera(model='PINHOLE',width=f['rgb_width'],height=f['rgb_height'],params=params)
            cam.has_prior_focal_length=True
            with pc.Database.open(dbpath) as db: cameras[key]=db.write_camera(cam)
        pc.import_images(dbpath,images,image_names=[name],options={'existing_camera_id':cameras[key]})
        mapping[name]={**f,'width':f['rgb_width'],'height':f['rgb_height'],'image_path':f['rgb_path']}
        selected=region_mask(f.get('capture_region'),(f['rgb_height'],f['rgb_width']))
        if f.get('mask_path'):
            mask=np.fromfile(scan_dir/f['mask_path'],dtype=np.uint8)
            shape=(f['depth_height'],f['depth_width']) if mask.size==f['depth_height']*f['depth_width'] else (f['rgb_height'],f['rgb_width'])
            selected &= cv2.resize(mask.reshape(shape),(f['rgb_width'],f['rgb_height']),interpolation=cv2.INTER_NEAREST)>0
        elif f.get('capture_region') is None:
            raise ValueError('Select the object in the capture guide before reconstructing')
        masks[f['frame_id']]=cv2.erode(selected.astype(np.uint8),np.ones((5,5),np.uint8))>0
        inputs[name]={'camera_id':cameras[key],'K_cv':K.tolist(),'COLMAP_params':params,
                      'source':'recorded_ARCamera_intrinsics','independently_calibrated':False,
                      'refined':False,'original_size':[f['rgb_width'],f['rgb_height']],
                      'working_transform':'none; feature extractor scales internally and returns original coordinates'}
    write_json(output/'camera-inputs.json',inputs)
    pc.set_random_seed(17); cv2.setNumThreads(1)
    pc.extract_features(dbpath,images,device=pc.Device.cpu,
        extraction_options={'num_threads':1,'use_gpu':False,'max_image_size':1600,
                            'sift':{'max_num_features':4096,'first_octave':0}})
    pc.match_exhaustive(dbpath,device=pc.Device.cpu,
        matching_options={'num_threads':1,'use_gpu':False,'guided_matching':True,'max_num_matches':4096})
    options=pc.IncrementalPipelineOptions()
    options.num_threads=1; options.min_model_size=3; options.multiple_models=False
    options.random_seed=17; options.max_runtime_seconds=90
    options.mapper.init_min_num_inliers=40;options.mapper.init_min_tri_angle=2
    options.mapper.filter_min_tri_angle=1.5
    options.ba_refine_focal_length=False;options.ba_refine_principal_point=False;options.ba_refine_extra_params=False
    options.mapper.abs_pose_refine_focal_length=False; options.mapper.abs_pose_refine_extra_params=False
    options.use_prior_position=False
    models=pc.incremental_mapping(dbpath,images,output/'models',options=options)
    if not models: raise ValueError('No translated multi-view model recovered. Move sideways with overlapping sharp views; keep the object still')
    rec=max(models.values(),key=lambda r:(r.num_reg_images(),r.num_points3D()))
    if rec.num_reg_images()<3: raise ValueError('Fewer than three views registered; show another side slowly')
    final=output/'model';final.mkdir();rec.write(final)
    report={'method':'COLMAP_SIFT_fixed_recorded_PINHOLE','pycolmap_version':pc.__version__,
            'registered_frames':rec.num_reg_images(),'input_frames':len(photos),
            'sparse_points':rec.num_points3D(),'mean_reprojection_error_px':rec.compute_mean_reprojection_error(),
            'poses_from':'real_image_correspondences','ARKit_pose_used':False,
            'intrinsics_refined':False,'range_bias_fitted':False,'working_max_image_size':1600,
            'random_seed':17,'worker_threads':1,
            'selection_sources':{f['frame_id']:('foreground_mask_and_guide' if f.get('mask_path') else 'guide_only_needs_visual_review') for f in photos}}
    write_json(output/'sfm.json',report)
    if not np.isfinite(report['mean_reprojection_error_px']) or report['mean_reprojection_error_px']>2.5:
        raise ValueError('Image correspondences are inconsistent; keep object still and improve overlap/light')
    return rec,mapping,masks,report


def observed_points(rec,mapping,masks):
    points=[]; colors=[]; ids=[]; support=[]
    for pid,p in rec.points3D.items():
        seen=[];outside=0
        for e in p.track.elements:
            im=rec.images[e.image_id]; f=mapping[im.name]; xy=np.rint(im.points2D[e.point2D_idx].xy-.5).astype(int)
            m=masks[f['frame_id']]
            if 0<=xy[0]<m.shape[1] and 0<=xy[1]<m.shape[0] and m[xy[1],xy[0]]:seen.append(f['frame_id'])
            else:outside+=1
        if len(set(seen))>=3 and outside<=len(seen)*.25 and p.error<=2.5:
            points.append(p.xyz);colors.append(p.color);ids.append(f'sfm:{pid}');support.append(sorted(set(seen)))
    return np.asarray(points).reshape(-1,3),np.asarray(colors).reshape(-1,3),ids,support
