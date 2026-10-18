"""Constrained exterior estimate from multiview cube outlines.

This is a photo-supported shape hypothesis, not a dense measured scan. A repeated
intact edge's 2D outline is used on perpendicular faces; unobserved relief and
internal mechanism are explicitly unresolved. No preset cube size/gap/radius.
"""
import json
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.ndimage import distance_transform_edt, gaussian_filter
from skimage.measure import marching_cubes
from .cube import analyze_cube_face, CubeInputError
from .geometry import project
from .capture_region import capture_bounds, masked_photo


def analyze_guided_face(image, region=None):
    """Detect within the guide, return calibrated full-image coordinates."""
    h,w=image.shape[:2]
    x0,y0,x1,y1=capture_bounds(region,image.shape)
    _,encoded=cv2.imencode('.jpg',image[y0:y1,x0:x1])
    result=analyze_cube_face(encoded.tobytes())
    for key in ('face_corners','missing_polygon'):
        result[key]=((np.asarray(result[key])*[x1-x0,y1-y0]+[x0,y0])/[w,h]).tolist()
    return result


def fit_square(views):
    if len(views)<3:raise ValueError('Need the same damaged face in at least three registered views')
    uvs=[np.array(a['face_corners'])*f['image_size'] for f,a in views]
    xyz=[]
    for j in range(4):
        rows=[]
        for (f,a),uv in zip(views,uvs):
            p=f['image_k']@np.linalg.inv(f['pose'])[:3];u,v=uv[j]
            rows.extend([u*p[2]-p[0],v*p[2]-p[1]])
        _,_,vt=np.linalg.svd(rows)
        if abs(vt[-1,3])<1e-9:raise ValueError('Face triangulation is degenerate')
        xyz.append(vt[-1,:3]/vt[-1,3])
    xyz=np.array(xyz);u=xyz[1]-xyz[0];v=xyz[3]-xyz[0]
    width=np.mean([np.linalg.norm(u),np.linalg.norm(v)])
    u/=np.linalg.norm(u);v-=u*np.dot(u,v);v/=np.linalg.norm(v)
    basis=np.column_stack([u,v,np.cross(u,v)])
    unit=np.array([[-.5,-.5,0],[.5,-.5,0],[.5,.5,0],[-.5,.5,0]])
    x0=np.r_[xyz.mean(0),Rotation.from_matrix(basis).as_rotvec(),np.log(width)]
    def corners(x):return unit@Rotation.from_rotvec(x[3:6]).as_matrix().T*np.exp(x[6])+x[:3]
    def residual(x,subset=None):
        ids=range(len(views)) if subset is None else subset
        return np.concatenate([(project(corners(x),views[i][0]['image_k'],views[i][0]['pose'])[0]-uvs[i]).ravel() for i in ids])
    fitted=least_squares(residual,x0,loss='soft_l1',f_scale=4,max_nfev=200)
    errors=np.linalg.norm(residual(fitted.x).reshape(-1,4,2),axis=2)
    spans=np.array([np.mean(np.linalg.norm(uv-np.roll(uv,1,axis=0),axis=1)) for uv in uvs])
    usable=np.flatnonzero(np.median(errors,axis=1)/spans<.06)
    if len(usable)<3:raise ValueError('Detected face outlines do not agree across photographs')
    fitted=least_squares(lambda x:residual(x,usable),fitted.x,loss='soft_l1',f_scale=4,max_nfev=200)
    center=fitted.x[:3];basis=Rotation.from_rotvec(fitted.x[3:6]).as_matrix();width=float(np.exp(fitted.x[6]))
    if not .025<width<.15:raise ValueError('Inferred cube scale is outside the supported capture range')
    if any(np.any(project(corners(fitted.x),views[i][0]['image_k'],views[i][0]['pose'])[1]<=0) for i in usable):
        raise ValueError('Triangulated face lies behind a camera')
    # Fit uses down-screen v; choose the face's outward normal explicitly.
    if np.dot(basis[:,2],views[usable[0]][0]['pose'][:3,3]-center)<0:basis[:,2]*=-1
    errors=np.linalg.norm(residual(fitted.x,usable).reshape(-1,4,2),axis=2)
    # Leave-one-view-out reprojection checks guard against a single-view template.
    held=[]
    for held_id in usable:
        train=[i for i in usable if i!=held_id]
        fit=least_squares(lambda x:residual(x,train),fitted.x,loss='soft_l1',f_scale=4,max_nfev=70)
        held.append(float(np.median(np.linalg.norm(residual(fit.x,[held_id]).reshape(4,2),axis=1))/spans[held_id]))
    if np.median(held)>.07:raise ValueError('Face geometry does not predict held-out views reliably')
    return {'center':center,'basis':basis,'width':width}, [views[i] for i in usable], {
        'views':[views[i][0]['frame_id'] for i in usable], 'median_corner_reprojection_px':float(np.median(errors)),
        'median_held_out_error_fraction_of_face':float(np.median(held)),
        'assumption':'Planar square face with a regular 3x3 repeated grid'}


