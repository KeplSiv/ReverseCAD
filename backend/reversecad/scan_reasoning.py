"""Observed-object evidence for reasoning. Never substitutes a replacement CAD."""
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from .jev import review_with_jev


def observed_context(reconstruction, preview, annotations=None):
    if preview.get('unit') != 'mm':
        raise ValueError('Observed preview must declare millimeters')
    points=np.asarray(preview.get('vertices',[]),dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points)<20 or len(points)>500000 or not np.isfinite(points).all():
        raise ValueError('Observed scan has no usable finite geometry; reconstruct the capture first')
    primitives=list(reconstruction.get('primitives',[]))
    if not any(p.get('type')=='plane' for p in primitives):
        from .geometry import fit_plane
        remaining=points[np.linspace(0,len(points)-1,min(5000,len(points)),dtype=int)]/1000
        for index in range(6):
            fit=fit_plane(remaining)
            if fit is None or int(fit['inliers'].sum())<80: break
            primitives.append({'id':f'preview_plane_{index}','type':'plane',
                'center_m':fit['center_m'].tolist(),'normal':fit['normal'].tolist(),
                'fit_residual_mm':fit['residual_mm'],'view_support_count':None})
            remaining=remaining[~fit['inliers']]
    faces=[]
    for primitive in primitives[:64]:
        if primitive.get('type') != 'plane': continue
        center=np.asarray(primitive['center_m'],dtype=float)*1000
        normal=np.asarray(primitive['normal'],dtype=float)
        if center.shape!=(3,) or normal.shape!=(3,) or not np.isfinite(center).all() or not np.isfinite(normal).all() or np.linalg.norm(normal)<.9:continue
        normal/=np.linalg.norm(normal)
        faces.append({'id':f'F{len(faces)+1}','source_id':primitive['id'],'surface':'observed_plane_fit',
                      'center_mm':center.tolist(),'normal':normal.tolist(),
                      'fit_residual_mm':primitive.get('fit_residual_mm'),
                      'view_support_count':primitive.get('view_support_count'),
                      'observation_ids':primitive.get('observation_ids',[]),
                      'uncertainty_status':'not_calibrated'})
    relationships=[]
    for i,a in enumerate(faces):
        for b in faces[i+1:]:
            cosine=abs(float(np.dot(a['normal'],b['normal'])))
            angle=float(np.degrees(np.arccos(np.clip(cosine,0,1))))
            relationships.append({'features':[a['id'],b['id']],'normal_angle_degrees':round(angle,3),
                'parallel_hypothesis':angle<5,'perpendicular_hypothesis':angle>85,
                'center_distance_mm':round(float(np.linalg.norm(np.array(a['center_mm'])-b['center_mm'])),3),
                'verified_symmetry':False})
    sample=points[np.linspace(0,len(points)-1,min(1000,len(points)),dtype=int)]
    warnings=reconstruction.get('warnings',[])
    context={'input_kind':'observed_scan','scan_id':reconstruction.get('scan_id'),
        'geometry':{'faces':faces,'shared_edges':[],'units':'mm','cad_valid':False,
                    'representation':'observed point cloud plus fitted surfaces; not a solid CAD model',
                    'bounds_mm':{'min':points.min(0).tolist(),'max':points.max(0).tolist()},
                    'point_count':len(points),'sample_points_mm':sample.round(3).tolist(),
                    'physical_fit':'not_tested'},
        'relationships':relationships,'measurements':reconstruction.get('measurements',[])[:32],
        'capture_status':reconstruction.get('status'),'warnings':warnings,
        'observations':reconstruction.get('observations',{}),
        'user_annotations':annotations or {},
        'unknown_regions':'Unobserved space is unknown, not missing material. Point cloud holes are not proof of damage.',
        'task':'Reason about the OBSERVED WHOLE OBJECT. Identify supported repeated or symmetric intact donor surfaces and possible missing counterparts. Cite observed feature IDs. Propose inspection/copy_feature only when supported; otherwise request a discriminating view. Do not turn the object category into preset geometry.',
        'repair_execution':'No repair is executed by this review. Surface fits and proposed symmetry require image validation.',
        'input_sha256':hashlib.sha256(json.dumps(preview,sort_keys=True,allow_nan=False).encode()).hexdigest()}
    json.dumps(context,allow_nan=False)
    return context, render_points(points)


def render_points(points):
    points=points[np.linspace(0,len(points)-1,min(30000,len(points)),dtype=int)]
    center=(points.min(0)+points.max(0))/2
    result=[]
    for axes in [(0,1),(0,2),(1,2)]:
        xy=(points-center)[:,axes]
        scale=620/max(float(np.ptp(xy,axis=0).max()),1e-6)
        xy=xy*[scale,-scale]+[384,400]
        im=Image.new('RGB',(768,768),'white');d=ImageDraw.Draw(im)
        for x,y in xy:d.ellipse((x-1,y-1,x+1,y+1),fill=(80,80,80))
        d.text((15,15),f'OBSERVED SCAN projection {axes}; gaps are unknown, not repaired',fill='black')
        output=io.BytesIO();im.save(output,format='PNG');result.append(output.getvalue())
    return result


def review_scan(reconstruction,preview,images,*,consent=False,annotations=None,**kwargs):
    context,views=observed_context(reconstruction,preview,annotations)
    result=review_with_jev(context,images,consent=consent,model_views=views,**kwargs)
    result['review_subject']='observed_whole_object'
    result['observed_geometry_sha256']=context['input_sha256']
    result['observed_features']=len(context['geometry']['faces'])
    result['capture_warnings']=context['warnings']
    result['repair_generated']=False
    return result
