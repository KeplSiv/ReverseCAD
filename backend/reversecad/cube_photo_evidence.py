"""Photo-supported cube repetition, with an explicit solved-face appearance prior.

Photos nominate a missing edge; an observed intact edge supplies its exterior.
Neither a dark pixel nor absent depth alone establishes an empty volume.
"""
import cv2
import numpy as np
from .geometry import project
from .capture_region import capture_bounds
from .cube import _analyze_face, CubeInputError
from .photo_cube import fit_outline


def load_photos(frames, scan_dir):
    photos=[]
    for f in frames:
        im=cv2.imread(str(scan_dir/f['rgb_path']))
        if im is None:continue
        h,w=im.shape[:2];factor=min(1,1280/max(h,w))
        size=(round(w*factor),round(h*factor))
        resize=np.array([[size[0]/w,0,(size[0]/w-1)/2],[0,size[1]/h,(size[1]/h-1)/2],[0,0,1.]])
        photos.append({**f,'image':cv2.cvtColor(cv2.resize(im,size),cv2.COLOR_BGR2RGB),
                       'image_k':resize@f['image_k'],'image_size':size})
    return photos


def projected_quad(points, frame):
    uv,z=project(points,frame['image_k'],frame['pose'])
    x0,y0,x1,y1=capture_bounds(frame.get('capture_region'),frame['image'].shape)
    if np.any(z<=0) or not np.isfinite(uv).all() or np.any(uv<[x0,y0]) or np.any(uv>[x1-1,y1-1]):return None
    return uv


def locate_photo_edge(geometry, photos, depth_candidates):
    basis,center,width=geometry['basis'],geometry['center'],geometry['width']
    votes={}
    for f in photos:
        for fixed in range(3):
            normal=basis[:,fixed];fc=center+normal*width/2
            direction=f['pose'][:3,3]-fc
            if normal@direction/np.linalg.norm(direction)<.25:continue
            free=[i for i in range(3) if i!=fixed]
            local=np.zeros((4,3));local[:,fixed]=width/2
            local[:,free]=np.array([[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]])*width
            uv=projected_quad(local@basis.T+center,f)
            if uv is None:continue
            try:a=_analyze_face(f['image'],(uv/f['image_size']).tolist())
            except CubeInputError:continue
            if a['confidence']!='high' or a['missing_cell']['type']!='edge':continue
            cell=np.zeros(3,int);cell[fixed]=1
            cell[free]=[a['missing_cell']['column']-1,a['missing_cell']['row']-1]
            # Require two observed exterior faces, never an unseen rear edge.
            if sorted(cell.tolist())!=[0,1,1]:continue
            votes.setdefault(tuple(cell),{}).setdefault(fixed,[]).append({
                'frame_id':f['frame_id'],'camera':f['pose'][:3,3].tolist(),
                'score_margin':a['score_margin'],'brightness_drop':a['brightness_drop']})
    candidates=[]
    for target,faces in votes.items():
        outer=[i for i in range(3) if target[i]]
        if any(len(faces.get(i,[]))<3 for i in outer):continue
        if any(np.linalg.norm(np.ptp([v['camera'] for v in faces[i]],axis=0))<.006 for i in outer):continue
        depths=next((c for c in depth_candidates if c['target']==list(target)),None)
        # Positive observed surviving surfaces veto an appearance-only guess.
        if depths and any(face['surface_fraction']>.20 for face in depths['faces']):continue
        candidates.append({'target':[int(v) for v in target],'outer_axes':outer,
            'score':min(len(faces[i]) for i in outer),'photo_faces':{str(i):faces[i] for i in outer},
            'method':'multiview_repeated_face_appearance_with_surface_collision_veto',
            'assumption':'User selected a mostly solved regular cube with a missing edge; appearance is not proof of empty space.',
            'gap_depth_required':False,'requires_visual_confirmation':True})
    if len(candidates)!=1:
        raise ValueError('Photos do not identify one consistent missing edge on both adjacent faces. No donor was placed.')
    return candidates[0],candidates