def donor_outline(views, scan_dir, missing):
    candidates=[]
    for row,col in [(0,1),(1,0),(1,2),(2,1)]:
        if (row,col)==(missing['row'],missing['column']):continue
        fields=[];ids=[]
        for f,a in views:
            im=cv2.cvtColor(cv2.imread(str(scan_dir/f['rgb_path'])),cv2.COLOR_BGR2RGB)
            corners=np.float32(a['face_corners'])*np.float32(f['image_size'])
            warped=cv2.warpPerspective(im,cv2.getPerspectiveTransform(corners,np.float32([[0,0],[600,0],[600,600],[0,600]])),(600,600))
            tile=warped[row*200:(row+1)*200,col*200:(col+1)*200]
            lab=cv2.cvtColor(tile,cv2.COLOR_RGB2LAB).astype(float)
            reference=np.median(lab[70:130,70:130].reshape(-1,3),axis=0)
            mask=(np.linalg.norm(lab-reference,axis=2)<10).astype(np.uint8)
            _,labels=cv2.connectedComponents(mask);label=labels[100,100]
            if not label:continue
            mask=(labels==label)
            area=float(mask.mean())
            # An unsegmented full tile has no observed outline; do not supply a default.
            if not .60<area<.995:continue
            mask=cv2.morphologyEx(mask.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8)).astype(bool)
            signed=distance_transform_edt(mask)-distance_transform_edt(~mask)
            fields.append(signed);ids.append(f['frame_id'])
        if len(fields)>=3:
            spread=float(np.median(np.std(np.stack(fields),axis=0)))
            profile=gaussian_filter(np.median(fields,axis=0),1)>0
            try: fitted=fit_outline(profile)
            except ValueError: continue
            # A solution at the radius bound has not resolved corner curvature.
            resolved=.008<fitted['radius_fraction']<.195
            candidates.append((int(resolved),len(fields),-spread,fields,ids,row,col))
    if not candidates:raise ValueError('Repeated intact edge outlines are not resolved in enough views')
    _,_,_,fields,ids,row,col=max(candidates,key=lambda x:x[:3])
    signed=gaussian_filter(np.median(fields,axis=0),1)
    mask=signed>0
    return mask, {'source_cell':{'row':row,'column':col,'type':'edge'},'frame_ids':ids,
        'profile_area_fraction':float(mask.mean()),'method':'median_color_boundary_signed_distance_of_intact_edge',
        'assumptions':['Rounded rectangular repeated face outline','The same outline applies to perpendicular exterior faces'],
        'relief_recovered':False}


def fit_outline(mask):
    # Robustly fit an idealized rounded rectangle to measured boundary samples.
    # Color/shadow jaggies must not become invented mechanical ridges.
    contours,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    if not contours:raise ValueError('No intact outline')
    contour=max(contours,key=cv2.contourArea).reshape(-1,2).astype(float)
    size=mask.shape[0]
    contour=contour[np.all((contour>1)&(contour<size-2),axis=1)]
    if len(contour)<size:raise ValueError('Too much of the donor outline is clipped by the grid cell')
    points=(contour+.5)/size-.5
    low,high=np.percentile(points,[2,98],axis=0);center=(low+high)/2;half=(high-low)/2
    def residual(x):
        q=abs(points-x[:2])-(x[2:4]-x[4])
        return np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(q.max(axis=1),0)-x[4]
    fit=least_squares(residual,np.r_[center,half,.05],bounds=([-.12,-.12,.3,.3,.005],[.12,.12,.5,.5,.20]),loss='soft_l1',f_scale=.008)
    error=float(np.median(abs(residual(fit.x))))
    if error>.02 or abs(fit.x[2]-fit.x[3])>.08:raise ValueError('Intact outline is not a consistent rounded cubie')
    return {'width_fraction':float(2*np.mean(fit.x[2:4])), 'radius_fraction':float(fit.x[4]),
            'center_fraction':fit.x[:2].tolist(),'half_extents_fraction':fit.x[2:4].tolist(),
            'median_boundary_error_fraction':error, 'fit':'robust_rounded_rectangle_from_observed_outline'}


