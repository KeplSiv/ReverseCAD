"""Geometry-only exterior repair for an explicitly selected 3x3 cube.

Photo stereo supplies surface coordinates; native depth supplies metric scale.
Observed planes and cube orthogonality define candidate frames. A missing edge
can be nominated by multiview recess depth or repeated face appearance, with
surviving surfaces vetoing a placement. A photographed intact donor supplies the
exterior. Sparse/noisy detail uses an explicitly inferred convex outline model;
hidden connectors are not modeled.
"""
import json
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull, Delaunay, cKDTree
from .geometry import project, unproject


def ray_evidence(points, frames, tolerance=.002):
    """Count distinct source cameras observing surface, recess, or occlusion.

    A zero/missing depth is unknown, never evidence that material is missing.
    """
    empty, on, occluded = {}, {}, {}
    for index, f in enumerate(frames):
        uv,z=project(points,f['k'],f['pose']); h,w=f['depth'].shape
        good=np.isfinite(uv).all(1)&(z>0)&(uv[:,0]>=1)&(uv[:,0]<w-1)&(uv[:,1]>=1)&(uv[:,1]<h-1)
        ids=np.flatnonzero(good); pixels=np.rint(uv[ids]).astype(int)
        d=f['depth'][pixels[:,1],pixels[:,0]]; valid=np.isfinite(d)&(d>0);ids=ids[valid];delta=d[valid]-z[ids]
        # Several pairs with the same reference image must not inflate votes.
        key=f.get('source_frames',[str(index)])[0]
        for store,condition in [(empty,delta>tolerance),(on,abs(delta)<=tolerance),(occluded,delta < -tolerance)]:
            votes=store.setdefault(key,np.zeros(len(points),bool));votes[ids[condition]]=True
    def total(store):return np.sum(list(store.values()),axis=0) if store else np.zeros(len(points),int)
    return total(empty),total(on),total(occluded)


