"""Bounded calibrated stereo refinement. RGB observations never set metric scale.

No shading-to-depth inference: textureless, occluded, inconsistent pixels stay
with native depth. Refinement is a surface hypothesis, not metrology evidence.
"""
from pathlib import Path
import cv2
import numpy as np
from .geometry import dot, project, transform_points
from .capture_region import region_mask, masked_photo


def stereo_pair(a, b, *, trust_native_depth=True):
    """Return a rectified, masked high-resolution depth frame, or no refinement."""
    relative = np.linalg.inv(b['pose']) @ a['pose']
    baseline = np.linalg.norm(relative[:3, 3])
    if not .006 <= baseline <= .06:
        return None
    image_a, image_b = [masked_photo(f['image'],f.get('capture_region')) for f in (a,b)]
    h, w = image_a.shape[:2]
    if image_b.shape != image_a.shape:
        return None
    r1, r2, p1, p2, q, _, _ = cv2.stereoRectify(a['image_k'], None, b['image_k'], None,
        (w, h), relative[:3, :3], relative[:3, 3], flags=cv2.CALIB_ZERO_DISPARITY, alpha=0)
    # SGBM uses positive horizontal disparity; reverse the pair if necessary.
    vertical = abs(p2[1, 3]) > abs(p2[0, 3])
    disparity_axis = 1 if vertical else 0
    if p2[disparity_axis, 3] >= 0:
        return None
    maps = [cv2.initUndistortRectifyMap(f['image_k'], None, r, p[:, :3], (w, h), cv2.CV_32FC1)
            for f, r, p in ((a, r1, p1), (b, r2, p2))]
    left, right = [cv2.remap(im, *m, cv2.INTER_LINEAR) for im, m in zip((image_a, image_b), maps)]
    mask_a = a.get('foreground_mask')
    mask_b = b.get('foreground_mask')
    if a.get('capture_region') is not None:
        mask_a=region_mask(a['capture_region'],image_a.shape) & (mask_a if mask_a is not None else True)
    if b.get('capture_region') is not None:
        mask_b=region_mask(b['capture_region'],image_b.shape) & (mask_b if mask_b is not None else True)
    if mask_a is not None and mask_b is not None:
        # Rectify the phone's foreground masks with the same calibration as the
        # photos. Without this, stereo happily reconstructs the tabletop and
        # background; the resulting scene-sized cloud makes small-part fitting
        # fail (or, worse, fit the wrong planes).
        rect_masks = [cv2.remap(mask.astype(np.uint8), *m, cv2.INTER_NEAREST,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0) > 0
                      for mask, m in zip((mask_a, mask_b), maps)]
    else:
        rect_masks = None
    gray_l, gray_r = [cv2.cvtColor(im, cv2.COLOR_RGB2GRAY) for im in (left, right)]
    if vertical:
        # SGBM searches horizontally. Transpose only the matching images;
        # restore the disparity map before Q reprojection in calibrated pixels.
        gray_l, gray_r = gray_l.T.copy(), gray_r.T.copy()
    h, w = gray_l.shape
    native = a['depth'][a['depth'] > 0]
    if native.size < 50:
        return None
    maximum = int(np.ceil((abs(p2[disparity_axis, 3]) / max(.04, np.percentile(native, 5) - .015) + 16) / 16) * 16)
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
    if rect_masks is not None:
        ml, mr = rect_masks
        if vertical:
            ml, mr = ml.T.copy(), mr.T.copy()
        valid &= ml & mr[yy, xr]
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
    if vertical:
        disparity, valid, lr_error = disparity.T.copy(), valid.T.copy(), lr_error.T.copy()
        h, w = disparity.shape
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
        # A failed depth surface cannot veto independent photo geometry. In
        # recovery mode depth supplies the foreground footprint only; independent
        # stereo pairs must subsequently confirm the recovered surface.
        good &= in_frame & (measured > 0)
        if trust_native_depth:
            good &= abs(z-measured) < np.minimum(.008, np.maximum(.003, measured*.025))
    depth = np.zeros((h, w), dtype=np.float32)
    depth[rows[good], cols[good]] = xyz[rows[good], cols[good], 2]
    if np.count_nonzero(depth) < 100:
        return None
    return {'depth': depth, 'color': left, 'k': p1[:, :3], 'pose': rect_pose,
            'source_frames': [a['frame_id'], b['frame_id']],
            'median_lr_error_px': float(np.median(lr_error[rows[good], cols[good]]))}