def solid_from_outline(mask, pitch_mm):
    import trimesh
    parameters=fit_outline(mask)
    width=pitch_mm*parameters['width_fraction'];radius=pitch_mm*parameters['radius_fraction']
    # Explicit idealization: a rounded solid using fitted exterior dimensions.
    # The 3D fillet is a hypothesis from the 2D outline, not recovered surface relief.
    n=96;axis=np.linspace(-width/2-radius/4,width/2+radius/4,n)
    x,y,z=np.meshgrid(axis,axis,axis,indexing='ij')
    q=np.stack([abs(x),abs(y),abs(z)],axis=-1)-(width/2-radius)
    field=np.linalg.norm(np.maximum(q,0),axis=-1)+np.minimum(q.max(axis=-1),0)-radius
    vertices,faces,_,_=marching_cubes(field.astype(np.float32),0,spacing=(axis[1]-axis[0],)*3)
    vertices+=axis[0]
    solid=trimesh.Trimesh(vertices,faces,process=True);solid.fix_normals()
    if not solid.is_watertight or not solid.is_winding_consistent or solid.body_count!=1 or solid.volume<=0:
        raise ValueError('Inferred exterior did not form one closed solid')
    solid.metadata['outline_fit']={**parameters,'width_mm':width,'radius_mm':radius,'three_dimensional_rounding':'inferred_from_outline'}
    return solid


def detect_views(frames, scan_dir):
    views=[]
    for f in frames:
        image=cv2.imread(str(scan_dir/f['rgb_path']))
        if image is None:continue
        factor=min(1,960/max(image.shape[:2]));image=cv2.resize(image,None,fx=factor,fy=factor)
        try:a=analyze_guided_face(image,f.get('capture_region'))
        except CubeInputError:continue
        if a['confidence']=='high' and a['missing_cell']['type']=='edge':views.append((f,a))
    return views


def tracked_groups(frames, views, scan_dir):
    """Carry a supported face identity through adjacent images; no size prior."""
    from .planar_tracking import track_region
    from .cube import _analyze_face
    images={}
    for f in frames:
        im=cv2.imread(str(scan_dir/f['rgb_path']))
        if im is None:continue
        factor=min(1,960/max(im.shape[:2]))
        images[f['frame_id']]=masked_photo(cv2.cvtColor(cv2.resize(im,None,fx=factor,fy=factor),cv2.COLOR_BGR2RGB),f.get('capture_region'))
    groups=[];indices={f['frame_id']:i for i,f in enumerate(frames)}
    for source,analysis in views[:4]:
        group=[(source,analysis)];index=indices[source['frame_id']]
        for step in [-1,1]:
            previous=source['frame_id']
            corners=np.float32(analysis['face_corners'])*images[previous].shape[1::-1]
            for i in range(index+step,len(frames) if step>0 else -1,step):
                f=frames[i];fid=f['frame_id']
                if fid not in images:break
                track=track_region(cv2.cvtColor(images[previous],cv2.COLOR_RGB2GRAY),
                                   cv2.cvtColor(images[fid],cv2.COLOR_RGB2GRAY),corners)
                if track is None:break
                quad,evidence=track
                x0,y0,x1,y1=capture_bounds(f.get('capture_region'),images[fid].shape)
                if np.any(quad<[x0,y0]) or np.any(quad>[x1-1,y1-1]):break
                a=_analyze_face(images[fid],(quad/images[fid].shape[1::-1]).tolist())
                if a['confidence']!='high' or a['missing_cell']!=analysis['missing_cell']:break
                a['tracking']={**evidence,'source_frame':source['frame_id'],'previous_frame':previous}
                a['detection_method']='temporally_tracked_planar_region'
                group.append((f,a));previous=fid;corners=quad
        groups.append(group)
    return groups