def fit_cube_frame(points, camera_positions, *, return_candidates=False):
    import open3d as o3d
    xyz=np.asarray(points,float)
    if len(xyz)<1000 or not np.isfinite(xyz).all():raise ValueError('Need more independently matched photo surface samples.')
    extent=float(np.linalg.norm(np.ptp(xyz,axis=0)))
    if not .02<extent<.5:raise ValueError('Photo geometry is outside the small-object capture range.')
    tolerance=float(np.clip(extent*.006,.00025,.0008))
    cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz)).voxel_down_sample(tolerance*.8)
    # Extract candidates first. Greedily accepting a noisy bevel as the third
    # axis can exclude a better-supported exterior plane later in RANSAC.
    remainder=cloud;planes=[];o3d.utility.random.seed(13)
    for _ in range(12):
        if len(remainder.points)<200:break
        plane,ids=remainder.segment_plane(tolerance,3,600)
        if len(ids)<max(150,len(cloud.points)*.025):break
        pts=np.asarray(remainder.points)[ids].copy();remainder=remainder.select_by_index(ids,invert=True)
        n=np.asarray(plane[:3]);n/=np.linalg.norm(n)
        planes.append((n,pts))
    from itertools import combinations
    # Weak texture on one face may fragment an unconstrained plane fit. The
    # cube prior supplies its normal, but actual samples must still support
    # the offset and later pass the same extent/residual checks.
    cloud_points=np.asarray(cloud.points)
    constrained=[]
    for (n0,_),(n1,_) in combinations(planes[:6],2):
        if abs(n0@n1)>.20:continue
        normal=np.cross(n0,n1);normal/=np.linalg.norm(normal)
        projected=cloud_points@normal
        low,high=np.percentile(projected,[1,99])
        if high-low<.02:continue
        counts,edges=np.histogram(projected,bins=max(10,int((high-low)/tolerance)),range=(low,high))
        centers=(edges[:-1]+edges[1:])/2
        for end in [centers<low+(high-low)*.15,centers>high-(high-low)*.15]:
            ids=np.flatnonzero(end)
            if not len(ids):continue
            peak=centers[ids[np.argmax(counts[ids])]]
            group=cloud_points[abs(projected-peak)<tolerance]
            if len(group)<150:continue
            if any(abs(normal@n)>.995 and abs(np.median(group@normal)-np.median(p@normal))<tolerance for n,p in planes+constrained):continue
            constrained.append((normal,group))
    planes+=constrained
    solutions=[]
    for selected in combinations(planes,3):
        normals=[n.copy() for n,_ in selected];groups=[p for _,p in selected]
        if any(abs(normals[i]@normals[j])>.20 for i,j in [(0,1),(0,2),(1,2)]):continue
        for i, normal in enumerate(normals):
            neighbors=np.concatenate([group for j,group in enumerate(groups) if j!=i])
            if np.median((neighbors-groups[i].mean(0))@normal)>0:normals[i]=-normal
        u,_,v=np.linalg.svd(normals);basis=(u@v).T
        offsets=np.array([np.median(pts@basis[:,i]) for i,pts in enumerate(groups)])
        corner=basis@offsets;local=(np.concatenate(groups)-corner)@basis
        widths=-np.percentile(local,1,axis=0);width=float(np.median(widths))
        if np.any(np.mean(local>tolerance*3,axis=0)>.15):continue
        if not .025<width<.15 or np.ptp(widths)>width*.10:continue
        residuals=[float(np.median(abs(pts@basis[:,i]-offsets[i]))) for i,pts in enumerate(groups)]
        if max(residuals)>width*.025:continue
        center=corner-basis@np.full(3,width/2)
        score=sum(len(g) for g in groups)*(1-np.ptp(widths)/width)
        solutions.append((score,{'center':center,'basis':basis,'width':width,'groups':groups,
                'evidence':{'widths_mm':(widths*1000).tolist(),'plane_median_residuals_mm':(np.array(residuals)*1000).tolist(),
                            'plane_candidates':len(planes),'scale_accuracy':'uncalibrated',
                            'assumption':'User selected a regular 3x3 cube; dimensions come from photo geometry.'}}))
    if not solutions:raise ValueError('The recovered surface does not resolve three consistent exterior planes yet; aligned photos alone do not guarantee surface depth.')
    ranked=[g for _,g in sorted(solutions,key=lambda x:-x[0])]
    return ranked if return_candidates else ranked[0]


def locate_missing_edge(geometry, frames, diagnostics=None):
    width=geometry['width'];pitch=width/3;basis=geometry['basis'];center=geometry['center'];candidates=[]
    # Only the three intersections of observed outward planes are eligible.
    # Back-side edges have no cavity evidence and are never called missing.
    for tangent in range(3):
        outer=[i for i in range(3) if i!=tangent];target=np.ones(3);target[tangent]=0;checks=[]
        for fixed in outer:
            free=[i for i in range(3) if i!=fixed]
            xy=np.linspace(-.35,.35,15)*pitch;a,b=np.meshgrid(xy,xy)
            coords=np.tile(target*pitch,(225,1));coords[:,fixed]=width/2
            coords[:,free[0]]+=a.ravel();coords[:,free[1]]+=b.ravel()
            empty,on,occluded=ray_evidence(coords@basis.T+center,frames,max(.0015,pitch*.10))
            checks.append({'recess_fraction':float(np.mean(empty>=2)),
                           'surface_fraction':float(np.mean(on>=2)),
                           'distinct_recess_views':int(empty.max())})
        score=min(c['recess_fraction'] for c in checks)
        candidates.append({'target':target.tolist(),'outer_axes':outer,'score':score,'faces':checks})
    candidates.sort(key=lambda c:-c['score'])
    if diagnostics is not None:
        diagnostics['tested_edges']=candidates
        diagnostics['minimum_recess_fraction']=.25
    best=candidates[0]
    if best['score']<.25 or any(c['surface_fraction']>.20 for c in best['faces']):
        raise ValueError('No edge has enough matched recess depth on both faces. The cube outline was recovered, but the gap remains unresolved. Capture sharp, overlapping views aimed into the opening from both sides in diffuse light.')
    if len(candidates)>1 and candidates[1]['score']>best['score']*.6:
        raise ValueError('More than one edge looks recessed. Capture another oblique view of the missing cubie.')
    return best,candidates


