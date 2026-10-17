"""Track an observed planar region across images without an object template."""
import cv2
import numpy as np


def track_region(previous, current, corners):
    """Return a homography-supported quad or reject an ambiguous/weak track.

    Coordinates are pixels in same-sized grayscale images. Forward/backward
    optical flow and distributed RANSAC inliers are required. This transfers an
    observation; it does not infer a hidden surface or a physical dimension.
    """
    if previous.shape != current.shape or previous.ndim != 2:
        return None
    corners = np.asarray(corners, np.float32).reshape(4,2)
    if not np.isfinite(corners).all():return None
    h,w = previous.shape
    mask = np.zeros((h,w),np.uint8)
    cv2.fillConvexPoly(mask,np.rint(corners).astype(np.int32),255)
    mask=cv2.erode(mask,np.ones((5,5),np.uint8))
    points=cv2.goodFeaturesToTrack(previous,maxCorners=400,qualityLevel=.006,minDistance=5,mask=mask,blockSize=5)
    if points is None or len(points)<12:return None
    params=dict(winSize=(25,25),maxLevel=4,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.01))
    found,status,_=cv2.calcOpticalFlowPyrLK(previous,current,points,None,**params)
    if found is None or status is None or not np.isfinite(found).all():return None
    back,reverse,_=cv2.calcOpticalFlowPyrLK(current,previous,found,None,**params)
    if back is None or reverse is None:return None
    good=(status.ravel()>0)&(reverse.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<.8)
    a=points[good].reshape(-1,2);b=found[good].reshape(-1,2)
    if len(a)<12:return None
    transform,inliers=cv2.findHomography(a,b,cv2.RANSAC,1.5,maxIters=2000,confidence=.999)
    if transform is None or inliers.sum()<10 or inliers.mean()<.65:return None
    a=a[inliers.ravel()>0];b=b[inliers.ravel()>0]
    area=cv2.contourArea(corners)
    coverage=cv2.contourArea(cv2.convexHull(a))/max(area,1)
    if coverage<.20:return None
    predicted=cv2.perspectiveTransform(corners[None],transform)[0]
    new_area=cv2.contourArea(predicted)
    if not cv2.isContourConvex(predicted) or not .45<new_area/max(area,1)<2.2:return None
    if np.any(predicted<2) or np.any(predicted[:,0]>w-3) or np.any(predicted[:,1]>h-3):return None
    errors=np.linalg.norm(cv2.perspectiveTransform(a[None],transform)[0]-b,axis=1)
    if np.median(errors)>.8:return None
    return predicted,{'inliers':int(len(a)),'coverage_fraction':float(coverage),
                      'median_flow_reprojection_px':float(np.median(errors))}
