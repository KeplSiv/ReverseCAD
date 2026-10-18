"""Sparse-range reconstruction at the existing reconstruct() service boundary."""
from __future__ import annotations
import time
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial import cKDTree
from .capture import validate_extension,decoded_records,timing_report,write_json,clean_json
from .sfm import reconstruct_images,observed_points
from .registration import build_constraints,select_scale
from .stereo import _cpu_mvs, _cv_camera
from ..geometry import dot


def object_visibility(points, ordered, mapping, masks):
    """Reject background supported by a few false matches but outside other silhouettes."""
    inside = np.zeros(len(points), int)
    outside = np.zeros(len(points), int)
    for im in ordered:
        camera = im.cam_from_world().matrix()
        local = dot(points, camera[:, :3].T) + camera[:, 3]
        K, _ = _cv_camera(im.camera)
        pixels = dot(local, K.T)
        uv = pixels[:, :2] / np.maximum(pixels[:, 2, None], 1e-10)
        xy = np.rint(np.clip(uv, -1e6, 1e6)).astype(int)
        mask = masks[mapping[im.name]['frame_id']]
        visible = (local[:, 2] > 0) & (xy[:, 0] >= 0) & (xy[:, 0] < mask.shape[1]) & (xy[:, 1] >= 0) & (xy[:, 1] < mask.shape[0])
        indexes = np.flatnonzero(visible)
        selected = mask[xy[indexes, 1], xy[indexes, 0]]
        inside[indexes[selected]] += 1
        outside[indexes[~selected]] += 1
    return (inside >= 3) & (outside <= np.maximum(1, inside * .15))


def surface_preview(points,colors,support,output):
    """Local triangles only, supported by common views; no closing/smoothing/Poisson."""
    import open3d as o3d
    cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(points)
    cloud.colors=o3d.utility.Vector3dVector(colors/255.)
    o3d.io.write_point_cloud(str(output/'observed_points_m.ply'),cloud)
    triangles=np.empty((0,3),int)
    if len(points)>=100:
        cloud.estimate_normals(o3d.geometry.KDTreeSearchParamKNN(knn=20))
        distance=cKDTree(points).query(points,k=2)[0][:,1]
        radius=float(np.clip(np.median(distance)*2,.0005,.008))
        mesh=o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(cloud,o3d.utility.DoubleVector([radius,radius*2]))
        t=np.asarray(mesh.triangles)
        if len(t):
            p=points[t];edge=np.max(np.linalg.norm(p-np.roll(p,1,axis=1),axis=2),axis=1)
            keep=edge<=min(.015,radius*4)
            for i,tri in enumerate(t):
                if keep[i] and len(set(support[tri[0]])&set(support[tri[1]])&set(support[tri[2]]))<2:keep[i]=False
            triangles=t[keep]
        mesh.triangles=o3d.utility.Vector3iVector(triangles)
        mesh.compute_vertex_normals()
        if len(triangles):o3d.io.write_triangle_mesh(str(output/'observed_surface_m.ply'),mesh)
    write_json(output/'scan_preview.json',{'vertices':points*1000,'triangles':triangles,
               'colors':colors/255.,'normals':[],'unit':'mm'})
    return {'kind':'locally_supported_display_mesh' if len(triangles) else 'observed_point_cloud',
            'triangles':len(triangles),'hole_filling':False,'smoothing':False,
            'engineering_geometry':'points_measurement.npz','unsupported_regions':'unknown'}