def planar_support(geometry, frames, observed_points):
    """Interpolate planar interiors within measured hulls, excluding seen recesses.

    These samples only support the broad flat face between observed boundaries.
    Original donor points take precedence near observed detail in close_edge.
    """
    samples=[];basis=geometry['basis'];width=geometry['width'];tree=cKDTree(observed_points)
    for axis,group in enumerate(geometry['groups']):
        other=[i for i in range(3) if i!=axis];origin=group.mean(0)
        xy=(group-origin)@basis[:,other];hull=ConvexHull(xy);domain=Delaunay(xy[hull.vertices])
        low,high=xy.min(0),xy.max(0);step=width/140
        a,b=np.meshgrid(np.arange(low[0],high[0],step),np.arange(low[1],high[1],step));q=np.column_stack([a.ravel(),b.ravel()]);q=q[domain.find_simplex(q)>=0]
        pts=q@basis[:,other].T+origin
        empty,_,_=ray_evidence(pts,frames,max(.0015,width/30))
        # Fill only textureless interiors, never overwrite captured relief or
        # cross a photographed cavity simply to produce a solid.
        pts=pts[(empty<2)&(tree.query(pts)[0]>.0008)]
        samples.extend(pts)
    return np.asarray(samples).reshape(-1,3)


def repair_cube_exterior(mesh, stereo_frames, output_dir, *, photo_frames=None, scan_dir=None):
    import open3d as o3d
    from .cube_counterpart import transfer_edge
    from .printable_edge import close_edge
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    points=np.concatenate([unproject(f['depth'],f['k'],f['pose'])[0] for f in stereo_frames])
    try:
        geometries=fit_cube_frame(points,[f['pose'][:3,3] for f in stereo_frames],return_candidates=True)
    except ValueError:
        if photo_frames is None or scan_dir is None:raise
        from .cube_photo_evidence import frames_from_photo_outlines
        geometries=frames_from_photo_outlines(photo_frames,scan_dir,points)
    failures=[]
    for geometry in geometries[:6]:
        try:
            return _repair_in_frame(mesh,stereo_frames,output_dir,geometry,points,
                                    photo_frames=photo_frames,scan_dir=scan_dir)
        except ValueError as exc:failures.append(str(exc))
    raise ValueError(' '.join(dict.fromkeys(failures)))