def donor_face_profile(center, basis, pitch, fixed, photos):
    free=[i for i in range(3) if i!=fixed];normal=basis[:,fixed]
    local=np.zeros((4,3));local[:,fixed]=pitch/2
    local[:,free]=np.array([[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]])*pitch
    world=local@basis.T+center;profiles=[];ids=[];positions=[]
    for f in photos:
        direction=f['pose'][:3,3]-(center+normal*pitch/2)
        if normal@direction/np.linalg.norm(direction)<.25:continue
        uv=projected_quad(world,f)
        if uv is None or min(np.linalg.norm(uv-np.roll(uv,1,axis=0),axis=1))<20:continue
        transform=cv2.getPerspectiveTransform(uv.astype(np.float32),np.float32([[0,0],[199,0],[199,199],[0,199]]))
        patch=cv2.warpPerspective(f['image'],transform,(200,200))
        lab=cv2.cvtColor(patch,cv2.COLOR_RGB2LAB).astype(float)
        reference=np.median(lab[70:130,70:130].reshape(-1,3),axis=0)
        mask=(np.linalg.norm(lab-reference,axis=2)<18).astype(np.uint8)
        _,labels=cv2.connectedComponents(mask)
        label=labels[100,100]
        if not label:continue
        mask=labels==label
        if not .55<float(mask.mean())<.995:continue
        mask=cv2.morphologyEx(mask.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        try:fit_outline(mask)
        except ValueError:continue
        profiles.append(mask);ids.append(f['frame_id']);positions.append(f['pose'][:3,3])
    if len(profiles)<3 or np.linalg.norm(np.ptp(positions,axis=0))<.006:
        raise ValueError('The intact donor outline is not resolved on both faces in at least three separated views.')
    median=np.mean(profiles,axis=0)>=.5
    fitted=fit_outline(median)
    agreement=float(np.mean([np.mean(mask==median) for mask in profiles]))
    if agreement<.85:raise ValueError('The donor outlines disagree across views.')
    return {**fitted,'frame_ids':ids,'mask_agreement':agreement,'local_face_axis':fixed,
            'free_axes':free,'outline_support':'photographed_color_boundary','relief_inferred_from_color':False}


def close_photo_donor(face, source_cell, target_cell, photos, output_dir):
    """Conservative convex exterior from two independently observed donor profiles.

    Sparse stereo is used for the frame and donor support, not copied as ridges.
    Inner faces and the transition between photographed face boundaries are
    inferred. This representation intentionally cannot recreate concave relief.
    """
    import trimesh
    import open3d as o3d
    pitch=face['width']/3
    source=np.array([source_cell['column']-1,source_cell['row']-1,0.])
    target=np.array([target_cell['column']-1,target_cell['row']-1,0.])
    up=face['basis'][:,2];outward=face['basis']@source
    source_basis=np.column_stack([outward,np.cross(up,outward),up])
    source_center=face['center']+face['basis']@(source*pitch)-up*pitch/2
    profiles=[donor_face_profile(source_center,source_basis,pitch,axis,photos) for axis in [0,2]]
    points=[];bounds={}
    for profile in profiles:
        center=np.array(profile['center_fraction']);half=np.array(profile['half_extents_fraction'])
        radius=profile['radius_fraction'];boundary=[]
        for signs,start in [((1,1),0),((-1,1),90),((-1,-1),180),((1,-1),270)]:
            angles=np.deg2rad(np.linspace(start,start+90,17))
            boundary.extend(center+np.array(signs)*(half-radius)+radius*np.column_stack([np.cos(angles),np.sin(angles)]))
        boundary=np.array(boundary)*pitch
        fixed=profile['local_face_axis'];local=np.zeros((len(boundary),3));local[:,fixed]=pitch/2
        local[:,profile['free_axes']]=boundary;points.extend(local)
        bounds[fixed]=(boundary.min(0),boundary.max(0))
    # Complete only the hidden backing corner. The outer crease is a convex
    # transition between the photographed face boundaries, never a guessed ridge.
    xlow=bounds[2][0][0];zlow=bounds[0][0][1]
    ylow=max(bounds[2][0][1],bounds[0][0][0]);yhigh=min(bounds[2][1][1],bounds[0][1][0])
    if yhigh<=ylow:raise ValueError('The two donor outlines do not overlap along their shared edge.')
    points.extend([[xlow,ylow,zlow],[xlow,yhigh,zlow]])
    solid=trimesh.convex.convex_hull(np.asarray(points)*1000)
    solid.fix_normals();solid.units='mm'
    if not solid.is_watertight or solid.body_count!=1 or solid.volume<=0:raise ValueError('Donor outline closure did not form a solid.')
    check=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(solid.vertices),o3d.utility.Vector3iVector(solid.faces))
    if check.is_self_intersecting():raise ValueError('Donor outline closure intersects itself.')
    printed=solid.copy();printed.apply_translation([0,0,-printed.bounds[0,2]])
    printed.export(output_dir/'printable_edge.stl');printed.export(output_dir/'printable_edge.3mf')
    for name in ['printable_edge.stl','printable_edge.3mf']:
        reopened=trimesh.load(output_dir/name,force='mesh',process=True)
        if not reopened.is_watertight or reopened.body_count!=1 or reopened.volume<=0:
            raise ValueError('Exported donor solid failed validation.')
    out=face['basis']@target;target_basis=np.column_stack([out,np.cross(up,out),up])
    target_center=face['center']+face['basis']@(target*pitch)-up*pitch/2
    world=(solid.vertices/1000)@target_basis.T+target_center
    preview={'vertices':(world*1000).tolist(),'triangles':solid.faces.tolist(),'colors':[],'normals':[],'unit':'mm'}
    report={'status':'closed_exterior_prototype','unit':'mm','watertight':True,'connected_solids':1,
            'self_intersections':False,'volume_mm3':float(solid.volume),'bounds_mm':printed.bounds.tolist(),
            'surface_method':'Convex completion between two photographed intact donor face outlines',
            'donor_photo_profiles':profiles,'relief_recovered':False,
            'closure':'Flat inferred backing faces and convex inferred transitions between observed face boundaries.',
            'physical_fit':'not_tested','hidden_geometry_reconstructed':False,
            'limitations':['Small ridges, concave recesses and hidden connectors are unresolved.',
                           'Colored face boundaries may differ from plastic boundaries; verify the exterior and dimensions before printing.'],
            'files':['printable_edge.stl','printable_edge.3mf']}
    return preview,report


