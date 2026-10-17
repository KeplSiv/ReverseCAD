"""Bounded calibrated stereo refinement. RGB observations never set metric scale.

No shading-to-depth inference: textureless, occluded, inconsistent pixels stay
with native depth. Refinement is a surface hypothesis, not metrology evidence.
"""
from pathlib import Path
import cv2
import numpy as np
from .geometry import dot, project, transform_points


def stereo_pair(a, b):
    """Return a rectified, masked high-resolution depth frame, or no refinement."""
    relative = np.linalg.inv(b['pose']) @ a['pose']
    baseline = np.linalg.norm(relative[:3, 3])
    if not .006 <= baseline <= .06:
        return None
    image_a, image_b = a['image'], b['image']
    h, w = image_a.shape[:2]
    if image_b.shape != image_a.shape:
        return None
    r1, r2, p1, p2, q, _, _ = cv2.stereoRectify(a['image_k'], None, b['image_k'], None,
        (w, h), relative[:3, :3], relative[:3, 3], flags=cv2.CALIB_ZERO_DISPARITY, alpha=0)
    # SGBM uses positive horizontal disparity; reverse the pair if necessary.
    if abs(p2[1, 3]) > abs(p2[0, 3]):
        return None
    if p2[0, 3] >= 0:
        return None
    maps = [cv2.initUndistortRectifyMap(f['image_k'], None, r, p[:, :3], (w, h), cv2.CV_32FC1)
            for f, r, p in ((a, r1, p1), (b, r2, p2))]
    left, right = [cv2.remap(im, *m, cv2.INTER_LINEAR) for im, m in zip((image_a, image_b), maps)]
    gray_l, gray_r = [cv2.cvtColor(im, cv2.COLOR_RGB2GRAY) for im in (left, right)]
    native = a['depth'][a['depth'] > 0]
    if native.size < 50:
        return None
    maximum = int(np.ceil((abs(p2[0, 3]) / max(.04, np.percentile(native, 5) - .015) + 16) / 16) * 16)
    if maximum >= w // 2 or maximum > 256:
        return None
    maximum = max(32, maximum)
    def matcher(minimum):
        return cv2.StereoSGBM_create(minDisparity=minimum, numDisparities=maximum,
            blockSize=5, P1=8*25, P2=32*25, disp12MaxDiff=1,
            uniquenessRatio=18, speckleWindowSize=60, speckleRange=1,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
    disparity = matcher(0).compute(gray_l, gray_r).astype(np.float32) / 16
    reverse = matcher(-maximum).compute(gray_r, gray_l).astype(np.float32) / 16
    yy, xx = np.indices((h, w))
    xr = np.rint(xx - disparity).astype(int)
    inside = (xr >= 0) & (xr < w)
    xr = np.clip(xr, 0, w-1)
    lr_error = abs(disparity + reverse[yy, xr])
    mean = cv2.boxFilter(gray_l.astype(np.float32), -1, (7, 7))
    variance = cv2.boxFilter(gray_l.astype(np.float32)**2, -1, (7, 7)) - mean**2
    valid = inside & (disparity > 1) & (disparity < maximum-1) & (lr_error < .75) & (variance > 25)
    # Stereo must also reproduce the same appearance in both images.
    valid &= abs(gray_l.astype(float) - gray_r[yy, xr].astype(float)) < 22
    # SGBM's discrete cost curve biases subpixel steps towards integer disparity.
    # Refine only already-validated matches by local photometric alignment.
    initial = disparity.copy()
    right_float = gray_r.astype(np.float32)
    gradient = cv2.Sobel(right_float, cv2.CV_32F, 1, 0, ksize=3, scale=1/8)
    for _ in range(5):
        map_x = (xx-disparity).astype(np.float32)
        map_y = yy.astype(np.float32)
        warped = cv2.remap(right_float, map_x, map_y, cv2.INTER_LINEAR)
        grad = cv2.remap(gradient, map_x, map_y, cv2.INTER_LINEAR)
        residual = gray_l.astype(np.float32)-warped
        numerator = cv2.boxFilter(grad*residual, -1, (5, 5))
        denominator = cv2.boxFilter(grad*grad, -1, (5, 5))
        delta = -numerator/np.maximum(denominator, 1)
        disparity = np.clip(disparity+np.clip(delta, -.25, .25), initial-.75, initial+.75)
    valid &= disparity > 1
    xyz = cv2.reprojectImageTo3D(disparity, q)
    rect_pose = a['pose'].copy()
    rect_pose[:3, :3] = a['pose'][:3, :3] @ r1.T
    rows, cols = np.nonzero(valid & np.isfinite(xyz).all(axis=2) & (xyz[:, :, 2] > .04) & (xyz[:, :, 2] < 3))
    if len(rows) < 100:
        return None
    world = transform_points(xyz[rows, cols], rect_pose)
    good = np.ones(len(world), dtype=bool)
    for frame in (a, b):
        uv, z = project(world, frame['k'], frame['pose'])
        uv = np.rint(uv).astype(int)
        dh, dw = frame['depth'].shape
        in_frame = (uv[:, 0] >= 0) & (uv[:, 0] < dw) & (uv[:, 1] >= 0) & (uv[:, 1] < dh)
        uv = np.clip(uv, 0, [dw-1, dh-1])
        measured = frame['depth'][uv[:, 1], uv[:, 0]]
        good &= in_frame & (measured > 0) & (abs(z-measured) < np.minimum(.008, np.maximum(.003, measured*.025)))
    depth = np.zeros((h, w), dtype=np.float32)
    depth[rows[good], cols[good]] = xyz[rows[good], cols[good], 2]
    if np.count_nonzero(depth) < 100:
        return None
    return {'depth': depth, 'color': left, 'k': p1[:, :3], 'pose': rect_pose,
            'source_frames': [a['frame_id'], b['frame_id']],
            'median_lr_error_px': float(np.median(lr_error[rows[good], cols[good]]))}


def refine_photos(frames, scan_dir: Path, max_pairs=8):
    """Load a bounded set of original photos; emit detail depth in fixed metric poses."""
    report = {'status': 'insufficient_photo_evidence', 'method': 'calibrated_bidirectional_stereo',
              'scale_source': 'ARKit_metric_camera_baseline_and_native_depth_check',
              'accuracy_calibrated': False, 'pairs': [], 'accepted_pixels': 0,
              'limitations': 'Textureless, reflective or unseen details are unresolved. Stereo does not infer missing geometry.'}
    results = []
    cache = {}
    def load(frame):
        if frame['frame_id'] in cache:
            return cache[frame['frame_id']]
        image = cv2.imread(str(scan_dir / frame['rgb_path']))
        if image is None:
            return None
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w = image.shape[:2]
        factor = min(1, 1280/max(h, w))
        size = (round(w*factor), round(h*factor))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        # image_k is calibrated to the original image, with OpenCV resize offsets.
        resize = np.array([[size[0]/w, 0, (size[0]/w-1)/2], [0, size[1]/h, (size[1]/h-1)/2], [0, 0, 1.]])
        result = {**frame, 'image': image, 'image_k': resize @ frame['image_k']}
        cache[frame['frame_id']] = result
        return result
    # Small overlapping baselines preserve common visibility. Never use distant
    # opposite views merely because they have similar repeated cube colors.
    selected = frames[::max(1, len(frames)//24)][:24]
    attempts = 0
    for i, a in enumerate(selected):
        candidates = [b for b in frames if b['frame_id'] != a['frame_id']
                      and .006 <= np.linalg.norm(a['pose'][:3, 3]-b['pose'][:3, 3]) <= .06
                      and np.dot(a['pose'][:3, 2], b['pose'][:3, 2]) > .97]
        if not candidates:
            continue
        b = min(candidates, key=lambda b: abs(np.linalg.norm(a['pose'][:3, 3]-b['pose'][:3, 3])-.018))
        aa, bb = load(a), load(b)
        if aa is None or bb is None:
            continue
        detail = stereo_pair(aa, bb)
        if detail is None:
            detail = stereo_pair(bb, aa)
        attempts += 1
        if detail is not None:
            pair = tuple(sorted(detail['source_frames']))
            if not any(tuple(sorted(x['source_frames'])) == pair for x in results):
                results.append(detail)
                report['pairs'].append({'frame_ids': detail['source_frames'], 'pixels': int(np.count_nonzero(detail['depth'])),
                                        'median_lr_error_px': detail['median_lr_error_px']})
        cache.clear()
        if len(results) >= max_pairs or attempts >= 12:
            break
    report['accepted_pixels'] = sum(x['pixels'] for x in report['pairs'])
    report['status'] = 'photo_detail_integrated' if results else 'insufficient_photo_evidence'
    return report, results


def integration_frames(native_frames, detail_frames):
    """Avoid averaging validated photo relief back into a coarse native plane.

    Preserve original observations for measurements; suppress only coarse surface
    integration pixels with several consistent projected detail samples.
    """
    from .geometry import unproject
    derived = [{**f, 'depth': f['depth'].copy()} for f in native_frames]
    removed = 0
    for detail in detail_frames:
        world, _ = unproject(detail['depth'], detail['k'], detail['pose'])
        world = world[::max(1, len(world)//30000)]
        for original, target in zip(native_frames, derived):
            if np.dot(original['pose'][:3, 2], detail['pose'][:3, 2]) < .8:
                continue
            uv, z = project(world, original['k'], original['pose'])
            uv = np.rint(uv).astype(int)
            h, w = original['depth'].shape
            valid = (z > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
            uv, z = uv[valid], z[valid]
            native = original['depth'][uv[:, 1], uv[:, 0]]
            valid = (native > 0) & (abs(z-native) < np.minimum(.008, np.maximum(.003, native*.025)))
            uv = uv[valid]
            counts = np.bincount(uv[:, 1]*w+uv[:, 0], minlength=h*w).reshape(h, w)
            supported = counts >= 3
            removed += int(np.count_nonzero(supported & (target['depth'] > 0)))
            target['depth'][supported] = 0
    return derived+detail_frames, removed
