"""Geometry-first 3x3 face repair. No hue, color labels or dark-cell classifier.

An observed repeated tile lattice seeds a planar track. The missing location is
an unobserved edge or corner in that lattice, a hypothesis requiring review.
A captured donor profile is extruded under the selected regular-cube prior;
internal mechanisms and the unseen depth profile are not recovered.
"""
import json
from pathlib import Path
import cv2
import numpy as np
from .capture_region import capture_bounds, masked_photo
from .cube import _ordered_quad
from .photo_cube import fit_square
from .planar_tracking import track_region
from .geometry import project


PERIMETER_CELLS = tuple((c,r) for r in range(3) for c in range(3) if (c,r)!=(1,1))


def cell_type(cell):
    c,r=cell
    if (c,r)==(1,1):return 'center'
    return 'corner' if c!=1 and r!=1 else 'edge'


def cell_record(cell):
    return {'column':int(cell[0]),'row':int(cell[1]),'type':cell_type(cell)}


def observed_cells(quads, corners):
    """Any coherent intact boundary vetoes a repair at that grid location."""
    transform=cv2.getPerspectiveTransform(np.float32(corners),np.float32([[0,0],[3,0],[3,3],[0,3]]))
    found=set()
    for tile in quads:
        local=cv2.perspectiveTransform(np.float32(tile)[None],transform)[0]
        cell=np.floor(local.mean(0)).astype(int)
        if np.any(cell<0) or np.any(cell>2):continue
        offset=local-(cell+.5);extent=np.ptp(offset,axis=0)
        if np.linalg.norm(offset.mean(0))<.2 and np.max(abs(offset))<.65 and np.min(extent)>.55 and np.max(extent)<1.25:
            found.add(tuple(int(v) for v in cell))
    return found


def confirm_missing(views,images,seed):
    """Consistent absence in supported, fully framed views; not proof of damage.

    An intact observation in *any* supported view prevents its replacement.
    Hidden/occluded material cannot be distinguished from damage by absence
    alone, so candidates still require the user's ghost review.
    """
    observed=set(map(tuple,seed['cells']));evidence=[]
    for f,a in views:
        gray=images[f['frame_id']];q=np.float32(a['face_corners'])*gray.shape[1::-1]
        visible=observed_cells(tile_quads(gray),q)
        if len(visible)<5:continue
        observed.update(visible);evidence.append({'frame_id':f['frame_id'],'observed_cells':sorted(visible)})
    missing=[cell for cell in map(tuple,seed['missing_cells']) if cell not in observed]
    if len(evidence)<2 or not missing:
        raise ValueError('Missing locations are not consistent across two clear views. Show the whole damaged face without fingers covering it.')
    return missing,sorted(observed),evidence


