"""Reused CPU stereo adapter; see docs/sparse-reconstruction/reuse.json."""
from pathlib import Path
import cv2
import numpy as np

def asset_path(root, relative):
    from ..reconstruction import _asset
    return _asset(root, relative)

def _cv_camera(camera):
    params = np.asarray(camera.params)
    model = camera.model_name
    if model in {'PINHOLE', 'OPENCV', 'FULL_OPENCV'}:
        K = np.array([[params[0], 0, params[2] - .5], [0, params[1], params[3] - .5], [0, 0, 1.]])
        D = params[4:] if model != 'PINHOLE' else np.zeros(5)
        return K, D
    if model in {'SIMPLE_PINHOLE', 'SIMPLE_RADIAL', 'RADIAL'}:
        K = np.array([[params[0], 0, params[1] - .5], [0, params[0], params[2] - .5], [0, 0, 1.]])
        D = np.zeros(5); D[:max(0, len(params) - 3)] = params[3:]
        return K, D
    raise ValueError(f'CPU dense fallback does not implement {model}; sparse model is preserved')


def _cpu_mvs(rec, mapping, manifest, masks, out, options):
    """CPU pair stereo with LR checks and a different pair confirming each point."""
    registered = sorted([im for im in rec.images.values() if im.has_pose], key=lambda im: im.name)
    known_frame_ids = {frame['frame_id'] for frame in mapping.values()}
    maximum_frame_id_length = max(map(len, known_frame_ids), default=1)
    max_width = int(options.get('dense_max_width', 640))
    records, skipped = [], []
    dense_dir = out / 'dense'; dense_dir.mkdir()
    for left, right in list(zip(registered[:-1], registered[1:]))[:int(options.get('dense_max_pairs', 6))]:
        try:
            Kl, Dl = _cv_camera(left.camera); Kr, Dr = _cv_camera(right.camera)
            size = (min(max_width, left.camera.width), round(left.camera.height * min(1., max_width / left.camera.width)))
            def resized(image, K):
                frame = mapping[image.name]
                rgb = cv2.imread(str(asset_path(Path(manifest['root']), frame['image_path'])))
                scale = np.asarray(size) / [frame['width'], frame['height']]
                k = K.copy(); k[0, 0] *= scale[0]; k[1, 1] *= scale[1]
                k[:2, 2] = (k[:2, 2] + .5) * scale - .5
                return cv2.resize(rgb, size, interpolation=cv2.INTER_AREA), k
            il, Kl = resized(left, Kl); ir, Kr = resized(right, Kr)
            tl, tr = left.cam_from_world(), right.cam_from_world()
            relative = tr * tl.inverse(); R, t = relative.rotation.matrix(), relative.translation
            if abs(t[1]) > abs(t[0]):
                raise ValueError('Vertical rectified baseline not supported by CPU horizontal-SGBM fallback')
            if t[0] > 0:
                left, right, il, ir, Kl, Kr, Dl, Dr = right, left, ir, il, Kr, Kl, Dr, Dl
                tl, tr = left.cam_from_world(), right.cam_from_world(); relative = tr * tl.inverse()
                R, t = relative.rotation.matrix(), relative.translation
            # Retain the field of view. alpha=0 can zoom toe-in views so far that
            # every real disparity exceeds the entire image width.
            R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(Kl, Dl, Kr, Dr, size, R, t, flags=cv2.CALIB_ZERO_DISPARITY, alpha=1)
            m1 = cv2.initUndistortRectifyMap(Kl, Dl, R1, P1, size, cv2.CV_32FC1)
            m2 = cv2.initUndistortRectifyMap(Kr, Dr, R2, P2, size, cv2.CV_32FC1)
            a = cv2.remap(il, *m1, cv2.INTER_LINEAR); b = cv2.remap(ir, *m2, cv2.INTER_LINEAR)
            gray_a, gray_b = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
            # Orbiting close objects can exceed 128 px disparity even after
            # preserving the full field of view. Keep the search bounded to
            # half the image width, at most 384 px.
            count = max(16, min(384, (size[0] // 2 // 16) * 16))
            parameters = dict(numDisparities=count, blockSize=5, P1=8 * 25, P2=32 * 25,
                              disp12MaxDiff=1, uniquenessRatio=12, speckleWindowSize=80,
                              speckleRange=2, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
            dl = cv2.StereoSGBM_create(minDisparity=0, **parameters).compute(gray_a, gray_b).astype('float32') / 16
            dr = cv2.StereoSGBM_create(minDisparity=-count, **parameters).compute(gray_b, gray_a).astype('float32') / 16
            yy, xx = np.mgrid[:size[1], :size[0]]
            matched_right = xx.astype('float32') - dl
            reverse = cv2.remap(dr, matched_right, yy.astype('float32'), cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=-10000)
            valid = (dl > .5) & (dl < count - 1) & (np.abs(dl + reverse) <= 1.)
            valid &= (m1[0] >= 1) & (m1[0] < size[0] - 2) & (m1[1] >= 1) & (m1[1] < size[1] - 2)
            rectified = cv2.reprojectImageTo3D(dl, Q)
            camera_points = np.einsum('...j,ji->...i', rectified, R1)
            Twc = tl.inverse().matrix(); world = np.einsum('...j,ij->...i', camera_points, Twc[:, :3]) + Twc[:, 3]
            valid &= np.isfinite(world).all(axis=-1) & (camera_points[..., 2] > 0)
            fid = mapping[left.name]['frame_id']
            if len(masks) >= 2:
                # Both source images must have object selection support.
                if fid not in masks or mapping[right.name]['frame_id'] not in masks:
                    valid[:] = False
                else:
                    lm = cv2.resize(masks[fid].astype('uint8'), size, interpolation=cv2.INTER_NEAREST)
                    rm = cv2.resize(masks[mapping[right.name]['frame_id']].astype('uint8'), size, interpolation=cv2.INTER_NEAREST)
                    lm = cv2.remap(lm, *m1, cv2.INTER_NEAREST) > 0
                    rm = cv2.remap(rm, *m2, cv2.INTER_NEAREST)
                    valid &= lm & (cv2.remap(rm, matched_right, yy.astype('float32'), cv2.INTER_NEAREST) > 0)
            records.append({'left': left, 'right': right, 'world': world, 'rect_z': rectified[..., 2], 'valid': valid,
                            'rgb': a[..., ::-1], 'R1': R1, 'P1': P1, 'cam_from_world': tl.matrix()})
            np.savez_compressed(dense_dir / f'pair-{len(records)-1:03d}.npz', disparity_px=dl, lr_valid=valid,
                                points_world_unscaled=world, original_frame_ids=[fid, mapping[right.name]['frame_id']])
        except (ValueError, cv2.error) as error:
            skipped.append({'pair': [left.name, right.name], 'reason': str(error)})
    xyz, colors, ids, support = [], [], [], []
    counts = []
    for index, row in enumerate(records):
        point = row['world'][row['valid']]
        rgb = row['rgb'][row['valid']]
        accepted = np.zeros(len(point), bool)
        confirmation = np.full(len(point), '', dtype=f'U{maximum_frame_id_length}')
        own = {row['left'].image_id, row['right'].image_id}
        for other in records:
            other_ids = {other['left'].image_id, other['right'].image_id}
            if len(own | other_ids) < 3:
                continue
            camera = np.einsum('nj,ij->ni', point, other['cam_from_world'][:, :3]) + other['cam_from_world'][:, 3]
            rect = np.einsum('nj,ij->ni', camera, other['R1'])
            projection = np.einsum('nj,ij->ni', rect, other['P1'][:, :3])
            uv = projection[:, :2] / projection[:, 2, None]
            finite = np.isfinite(uv).all(axis=1)
            q = np.rint(np.where(np.isfinite(uv), uv, -1)).astype(int)
            h, w = other['valid'].shape
            inside = finite & (rect[:, 2] > 0) & (q[:, 0] >= 0) & (q[:, 0] < w) & (q[:, 1] >= 0) & (q[:, 1] < h)
            candidates = np.flatnonzero(inside)
            x, y = q[candidates, 0], q[candidates, 1]
            ok = other['valid'][y, x] & (np.abs(rect[candidates, 2] - other['rect_z'][y, x]) <= .02 * rect[candidates, 2])
            chosen = candidates[ok]
            accepted[chosen] = True
            extra = other_ids - own
            confirmation[chosen] = mapping[rec.images[min(extra)].name]['frame_id']
        stride = max(1, int(options.get('dense_point_stride', 2)))
        keep = np.flatnonzero(accepted)[::stride]
        if not set(confirmation[keep]) <= known_frame_ids:
            raise ValueError('Dense confirmation frame IDs changed; support must resolve to preserved source frames')
        counts.append({'pair': index, 'lr_consistent': len(point), 'cross_pair_consistent': int(accepted.sum()), 'exported': len(keep)})
        xyz.extend(point[keep]); colors.extend(rgb[keep])
        ids.extend(f'dense:{index}:{int(k)}' for k in keep)
        support.extend([[mapping[row['left'].name]['frame_id'], mapping[row['right'].name]['frame_id'], confirmation[k]] for k in keep])
    report = {'state': 'complete' if xyz else 'unavailable', 'method': 'cpu_rectified_sgbm_multiview_consistency',
              'rectification_alpha': 1,
              'native_colmap_patchmatch': False, 'maximum_derived_image_width': max_width, 'source_images_preserved': True,
              'left_right_gate_px': 1., 'cross_pair_relative_z_gate': .02, 'minimum_distinct_support_views': 3,
              'pairs': counts, 'skipped': skipped, 'exported_points': len(xyz),
              'limits': ['Rectified downsampled CPU matching is not native COLMAP CUDA MVS.',
                         'Three-view consistency is an internal diagnostic, not physical accuracy.',
                         'Points accumulate across overlapping rectified pairs; the count is not independent surface samples.',
                         'Only supported observed points exported; no surface completion or hole filling.']}
    return np.asarray(xyz).reshape(-1, 3), np.asarray(colors, np.uint8).reshape(-1, 3), ids, support, report
