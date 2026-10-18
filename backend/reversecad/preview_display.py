"""Presentation-only orientation and piece identity; never changes calibration."""
import cv2
import numpy as np

PALETTE = [(1.,.55,.05),(.12,.72,1.),(.72,.42,1.),(.25,.85,.48),
           (1.,.38,.58),(.88,.80,.25),(.48,.65,.92),(.8,.55,.35)]

def piece_color(index):
    return list(PALETTE[index % len(PALETTE)])

def display_rotation(frame):
    explicit=frame.get('display_rotation_cw_deg')
    if explicit in (0,90,180,270):
        return int(explicit)
    # Legacy AR captures omitted UI orientation. Recover upright from ARKit's
    # gravity-aligned world, only when gravity has a useful image projection.
    raw=frame.get('T_world_camera')
    if raw is not None:
        pose=np.asarray(raw,float).reshape(4,4,order='F')
        up=pose[:3,:3].T@np.array([0.,1.,0.])
        if np.isfinite(up).all() and np.linalg.norm(up[:2])>.25:
            if abs(up[0])>abs(up[1]):return 90 if up[0]<0 else 270
            return 0 if up[1]>0 else 180
    return 0

def orient_preview(image,frame):
    rotation=display_rotation(frame)
    flags={90:cv2.ROTATE_90_CLOCKWISE,180:cv2.ROTATE_180,270:cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(image,flags[rotation]) if rotation else image