def tile_quads(gray):
    if gray.ndim != 2:raise ValueError('Tile geometry requires a grayscale image')
    h,w=gray.shape;found=[]
    for low,high in [(15,45),(30,80),(45,120)]:
        edges=cv2.morphologyEx(cv2.Canny(gray,low,high),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        for c in cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            area=cv2.contourArea(c)
            if not 150<area<h*w*.16:continue
            hull=cv2.convexHull(c);a=cv2.approxPolyDP(hull,.035*cv2.arcLength(hull,True),True)
            if len(a)!=4 or area/max(1,cv2.contourArea(hull))<.8:continue
            q=_ordered_quad(a);lengths=np.linalg.norm(q-np.roll(q,1,axis=0),axis=1)
            if lengths.min()<15 or lengths.max()/lengths.min()>2.5:continue
            if any(np.linalg.norm(q.mean(0)-x.mean(0))<lengths.min()*.25 for x in found):continue
            found.append(q)
    return rounded_tile_quads(gray,found)


def rounded_tile_quads(gray, found):
    """Retain convex rounded boundaries that have no four sharp corners."""
    found=list(found);h,w=gray.shape
    for low,high in [(3,10),(8,20),(10,30),(20,60),(40,100)]:
        edges=cv2.morphologyEx(cv2.Canny(gray,low,high),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        for contour in cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            area=cv2.contourArea(contour)
            if not 100<area<h*w*.16:continue
            hull=cv2.convexHull(contour);rect=cv2.minAreaRect(hull)
            if min(rect[1])<10 or max(rect[1])/min(rect[1])>4 or area/max(1,np.prod(rect[1]))<.70:continue
            if area/max(1,cv2.contourArea(hull))<.85:continue
            q=_ordered_quad(cv2.boxPoints(rect))
            if any(np.linalg.norm(q.mean(0)-x.mean(0))<min(rect[1])*.25 for x in found):continue
            found.append(q)
    return found


def calibrated_quad(gray, corners, frame):
    """Fit the grid centers to a square under the actual camera calibration.

    An unconstrained homography can extrapolate a plausible but severely
    stretched missing corner from noisy rounded-tile centers.
    """
    q=np.float32(corners);inv=cv2.getPerspectiveTransform(q,np.float32([[0,0],[3,0],[3,3],[0,3]]))
    matches={}
    for tile in tile_quads(gray):
        local=cv2.perspectiveTransform(tile.astype('float32')[None],inv)[0]
        cell=np.floor(local.mean(0)).astype(int);offset=local-(cell+.5)
        if np.any(cell<0) or np.any(cell>2) or np.linalg.norm(offset.mean(0))>.22:continue
        extent=np.ptp(offset,axis=0)
        if np.min(extent)<.55 or np.max(extent)>1.25:continue
        key=tuple(cell);error=float(np.linalg.norm(offset.mean(0)))
        if key not in matches or error<matches[key][0]:matches[key]=(error,tile.mean(0))
    if len(matches)<5:return None
    obj=np.array([[((c+.5)/3-.5),((r+.5)/3-.5),0] for c,r in matches],np.float64)
    pixels=np.array([v[1] for v in matches.values()],np.float64)
    k=np.array(frame['image_k'],float).copy()
    scale=np.array(gray.shape[1::-1])/np.array(frame['image_size']);k[:2]*=scale[:,None]
    okay,rotation,translation=cv2.solvePnP(obj,pixels,k,None,flags=cv2.SOLVEPNP_IPPE)
    if not okay or translation[2,0]<=0:return None
    fitted,_=cv2.projectPoints(obj,rotation,translation,k,None)
    error=np.linalg.norm(fitted.reshape(-1,2)-pixels,axis=1)
    span=np.mean(np.linalg.norm(q-np.roll(q,1,axis=0),axis=1))
    if np.median(error)/span>.025:return None
    unit=np.array([[-.5,-.5,0],[.5,-.5,0],[.5,.5,0],[-.5,.5,0]])
    refined,_=cv2.projectPoints(unit,rotation,translation,k,None);refined=refined.reshape(4,2).astype('float32')
    if np.mean(np.linalg.norm(refined-q,axis=1))/span>.15:return None
    return refined


def lattice_candidates(gray,region):
    """Accept coherent projective lattices, never isolated background contours."""
    x0,y0,x1,y1=capture_bounds(region,gray.shape)
    qs=[q+[x0,y0] for q in tile_quads(gray[y0:y1,x0:x1])]
    centers=np.array([q.mean(0) for q in qs],np.float32);candidates=[]
    if len(qs)<5:return []
    for seed in qs[:60]:
        for margin in [0.,.04,.08]:
            to=cv2.getPerspectiveTransform(seed.astype('float32'),np.float32([[margin,margin],[1-margin,margin],[1-margin,1-margin],[margin,1-margin]]))
            local=cv2.perspectiveTransform(centers[None],to)[0]-.5
            integer=np.rint(local);okay=np.linalg.norm(local-integer,axis=1)<.18
            for r in range(3):
                for c in range(3):
                    cell=integer+[c,r];keep=okay&np.all(cell>=0,axis=1)&np.all(cell<=2,axis=1)
                    unique={tuple(cell[i]):i for i in np.flatnonzero(keep)}
                    if len(unique)<5:continue
                    coords=np.array(list(unique));ids=np.array(list(unique.values()))
                    if len(np.unique(coords[:,0]))<3 or len(np.unique(coords[:,1]))<3:continue
                    src=(coords+.5).astype('float32');dst=centers[ids]
                    tolerance=max(1.5,float(np.median(np.linalg.norm(seed-np.roll(seed,1,axis=0),axis=1)))*.08)
                    H,inliers=cv2.findHomography(src,dst,cv2.RANSAC,tolerance)
                    if H is None or inliers.sum()<5:continue
                    predicted=cv2.perspectiveTransform(np.float32([[[0,0],[3,0],[3,3],[0,3]]]),H)[0]
                    if not cv2.isContourConvex(predicted) or np.any(predicted<[x0+2,y0+2]) or np.any(predicted>[x1-3,y1-3]):continue
                    inv=np.linalg.inv(H);valid=[]
                    for pos,idx,accepted in zip(coords,ids,inliers.ravel()):
                        if not accepted:continue
                        pq=cv2.perspectiveTransform(qs[idx].astype('float32')[None],inv)[0]-(pos+.5)
                        extent=np.ptp(pq,axis=0)
                        if np.max(abs(pq))<.65 and np.min(extent)>.55 and np.max(extent)<1.25:
                            valid.append(tuple(int(v) for v in pos))
                    if len(valid)<5:continue
                    # A tile omitted by the initial seed/RANSAC is not damage.
                    # Recheck every observed outline in the fitted lattice.
                    for tile in qs:
                        local_quad=cv2.perspectiveTransform(tile.astype('float32')[None],inv)[0]
                        position=np.floor(local_quad.mean(0)).astype(int)
                        if np.any(position<0) or np.any(position>2):continue
                        offset=local_quad-(position+.5);extent=np.ptp(offset,axis=0)
                        if np.linalg.norm(offset.mean(0))<.2 and np.max(abs(offset))<.65 and np.min(extent)>.55 and np.max(extent)<1.25:
                            cell=tuple(int(v) for v in position)
                            if cell not in valid:valid.append(cell)
                    missing=sorted(set(PERIMETER_CELLS)-set(valid))
                    if not missing:continue
                    # Every proposed type needs an intact, same-type donor.
                    if any(not any(cell_type(v)==cell_type(m) for v in valid) for m in missing):continue
                    error=float(np.median(np.linalg.norm(cv2.perspectiveTransform(src[None],H)[0]-dst,axis=1)))
                    candidates.append({'corners':predicted.tolist(),'cells':valid,'missing':list(missing[0]),
                                       'missing_cells':[list(m) for m in missing],'score':len(valid)-error/10,'error_px':error})
    candidates.sort(key=lambda x:-x['score'])
    unique=[]
    for candidate in candidates:
        q=np.asarray(candidate['corners'])
        if any(np.mean(np.linalg.norm(q-np.asarray(other['corners']),axis=1))<3 for other in unique):continue
        unique.append(candidate)
        if len(unique)>=6:break
    return unique


def tracked_faces(frames,scan_dir):
    images={}
    for f in frames:
        im=cv2.imread(str(scan_dir/f['rgb_path']))
        if im is None:continue
        factor=min(1,960/max(im.shape[:2]));im=cv2.resize(im,None,fx=factor,fy=factor)
        im=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        images[f['frame_id']]=masked_photo(im,f.get('capture_region'))
    attempts=[]; covered={}
    for seed_index,source in enumerate(frames):
        if source['frame_id'] not in images:continue
        seed_image=images[source['frame_id']]
        for seed in lattice_candidates(seed_image,source.get('capture_region')):
            q=calibrated_quad(seed_image,seed['corners'],source)
            if q is None:continue
            x0,y0,x1,y1=capture_bounds(source.get('capture_region'),seed_image.shape)
            if np.any(q<[x0,y0]) or np.any(q>[x1-1,y1-1]):continue
            normalized=q/seed_image.shape[1::-1]
            span=np.mean(np.linalg.norm(normalized-np.roll(normalized,1,axis=0),axis=1))
            if any(np.mean(np.linalg.norm(normalized-old,axis=1))<span*.035 for old in covered.get(source['frame_id'],[])):continue
            seed={**seed,'corners':q.tolist()}
            views=[(source,{'face_corners':(q/seed_image.shape[1::-1]).tolist()})]
            tracks=[]
            for step in [1,-1]:
                previous=source;q=np.array(seed['corners'],np.float32)
                for index in range(seed_index+step,len(frames) if step>0 else -1,step):
                    f=frames[index]
                    if f['frame_id'] not in images:continue
                    H=cv2.getPerspectiveTransform(np.float32([[0,0],[3,0],[3,3],[0,3]]),q)
                    gaps=[cv2.perspectiveTransform(np.float32([[[c-.12,r-.12],[c+1.12,r-.12],[c+1.12,r+1.12],[c-.12,r+1.12]]]),H)[0]
                          for c,r in seed['missing_cells']]
                    result=track_region(images[previous['frame_id']],images[f['frame_id']],q,excluded_polygons=gaps)
                    if result is None:continue
                    candidate,evidence=result
                    x0,y0,x1,y1=capture_bounds(f.get('capture_region'),images[f['frame_id']].shape)
                    if np.any(candidate<[x0,y0]) or np.any(candidate>[x1-1,y1-1]):continue
                    q=candidate;previous=f
                    views.append((f,{'face_corners':(q/images[f['frame_id']].shape[1::-1]).tolist()}))
                    tracks.append({'frame_id':f['frame_id'],**evidence})
            if len(views)<3:continue
            if np.linalg.norm(np.ptp([f['pose'][:3,3] for f,a in views],axis=0))<.006:continue
            try:geometry,supported,fit=fit_square(views)
            except ValueError as exc:attempts.append(str(exc));continue
            try:missing,observed,evidence=confirm_missing(supported,images,seed)
            except ValueError as exc:attempts.append(str(exc));continue
            seed={**seed,'missing_cells':missing,'missing':missing[0],'cells':observed}
            for f,a in supported:covered.setdefault(f['frame_id'],[]).append(np.asarray(a['face_corners']))
            yield geometry,supported,seed,{'seed_frame':source['frame_id'],'tracks':tracks,'missing_evidence':evidence,**fit},images
    return


def outline_profile(mask):
    """Retain the observed asymmetric contour instead of imposing one radius.

    Smooth at one rectified pixel and simplify below the source-photo sampling
    scale. This removes raster stair-steps, not genuine large corner curvature.
    Fractions are relative to a 200-pixel lattice pitch, not a preset dimension.
    """
    from shapely.geometry import Polygon
    from scipy.optimize import least_squares
    smooth=(cv2.GaussianBlur(mask.astype(np.float32),(5,5),.8)>.5).astype(np.uint8)
    contours=cv2.findContours(smooth,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)[0]
    if not contours:raise ValueError('No closed donor outline')
    contour=max(contours,key=cv2.contourArea)
    boundary=cv2.approxPolyDP(contour,1.0,True).reshape(-1,2).astype(float)
    boundary=(boundary-140)/200
    polygon=Polygon(boundary)
    extent=np.ptp(boundary,axis=0)
    if (not polygon.is_valid or not .5<polygon.area<1.05 or np.any(extent<.7)
            or np.any(extent>1.12) or np.max(abs(boundary))>.62):
        raise ValueError('Donor boundary is clipped or inconsistent with the repeated spacing')
    center=(boundary.min(0)+boundary.max(0))/2
    # Independent radii retain the inner/outer corner asymmetry. Directly
    # extruding Canny's pixel contour would mistake shadows and aliasing for
    # submillimeter surface detail. Fit low-frequency curvature only.
    points=(contour.reshape(-1,2).astype(float)-140)/200
    def residual(v):
        xy=points-v[:2]
        quadrant=np.where(xy[:,1]>=0,np.where(xy[:,0]>=0,0,1),np.where(xy[:,0]<0,2,3))
        radius=v[4:][quadrant]
        q=np.abs(xy)-v[2:4]+radius[:,None]
        return np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(np.max(q,axis=1),0)-radius
    fits=[least_squares(residual,np.r_[np.clip(center,-.1,.1),np.clip(extent/2,.35,.55),[initial]*4],
                       bounds=([-.12,-.12,.35,.35,0,0,0,0],[.12,.12,.56,.56,.34,.34,.34,.34]),
                       loss='soft_l1',f_scale=.008,max_nfev=180) for initial in [.08,.25]]
    fit=min(fits,key=lambda result:result.cost)
    error=float(np.median(abs(residual(fit.x))))
    if error>.02:raise ValueError('Donor curvature does not have a stable simple contour fit')
    center=fit.x[:2];half=fit.x[2:4];radii=fit.x[4:].copy();fitted=[]
    # Curvature below one rectified pixel is unresolved, not a tiny feature.
    radii[radii<.005]=0.
    for index,(signs,start) in enumerate([((1,1),0),((-1,1),90),((-1,-1),180),((1,-1),270)]):
        radius=radii[index];theta=np.deg2rad(np.linspace(start,start+90,17))
        fitted.extend(center+np.asarray(signs)*(half-radius)+radius*np.column_stack([np.cos(theta),np.sin(theta)]))
    polygon=Polygon(fitted)
    rectangularity=float(polygon.area/np.prod(half*2))
    return {'outline_fraction':np.asarray(fitted).tolist(),'raw_outline_fraction':boundary.tolist(),
            'half_extents_fraction':half.tolist(),'corner_radii_fraction':radii.tolist(),
            'median_boundary_error_fraction':error,
            'center_fraction':center.tolist(),'width_fraction':float(np.mean(half*2)),
            'outline_area_fraction':polygon.area,'outline_rectangularity':rectangularity,
            'fit':'independent_corner_arcs_from_multiview_boundary','radius_fraction':None,
            'rounding_source':'observed_boundary_curvature_no_uniform_radius',
            'smoothing_pitch_fraction':.005}


def donor_profile(views,images,missing,observed_cells,return_candidates=False):
    """Fit a same-type intact feature's outline in separated views.

    The face itself has already passed 3+ view and held-out reprojection checks.
    Closed edges, rather than color segmentation, determine the donor boundary.
    """
    candidates=[]
    for c,r in PERIMETER_CELLS:
        if cell_type((c,r))!=cell_type(missing) or (c,r) not in map(tuple,observed_cells):continue
        masks=[];ids=[];positions=[]
        for f,a in views:
            gray=images[f['frame_id']];q=np.float32(a['face_corners'])*gray.shape[1::-1]
            H=cv2.getPerspectiveTransform(q.astype('float32'),np.float32([[60,60],[660,60],[660,660],[60,660]]))
            face=cv2.warpPerspective(gray,H,(720,720))
            patch=face[r*200+20:(r+1)*200+100,c*200+20:(c+1)*200+100];options=[]
            for lo,hi in [(10,30),(20,60),(40,100)]:
                for size in [3,5,9]:
                    edges=cv2.morphologyEx(cv2.Canny(patch,lo,hi),cv2.MORPH_CLOSE,np.ones((size,size),np.uint8))
                    for contour in cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
                        area=cv2.contourArea(contour)
                        if not 20000<area<39000 or cv2.pointPolygonTest(contour,(140.,140.),False)<0:continue
                        xy=contour.reshape(-1,2);extent=np.ptp(xy,axis=0)/200
                        if np.any(extent<.7) or np.any(extent>1.12) or np.max(abs(xy-140))>124:continue
                        if area/max(1,cv2.contourArea(cv2.convexHull(contour)))<.85:continue
                        mask=np.zeros((280,280),np.uint8);cv2.fillPoly(mask,[contour],1)
                        options.append((area,mask))
            if options:
                masks.append(max(options,key=lambda x:x[0])[1]);ids.append(f['frame_id']);positions.append(f['pose'][:3,3])
        if len(masks)<2 or np.linalg.norm(np.ptp(positions,axis=0))<.006:continue
        median=np.mean(masks,axis=0)>=.5
        try:fitted=outline_profile(median)
        except ValueError:continue
        agreement=float(np.mean([np.mean(m==median) for m in masks]))
        if agreement<.85:continue
        candidates.append({**fitted,'source_cell':cell_record((c,r)),'frame_ids':ids,
                           'mask_agreement':agreement,'outline_support':'grayscale_closed_boundary','relief_recovered':False})
    if not candidates:raise ValueError(f"A face is tracked, but an intact {cell_type(missing)} outline is not resolved in two separated views.")
    candidates.sort(key=lambda p:(len(p['frame_ids']),p['mask_agreement']),reverse=True)
    return candidates if return_candidates else candidates[0]


def make_piece(face,profile,missing,output_dir,stem='printable_edge',reference=None,assembly_solids=None):
    import trimesh
    import open3d as o3d
    from shapely.geometry import Polygon
    from .planar_repair import mesh_polygon
    source_cell=(profile['source_cell']['column'],profile['source_cell']['row'])
    if cell_type(source_cell)!=cell_type(missing):raise ValueError('A corner and an edge cannot share a donor.')
    pitch=face['width']/3*1000
    boundary=profile.get('outline_fraction')
    if boundary is None:
        half=np.array(profile['half_extents_fraction']);radius=profile['radius_fraction'];center=np.array(profile['center_fraction']);boundary=[]
        for signs,start in [((1,1),0),((-1,1),90),((-1,-1),180),((1,-1),270)]:
            theta=np.deg2rad(np.linspace(start,start+90,17))
            boundary.extend(center+np.array(signs)*(half-radius)+radius*np.column_stack([np.cos(theta),np.sin(theta)]))
    boundary=np.array(boundary)*pitch
    # Only the front profile is observed. The extrusion depth uses the selected
    # repeated-cubie assumption; it is not presented as captured inner geometry.
    depth=profile['width_fraction']*pitch
    # A fitted corner may be truly sharp (radius ~= 0). Remove coincident arc
    # samples before sending edges to the CAD kernel; do not invent a fillet.
    polygon=Polygon(boundary).simplify(1e-5,preserve_topology=True)
    reference_evidence=None
    if reference is not None:
        from .reference_donor import build_reference_solid
        solid,shape,reference_evidence=build_reference_solid(boundary,depth,source_cell,reference)
    else:
        solid,_=mesh_polygon(polygon,depth)
        solid.apply_translation([0,0,-depth]);solid.fix_normals();solid.units='mm'
    check=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(solid.vertices),o3d.utility.Vector3iVector(solid.faces))
    if not solid.is_watertight or solid.body_count!=1 or solid.volume<=0 or check.is_self_intersecting():
        raise ValueError('Donor extrusion did not form a valid closed solid.')
    source=np.array([profile['source_cell']['column']-1,profile['source_cell']['row']-1],float)
    target=np.array(missing,float)-1
    angle=np.arctan2(target[1],target[0])-np.arctan2(source[1],source[0]);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    render_vertices=solid.vertices.copy();render_faces=solid.faces;render_normals=None
    if reference_evidence is not None:
        from .reference_donor import cad_surface_preview
        render_vertices,render_faces,render_normals=cad_surface_preview(shape)
        if assembly_solids is not None:
            assembly_solids.append(shape.rotate((0,0,0),(0,0,1),float(np.degrees(angle))).translate((float(target[0]*pitch),float(target[1]*pitch),0)))
    local=render_vertices.copy();local[:,:2]=local[:,:2]@rotation.T+target*pitch
    world=local@face['basis'].T+face['center']*1000
    faces=render_faces[:,::-1] if np.linalg.det(face['basis'])<0 else render_faces
    preview={'vertices':world.tolist(),'triangles':faces.tolist(),'unit':'mm'}
    if render_normals is not None:
        render_normals[:,:2]=render_normals[:,:2]@rotation.T
        preview['normals']=(render_normals@face['basis'].T).tolist()
    printed=solid.copy();printed.apply_translation([0,0,-solid.bounds[0,2]])
    exported=[stem+'.stl',stem+'.3mf']
    if reference_evidence is not None:
        import cadquery as cq
        cq.exporters.export(shape.translate((0,0,float(-solid.bounds[0,2]))),str(output_dir/(stem+'.step')))
        exported.append(stem+'.step')
    for name in [stem+'.stl',stem+'.3mf']:
        printed.export(output_dir/name)
        reopened=trimesh.load(output_dir/name,force='mesh',process=True)
        if not reopened.is_watertight or reopened.body_count!=1 or reopened.volume<=0:raise ValueError('Export failed solid validation.')
    return preview,{'status':'closed_exterior_prototype','watertight':True,'connected_solids':1,'self_intersections':False,
                    'volume_mm3':float(solid.volume),'bounds_mm':printed.bounds.tolist(),'unit':'mm',
                    'surface_method':'Reference-guided estimated body and connector' if reference_evidence else 'Observed asymmetric donor boundary with inferred straight extrusion',
                    'extrusion_depth_mm':depth,'depth_source':'regular_cubie_assumption_from_observed_pitch_and_width',
                    'hidden_geometry_reconstructed':False,'physical_fit':'not_tested','relief_recovered':False,
                    'limitations':reference_evidence['limitations'] if reference_evidence else ['Only the front donor outline is measured in photos.','Side shape and depth are inferred; connectors and small surface relief are unresolved.'],
                    'reference_prototype':reference_evidence,
                    'files':exported}


def _make_pieces(face,profiles,missing_cells,output_dir,references=None):
    """One independent closed solid per gap, plus a laid-out print bundle."""
    import trimesh
    from shapely.geometry import Polygon
    if not missing_cells or len(set(map(tuple,missing_cells)))!=len(missing_cells):
        raise ValueError('Replacement locations must be nonempty and distinct')
    if len(profiles)!=len(missing_cells):raise ValueError('Every replacement needs its own donor evidence')
    from .preview_display import piece_color
    vertices=[];triangles=[];colors=[];normals=[];pieces=[];printed=[];outlines=[];assembly_solids=[];cursor=0.
    for index,(profile,missing) in enumerate(zip(profiles,missing_cells)):
        stem='printable_edge' if len(missing_cells)==1 else f'replacement_{index+1:02d}'
        reference=(references or {}).get('pieces',{}).get(cell_type(missing))
        preview,closure=make_piece(face,profile,missing,output_dir,stem,reference=reference,assembly_solids=assembly_solids)
        world=np.asarray(preview['vertices'])
        local=(world-face['center']*1000)@face['basis']
        # Check visible faces here. Reference stems extend inward and need a
        # separate 3D clearance assessment; their 2D projection is not a face.
        front=local[local[:,2]>=-.02] if reference else local
        footprint=Polygon(front[:,:2]).convex_hull
        if any(footprint.intersection(other).area>.01 for other in outlines):
            raise ValueError('Proposed neighboring pieces overlap. More precise donor boundaries are needed.')
        outlines.append(footprint)
        triangles.extend((np.asarray(preview['triangles'])+len(vertices)).tolist());vertices.extend(preview['vertices'])
        colors.extend([piece_color(index)]*len(preview['vertices']))
        normals.extend(preview.get('normals',[]))
        part=trimesh.load(output_dir/(stem+'.stl'),force='mesh')
        part.apply_translation([cursor-part.bounds[0,0],-part.bounds[0,1],-part.bounds[0,2]])
        cursor=part.bounds[1,0]+2.;printed.append(part)
        pieces.append({'id':f'piece_{index+1:02d}','target_cell':cell_record(missing),
                       'preview_color_rgb':piece_color(index),
                       'source_cell':profile['source_cell'],'donor_profile':profile,'closure':closure})
    assembly=None
    if assembly_solids:
        from .reference_donor import validate_reference_assembly
        assembly=validate_reference_assembly(assembly_solids)
    files=[name for p in pieces for name in p['closure']['files']]
    if len(pieces)>1:
        bundle=trimesh.util.concatenate(printed);bundle.units='mm'
        for name in ['printable_edge.stl','printable_edge.3mf']:
            bundle.export(output_dir/name)
            check=trimesh.load(output_dir/name,force='mesh',process=True)
            if not check.is_volume or check.body_count!=len(pieces):raise ValueError('Multi-piece print export lost a closed component')
            files.append(name)
    summary={**pieces[0]['closure'],'connected_solids':len(pieces),'piece_count':len(pieces),
             'volume_mm3':sum(p['closure']['volume_mm3'] for p in pieces),
             'pieces':pieces,'files':files,'print_layout':'Independent pieces; multi-piece bundle uses 2 mm spacing'}
    summary['bounds_mm']=trimesh.util.concatenate(printed).bounds.tolist() if len(pieces)>1 else pieces[0]['closure']['bounds_mm']
    if assembly is not None: summary['assembly_validation']=assembly
    preview={'vertices':vertices,'triangles':triangles,'colors':colors,'unit':'mm'}
    if len(normals)==len(vertices): preview['normals']=normals
    return preview,summary



def make_pieces(face,profiles,missing_cells,output_dir,references=None):
    # An intersecting assembly must not leave apparently usable STEP/STL files
    # behind in the job's published artifact directory.
    from tempfile import TemporaryDirectory
    import shutil
    with TemporaryDirectory(prefix='reversecad-assembly-') as temporary:
        preview,summary=_make_pieces(face,profiles,missing_cells,Path(temporary),references)
        for name in summary['files']:
            shutil.copy2(Path(temporary)/name,Path(output_dir)/name)
        return preview,summary


def photo_overlay(scan_dir,views,face,missing,output_dir,preview=None):
    from .preview_display import piece_color, orient_preview
    # Choose a face-on supported view and show only its capture guide.
    def facing(view):
        f,a=view;delta=f['pose'][:3,3]-face['center'];return abs(face['basis'][:,2]@delta/np.linalg.norm(delta))
    f,a=max(views,key=facing);original=cv2.imread(str(scan_dir/f['rgb_path']));h,w=original.shape[:2];overlay=original.copy();layer=original.copy()
    if preview:
        vertices=np.array(preview['vertices'])/1000;uv,z=project(vertices,f['image_k'],f['pose'])
        local=(vertices-face['center'])@face['basis']
        for tri in preview['triangles']:
            # Only the front cap is observed. Inferred side walls must not
            # paint over surviving material on an adjacent photographed face.
            if np.all(abs(local[tri,2])<1e-7) and np.all(z[tri]>0):
                rgb=preview['colors'][tri[0]] if preview.get('colors') else piece_color(0)
                cv2.fillConvexPoly(layer,np.rint(uv[tri]).astype('int32'),tuple(int(v*255) for v in rgb[::-1]))
    else:
        H=cv2.getPerspectiveTransform(np.float32([[0,0],[3,0],[3,3],[0,3]]),(np.asarray(a['face_corners'])*[w,h]).astype('float32'))
        for index,(c,r) in enumerate(missing):
            gap=cv2.perspectiveTransform(np.float32([[[c,r],[c+1,r],[c+1,r+1],[c,r+1]]]),H)[0]
            cv2.fillConvexPoly(layer,np.rint(gap).astype('int32'),tuple(int(v*255) for v in piece_color(index)[::-1]))
    overlay=cv2.addWeighted(overlay,.60,layer,.40,0)
    q=np.rint(np.array(a['face_corners'])*[w,h]).astype('int32');cv2.polylines(overlay,[q],True,(255,220,0),max(2,w//600),cv2.LINE_AA)
    x0,y0,x1,y1=capture_bounds(f.get('capture_region'),original.shape)
    metadata=f
    records=Path(scan_dir)/'frames.jsonl'
    if records.exists():
        metadata=next((r for line in records.read_text().splitlines() if (r:=json.loads(line))['frame_id']==f['frame_id']),f)
    for name,image in [('cube_original.jpg',original),('cube_overlay.jpg',overlay)]:
        image=image[y0:y1,x0:x1]
        image=orient_preview(image,metadata)
        cv2.imwrite(str(output_dir/name),image)
    return f['frame_id']


def same_tracked_face(first, second):
    """Compare image-space grid identity, not drift-prone world normals."""
    quads={f['frame_id']:np.asarray(a['face_corners']) for f,a in first}
    errors=[]
    for f,a in second:
        if f['frame_id'] not in quads:continue
        q=np.asarray(a['face_corners']);span=np.mean(np.linalg.norm(q-np.roll(q,1,axis=0),axis=1))
        errors.append(float(np.mean(np.linalg.norm(q-quads[f['frame_id']],axis=1))/span))
    return len(errors)>=2 and np.median(errors)<.08 and max(errors)<.12


def depth_support(face, views, observed):
    """Coarse native-depth check on intact centers; never sample a gap.

    LiDAR is not a millimeter calibration. This rejects a gross pose/scale
    mismatch (>20% of the face width), while preserving the finer RGB outline.
    """
    local=np.array([[(c+x)/3-.5,(r+y)/3-.5,0] for c,r in observed
                    for x in [.35,.5,.65] for y in [.35,.5,.65]])*face['width']
    world=local@face['basis'].T+face['center'];checks=[]
    for f,a in views:
        if 'depth' not in f or 'k' not in f:continue
        uv,z=project(world,f['k'],f['pose']);uv=np.rint(uv).astype(int);depth=f['depth']
        valid=(z>0)&(uv[:,0]>=0)&(uv[:,0]<depth.shape[1])&(uv[:,1]>=0)&(uv[:,1]<depth.shape[0])
        uv=uv[valid];z=z[valid];measured=depth[uv[:,1],uv[:,0]];valid=measured>0
        if valid.sum()<12:continue
        error=float(np.median(abs(z[valid]-measured[valid])))
        checks.append({'frame_id':f['frame_id'],'samples':int(valid.sum()),'median_error_mm':error*1000})
    median=float(np.median([c['median_error_mm'] for c in checks])) if checks else None
    good=sum(c['median_error_mm']<=face['width']*1000*.2 for c in checks)
    return {'accepted':good>=3 and median is not None and median<=face['width']*1000*.2,
            'consistent_views':good,'median_error_mm':median,'views':checks,
            'sample_source':'intact_cell_centers_only','tolerance_fraction_of_face':.2,
            'accuracy':'coarse_consistency_only_not_print_fit_calibration'}


def select_visual_candidate(adviser,options,scan_dir,output_dir):
    """A model may choose supported geometry, but cannot bypass solid checks."""
    import tempfile
    from .visual_adviser import feature_id
    baseline=options[0]
    try:plan=adviser.choose(scan_dir,options)
    except (ValueError,OSError,cv2.error):plan={'status':'unavailable','error_code':'visual_evidence_unavailable'}
    visual={'provider':'grok','status':plan['status'],'plan':plan,
            'selection_applied':False,'selected_candidate_id':'C1'}
    advice=plan.get('advice',{});cid=advice.get('selected_candidate_id')
    if plan['status']!='available' or not cid:return baseline,visual
    index=int(cid[1:])-1
    selected={**options[index]};profiles=list(selected['profiles'])
    # Different faces are complementary evidence, not competing descriptions
    # of the entire object. A one-gap view cannot erase two supported gaps.
    if len(selected['seed']['missing_cells'])<len(baseline['seed']['missing_cells']):
        visual.update(status='geometry_rejected_selection',error_code='would_drop_supported_repairs')
        return baseline,visual
    if advice.get('concerns'):
        visual.update(status='geometry_rejected_selection',error_code='model_selection_has_unresolved_concerns')
        return baseline,visual
    if not getattr(adviser,'config',{}).get('apply_selections',False):
        visual['suggestion_only']=True
        return baseline,visual
    choices={v['target_id']:v['donor_id'] for v in advice['donor_choices']}
    for i,cell in enumerate(selected['seed']['missing_cells']):
        target=feature_id(cid,cell)
        if target not in choices:continue
        profiles[i]=next(p for p in selected['donor_pools'][cell_type(cell)]
                         if feature_id(cid,(p['source_cell']['column'],p['source_cell']['row']))==choices[target])
    selected['profiles']=profiles
    try:
        with tempfile.TemporaryDirectory(prefix='visual-solid-check-',dir=output_dir.parent) as folder:
            make_pieces(selected['face'],profiles,selected['seed']['missing_cells'],Path(folder))
    except (ValueError,RuntimeError):
        visual.update(status='geometry_rejected_selection',error_code='selected_donor_failed_solid_checks')
        return baseline,visual
    visual.update(selection_applied=True,selected_candidate_id=cid)
    return selected,visual


def repair_from_faces(frames,scan_dir,output_dir,pose_source="photo_alignment",adviser=None):
    from .reference_donor import load_reference_set
    references=load_reference_set(scan_dir)
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    best=None;failure=None;best_score=None;full_images={};candidates=[];tracked=[];rejected=[];visual_options=[]
    for face,views,seed,tracking,images in tracked_faces(frames,scan_dir):
        tracking={**tracking,'pose_source':pose_source}
        if pose_source=='native_camera_tracking':
            support=depth_support(face,views,seed['cells']);tracking['native_depth_check']=support
            if tracking['median_held_out_error_fraction_of_face']>.04 or not support['accepted']:
                rejected.append({'seed_frame':tracking['seed_frame'],'reason':'native_pose_or_depth_inconsistent'})
                continue
        tracked.append((face,views,seed,tracking,images))
    for face,views,seed,tracking,images in tracked:
        # A less complete detection must not erase an intact tile that another
        # independently seeded track sees on the same face.
        observed=set(map(tuple,seed['cells']))
        for _,other_views,other_seed,_,_ in tracked:
            if same_tracked_face(views,other_views):observed.update(map(tuple,other_seed['cells']))
        missing=[cell for cell in seed['missing_cells'] if tuple(cell) not in observed]
        if not missing:continue
        seed={**seed,'missing_cells':missing,'cells':sorted(observed)}
        if best is None:best=(face,views,seed,tracking,images,None)
        try:
            for f,a in views:
                if f['frame_id'] not in full_images:
                    raw=cv2.imread(str(scan_dir/f['rgb_path']),cv2.IMREAD_GRAYSCALE)
                    full_images[f['frame_id']]=masked_photo(raw,f.get('capture_region'))
            pools={}
            for cell in missing:
                if cell_type(cell) not in pools:pools[cell_type(cell)]=donor_profile(views,full_images,cell,seed['cells'],return_candidates=True)[:3]
            profiles=[pools[cell_type(cell)][0] for cell in missing]
            tracking={**tracking,'donor_image_resolution':'original'}
            # Prefer coverage, then the face with the most independent intact
            # observations. Never reward a false gap caused by a missed tile.
            strongest=max(len(e['observed_cells']) for e in tracking['missing_evidence'])
            score=(len(profiles),strongest,len(views),-tracking['median_held_out_error_fraction_of_face'])
            candidates.append({'seed_frame':tracking['seed_frame'],'target_cells':missing,
                               'supported_views':len(views),'held_out_error':tracking['median_held_out_error_fraction_of_face']})
            visual_options.append({'face':face,'views':views,'seed':seed,'tracking':tracking,'images':images,
                                   'profiles':profiles,'donor_pools':pools,'score':score})
            if best_score is None or score>best_score:
                best_score=score;best=(face,views,seed,tracking,images,profiles)
        except ValueError as exc:failure=str(exc);continue
    if best is None:raise ValueError('No repeated face has a consistent track in three views. Review the saved photographs; no replacement was generated.')
    geometry_baseline=best
    from .visual_adviser import GrokAdviser
    adviser=adviser or GrokAdviser();visual={'provider':'grok','status':adviser.status,'selection_applied':False}
    if visual_options and adviser.status=='ready':
        ranked=[]
        for option in sorted(visual_options,key=lambda x:x['score'],reverse=True):
            if any(same_tracked_face(option['views'],old['views']) for old in ranked):continue
            ranked.append(option)
            if len(ranked)==3:break
        selected,visual=select_visual_candidate(adviser,ranked,Path(scan_dir),output_dir)
        best=tuple(selected[k] for k in ['face','views','seed','tracking','images','profiles'])
    face,views,seed,tracking,images,profiles=best
    tracking={**tracking,'candidate_faces':candidates,'rejected_faces':rejected}
    report={'method':'grayscale_repeated_outlines_and_masked_planar_tracking','color_used':False,
            'status':'face_tracked','scope':'closed_exterior_prototype','tracking':tracking,
            'vision_adviser':visual,'geometry_version':3,'ghost_scope':'observed_front_profile_only','target_cell':cell_record(seed['missing_cells'][0]),
            'target_cells':[cell_record(cell) for cell in seed['missing_cells']],
            'piece_count':len(seed['missing_cells']),
            'observed_cells':seed['cells'],'width_mm':face['width']*1000,
            'assumptions':['User selected a regular 3x3 cube.','An absent repeated front outline is a missing-piece hypothesis; confirm every ghost.',
                           'Only missing locations on the tracked face are proposed. Hidden faces are not assessed.'],
            'metric_accuracy':'uncalibrated','physical_fit':'not_tested','hidden_geometry_reconstructed':False}
    # Keep a useful image-space hypothesis even if the donor/export cannot resolve.
    report['overlay_frame_id']=photo_overlay(scan_dir,views,face,seed['missing_cells'],output_dir)
    (output_dir/'face_repair.json').write_text(json.dumps(report,indent=2))
    if profiles is None:raise ValueError(failure or 'An intact donor outline is unresolved.')
    preview,closure=make_pieces(face,profiles,seed['missing_cells'],output_dir,references=references)
    if references:
        report['reference_prototype']={'reference_set_id':references['reference_set_id'],
            'method':'image_guided_parametric_approximation','physical_fit':'not_tested',
            'detail_revision':max((p.get('details',{}).get('version',1) for p in references['pieces'].values()),default=1),
            'automatic_multiview_reconstruction_succeeded':False,
            'source_hashes':references['source_hashes']}
        (output_dir/'reference_proportions.json').write_text(json.dumps(references,indent=2))
    report.update(status='proposal_needs_review',source_cell=profiles[0]['source_cell'],donor_profile=profiles[0],pieces=closure['pieces'],
                  geometry_is_estimated=True,watertight_replacement=True,closure=closure,
                  reason='Tracked face and same-type intact donor contours. Side shape and depth are inferred; confirm every ghost before a test print.')
    ghost_preview=preview
    if references:
        from tempfile import TemporaryDirectory
        # Preserve the observed front-outline ghost. Approximate connector CAD
        # is inspected in Piece, not painted as if it were observed in the gap.
        with TemporaryDirectory() as temporary:
            ghost_preview,_=make_pieces(face,profiles,seed['missing_cells'],Path(temporary))
        report['reason']='Reference-guided estimated test piece. Body and connector proportions are approximate; physical fit is untested.'
    report['overlay_frame_id']=photo_overlay(scan_dir,views,face,seed['missing_cells'],output_dir,ghost_preview)
    if adviser.status=='ready':
        from .visual_adviser import feature_id,candidate_images
        cid=visual.get('selected_candidate_id','C1')
        references=candidate_images(Path(scan_dir),selected,cid)
        review=adviser.review(output_dir,[feature_id(cid,c) for c in seed['missing_cells']],reference_images=references)
        visual['review']=review
        if visual['selection_applied'] and review.get('advice',{}).get('verdict')=='mismatch':
            # Review disagrees with the model-selected repair. Restore the
            # deterministic baseline; the review is not transferred to it.
            face,views,seed,tracking,images,profiles=geometry_baseline
            for path in output_dir.glob('replacement_*'):
                if path.suffix in ('.stl','.3mf'):path.unlink()
            preview,closure=make_pieces(face,profiles,seed['missing_cells'],output_dir,references=references)
            report.update(target_cell=cell_record(seed['missing_cells'][0]),
                          target_cells=[cell_record(c) for c in seed['missing_cells']],
                          piece_count=len(seed['missing_cells']),observed_cells=seed['cells'],
                          width_mm=face['width']*1000,source_cell=profiles[0]['source_cell'],
                          donor_profile=profiles[0],pieces=closure['pieces'],closure=closure,
                          tracking={**tracking,'candidate_faces':candidates,'rejected_faces':rejected})
            report['overlay_frame_id']=photo_overlay(scan_dir,views,face,seed['missing_cells'],output_dir,preview)
            visual.update(selection_applied=False,status='geometry_rejected_selection',
                          error_code='visual_review_rejected_model_selection',
                          rejected_selection_review=review,selected_candidate_id='C1')
            visual['review']={'status':'not_run','provider':'grok','phase':'review',
                              'note':'The model-selected result was rejected. The restored geometry baseline has not been visually reviewed.'}
        plan_advice=visual.get('plan',{}).get('advice',{})
        visual['needs_attention']=(review.get('advice',{}).get('verdict') in ('mismatch','uncertain')
                                   or bool(plan_advice.get('concerns'))
                                   or (bool(plan_advice) and plan_advice.get('selected_candidate_id') is None))
        if visual['review']['status']=='available' and visual['status'] not in ('available','geometry_rejected_selection'):visual['status']='review_only'
    (output_dir/'visual_adviser.json').write_text(json.dumps(visual,indent=2,allow_nan=False))
    for name,data in [('face_repair.json',report),('counterpart.json',report),('printable_edge.json',closure),('counterpart_preview.json',preview)]:
        (output_dir/name).write_text(json.dumps(data,indent=2,allow_nan=False))
    return report


def reconstruct_faces(scan_dir, output_dir, capture_frames, frames, base):
    """Normal service path: align photos, solve a face, transfer its donor."""
    import time
    from .photo_alignment import align_photos
    from .visual_adviser import GrokAdviser
    adviser=GrokAdviser()
    started=time.monotonic();output_dir=Path(output_dir)
    alignment={'status':'insufficient_photo_evidence','registered_frames':0}
    base.update(status='needs_input',point_count=0,
                surface={'kind':'tracked_face_outlines','unit':'mm','exports':[],
                         'note':'Photographed boundaries. No dense object mesh is required.'})
    (output_dir/'scan_preview.json').write_text(json.dumps({'vertices':[],'triangles':[],'unit':'mm'}))
    try:
        report=None;native_failure=None
        if len(frames)>=3:
            try:
                report=repair_from_faces(frames,scan_dir,output_dir,pose_source='native_camera_tracking',adviser=adviser)
                alignment={'status':'native_face_tracks_verified','registered_frames':len(report['tracking']['views']),
                           'method':'native_metric_camera_poses_with_RGB_tracks_and_intact_depth_checks'}
            except (ValueError,RuntimeError,cv2.error) as exc:native_failure=str(exc)
        if report is None:
            aligned,alignment=align_photos(scan_dir,frames,capture_frames,output_dir)
            if native_failure:alignment['native_face_failure']=native_failure
            if not aligned:
                raise ValueError(alignment.get('reason','More overlapping photographs with reliable scale evidence are needed.'))
            report=repair_from_faces(aligned,scan_dir,output_dir,adviser=adviser)
        base.update(status='proposal_needs_review',counterpart=report,face_repair=report,
                    photo_detail={'status':'observed_outline_with_inferred_extrusion','accepted_pixels':0,
                                  'limitations':'Donor front boundary observed; side profile, depth and internal connectors are not measured.'})
        base['measurements']=[{'id':'face_width','name':'Inferred face width','value':report['width_mm'],
                              'unit':'mm','source':'multiview_face_fit','confirmed':False,
                              'uncertainty_status':'not_calibrated'}]
    except (ValueError,RuntimeError,ImportError,cv2.error) as exc:
        reason=str(exc);alignment['repair_failure']=reason
        base['counterpart']={'status':'needs_input','reason':reason}
        if (output_dir/'face_repair.json').is_file():
            base['face_repair']=json.loads((output_dir/'face_repair.json').read_text())
        for name in ['counterpart_preview.json','counterpart.json','printable_edge.stl','printable_edge.3mf','printable_edge.json']:
            (output_dir/name).unlink(missing_ok=True)
        for path in output_dir.glob('replacement_*'):
            if path.suffix in ('.stl','.3mf'):path.unlink()
    base['photo_alignment']=alignment
    base['metrics']['elapsed_s']=time.monotonic()-started
    for name,data in [('photo_alignment.json',alignment),('reconstruction.json',base)]:
        (output_dir/name).write_text(json.dumps(data,indent=2,allow_nan=False))
    return base


def analyze_photo_geometry(raw, corners=None):
    """Single-photo review hypothesis using outlines only; no metric claim."""
    import hashlib
    from .cube import _photo, CubeInputError
    rgb=_photo(raw);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    candidates=lattice_candidates(gray,None)
    if corners:
        marked=np.asarray(corners,float)
        if marked.shape!=(4,2) or not np.isfinite(marked).all() or np.any(marked<0) or np.any(marked>1):
            raise CubeInputError('Mark four corners inside the photograph.')
        marked*=gray.shape[1::-1]
        scale=np.mean(np.linalg.norm(marked-np.roll(marked,1,axis=0),axis=1))
        candidates=[c for c in candidates if np.mean(np.linalg.norm(np.asarray(c['corners'])-marked,axis=1))<scale*.15]
    if not candidates:
        raise CubeInputError('Repeated outlines are unresolved. Show the damaged face and intact neighboring features sharply inside the guide.')
    seed=candidates[0]
    if len(seed['missing_cells'])>1:
        raise CubeInputError('Several missing locations are visible. Use Start 3D scan to verify and export them together.')
    q=np.float32(seed['corners']);c,r=seed['missing']
    H=cv2.getPerspectiveTransform(np.float32([[0,0],[3,0],[3,3],[0,3]]),q)
    gap=cv2.perspectiveTransform(np.float32([[[c,r],[c+1,r],[c+1,r+1],[c,r+1]]]),H)[0]
    widths=[]
    for tile in tile_quads(gray):
        local=cv2.perspectiveTransform(tile[None].astype('float32'),np.linalg.inv(H))[0]
        center=local.mean(0);cell=np.floor(center).astype(int)
        if tuple(cell) not in map(tuple,seed['cells']):continue
        extent=np.ptp(local,axis=0)
        if np.all(extent>.65) and np.all(extent<1.05):widths.extend(extent)
    if not widths:raise CubeInputError('Repeated spacing is visible, but the intact feature widths are unresolved.')
    return {'schema_version':1,'photo_sha256':hashlib.sha256(raw).hexdigest(),
            'face_corners':(q/gray.shape[1::-1]).tolist(),
            'missing_polygon':(gap/gray.shape[1::-1]).tolist(),
            'missing_cell':cell_record((c,r)),'confidence':'medium',
            'detection_method':'grayscale_repeated_outlines','color_used':False,
            'evidence':'Repeated boundaries suggest this missing feature. Confirm the proposed location; one photo cannot verify a 3D repair.',
            'measurement_status':'needs_metric_reference',
            'exterior_details':{'gap_face_fraction':max(0.,1-float(np.median(widths)))/3,
                                'gap_source':'observed_boundary_spacing',
                                'radius_face_fraction':0.,'radius_source':'unresolved_no_rounding_added'}}