def frames_from_photo_outlines(photo_frames, scan_dir, points):
    """Recover a cube frame from calibrated multiview square-face outlines.

    The square face must predict held-out views. The remaining orthogonal axes
    are the explicitly selected cube prior, not three measured depth planes.
    """
    from .photo_cube import detect_views,fit_square
    views=detect_views(photo_frames,scan_dir);groups=[]
    for view in views:
        f,a=view;color=np.array(a['face_color_rgb'],float)
        group=next((g for g in groups if g[0][1]['missing_cell']==a['missing_cell'] and
                    np.linalg.norm(np.array(g[0][1]['face_color_rgb'],float)-color)<35),None)
        if group is None:groups.append([view])
        else:group.append(view)
    solutions=[]
    for group in sorted(groups,key=len,reverse=True):
        if len(group)<3:continue
        try:face,views,fit=fit_square(group)
        except ValueError:continue
        width=face['width'];center=face['center']-face['basis'][:,2]*width/2
        # Enumerate the two visible side choices; photo votes decide which
        # frame makes the same damaged feature agree on adjacent faces.
        for sx,sy in [(1,1),(1,-1),(-1,1),(-1,-1)]:
            basis=face['basis']@np.diag([sx,sy,1])
            local=(points-center)@basis;groups3=[]
            for axis in range(3):groups3.append(points[abs(local[:,axis]-width/2)<max(.0008,width*.02)])
            solutions.append({'center':center,'basis':basis,'width':width,'groups':groups3,
                'evidence':{'frame_source':'calibrated_multiview_face_outline',
                            'assumption':'Regular cube inferred from a triangulated square face; side planes are not independently measured.',
                            'scale_accuracy':'uncalibrated','photo_face_fit':fit}})
    if not solutions:raise ValueError('Neither surface planes nor repeated face outlines agree in enough views to place a donor.')
    return solutions
