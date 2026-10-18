"""Measured three-camera observations, bounded clock alignment and stereo reuse.

Factory extrinsics are converted from millimetres once. No timestamp extrapolation,
synthetic depth completion, or category geometry is permitted.
"""
from __future__ import annotations
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from .contracts import safe_asset_path
from .geometry import AR_TO_CV, scaled_intrinsics, project, unproject


def validate_frame(root, frame, actual):
    observation = frame['multi_camera']
    if observation.get('schema_version') != 1 or observation.get('clock') != 'capture_elapsed_seconds':
        raise ValueError('Unsupported multi-camera clock or schema')
    cameras = observation.get('cameras', {})
    if set(cameras) != {'wide', 'ultra', 'tele'}:
        raise ValueError('All three physical camera observations are required')
    declared = set(frame.get('additional_assets') or [])
    calibration_path = safe_asset_path(observation['calibration_path'])
    if calibration_path not in declared or calibration_path not in actual or actual[calibration_path].stat().st_size > 256*1024:
        raise ValueError('Missing or oversized camera calibration')
    calibration = json.loads(actual[calibration_path].read_text())
    for name, camera in cameras.items():
        k = np.asarray(camera['intrinsics'], float)
        if k.shape != (9,) or not np.isfinite(k).all() or k[0] <= 0 or k[4] <= 0 or abs(k[8]-1) > 1e-6:
            raise ValueError('Invalid camera intrinsics')
        timestamp, offset = camera['timestamp_s'], camera['offset_from_primary_s']
        if not np.isfinite([timestamp, offset]).all() or abs(offset) > .045001 or abs(timestamp-frame['timestamp_s']-offset) > 1e-6:
            raise ValueError('Camera timestamp does not match the bounded clock join')
        paths, layout = camera['original_plane_paths'], camera['plane_layout']
        if len(paths) != 2 or len(layout) != 2 or len(set(paths)) != 2:
            raise ValueError('Original NV12 camera planes are required')
        w, h = camera['width'], camera['height']
        if not 0 < w <= 4096 or not 0 < h <= 4096:
            raise ValueError('Camera image dimensions exceed the budget')
        for index, (path, plane) in enumerate(zip(paths, layout)):
            safe_asset_path(path)
            expected_h = h if index == 0 else h//2
            expected_w = w if index == 0 else w//2
            if path not in actual or path not in declared or plane['width'] != expected_w or plane['height'] != expected_h or not w <= plane['row_bytes'] <= w+4096 or actual[path].stat().st_size != plane['row_bytes']*expected_h:
                raise ValueError('Original camera plane is missing or has inconsistent dimensions')
        path = safe_asset_path(camera['rgb_path'])
        if path not in actual or path not in declared:
            raise ValueError('Missing full camera image')
        from PIL import Image
        with Image.open(actual[path]) as image:
            if image.size != (w,h):
                raise ValueError('Camera preview dimensions do not match its originals')
            image.verify()
        if name != 'wide':
            extrinsic(calibration, name)
    path = safe_asset_path(calibration['original_depth_path'])
    w, h = calibration['original_depth_size']
    if path not in actual or path not in declared or not 0 < w*h <= 640*480 or actual[path].stat().st_size != w*h*4:
        raise ValueError('Missing original LiDAR observations')


def extrinsic(calibration, name):
    raw = np.asarray(calibration[name]['from_wide_extrinsics_column_major_mm'],float)
    if raw.shape != (12,) or not np.isfinite(raw).all():
        raise ValueError('Invalid factory extrinsics')
    matrix = np.eye(4); matrix[:3] = raw.reshape((3,4),order='F')
    matrix[:3,3] *= .001
    if not np.allclose(matrix[:3,:3].T @ matrix[:3,:3],np.eye(3),atol=2e-3) or np.linalg.det(matrix[:3,:3]) < .99 or not .001 < np.linalg.norm(matrix[:3,3]) < .08:
        raise ValueError('Factory camera alignment is not a physical rigid baseline')
    return matrix


class Trajectory:
    def __init__(self, rows):
        rows = [r for r in rows if r.get('tracked')]
        self.times = np.asarray([r['time_s'] for r in rows])
        self.poses = [np.asarray(AR_TO_CV) @ np.asarray(r['pose']).reshape((4,4),order='F') for r in rows]
        if len(self.times) and (not np.isfinite(self.times).all() or np.any(np.diff(self.times)<=0)):
            raise ValueError('Motion timestamps must increase')
    def at(self, time):
        if len(self.times)<2 or time<self.times[0] or time>self.times[-1]:
            return None
        right=min(len(self.times)-1,max(1,int(np.searchsorted(self.times,time))))
        left=right-1; gap=self.times[right]-self.times[left]
        if gap>.6:
            return None
        a,b=self.poses[left],self.poses[right]
        if np.linalg.norm(a[:3,3]-b[:3,3])>.15:
            return None
        rotations=Rotation.from_matrix(np.array([a[:3,:3],b[:3,:3]]))
        if (rotations[0].inv()*rotations[1]).magnitude()>.35:
            return None
        ratio=(time-self.times[left])/gap
        pose=np.eye(4)
        pose[:3,:3]=Slerp([0.,1.],rotations)([ratio]).as_matrix()[0]
        pose[:3,3]=(1-ratio)*a[:3,3]+ratio*b[:3,3]
        return pose


