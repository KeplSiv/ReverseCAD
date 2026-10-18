"""Time-resolved sparse constraints against visible, locally supported SfM surfaces."""
from __future__ import annotations
from collections import defaultdict
import math
import numpy as np
from scipy.spatial import cKDTree, Delaunay, QhullError
from scipy.spatial.transform import Rotation, Slerp
from .capture import camera_point
from ..geometry import dot


def interpolate_pose(times, poses, timestamp, max_gap=.55):
    """No extrapolation or stale bank reuse; interpolate real-image camera estimates."""
    i=int(np.searchsorted(times,timestamp))
    if i<len(times) and abs(times[i]-timestamp)<1e-8: return poses[i],0.,[i,i]
    if i==0 or i==len(times) or times[i]-times[i-1]>max_gap:return None,None,None
    alpha=(timestamp-times[i-1])/(times[i]-times[i-1])
    p=np.eye(4);p[:3,3]=(1-alpha)*poses[i-1][:3,3]+alpha*poses[i][:3,3]
    p[:3,:3]=Slerp([times[i-1],times[i]],Rotation.from_matrix([poses[i-1][:3,:3],poses[i][:3,:3]]))([timestamp]).as_matrix()[0]
    return p,min(timestamp-times[i-1],times[i]-timestamp),[i-1,i]


def build_constraints(records,calibration,points,times,poses,intrinsics,frame_ids,image_sizes,masks):
    accepted=[]; reasons=defaultdict(int)
    # One surface estimate per packet: candidates remain separate, never coalesced across cycles.
    packet_cache={}
    for row in records:
        if not row['valid_for_geometry']:reasons['invalid_slot']+=1;continue
        stamp=row['timestamp_s']
        if stamp not in packet_cache:
            pose,age,pair=interpolate_pose(times,poses,stamp)
            if pose is None:packet_cache[stamp]=None
            else:
                j=pair[0] if stamp-times[pair[0]]<=times[pair[1]]-stamp else pair[1]
                K=intrinsics[j]
                pc=dot(points-pose[:3,3],pose[:3,:3])
                keep=np.isfinite(pc).all(axis=1)&(pc[:,2]>1e-5)
                projected=dot(pc[keep],K.T);uv=projected[:,:2]/projected[:,2,None]
                packet_cache[stamp]=(pose,age,pair,j,pc[keep],uv,cKDTree(uv)) if len(uv)>=6 else None
        cached=packet_cache[stamp]
        if cached is None:reasons['no_bracketed_pose_or_surface']+=1;continue
        pose,age,pair,j,pc,uv,tree=cached
        point=camera_point(row['fields']['points'][:3],calibration)
        if point[2]<=0:reasons['behind_camera']+=1;continue
        projected=intrinsics[j]@point;pixel=projected[:2]/projected[2]
        width,height=image_sizes[j];x,y=np.rint(pixel).astype(int)
        if not (2<=x<width-2 and 2<=y<height-2) or not masks[frame_ids[j]][y,x]:
            reasons['outside_object']+=1;continue
        # A triangulated patch must surround the projection, not just be the closest RGB feature.
        nearest=tree.query_ball_point(pixel,25.)
        if len(nearest)<6:reasons['unsupported_surface']+=1;continue
        patch=pc[nearest];pixels=uv[nearest]
        try:
            if Delaunay(pixels).find_simplex(pixel)<0:reasons['outside_surface_hull']+=1;continue
        except QhullError:reasons['degenerate_surface']+=1;continue
        center=np.median(patch,axis=0);_,singular,v=np.linalg.svd(patch-center,full_matrices=False)
        n=v[-1];plane=float(np.median(dot(patch,n)));residual=np.median(abs(dot(patch,n)-plane))
        # Reject depth edges / slivers; these may have two surfaces behind the same pixel.
        if singular[1]<singular[0]*.03 or np.ptp(patch[:,2])>center[2]*.18 or residual>center[2]*.008:
            reasons['ambiguous_or_nonplanar_surface']+=1;continue
        native=np.asarray(row['fields']['points'][:3],float)
        rng=float(row['fields']['euclideanDistances'])/1000
        origin=camera_point([0,0,0],calibration);direction=(point-origin)/rng
        incidence=float(n@direction)
        if abs(incidence)<.3 or abs(plane)<1e-8:reasons['grazing_surface']+=1;continue
        scale=float(n@point/plane)
        if not math.isfinite(scale) or scale<=0:reasons['invalid_scale']+=1;continue
        f=row['fields'];group=f"{row['sequence']}:{f['bankIds']}:{f['spotIds']}"
        accepted.append({'id':row['id'],'group':group,'timestamp_s':stamp,
            'bank':f['bankIds'],'spot':f['spotIds'],'echo':f['echoIds'],
            'frame_ids':[frame_ids[k] for k in sorted(set(pair))],
            'scale_m_per_unit':scale,'range_m':rng,'camera_point_m':point.tolist(),
            'origin_dot_normal_m':float(n@origin),'incidence':incidence,'plane_unscaled':plane,
            'surface_residual_unscaled':float(residual),'nearest_image_time_s':float(age),
            'weight':float(np.clip(f['confidences'],.1,1)/(1+age/.1+residual/center[2]*100)),
            'pixel':pixel.tolist(),'world_camera_unscaled':pose.tolist(),
            'selection':'candidate_not_yet_selected'})
    return accepted,dict(reasons)


