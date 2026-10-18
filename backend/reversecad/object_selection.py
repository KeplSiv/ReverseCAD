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