def _repair_in_frame(mesh, stereo_frames, output_dir, geometry, points, *, photo_frames=None, scan_dir=None):
    import open3d as o3d
    from .cube_counterpart import transfer_edge
    from .printable_edge import close_edge
    diagnostics={**geometry['evidence'],'status':'exterior_frame_resolved'}
    photos=None
    try:
        missing,alternatives=locate_missing_edge(geometry,stereo_frames,diagnostics)
    except ValueError as exc:
        diagnostics.update(status='gap_unresolved',reason=str(exc),replacement_generated=False)
        (output_dir/'cube_exterior_evidence.json').write_text(json.dumps(diagnostics,indent=2))
        if photo_frames is None or scan_dir is None:raise
        from .cube_photo_evidence import load_photos,locate_photo_edge
        photos=load_photos(photo_frames,scan_dir)
        missing,alternatives=locate_photo_edge(geometry,photos,diagnostics.get('tested_edges',[]))
    inferred=(np.empty((0,3)) if geometry['evidence'].get('frame_source')=='calibrated_multiview_face_outline'
              else planar_support(geometry,stereo_frames,points))
    results=[];failures=[]
    for fixed in missing['outer_axes']:
        radial=next(i for i in missing['outer_axes'] if i!=fixed)
        u=geometry['basis'][:,radial];normal=geometry['basis'][:,fixed]
        face={'center':geometry['center']+normal*geometry['width']/2,
              'basis':np.column_stack([u,np.cross(normal,u),normal]),'width':geometry['width']}
        cell={'row':1,'column':2,'type':'edge'}
        transferred=transfer_edge(mesh,face,cell)
        if transferred is None:failures.append('Both exterior faces of an intact edge are not visible.');continue
        patch,provenance=transferred;t=np.asarray(provenance['transform_world_m'])
        # Restrict inferred support to the same source cubie's footprint.
        local=(inferred-face['center'])@face['basis'];src=np.array([provenance['source_cell']['column']-1,provenance['source_cell']['row']-1])
        pitch=face['width']/3;offset=local[:,:2]-src*pitch;rad=offset@src;tan=offset@np.array([-src[1],src[0]])
        keep=(abs(tan)<pitch*.5)&(rad>-pitch*.5)&(rad<pitch*.5)&(local[:,2]>-pitch)&(local[:,2]<.002)
        fill=inferred[keep]@t[:3,:3].T+t[:3,3]
        try:
            preview,closure=close_edge(patch,face,cell,output_dir,inferred_points=fill)
            results.append((preview,closure,provenance,patch));break
        except ValueError as exc:failures.append(str(exc))
    if not results and photo_frames is not None and scan_dir is not None:
        from .cube_counterpart import transfer_edge_points
        from .cube_photo_evidence import load_photos,close_photo_donor
        if photos is None:photos=load_photos(photo_frames,scan_dir)
        for fixed in missing['outer_axes']:
            radial=next(i for i in missing['outer_axes'] if i!=fixed)
            u=geometry['basis'][:,radial];normal=geometry['basis'][:,fixed]
            face={'center':geometry['center']+normal*geometry['width']/2,
                  'basis':np.column_stack([u,np.cross(normal,u),normal]),'width':geometry['width']}
            cell={'row':1,'column':2,'type':'edge'}
            for observed,provenance in transfer_edge_points(points,face,cell):
                try:
                    preview,closure=close_photo_donor(face,provenance['source_cell'],cell,photos,output_dir)
                    provenance['donor_photo_profiles']=closure['donor_photo_profiles']
                    provenance['relief_recovered']=False
                    cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(observed))
                    o3d.io.write_point_cloud(str(output_dir/'donor_observed_points_m.ply'),cloud)
                    results.append((preview,closure,provenance,None));break
                except ValueError as exc:failures.append(str(exc))
            if results:break
    evidence={'method':'photo_geometry_and_intact_donor',
              **geometry['evidence'],'missing_edge':missing,'tested_edges':alternatives,
              'colors_used_for_shape':False,'internal_mechanism_reconstructed':False}
    (output_dir/'cube_exterior_evidence.json').write_text(json.dumps(evidence,indent=2))
    if not results:raise ValueError(' '.join(failures))
    preview,closure,provenance,patch=results[0]
    if patch is not None:
        patch.scale(1000,center=(0,0,0));o3d.io.write_triangle_mesh(str(output_dir/'counterpart_surface.stl'),patch)
    (output_dir/'counterpart_preview.json').write_text(json.dumps(preview))
    (output_dir/'printable_edge.json').write_text(json.dumps(closure,indent=2))
    report={**evidence,**provenance,'status':'proposal_needs_review','scope':'closed_exterior_prototype',
        'watertight_replacement':True,'geometry_is_estimated':True,'hidden_geometry_reconstructed':False,
        'physical_fit':'not_tested','width_mm':geometry['width']*1000,'closure':closure,
        'reason':'Cubie exterior inferred from an intact edge. Review its position and shape; inner faces are flat closures, with no connector.'}
    (output_dir/'counterpart.json').write_text(json.dumps(report,indent=2))
    return report
