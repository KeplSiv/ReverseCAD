"""Geometry-only exterior repair for an explicitly selected 3x3 cube.

Photo stereo supplies surface coordinates; native depth supplies metric scale in
photo_alignment. Three observed planes define the frame. A missing edge requires
visible recessed geometry on both outward faces. Color is never an input here.
Planar interpolation and flat hidden caps are reported as inference, not sensing.
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


def fit_cube_frame(points, camera_positions):
    import open3d as o3d
    xyz=np.asarray(points,float)
    if len(xyz)<1000 or not np.isfinite(xyz).all():raise ValueError('Need more independently matched photo surface samples.')
    extent=float(np.linalg.norm(np.ptp(xyz,axis=0)))
    if not .02<extent<.5:raise ValueError('Photo geometry is outside the small-object capture range.')
    tolerance=float(np.clip(extent*.006,.00025,.0008))
    cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz)).voxel_down_sample(tolerance*.8)
    remainder=cloud;normals=[];groups=[];o3d.utility.random.seed(13)
    for _ in range(12):
        if len(remainder.points)<200:break
        plane,ids=remainder.segment_plane(tolerance,3,600)
        if len(ids)<max(150,len(cloud.points)*.025):break
        pts=np.asarray(remainder.points)[ids];remainder=remainder.select_by_index(ids,invert=True)
        n=np.asarray(plane[:3]);n/=np.linalg.norm(n)
        if any(abs(n@v)>.20 for v in normals):continue
        if n@(np.mean(camera_positions,axis=0)-pts.mean(0))<0:n=-n
        normals.append(n);groups.append(pts)
        if len(normals)==3:break
    if len(normals)!=3:raise ValueError('Show three outside faces of the cube across the scan; their planes are not resolved yet.')
    u,_,v=np.linalg.svd(normals);basis=(u@v).T
    offsets=np.array([np.median(pts@basis[:,i]) for i,pts in enumerate(groups)])
    corner=basis@offsets
    local=(np.concatenate(groups)-corner)@basis
    widths=-np.percentile(local,1,axis=0);width=float(np.median(widths))
    if not .025<width<.15 or np.ptp(widths)>width*.10:
        raise ValueError('The observed exterior does not support equal cube dimensions; show its outer edges clearly.')
    residuals=[float(np.median(abs(pts@basis[:,i]-offsets[i]))) for i,pts in enumerate(groups)]
    if max(residuals)>width*.025:raise ValueError('The three exterior planes are not consistent enough for a cubie.')
    center=corner-basis@np.full(3,width/2)
    return {'center':center,'basis':basis,'width':width,'groups':groups,
            'evidence':{'widths_mm':(widths*1000).tolist(),'plane_median_residuals_mm':(np.array(residuals)*1000).tolist(),
                        'scale_accuracy':'uncalibrated','assumption':'User selected a regular 3x3 cube; dimensions come from photo geometry.'}}


def locate_missing_edge(geometry, frames):
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
    best=candidates[0]
    if best['score']<.25 or any(c['surface_fraction']>.20 for c in best['faces']):
        raise ValueError('No edge has a visible recess on both exterior faces. Aim at the gap from its two sides; an unseen patch is not enough.')
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


def repair_cube_exterior(mesh, stereo_frames, output_dir):
    import open3d as o3d
    from .cube_counterpart import transfer_edge
    from .printable_edge import close_edge
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    points=np.concatenate([unproject(f['depth'],f['k'],f['pose'])[0] for f in stereo_frames])
    geometry=fit_cube_frame(points,[f['pose'][:3,3] for f in stereo_frames])
    missing,alternatives=locate_missing_edge(geometry,stereo_frames)
    inferred=planar_support(geometry,stereo_frames,points)
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
    evidence={'method':'photo_geometry_planes_visible_cavity_and_intact_donor',
              **geometry['evidence'],'missing_edge':missing,'tested_edges':alternatives,
              'colors_used_for_shape':False,'internal_mechanism_reconstructed':False}
    (output_dir/'cube_exterior_evidence.json').write_text(json.dumps(evidence,indent=2))
    if not results:raise ValueError(' '.join(failures))
    preview,closure,provenance,patch=results[0]
    patch.scale(1000,center=(0,0,0));o3d.io.write_triangle_mesh(str(output_dir/'counterpart_surface.stl'),patch)
    (output_dir/'counterpart_preview.json').write_text(json.dumps(preview))
    (output_dir/'printable_edge.json').write_text(json.dumps(closure,indent=2))
    report={**evidence,**provenance,'status':'proposal_needs_review','scope':'closed_exterior_prototype',
        'watertight_replacement':True,'geometry_is_estimated':True,'hidden_geometry_reconstructed':False,
        'physical_fit':'not_tested','width_mm':geometry['width']*1000,'closure':closure,
        'reason':'Cubie exterior inferred from an intact edge. Review its position and shape; inner faces are flat closures, with no connector.'}
    (output_dir/'counterpart.json').write_text(json.dumps(report,indent=2))
    return report