def select_scale(candidates,minimum=12):
    """Robust consensus counts each packet/address once; ambiguous echoes abstain."""
    if len(candidates)<minimum:raise ValueError('Too few timed sparse-to-surface constraints; add overlapping textured views')
    times=sorted(set(c['timestamp_s'] for c in candidates))
    split=times[max(0,int(len(times)*.75)-1)]
    training=[c for c in candidates if c['timestamp_s']<=split]
    heldout=[c for c in candidates if c['timestamp_s']>split]
    values=np.array([c['scale_m_per_unit'] for c in training])
    if len(values)<minimum:raise ValueError('Too few constraints before the held-out time block')
    # RANSAC hypotheses rather than a score/nearest-return preference.
    models=[]
    for s in np.unique(np.quantile(values,np.linspace(0,1,min(101,len(values))))):
        support=[c for c in training if abs(math.log(c['scale_m_per_unit']/s))<.06]
        groups={c['group'] for c in support}
        models.append((len(groups),float(s)))
    models.sort(reverse=True)
    count,s=models[0]
    rivals=[v for n,v in models if n>=max(minimum,count*.8) and abs(math.log(v/s))>.15]
    if rivals:raise ValueError('Competing echo/surface scale solutions remain ambiguous; scan a broad interior surface from another side')
    def selected(rows,scale):
        by=defaultdict(list)
        for c in rows:
            if abs(math.log(c['scale_m_per_unit']/scale))<.06:by[c['group']].append(c)
        # Even equal-distance positive echoes are not independent support.
        return [r[0] for r in by.values() if len(r)==1]
    fit=selected(training,s)
    if len(fit)<minimum:raise ValueError('Too many ambiguous echo candidates for metric scale')
    for _ in range(5):
        if len(fit)<minimum:raise ValueError('Robust scale lost consistent support')
        weights=np.array([c['weight'] for c in fit]);v=np.array([c['scale_m_per_unit'] for c in fit])
        # Huber reweighting on relative scale; score only weights already geometrically selected candidates.
        weights*=np.minimum(1.,.02/np.maximum(abs(v/s-1),1e-9))
        s=float(np.average(v,weights=weights));fit=selected(training,s)
    if len(fit)<minimum or len({(c['bank'],c['spot']) for c in fit})<4 or len({f for c in fit for f in c['frame_ids']})<3:
        raise ValueError('Metric support lacks enough distinct viewpoints or bank/spot addresses')
    check=selected(heldout,s)
    if len(check)<4 or len({c['group'] for c in check})<len({c['group'] for c in heldout})*.4:
        raise ValueError('Sparse scale does not have enough agreement in the held-out time block')
    chosen=selected(candidates,s)
    def stats(rows):
        residual=np.array([(s*c['plane_unscaled']-c['origin_dot_normal_m'])/c['incidence']-c['range_m'] for c in rows])*1000
        return {'count':len(rows),'median_signed_radial_residual_mm':float(np.median(residual)),
                'median_absolute_radial_residual_mm':float(np.median(abs(residual))),
                'p90_absolute_radial_residual_mm':float(np.percentile(abs(residual),90))}
    report={'factor_m_per_sfm_unit':s,'source':'timed_BackSparseTimeOfFlight_surface_constraints',
            'fitted_parameters':['one_global_scale'],'fixed_parameters':['intrinsics','SfM_poses','range_bias','sensor_extrinsics'],
            'training':stats(fit),'heldout_time_block':stats(check),'selected':len(chosen),
            'rejected_or_ambiguous':len(candidates)-len(chosen),'unique_addresses':len({(c['bank'],c['spot']) for c in chosen}),
            'absolute_accuracy_mm':None,'relative_scale_MAD':float(np.median(abs(np.array([c['scale_m_per_unit'] for c in fit])/s-1))),
            'limits':['Internal surface agreement is not independent dimensional accuracy.',
                      'Timestamp semantics, sensor footprint, upstream processing and factory calibration remain systematic uncertainties.']}
    return s,chosen,report
