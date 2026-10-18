"""Apply capture-first masks to geometry while retaining full-image tracking evidence."""
from __future__ import annotations
import hashlib
import numpy as np
from .contracts import safe_asset_path


def selection_mask(root, frame, shape, target):
    if target.get('confirmed') is not True:
        raise ValueError('Confirm the captured object before reconstruction')
    record = target.get('frames', {}).get(frame['frame_id'])
    if record is None:
        return np.zeros(shape, dtype=bool), 'unconfirmed_object_view'
    path = safe_asset_path(record['mask_path'])
    if not path.startswith('masks/objects/'):
        raise ValueError('Object masks must be derived assets')
    source = root / safe_asset_path(frame['rgb_path'])
    mask_file = root / path
    for file, expected in [(source, record['rgb_sha256']), (mask_file, record['mask_sha256'])]:
        if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):
            raise ValueError('Object selection asset escapes the capture')
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError('Object selection does not match the saved capture')
    raw = np.frombuffer(mask_file.read_bytes(), dtype=np.uint8)
    if raw.size != int(np.prod(shape)) or not np.isin(raw, [0, 255]).all():
        raise ValueError('Invalid derived object silhouette')
    return raw.reshape(shape) > 0, 'confirmed_same_instance_local_mask'


def remove_support_plane(depth, selected, k, pose):
    """Remove horizontal support only when broad surrounding depth supports it.

    No class dimensions or shape prior. A removed contact surface remains missing.
    """
    h, w = depth.shape
    y, x = np.mgrid[:h, :w]
    valid = np.isfinite(depth) & (depth > .04) & (depth < 3)
    rays = np.stack(((x-k[0, 2])/k[0, 0], (y-k[1, 2])/k[1, 1], np.ones_like(x)), -1)
    world = (rays * np.where(valid, depth, 0)[..., None]) @ pose[:3, :3].T + pose[:3, 3]
    outside = valid & ~selected
    if np.count_nonzero(outside) < 100 or not np.any(selected & valid):
        return selected
    heights = world[..., 1]
    bins = np.round(heights[outside] / .003).astype(np.int64)
    values, counts = np.unique(bins, return_counts=True)
    mode = values[np.argmax(counts)] * .003
    in_plane = outside & (np.abs(heights-mode) <= .003)
    # A broad plane, not a narrow object feature or arbitrary depth cluster.
    points = world[in_plane]
    if len(points) < max(100, np.count_nonzero(outside)*.12) or np.ptp(points[:, 0]) < .15 or np.ptp(points[:, 2]) < .15:
        return selected
    return selected & (np.abs(heights-mode) > .003)


def consistent_views(frames):
    """Reject disjoint object masks; require measured overlap with another view."""
    from scipy.spatial import cKDTree
    if len(frames) < 2:
        return [], frames
    trees = [cKDTree(f['points']) for f in frames]
    keep = []
    for i, frame in enumerate(frames):
        sample = frame['points'][::max(1, len(frame['points']) // 1000)]
        supported = any(np.mean(tree.query(sample, workers=1)[0] < .015) >= .08
                        for j, tree in enumerate(trees) if i != j)
        if supported: keep.append(i)
    return [f for i, f in enumerate(frames) if i in keep], [f for i, f in enumerate(frames) if i not in keep]


def repair_selection_frames(root, frames, annotations):
    """Give main's existing repair detector a bounded, verified object search region.

    This is a transient view of the original frames. Missing areas inside the
    object's padded extent stay visible so a repair can be inferred separately
    from the observed mesh. Labels and Jev boxes never supply CAD dimensions.
    """
    target = annotations.get('object_target') or {}
    if target.get('workflow') != 'capture_first_v1':
        return frames
    selected = []
    for frame in frames:
        if not frame.get('quality', {}).get('accepted', False) or not frame.get('depth_path'):
            continue
        shape = (frame['depth_height'], frame['depth_width'])
        mask, _ = selection_mask(root, frame, shape, target)
        y, x = np.nonzero(mask)
        if len(x) < 30:
            continue
        h, w = shape
        bounds = [x.min()/w, y.min()/h, (x.max()+1)/w, (y.max()+1)/h]
        record = target['frames'][frame['frame_id']]
        box = record.get('box')
        if box is not None:
            box = np.asarray(box, dtype=float)
            if box.shape != (4,) or not np.isfinite(box).all() or (box[:2]<0).any() or (box[2:]<=0).any() or (box[:2]+box[2:]>1.000001).any():
                raise ValueError('Invalid object selection bounds')
            bounds = [min(bounds[0],box[0]),min(bounds[1],box[1]),max(bounds[2],box[0]+box[2]),max(bounds[3],box[1]+box[3])]
        pad_x, pad_y = (bounds[2]-bounds[0])*.20, (bounds[3]-bounds[1])*.20
        left, top, right, bottom = max(0,bounds[0]-pad_x),max(0,bounds[1]-pad_y),min(1,bounds[2]+pad_x),min(1,bounds[3]+pad_y)
        selected.append({**frame, 'capture_region':[left,top,right-left,bottom-top],
                         'mask_path': record['mask_path'], 'selection_source':'confirmed_same_instance'})
    if len(selected) < 3:
        raise ValueError('Damage analysis needs three confirmed object views. The original capture is preserved; add sharp overlapping views of the damage and intact features.')
    return selected


def supports_repair_region(root, frame, polygon, image_shape):
    """Reject damage candidates on background inside the padded search box."""
    if frame.get('selection_source') != 'confirmed_same_instance':
        return True
    import cv2
    raw = np.frombuffer((root / frame['mask_path']).read_bytes(), dtype=np.uint8)
    mask = raw.reshape(frame['depth_height'],frame['depth_width']) > 0
    mask = cv2.resize(mask.astype(np.uint8), (image_shape[1],image_shape[0]), interpolation=cv2.INTER_NEAREST)
    candidate = np.zeros(image_shape[:2],dtype=np.uint8)
    cv2.fillPoly(candidate,[np.rint(polygon).astype(np.int32)],1)
    count = np.count_nonzero(candidate)
    # Missing cells may be empty; most of the proposed face must still be this object.
    return count > 0 and np.count_nonzero(candidate & mask) / count >= .45