def refine_photos(frames, scan_dir: Path, max_pairs=8, *, trust_native_depth=True):
    """Load a bounded set of original photos; emit detail depth in fixed metric poses."""
    report = {'status': 'insufficient_photo_evidence', 'method': 'calibrated_bidirectional_stereo',
              'scale_source': 'ARKit_metric_camera_baseline_and_native_depth_check',
              'accuracy_calibrated': False, 'pairs': [], 'accepted_pixels': 0,
              'limitations': 'Textureless, reflective or unseen details are unresolved. Stereo does not infer missing geometry.'}
    report['native_surface_gate'] = 'enabled' if trust_native_depth else 'disabled_failed_native_surface'
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
        foreground = frame.get('foreground_mask')
        if foreground is not None:
            foreground = cv2.resize(foreground.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
        mask_path = frame.get('mask_path')
        if mask_path:
            raw = np.fromfile(scan_dir / mask_path, dtype=np.uint8)
            if raw.size == frame['rgb_width'] * frame['rgb_height']:
                foreground = raw.reshape(frame['rgb_height'], frame['rgb_width'])
            elif raw.size == frame.get('depth_width', 0) * frame.get('depth_height', 0):
                foreground = cv2.resize(raw.reshape(frame['depth_height'], frame['depth_width']),
                                        (frame['rgb_width'], frame['rgb_height']),
                                        interpolation=cv2.INTER_NEAREST)
            if foreground is not None:
                foreground = cv2.resize(foreground, size, interpolation=cv2.INTER_NEAREST) > 0
        if frame.get('capture_region') is not None:
            guide=region_mask(frame['capture_region'],image.shape)
            foreground=guide & (foreground if foreground is not None else True)
            image=masked_photo(image,frame['capture_region'])
        result = {**frame, 'image': image, 'image_k': resize @ frame['image_k'],
                  'foreground_mask': foreground}
        cache[frame['frame_id']] = result
        return result
    # Small overlapping baselines preserve common visibility. Never use distant
    # opposite views merely because they have similar repeated cube colors.
    selected = frames[::max(1, len(frames)//24)][:24]
    candidates = []
    for i, a in enumerate(selected):
        for b in selected[i+1:]:
            baseline = np.linalg.norm(a['pose'][:3, 3]-b['pose'][:3, 3])
            if .006 <= baseline <= .06 and np.dot(a['pose'][:3, 2], b['pose'][:3, 2]) > .97:
                candidates.append((abs(baseline-.018), a, b))
    uses = {}; attempted = []
    while candidates and len(attempted) < max(12, max_pairs * 2) and len(results) < max_pairs:
        # Spend the bounded budget on distinct pairs and spread support across views.
        candidates.sort(key=lambda item: (uses.get(item[1]['frame_id'],0)+uses.get(item[2]['frame_id'],0), item[0]))
        _, a, b = candidates.pop(0)
        pair = [a['frame_id'], b['frame_id']]
        attempted.append(pair)
        for frame_id in pair: uses[frame_id] = uses.get(frame_id,0)+1
        aa, bb = load(a), load(b)
        if aa is None or bb is None: continue
        detail = stereo_pair(aa, bb, trust_native_depth=trust_native_depth)
        if detail is None: detail = stereo_pair(bb, aa, trust_native_depth=trust_native_depth)
        if detail is not None:
            results.append(detail)
            report['pairs'].append({'frame_ids': detail['source_frames'], 'pixels': int(np.count_nonzero(detail['depth'])),
                                    'median_lr_error_px': detail['median_lr_error_px']})
        cache.clear()
    report['attempted_pairs'] = attempted
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


def cross_validate_details(details, tolerance_m=.001):
    """Retain samples supported by a different stereo pair (at least 3 photos).

    The tolerance is an agreement gate, not an accuracy claim. No filling,
    smoothing or native depth substitution is performed here.
    """
    from .geometry import unproject
    accepted = []
    for i, source in enumerate(details):
        rows, cols = np.nonzero(np.isfinite(source['depth']) & (source['depth'] > 0))
        world, _ = unproject(source['depth'], source['k'], source['pose'])
        supported = np.zeros(len(world), dtype=bool)
        for j, target in enumerate(details):
            if i == j or len(set(source['source_frames']) | set(target['source_frames'])) < 3:
                continue
            uv, z = project(world, target['k'], target['pose'])
            valid = np.isfinite(uv).all(axis=1) & (z > 0)
            h, w = target['depth'].shape
            valid &= (uv[:,0]>=0)&(uv[:,0]<w-1)&(uv[:,1]>=0)&(uv[:,1]<h-1)
            ids = np.flatnonzero(valid)
            pixels = np.rint(uv[ids]).astype(int)
            measured = target['depth'][pixels[:,1],pixels[:,0]]
            supported[ids] |= (measured > 0) & (abs(measured-z[ids]) <= tolerance_m)
        depth = np.zeros_like(source['depth'])
        depth[rows[supported], cols[supported]] = source['depth'][rows[supported], cols[supported]]
        if supported.sum() >= 100:
            accepted.append({**source,'depth':depth})
    count = sum(int(np.count_nonzero(f['depth'])) for f in accepted)
    return accepted, {'cross_pair_supported_pixels':count, 'cross_pair_tolerance_mm':tolerance_m*1000,
                     'minimum_source_photos':3,'accuracy_calibrated':False}
