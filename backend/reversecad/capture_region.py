"""Shared calibrated guide bounds. Crops never change full-image coordinates."""
import numpy as np


def capture_bounds(region, shape, minimum=1):
    """Strict normalized raw-image guide; no silently expanded search area."""
    h, w = shape[:2]
    if region is None: return (0, 0, w, h)
    r = np.asarray(region, dtype=float)
    if r.shape != (4,) or not np.isfinite(r).all() or min(r[:2]) < 0 or min(r[2:]) <= 0 or max(r[:2]+r[2:]) > 1.000001:
        raise ValueError('Invalid capture guide coordinates')
    x0,y0 = np.ceil(r[:2]*[w,h]).astype(int)
    x1,y1 = np.floor((r[:2]+r[2:])*[w,h]).astype(int)
    if min(x1-x0,y1-y0) < minimum: raise ValueError('Capture guide is too small')
    return x0,y0,x1,y1


def region_mask(region, shape):
    x0,y0,x1,y1=capture_bounds(region,shape)
    mask=np.zeros(shape[:2],dtype=bool)
    mask[y0:y1,x0:x1]=True
    return mask


def masked_photo(image, region):
    if region is None:return image
    result=image.copy()
    result[~region_mask(region,image.shape)]=0
    return result