def estimate_cube(frames,scan_dir,output_dir,alignment, *, track_faces=False, detections=None):
    views=detect_views(frames,scan_dir) if detections is None else detections
    (output_dir/'face_detections.json').write_text(json.dumps([
        {'frame_id':f['frame_id'],'analysis':a} for f,a in views]))
    groups=[]
    if track_faces:
        groups=tracked_groups(frames,views,scan_dir)
    else:
        for view in views:
            f,a=view;hue=cv2.cvtColor(np.uint8([[a['face_color_rgb']]]),cv2.COLOR_RGB2HSV)[0,0,0]
            group=next((g for g in groups if g[0][1]['missing_cell']==a['missing_cell'] and abs(int(hue)-int(cv2.cvtColor(np.uint8([[g[0][1]['face_color_rgb']]]),cv2.COLOR_RGB2HSV)[0,0,0]))<10),None)
            if group is None:groups.append([view])
            else:group.append(view)
    if not groups:raise ValueError('No missing edge was consistently recognized')
    failures=[];solutions=[]
    for group in sorted(groups,key=len,reverse=True):
        try:
            geometry,supported,fit=fit_square(group)
            missing=supported[0][1]['missing_cell'];outline,donor=donor_outline(supported,scan_dir,missing)
            solutions.append((geometry,supported,fit,missing,outline,donor))
        except ValueError as exc:failures.append(str(exc))
    if not solutions:raise ValueError(failures[0] if failures else 'No supported repeated face')
    geometry,supported,fit,missing,outline,donor=min(solutions,key=lambda x:x[2]['median_held_out_error_fraction_of_face'])
    pitch=geometry['width']/3*1000
    solid=solid_from_outline(outline,pitch)
    import open3d as o3d
    check=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(solid.vertices),o3d.utility.Vector3iVector(solid.faces))
    if check.is_self_intersecting():raise ValueError('Estimated exterior intersects itself')
    printed=solid.copy();printed.apply_translation([0,0,-printed.bounds[0,2]]);printed.units='mm'
    printed.export(output_dir/'printable_edge.stl');printed.export(output_dir/'printable_edge.3mf')
    import trimesh
    reopened=trimesh.load_mesh(output_dir/'printable_edge.stl',process=True)
    if not reopened.is_watertight or reopened.body_count!=1:raise ValueError('Exported exterior failed validation')
    # Display a structural context model, clearly labeled as inferred, never a scanned surface.
    basecenter=geometry['center']-geometry['basis'][:,2]*geometry['width']/2
    target=np.array([missing['column']-1,missing['row']-1,1])
    def placed(position):
        mesh=solid.copy();mesh.vertices=(mesh.vertices/1000+position*geometry['width']/3)@geometry['basis'].T+basecenter
        mesh.fix_normals()
        return mesh
    part=placed(target)
    def preview(mesh):
        return {'vertices':(mesh.vertices*1000).tolist(),'triangles':mesh.faces.tolist(),'colors':[],'normals':[],'unit':'mm'}
    # Context boxes are structural inference, never labeled as measured scan geometry.
    boxes=[]
    for x in [-1,0,1]:
        for y in [-1,0,1]:
            for z in [-1,0,1]:
                if np.array_equal([x,y,z],target) or (x==y==z==0):continue
                box=trimesh.creation.box(extents=solid.extents/1000)
                box.vertices=(box.vertices+np.array([x,y,z])*geometry['width']/3)@geometry['basis'].T+basecenter;box.fix_normals();boxes.append(box)
    context=trimesh.util.concatenate(boxes)
    (output_dir/'scan_preview.json').write_text(json.dumps(preview(context)))
    (output_dir/'counterpart_preview.json').write_text(json.dumps(preview(part)))
    report={'status':'proposal_needs_review','method':('tracked_multiview_repeated_outline' if track_faces else 'multiview_photo_grid_and_observed_repeated_outline'),
        'scope':'inferred_closed_exterior','watertight_replacement':True,'hidden_geometry_reconstructed':False,
        'physical_fit':'not_tested','width_mm':geometry['width']*1000,'target_cell':missing,'donor':donor,
        'tracked_observations':[{'frame_id':f['frame_id'],'tracking':a.get('tracking')} for f,a in supported],
        'outline_fit':solid.metadata['outline_fit'],'photo_geometry':fit,'scale':alignment['scale'],'geometry_is_estimated':True,
        'reason':'Estimated from aligned photos and intact cubie outlines. Scale is inferred from depth; fine surface relief and physical fit remain unverified.',
        'closure':{'status':'closed_exterior_estimate','watertight':True,'connected_solids':1,
            'volume_mm3':float(printed.volume),'bounds_mm':printed.bounds.tolist(),
            'sampling_pitch_is_accuracy':False,'hidden_geometry_reconstructed':False,
            'limitations':['Rounded exterior fitted to observed outlines; 3D rounding is inferred and surface bumps remain unresolved.',
                'Unseen geometry is inferred. No internal locking mechanism or mechanical clearance.',
                'Automatic metric scale has uncalibrated uncertainty; test fit before use.']}}
    for name,data in [('counterpart.json',report),('printable_edge.json',report['closure'])]:
        (output_dir/name).write_text(json.dumps(data,indent=2))
    cv2.imwrite(str(output_dir/'donor_outline.png'),outline.astype(np.uint8)*255)
    return report