def reconstruct_sparse(scan_dir,output,manifest,frames,annotations):
    started=time.monotonic();output=Path(output)
    result={'schema_version':1,'algorithm_version':'sparse-rgb-1','scan_id':manifest['scan_id'],
            'source':'sparse_range_rgb','unit':'mm','status':'needs_input','point_count':0,
            'input_source':manifest['source'],'capture_provenance':manifest.get('provenance',{}),
            'measurements':annotations.get('measurements',[]).copy(),'primitives':[],
            'bounds_mm':None,'warnings':[], 'metrics':{},
            'sparse_reconstruction':{'version':1,'status':'needs_input','capture_is_synthetic':manifest['source']=='synthetic'},
            'physical_fit':'not_tested','uncertainty_budget':{'status':'not_calibrated',
            'capture_mm':None,'registration_mm':None,'reference_mm':None,'printer_mm':None},
            'coordinate_frame':{'name':'first_registered_camera_cv','handedness':'right',
                                'axes':'x right, y down, z forward','point_unit':'m','preview_unit':'mm'}}
    write_json(output/'scan_preview.json',{'vertices':[],'triangles':[],'colors':[],'normals':[],'unit':'mm'})
    try:
        ext,cal,packets=validate_extension(scan_dir,manifest,frames)
        result['metrics']['sparse_timing']=timing_report(packets)
        if ext.get('status')!='available' or not packets:
            raise ValueError('Sparse range capture unavailable: no genuine BackSparseTimeOfFlight packets were recorded. Retry the Debug capture on a supported phone')
        if not cal.get('T_sparse_camera'):raise ValueError('No sensor-to-1× camera calibration was recorded; sparse points cannot be registered safely')
        records=list(decoded_records(packets))
        with (output/'decoded_sparse.jsonl').open('w') as file:
            import json
            for r in records:file.write(json.dumps(clean_json(r),allow_nan=False)+'\n')
        rec,mapping,masks,sfm=reconstruct_images(Path(scan_dir),frames,output/'sfm')
        result['metrics']['sfm']=sfm
        points,colors,ids,support=observed_points(rec,mapping,masks)
        if len(points)<30:raise ValueError('Too little multi-view geometry inside the selected object; show textured surfaces from another side')
        ordered=sorted([im for im in rec.images.values() if im.has_pose],key=lambda im:mapping[im.name]['sensor_observation']['source_timestamp_s'])
        poses=np.array([np.linalg.inv(np.vstack([im.cam_from_world().matrix(),[0,0,0,1]])) for im in ordered])
        times=np.array([mapping[im.name]['sensor_observation']['source_timestamp_s'] for im in ordered])
        K=np.array([_cv_camera(im.camera)[0] for im in ordered]);fids=[mapping[im.name]['frame_id'] for im in ordered]
        sizes=[(im.camera.width,im.camera.height) for im in ordered]
        constraints,rejected=build_constraints(records,cal,points,times,poses,K,fids,sizes,masks)
        write_json(output/'sparse_associations.json',{'candidates':constraints,'rejection_counts':rejected})
        scale,selected,scale_report=select_scale(constraints)
        result['metrics']['scale']=scale_report
        # The CV frame of the first image is the stable object coordinate convention.
        origin=poses[0];R=origin[:3,:3];C=origin[:3,3]
        baseline=float(np.linalg.norm(np.ptp(poses[:,:3,3],axis=0))*scale)
        if baseline<.01:raise ValueError('Recovered camera translation is below 10 mm. Move sideways around the stationary object')
        dense,dc,di,ds,dense_report=_cpu_mvs(rec,mapping,{'root':str(scan_dir)},masks,output/'sfm',
                      {'dense_max_width':640,'dense_max_pairs':16,'dense_point_stride':2})
        result['metrics']['dense']=dense_report
        kinds=['image_triangulation']*len(points)
        if len(dense):
            # Repetitive textures can satisfy pair checks at the wrong depth.
            # Require the object silhouettes and nearby triangulated support;
            # never snap these points onto a fitted surface.
            neighbor = cKDTree(points).query(points, k=2)[0][:, 1] * scale
            distance_limit = float(np.clip(np.median(neighbor) * 3, .003, .01))
            distance = cKDTree(points).query(dense)[0] * scale
            keep = object_visibility(dense, ordered, mapping, masks) & (distance <= distance_limit)
            dense_report.update(object_support_distance_limit_m=distance_limit,
                                rejected_by_object_support=int((~keep).sum()),
                                retained_object_points=int(keep.sum()))
            dense, dc = dense[keep], dc[keep]
            di = [x for x, use in zip(di, keep) if use]
            ds = [x for x, use in zip(ds, keep) if use]
            points=np.vstack([points,dense]);colors=np.vstack([colors,dc]);ids+=di;support+=ds;kinds+=['image_stereo']*len(dense)
        metric=dot(points-C,R)*scale
        # Retain direct sparse points separately and link them to the selected constraints.
        direct=[];direct_ids=[];direct_support=[];direct_colors=[]
        images={}
        for c in selected:
            pose=np.array(c['world_camera_unscaled']);cp=np.array(c['camera_point_m'])
            world=pose[:3,:3]@cp+pose[:3,3]*scale
            direct.append(dot(world-C*scale,R));direct_ids.append(c['id']);direct_support.append(c['frame_ids'])
            fid=c['frame_ids'][0];f=next(v for v in mapping.values() if v['frame_id']==fid)
            if fid not in images:images[fid]=cv2.imread(str(Path(scan_dir)/f['rgb_path']))[:,:,::-1]
            # Color sampled in nearest image is visualization only, not another measurement.
            x,y=np.rint(c['pixel']).astype(int);im=images[fid]
            direct_colors.append(im[np.clip(y,0,im.shape[0]-1),np.clip(x,0,im.shape[1]-1)])
        write_json(output/'selected_sparse_support.json',{'scale':scale_report,'observations':selected})
        np.savez_compressed(output/'direct_range_points.npz',points_m=direct,observation_ids=direct_ids)
        # Engineering support retains provenance for every row; display-only triangles never enter CAD.
        metric=np.vstack([metric,direct]);colors=np.vstack([colors,direct_colors]);ids+=direct_ids;support+=direct_support
        kinds+=['direct_sparse_range']*len(direct)
        keep=np.isfinite(metric).all(axis=1)
        if annotations.get('crop_min_m'):
            keep&=(metric>=annotations['crop_min_m']).all(axis=1)&(metric<=annotations['crop_max_m']).all(axis=1)
        # Quantization selects existing observations; never averages away their provenance.
        _,first=np.unique(np.floor(metric/.0007).astype(np.int64),axis=0,return_index=True)
        voxel=np.zeros(len(metric),bool);voxel[first]=True;keep&=voxel
        selected_indices=np.flatnonzero(keep)
        metric=metric[keep];colors=colors[keep]
        ids=[ids[i] for i in selected_indices];support=[support[i] for i in selected_indices];kinds=[kinds[i] for i in selected_indices]
        if len(metric)<30:raise ValueError('Object crop contains insufficient observations')
        if np.ptp(metric,axis=0).max()>1.5:raise ValueError('Reconstruction is dominated by background or inconsistent scale; tighten the object selection')
        np.savez_compressed(output/'points_measurement.npz',points_m=metric,colors=colors/255.,observation_ids=ids,source_kind=kinds)
        write_json(output/'point_support.json',{'points':[{'id':i,'source':k,'frame_ids':s} for i,k,s in zip(ids,kinds,support)]})
        from ..reconstruction import _features
        fit_frames=[{'frame_id':fid,'points':metric[[fid in s for s in support]]} for fid in fids]
        primitives,measurements=_features(metric,fit_frames,annotations)
        for item in primitives+measurements:
            if item.get('source')=='depth_fit':item['source']='multiview'
            item['metric_scale_source']='selected_sparse_support.json'
            item['geometry_source']='observed_image_and_sparse_range_points'
            if item.get('repeatability_mm') is not None:
                item['support_subset_variation_mm']=item['repeatability_mm']
                item['repeatability_mm']=None
            if 'repeatability_method' in item:
                item['repeatability_method']='Variation of overlapping correlated point subsets; not temporal or independent measurement repeatability'
        lo,hi=metric.min(axis=0)*1000,metric.max(axis=0)*1000
        for axis,value in zip('xyz',hi-lo):
            measurements.append({'id':'sparse_extent_'+axis,'name':'Observed '+axis.upper()+' extent',
                 'value':float(value),'unit':'mm','source':'multiview','confirmed':False,'critical':False,
                 'uncertainty_mm':None,'observation_ids':fids,'support_artifact':'point_support.json',
                 'scale_artifact':'selected_sparse_support.json','meaning':'observed support extent, not hidden full-object dimension'})
        result.update(status='ready',point_count=len(metric),bounds_mm={'min':lo,'max':hi,'extent':hi-lo},primitives=primitives)
        result['measurements']+=measurements
        result['surface']=surface_preview(metric,colors,support,output)
        camera_rows=[]
        for im,pose,k,fid,stamp in zip(ordered,poses,K,fids,times):
            transformed=np.eye(4);transformed[:3,:3]=R.T@pose[:3,:3];transformed[:3,3]=dot(pose[:3,3]-C,R)*scale
            camera_rows.append({'frame_id':fid,'timestamp_s':stamp,'T_object_camera_cv':transformed.flatten(order='F'),
                                'K_cv':k,'unit':'m','source':'COLMAP_real_images'})
        write_json(output/'camera_poses.json',{'layout':'column_major','calibration':cal,'poses':camera_rows})
        result['metrics'].update(camera_baseline_m=baseline,measurement_support='image geometry scaled by selected timed sparse ranges; direct range rows separately identified',
                               range_supported_points=len(direct),coverage_is_complete=False,
                               registered_object_views=len(fids))
        result['observations']={'accepted_frames':fids,
                                'unregistered_frames':[f['frame_id'] for f in frames if f['frame_id'] not in fids],
                                'support_artifact':'point_support.json'}
        result['sparse_reconstruction'].update(status='ready',scale_support=len(selected),view_count=len(fids),
                   preview_triangles=result['surface']['triangles'],diagnostics=['decoded_sparse.jsonl','sparse_associations.json','selected_sparse_support.json','camera_poses.json'])
        result['warnings']+=['Dimensions are experimental: absolute sensor/calibration error is not calibrated.',
                             'Unobserved surfaces remain unknown. Repair geometry and reference-photo shape are inferences; printed fit is untested.']
        if any(not f.get('mask_path') for f in mapping.values()):
            result['warnings'].append('Some views use only the capture box for object selection. Review the preview for background contamination before continuing')
        if manifest['source']=='synthetic':
            result['warnings'].append('Synthetic algorithm fixture: this result is not a physical scan or device accuracy validation')
        if not manifest['complete']:
            result['status']='needs_input';result['warnings'].append('Capture was interrupted; retained observations require a fresh completed scan')
        if any(p.get('status')=='needs_measurement' for p in primitives):
            result['status']='needs_input';result['warnings'].append('Selected attachment patches need more observations')
    except (ValueError,ImportError) as exc:
        result['warnings'].append(str(exc));result['sparse_reconstruction']['reason']=str(exc)
    result['sparse_reconstruction']['status']=result['status']
    result['metrics']['elapsed_s']=time.monotonic()-started
    result=clean_json(result);write_json(output/'reconstruction.json',result)
    return result