def load_trajectory(root):
    path=Path(root)/'capture_diagnostics.json'
    if not path.exists():
        return Trajectory([])
    return Trajectory(json.loads(path.read_text()).get('tracking',[]))


def auxiliary_pose(row, name, calibration, trajectory):
    camera=row['multi_camera']['cameras'][name]
    at=trajectory.at(camera['timestamp_s'])
    return None if at is None else at @ np.linalg.inv(extrinsic(calibration,name))


def auxiliary_observation(root, raw, native, name, trajectory, profile=None):
    from .reconstruction import _asset
    observation=raw['multi_camera']; sensor=observation['cameras'][name]
    calibration=json.loads(_asset(root,observation['calibration_path']).read_text())
    pose=auxiliary_pose(raw,name,calibration,trajectory)
    if pose is None:
        return None
    image=cv2.imread(str(_asset(root,sensor['rgb_path'])))
    if image is None:
        return None
    image=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
    size=native['image_size']
    k=scaled_intrinsics(sensor['intrinsics'],sensor['width'],sensor['height'],*size)
    image=cv2.resize(image,size,interpolation=cv2.INTER_AREA)
    if profile and profile.get('correction_applied'):
        from .phone_calibration import camera_model
        revised,distortion=camera_model(k,np.asarray(profile['correction']))
        image=cv2.undistort(image,revised,distortion,None,revised);k=revised
    # Only primary object observations may seed this camera's footprint.
    points,_=unproject(native['depth'],native['k'],native['pose'])
    dw,dh=native['depth'].shape[1],native['depth'].shape[0]
    depth_k=scaled_intrinsics(k.T.ravel().tolist(),*size,dw,dh)
    uv,z=project(points,depth_k,pose)
    uv=np.rint(uv).astype(int)
    good=np.isfinite(z)&(z>.04)&(uv[:,0]>=0)&(uv[:,0]<dw)&(uv[:,1]>=0)&(uv[:,1]<dh)
    depth=np.full(dw*dh,np.inf)
    np.minimum.at(depth,uv[good,1]*dw+uv[good,0],z[good])
    depth=depth.reshape(dh,dw);depth[~np.isfinite(depth)]=0
    return {'frame_id':raw['frame_id']+'-'+name,'pose':pose,'image':image,'image_k':k,'depth':depth.astype(np.float32),'k':depth_k,
            'foreground_mask':cv2.resize((depth>0).astype('uint8'),size,interpolation=cv2.INTER_NEAREST)>0,'capture_region':None}


def refine_multicamera(frames, raw_frames, root, calibration=None, max_pairs=8):
    """Reuse existing bidirectional stereo, anchored to the selected depth surface."""
    from .photo_detail import stereo_pair
    from .reconstruction import _asset
    root=Path(root);trajectory=load_trajectory(root)
    raw_by_id={r['frame_id']:r for r in raw_frames}
    results=[];report={'status':'insufficient_evidence','method':'three_camera_bidirectional_stereo','pairs':[],'attempted_pairs':[],
                      'accepted_pixels':0,'timestamp_extrapolation':False,'physical_accuracy_validated':False}
    selected=frames[::max(1,len(frames)//8)][:8]
    for native in selected:
        raw=raw_by_id[native['frame_id']]
        if not raw.get('multi_camera'):
            continue
        image=cv2.imread(str(_asset(root,native['rgb_path'])))
        if image is None:
            continue
        image=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        mask=cv2.resize(native['foreground_mask'].astype('uint8'),native['image_size'],interpolation=cv2.INTER_NEAREST)>0
        primary={**native,'image':image,'foreground_mask':mask,'capture_region':None}
        for name in ['ultra','tele']:
            if len(report['attempted_pairs'])>=max_pairs*2 or len(results)>=max_pairs:
                break
            profile=(calibration or {}).get('auxiliary_cameras',{}).get(name)
            # A failed measured reference check must never be ignored.
            if profile and not profile.get('reference_registered'):
                continue
            auxiliary=auxiliary_observation(root,raw,native,name,trajectory,profile)
            if auxiliary is None:
                continue
            pair=[primary['frame_id'],auxiliary['frame_id']];report['attempted_pairs'].append(pair)
            detail=stereo_pair(primary,auxiliary)
            if detail is None:
                detail=stereo_pair(auxiliary,primary)
            if detail is not None:
                results.append(detail);report['pairs'].append({'frame_ids':pair,'pixels':int(np.count_nonzero(detail['depth'])),'median_lr_error_px':detail['median_lr_error_px']})
    report['accepted_pixels']=sum(p['pixels'] for p in report['pairs'])
    if results:report['status']='photo_detail_integrated'
    return report,results
