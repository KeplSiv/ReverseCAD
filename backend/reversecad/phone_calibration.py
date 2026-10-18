"""Front TrueDepth reference -> rear optical rays, with held-out acceptance.

Uses the existing reference calibration experiment's SIFT/PnP/bounded residual
model. ARKit poses and native depth scale stay fixed. No nominal object sizes,
front distortion copied to rear lenses, or unrestricted deformation field.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

from .geometry import AR_TO_CV, rigid_transform, scaled_intrinsics, dot

MAX_VIEWS = 16


def read_json(path):
    return json.loads(Path(path).read_text())


def asset(root, name):
    from .reconstruction import _asset
    return _asset(root, name)


def transform(points, pose):
    return dot(points, pose[:3, :3].T) + pose[:3, 3]


def pose_matrix(parameters):
    result = np.eye(4)
    result[:3, :3] = cv2.Rodrigues(np.asarray(parameters[:3]))[0]
    result[:3, 3] = parameters[3:6]
    return result


def camera_model(k, correction):
    revised = k.copy()
    revised[0, 0] *= np.exp(correction[0])
    revised[1, 1] *= np.exp(correction[0])
    return revised, np.array([correction[1], correction[2], 0., 0., 0.])


def projected(points, object_from_front, camera, correction):
    optical = transform(transform(points, object_from_front), camera['camera_from_object'])
    k, d = camera_model(camera['k'], correction)
    uv, _ = cv2.projectPoints(optical, np.zeros(3), np.zeros(3), k, d)
    return uv[:, 0], optical[:, 2]


def fit_tracks(points, view_indices, pixels, cameras, heldout, initial_pose):
    """Explicit rigid registration plus optional 3-parameter rear residual model."""
    points, pixels = np.asarray(points, float), np.asarray(pixels, float)
    heldout, view_indices = np.asarray(heldout, bool), np.asarray(view_indices, int)
    train = ~heldout
    if train.sum() < 40 or heldout.sum() < 20 or len(np.unique(view_indices)) < 3:
        raise ValueError('Need matching textured surfaces in at least three rear views, with independent held-out points.')
    spread = np.linalg.svd(points[train] - points[train].mean(0), compute_uv=False)
    depth_span = float(np.ptp(np.percentile(points[train, 2], [5, 95])))
    identifiable = spread[-1] / max(spread[0], 1e-12) >= .02 and depth_span >= .03
    initial = np.r_[cv2.Rodrigues(initial_pose[:3, :3])[0][:, 0], initial_pose[:3, 3]]

    def predictions(x):
        correction = x[6:] if len(x) == 9 else np.zeros(3)
        result, positive = np.zeros_like(pixels), np.zeros(len(points), bool)
        for i, camera in enumerate(cameras):
            rows = view_indices == i
            result[rows], z = projected(points[rows], pose_matrix(x), camera, correction)
            positive[rows] = z > .04
        return result, positive

    def errors(x, priors=False):
        predicted, positive = predictions(x)
        residual = (predicted[train] - pixels[train]) / 2
        residual[~positive[train]] += 1000
        values = residual.ravel()
        if priors:
            values = np.r_[values, x[6:] / [.01, .03, .02]]
        return values

    factory = least_squares(errors, initial, loss='soft_l1', f_scale=1, x_scale='jac', max_nfev=150)
    candidate = None
    if identifiable:
        candidate = least_squares(lambda x: errors(x, True), np.r_[factory.x, np.zeros(3)],
                                  bounds=(np.r_[np.full(6, -np.inf), [-.03, -.08, -.05]],
                                          np.r_[np.full(6, np.inf), [.03, .08, .05]]),
                                  loss='soft_l1', f_scale=1, x_scale='jac', max_nfev=150)

    def metrics(x):
        pred, positive = predictions(x)
        residual = np.linalg.norm(pred[heldout] - pixels[heldout], axis=1)
        return {'median_px': float(np.median(residual)), 'p95_px': float(np.percentile(residual, 95)),
                'positive_fraction': float(positive[heldout].mean())}

    before = metrics(factory.x)
    after = metrics(candidate.x) if candidate is not None else before
    # Numerical observability uses only image rows, excluding camera prior rows.
    information_ratio = 0.
    if candidate is not None:
        j = np.asarray(candidate.jac)[:2*train.sum()]
        s = np.linalg.svd(j * np.array([.02]*3 + [.02]*3 + [.01,.03,.02]), compute_uv=False)
        information_ratio = float(s[-1] / max(s[0], 1e-12))
    candidate_ok = candidate is not None and candidate.success and information_ratio > 1e-5
    if candidate_ok:
        candidate_ok = bool(np.all(np.abs(candidate.x[6:]) < np.array([.03,.08,.05])*.98))
        candidate_ok &= after['median_px'] < before['median_px']*.8 and after['p95_px'] <= before['p95_px']+.2
    return {'factory_parameters': factory.x, 'candidate_parameters': candidate.x if candidate is not None else None,
            'candidate_image_pass': bool(candidate_ok), 'factory_heldout': before, 'candidate_heldout': after,
            'identifiable': bool(identifiable), 'information_ratio': information_ratio,
            'train_observations': int(train.sum()), 'heldout_observations': int(heldout.sum()), 'depth_span_m': depth_span}


def features(image):
    height, width = image.shape[:2]
    scale = min(1., 1280 / max(width, height))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    keypoints, descriptors = cv2.SIFT_create(nfeatures=4500, contrastThreshold=.01).detectAndCompute(small, None)
    if descriptors is None or len(keypoints) < 30:
        raise ValueError('Too little sharp texture. Include the same textured surroundings in the front reference and rear views.')
    return (np.asarray([p.pt for p in keypoints]) + .5) / scale - .5, descriptors


def links(front, rear):
    matcher = cv2.BFMatcher()
    fwd, rev = matcher.knnMatch(front[1], rear[1], k=2), matcher.knnMatch(rear[1], front[1], k=2)
    back = {a.queryIdx: a.trainIdx for row in rev if len(row) == 2 for a,b in [row] if a.distance < .75*b.distance}
    selected = [a for row in fwd if len(row) == 2 for a,b in [row] if a.distance < .75*b.distance and back.get(a.trainIdx) == a.queryIdx]
    if len(selected) < 12:
        return []
    left = np.asarray([front[0][m.queryIdx] for m in selected]); right = np.asarray([rear[0][m.trainIdx] for m in selected])
    cv2.setRNGSeed(20261018)
    _, mask = cv2.findFundamentalMat(left, right, cv2.USAC_MAGSAC, 3., .999, 3000)
    return [m for m,yes in zip(selected, mask.ravel()) if yes] if mask is not None else []


def signature(frame):
    return {'rgb_width': frame['rgb_width'], 'rgb_height': frame['rgb_height'],
            'intrinsics_width': frame['intrinsics_width'], 'intrinsics_height': frame['intrinsics_height'],
            'depth_calibration_mode': frame.get('depth_calibration_mode'), 'source': 'MultiCam-rectified-primary' if frame.get('multi_camera') else 'ARKit-primary'}


def compatible(profile, frames):
    if not frames or not profile.get('correction_applied') or profile.get('schema_version') != 1:
        return False
    limits = profile.get('factory_intrinsics_range')
    if limits is None:
        return False
    lo, hi = np.array(limits[0]), np.array(limits[1])
    for f in frames:
        k = np.array(f['intrinsics'], dtype=float)
        if f.get('depth_intrinsics') is not None:
            return False
        if signature(f) != profile.get('camera_signature') or k.shape != (9,) or not np.isfinite(k).all():
            return False
        # No extrapolation to a new crop, zoom, focal state or camera format.
        if np.any(k < lo-0.01) or np.any(k > hi+0.01):
            return False
    return True


def calibration_for_scan(root, frames, segments, output):
    config = root/'calibration/setup.json'
    if not config.exists():
        return None
    setup = read_json(config)
    record = {'schema_version': 1, 'reference_archive_sha256': setup.get('reference_archive_sha256'), 'device_identity_sha256':setup.get('device_identity_sha256'),
              'reference_registered': False, 'correction_applied': False, 'status': 'needs_reference_overlap',
              'source': 'front_TrueDepth_reference_to_rear_ARKit', 'distance_scale_fitted': False,
              'uncertainty': 'TrueDepth systematic bias and absolute measurement accuracy remain unvalidated.',
              'active_camera_count': 1, 'three_rear_camera_calibration': False}
    if any(f.get('multi_camera') for f in frames):
        record.update(source='front_TrueDepth_reference_to_rear_MultiCam', active_camera_count=3)
    target = output/'phone-calibration.json'
    if not setup.get('same_object_required'):
        prior = root/'calibration/active-rear-profile.json'
        if prior.exists() and read_json(prior).get('reference_archive_sha256') == setup.get('reference_archive_sha256') and read_json(prior).get('device_identity_sha256') == setup.get('device_identity_sha256') and compatible(read_json(prior), frames):
            record = read_json(prior)
            record['status'] = 'compatible_saved_residual_correction'
            record['reference_registered'] = False  # New object was not registered to the old scene.
        else:
            record.update(status='factory_retained_for_this_configuration', guidance='Stored phone setup retained; this camera configuration has no validated residual correction.')
        target.write_text(json.dumps(record, indent=2, allow_nan=False))
        return record
    try:
        link = read_json(asset(root, 'calibration/object-link.json'))
        if link.get('same_instance') is not True or link.get('evidence_sha256') != setup.get('evidence_sha256'):
            raise ValueError('The rear object must be matched to the accepted front reference before calibration.')
        front_root = root/'calibration/front'
        evidence_path = asset(front_root, 'reference-evidence.json')
        if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != setup.get('evidence_sha256'):
            raise ValueError('Front-reference evidence checksum differs from the setup record.')
        evidence = read_json(evidence_path)
        if evidence.get('depth_kind') != 'optical_axis_z' or evidence.get('point_layout') != 'little_endian_float32_xyz_sigma_z':
            raise ValueError('Unsupported front-reference coordinates.')
        for name, expected in evidence['assets'].items():
            f = asset(front_root, name)
            if f.stat().st_size > 32*1024*1024 or hashlib.sha256(f.read_bytes()).hexdigest() != expected:
                raise ValueError('Front-reference asset checksum failed.')
        width, height = int(evidence['width']), int(evidence['height'])
        if min(width,height) < 2 or width*height > 640*480:
            raise ValueError('Front-reference sampling dimensions exceed the supported budget.')
        grid = np.fromfile(asset(front_root, evidence['points']), dtype='<f4').reshape(height,width,4)
        image = cv2.imread(str(asset(front_root,evidence['rgb'])), cv2.IMREAD_GRAYSCALE)
        if image is None or image.shape != (evidence['rgb_height'],evidence['rgb_width']):
            raise ValueError('Front-reference photo dimensions do not match its points.')
        front = features(image)
        usable = [f for f in frames if f.get('tracking_state')=='normal' and f.get('quality',{}).get('accepted') and f.get('depth_path')]
        if len(usable) > MAX_VIEWS:
            usable = [usable[i] for i in np.linspace(0,len(usable)-1,MAX_VIEWS).astype(int)]
        cameras, points, observations, indices, heldout, original_ids, initial_poses = [], [], [], [], [], [], []
        from .reconstruction import _read_depth
        for f in usable:
            rear_image = cv2.imread(str(asset(root,f['rgb_path'])), cv2.IMREAD_GRAYSCALE)
            if rear_image is None:
                continue
            try:
                rear = features(rear_image)
            except ValueError:
                continue
            matches = links(front,rear)
            xyz, uv, held, ids = [], [], [], []
            for m in matches:
                point = front[0][m.queryIdx]
                px = np.rint(point*[width/image.shape[1],height/image.shape[0]]).astype(int)
                x,y = px
                if x < 1 or y < 1 or x >= width-1 or y >= height-1:
                    continue
                sample, patch = grid[y,x], grid[y-1:y+2,x-1:x+2]
                if not np.isfinite(patch).all() or sample[2] < .15 or sample[2] > 1.5 or np.ptp(patch[:,:,2]) > max(.006,.02*sample[2]):
                    continue
                cell = (point / [image.shape[1],image.shape[0]] * [8,6]).astype(int)
                is_held = int(hashlib.sha256(f'{cell[0]}:{cell[1]}:20261017'.encode()).hexdigest()[:8],16)%4==0
                xyz.append(sample[:3]); uv.append(rear[0][m.trainIdx]); held.append(is_held); ids.append(m.queryIdx)
            if len(xyz)<16 or sum(not h for h in held)<12:
                continue
            xyz,uv,held = np.asarray(xyz,dtype=float),np.asarray(uv,dtype=float),np.array(held,dtype=bool)
            k = scaled_intrinsics(f['intrinsics'],f['intrinsics_width'],f['intrinsics_height'],f['rgb_width'],f['rgb_height'],mode=f.get('depth_calibration_mode','pixel_center'))
            ok,r,t,inliers = cv2.solvePnPRansac(xyz[~held],uv[~held],k,None,iterationsCount=500,reprojectionError=8,confidence=.999,flags=cv2.SOLVEPNP_EPNP)
            if not ok or inliers is None or len(inliers)<12:
                continue
            object_from_camera = dot(dot(np.asarray(segments[f['segment_id']]),np.asarray(rigid_transform(f['T_world_camera']))),np.asarray(AR_TO_CV))
            initial_poses.append(dot(object_from_camera,pose_matrix(np.r_[r[:,0],t[:,0]])))
            confidence = None
            if f.get('confidence_path'):
                confidence = np.fromfile(asset(root,f['confidence_path']),dtype=np.uint8).reshape(f['depth_height'],f['depth_width'])
            cameras.append({'k':k,'camera_from_object':np.linalg.inv(object_from_camera),'object_from_camera':object_from_camera,'frame':f,'depth':_read_depth(root,f),'confidence':confidence})
            points.extend(xyz); observations.extend(uv); heldout.extend(held); original_ids.extend(ids); indices.extend([len(cameras)-1]*len(xyz))
        points, observations, indices, heldout = np.array(points),np.array(observations),np.array(indices),np.array(heldout,dtype=bool)
        if len(cameras)<3 or len(set(np.array(original_ids)[heldout]))<20 or len(set(np.array(original_ids)[~heldout]))<40:
            raise ValueError('Keep the first object and textured surroundings still. Add three nearby rear views of the same front-visible surface; a second full orbit is unnecessary.')
        # Initial pose comes only from training correspondences.
        def initial_error(p):
            errors=[]
            for i,camera in enumerate(cameras):
                mask=(indices==i)&(~heldout)
                uv,_=projected(points[mask],p,camera,np.zeros(3))
                errors.extend(np.linalg.norm(uv-observations[mask],axis=1))
            return float(np.median(errors))
        initial_pose=min(initial_poses,key=initial_error)
        fit=fit_tracks(points,indices,observations,cameras,heldout,initial_pose)
        def depth_error(parameters):
            residual=[]
            correction=parameters[6:] if len(parameters)==9 else np.zeros(3)
            world=transform(points,pose_matrix(parameters))
            for j in np.nonzero(heldout)[0]:
                camera=cameras[indices[j]]; f=camera['frame']; depth=camera['depth']; uv=observations[j]
                x,y=np.rint(uv*[depth.shape[1]/f['rgb_width'],depth.shape[0]/f['rgb_height']]).astype(int)
                if x<1 or y<1 or x>=depth.shape[1]-1 or y>=depth.shape[0]-1:
                    continue
                patch=depth[y-1:y+2,x-1:x+2]
                if camera['confidence'] is not None and camera['confidence'][y,x] < 1:
                    continue
                if not np.isfinite(patch).all() or np.min(patch)<=0 or np.ptp(patch)>.015:
                    continue
                k,d=camera_model(camera['k'],correction)
                ray=cv2.undistortPoints(uv.reshape(1,1,2),k,d)[0,0]
                measured=transform(np.array([[ray[0],ray[1],1.]])*depth[y,x],camera['object_from_camera'])[0]
                residual.append(np.linalg.norm(measured-world[j])*1000)
            return {'count':len(residual),'median_mm':float(np.median(residual)) if residual else None,'p95_mm':float(np.percentile(residual,95)) if residual else None}
        factory_depth=depth_error(fit['factory_parameters'])
        candidate_depth=depth_error(fit['candidate_parameters']) if fit['candidate_parameters'] is not None else factory_depth
        registered=fit['factory_heldout']['median_px']<=5 and fit['factory_heldout']['p95_px']<=15 and fit['factory_heldout']['positive_fraction']==1 and factory_depth['count']>=20 and factory_depth['median_mm']<=20
        apply=fit['candidate_image_pass'] and candidate_depth['count']>=20 and factory_depth['count']>=20
        if apply:
            apply=candidate_depth['median_mm']<=factory_depth['median_mm']+.25 and candidate_depth['p95_mm']<=factory_depth['p95_mm']+.5 and candidate_depth['median_mm']<=20
        apply=bool(apply and registered)
        parameters=fit['candidate_parameters'] if apply else fit['factory_parameters']
        record.update(reference_registered=bool(registered), correction_applied=apply,
                      status='heldout_residual_correction' if apply else ('registered_factory_retained' if registered else 'reference_geometry_disagrees'),
                      reference_to_object=pose_matrix(parameters).tolist(),
                      correction=parameters[6:].tolist() if apply else [0.,0.,0.],
                      camera_signature=signature(cameras[0]['frame']),
                      factory_intrinsics_range=[np.min([c['frame']['intrinsics'] for c in cameras],axis=0).tolist(),np.max([c['frame']['intrinsics'] for c in cameras],axis=0).tolist()],
                      factory_heldout=fit['factory_heldout'],candidate_heldout=fit['candidate_heldout'],
                      factory_depth_agreement=factory_depth,candidate_depth_agreement=candidate_depth,
                      identifiable=fit['identifiable'], information_ratio=fit['information_ratio'],
                      train_observations=fit['train_observations'],heldout_observations=fit['heldout_observations'],
                      guidance='Phone setup saved. Only corrections supported by held-out images and depth are applied.' if registered else 'The two camera captures disagree. Keep the scene stationary and add overlapping rear views of the front-visible surfaces.')
        if apply and not compatible(record,frames):
            record.update(correction_applied=False,correction=[0.,0.,0.],status='registered_factory_retained',
                          guidance='Reference registered. Camera settings varied outside the fitted range; factory rays retained for the whole scan.')
    except (ValueError,KeyError,OSError,cv2.error) as error:
        record['guidance']=str(error)
    if record.get('reference_registered') and any(f.get('multi_camera') for f in frames):
        record['auxiliary_cameras']=check_auxiliary_references(root,usable,front,grid,image,record)
        record['three_rear_camera_calibration']=all(r.get('reference_registered') for r in record['auxiliary_cameras'].values())
        if not record['three_rear_camera_calibration']:
            record['guidance']='Primary depth reference registered. Some auxiliary views need more sharp texture or overlap; their unsupported stereo samples are excluded.'
    target.write_text(json.dumps(record,indent=2,allow_nan=False))
    return record


def rectify_observations(frame, depth, rgb, color_depth, selected, valid, raw_valid, profile):
    """Resample derived observations once; original captures never change.

    Nearest-neighbour depth/masks preserve missing samples. RGB uses linear
    interpolation. No invented depth or per-object scale adjustment occurs.
    """
    if not compatible(profile,[frame]):
        return frame,depth,rgb,color_depth,selected,valid,raw_valid
    correction=np.asarray(profile['correction'],float)
    if correction.shape!=(3,) or not np.isfinite(correction).all() or np.any(np.abs(correction)>[.03,.08,.05]):
        raise ValueError('Invalid bounded camera correction')
    def maps(width,height):
        k=scaled_intrinsics(frame['intrinsics'],frame['intrinsics_width'],frame['intrinsics_height'],width,height,mode=frame.get('depth_calibration_mode','pixel_center'))
        revised,d=camera_model(k,correction)
        return cv2.initUndistortRectifyMap(revised,d,None,revised,(width,height),cv2.CV_32FC1)
    mx,my=maps(depth.shape[1],depth.shape[0])
    def nearest(value):
        return cv2.remap(value,mx,my,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    depth=nearest(depth)
    color_depth=cv2.remap(color_depth,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    selected=nearest(selected.astype('uint8'))>0
    valid=nearest(valid.astype('uint8'))>0
    raw_valid=nearest(raw_valid.astype('uint8'))>0
    rx,ry=maps(rgb.shape[1],rgb.shape[0])
    rgb=cv2.remap(rgb,rx,ry,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    revised=dict(frame)
    intrinsics=list(frame['intrinsics']);intrinsics[0]*=float(np.exp(correction[0]));intrinsics[4]*=float(np.exp(correction[0]))
    revised['intrinsics']=intrinsics
    # Both paths have depth registered to their primary RGB camera.
    revised.pop('depth_intrinsics',None)
    return revised,depth,rgb,color_depth,selected,valid,raw_valid


def check_auxiliary_references(root, frames, front, grid, image, record):
    """Fit each auxiliary lens against measured front points in the primary world.

    The primary registration and metric scale stay fixed; held-out image regions
    decide whether a bounded focal/radial residual correction is useful.
    """
    from .multicamera import auxiliary_pose, load_trajectory
    trajectory=load_trajectory(root)
    world_from_front=np.asarray(record['reference_to_object'])
    reports={}
    h,w=grid.shape[:2]
    for name in ['ultra','tele']:
        xyzs=[];uvs=[];ks=[];poses=[];held=[];ids=[];views=set()
        for f in frames[:MAX_VIEWS]:
            observation=f.get('multi_camera')
            if not observation:
                continue
            sensor=observation['cameras'][name]
            calibration=read_json(asset(root,observation['calibration_path']))
            pose=auxiliary_pose(f,name,calibration,trajectory)
            if pose is None:
                continue
            rear=cv2.imread(str(asset(root,sensor['rgb_path'])),cv2.IMREAD_GRAYSCALE)
            if rear is None:
                continue
            try:
                rear_features=features(rear)
                matched=links(front,rear_features)
            except ValueError:continue
            k=np.asarray(sensor['intrinsics']).reshape((3,3),order='F')
            for match in matched:
                point=front[0][match.queryIdx]
                x,y=np.rint(point*[w/image.shape[1],h/image.shape[0]]).astype(int)
                if x<1 or y<1 or x>=w-1 or y>=h-1:
                    continue
                patch=grid[y-1:y+2,x-1:x+2]
                if not np.isfinite(patch).all() or np.ptp(patch[:,:,2])>max(.006,.02*grid[y,x,2]):
                    continue
                cell=(point/[image.shape[1],image.shape[0]]*[8,6]).astype(int)
                hold=int(hashlib.sha256(f'{cell[0]}:{cell[1]}:20261017'.encode()).hexdigest()[:8],16)%4==0
                optical=transform(transform(grid[y,x,:3][None],world_from_front),np.linalg.inv(pose))[0]
                if optical[2]<=.1:
                    continue
                xyzs.append(optical);uvs.append(rear_features[0][match.trainIdx]);ks.append(k);poses.append(f['frame_id']);held.append(hold);ids.append(match.queryIdx);views.add(f['frame_id'])
        r={'reference_registered':False,'correction_applied':False,'correction':[0.,0.,0.],'matched_views':len(views),'status':'insufficient_reference_overlap'}
        reports[name]=r
        xyzs,uvs,ks,held=np.asarray(xyzs),np.asarray(uvs),np.asarray(ks),np.asarray(held,dtype=bool)
        if len(views)<3 or len(set(np.asarray(ids)[held]))<20 or len(set(np.asarray(ids)[~held]))<40:
            continue
        def residual(correction):
            x=xyzs[:,:2]/xyzs[:,2:];radius=(x*x).sum(axis=1)
            distorted=x*(1+correction[1]*radius+correction[2]*radius*radius)[:,None]
            prediction=distorted*np.stack([ks[:,0,0],ks[:,1,1]],axis=1)*np.exp(correction[0])+ks[:,:2,2]
            return prediction-uvs
        before=np.linalg.norm(residual(np.zeros(3))[held],axis=1)
        fit=least_squares(lambda c:np.r_[residual(c)[~held].ravel()/2,c/[.01,.03,.02]],np.zeros(3),bounds=([-.03,-.08,-.05],[.03,.08,.05]),loss='soft_l1',max_nfev=100)
        after=np.linalg.norm(residual(fit.x)[held],axis=1)
        singular=np.linalg.svd(fit.jac[:-3]*np.array([.01,.03,.02]),compute_uv=False)
        identifiable=singular[-1]/max(singular[0],1e-12)>1e-5
        factory_ok=np.median(before)<=6 and np.percentile(before,95)<=18
        apply=bool(identifiable and fit.success and np.all(abs(fit.x)<np.array([.03,.08,.05])*.98) and np.median(after)<np.median(before)*.8 and np.percentile(after,95)<=np.percentile(before,95)+.2)
        registered=bool(factory_ok or (apply and np.median(after)<=6 and np.percentile(after,95)<=18))
        r.update(reference_registered=registered,correction_applied=bool(apply and registered),correction=fit.x.tolist() if apply and registered else [0.,0.,0.],
                 status='heldout_residual_correction' if apply and registered else 'registered_factory_retained' if registered else 'reference_geometry_disagrees',
                 factory_heldout={'median_px':float(np.median(before)),'p95_px':float(np.percentile(before,95))},
                 candidate_heldout={'median_px':float(np.median(after)),'p95_px':float(np.percentile(after,95))},
                 train_points=len(set(np.asarray(ids)[~held])),heldout_points=len(set(np.asarray(ids)[held])))
    return reports
