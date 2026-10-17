"""Geometry hypotheses, not damage detection or manufacturing certification.

Repetition/reflection preserve source triangles. Planar continuation only bridges
an interior coplanar boundary; it never extrapolates an unseen outer contour.
The ranking uses observed support, not a calibrated probability of correctness.
"""
import numpy as np
from scipy.spatial import cKDTree, ConvexHull


def planar_continuations(mesh):
    import trimesh
    from shapely.geometry import Polygon
    from shapely.ops import triangulate
    m = trimesh.Trimesh(np.asarray(mesh.vertices), np.asarray(mesh.triangles), process=True)
    extent = np.linalg.norm(m.extents)
    if extent <= 0: return []
    tolerance = extent * .001
    edges, counts = np.unique(np.sort(m.edges, axis=1), axis=0, return_counts=True)
    boundary = edges[counts == 1]
    adjacency = {}
    for a,b in boundary:
        adjacency.setdefault(int(a), []).append(int(b)); adjacency.setdefault(int(b), []).append(int(a))
    seen = set(); candidates = []
    for start in sorted(adjacency):
        if start in seen: continue
        component = {start}; pending = [start]
        while pending:
            for nxt in adjacency[pending.pop()]:
                if nxt not in component: component.add(nxt); pending.append(nxt)
        seen |= component
        if len(component) < 4 or any(len(adjacency[i]) != 2 for i in component): continue
        loop = [start]; previous = None; current = start
        while True:
            nxt = next(i for i in adjacency[current] if i != previous)
            if nxt == start: break
            loop.append(nxt); previous,current = current,nxt
            if len(loop) > len(component): break
        if len(loop) != len(component): continue
        xyz = m.vertices[loop]; center = xyz.mean(0)
        _, singular, axes = np.linalg.svd(xyz-center, full_matrices=False)
        if singular[1] < tolerance or np.max(abs((xyz-center) @ axes[2])) > tolerance: continue
        incident = np.any(np.isin(m.faces, loop), axis=1)
        parallel = abs(m.face_normals @ axes[2]) > .995
        coplanar = np.max(abs((m.vertices[m.faces]-center) @ axes[2]),axis=1) < tolerance
        if np.mean(parallel[incident] & coplanar[incident]) < .90: continue
        support = np.unique(m.faces[parallel & coplanar])
        if len(support) < len(loop)+3: continue
        xy = (xyz-center) @ axes[:2].T
        polygon = Polygon(xy)
        if not polygon.is_valid or polygon.area < tolerance**2*10: continue
        support_xy = (m.vertices[support]-center) @ axes[:2].T
        hull = ConvexHull(support_xy)
        hull_polygon = Polygon(support_xy[hull.vertices])
        # Every point of the loop must be strictly inside the measured planar
        # footprint. An outer perimeter cannot establish a missing surface.
        if not hull_polygon.buffer(-tolerance).contains(polygon): continue
        if polygon.area > hull_polygon.area*.35: continue
        caps=[]
        for triangle in triangulate(polygon):
            if not polygon.covers(triangle): continue
            ids=[]
            for p in np.asarray(triangle.exterior.coords)[:3]:
                distance=np.linalg.norm(xy-p,axis=1)
                if distance.min()>tolerance: break
                ids.append(int(distance.argmin()))
            if len(ids)==3: caps.append(ids)
        if not caps: continue
        patch={'vertices':xyz.copy(),'faces':np.asarray(caps,dtype=int),
               'source_vertex_indices':np.asarray(loop),'source_triangle_indices':np.array([],dtype=int)}
        candidates.append({'patch':patch,'transform':np.eye(4),'pattern_kind':'planar_continuation',
            'overlap_fraction':float(np.mean(parallel[incident] & coplanar[incident])),
            'matched_surface_rmse':float(np.sqrt(np.mean(((xyz-center)@axes[2])**2))),
            'normal_agreement':float(np.median(abs(m.face_normals[incident]@axes[2]))),
            'assumptions':['Interior planar boundary is damage rather than an intentional opening or occlusion.',
                           'No thickness or hidden surface is inferred.']})
    return candidates


def predict_geometry(mesh, *, fast=False, max_candidates=5):
    from .pattern_completion import propose_patterns
    import time
    started=time.monotonic()
    vertices=np.asarray(mesh.vertices)
    spread=np.linalg.svd(vertices-vertices.mean(0),compute_uv=False) if len(vertices)>=3 else np.zeros(3)
    # A single plane has infinitely many approximate self-alignments. Those
    # cannot establish its unseen outer contour; only bounded inner loops qualify.
    if spread[0]>0 and spread[-1]/spread[0]<.002:
        candidates=[];evidence={'status':'planar_surface','printable':False}
    else:
        candidates, evidence = propose_patterns(mesh, max_candidates=max_candidates, fast=fast)
    candidates += planar_continuations(mesh)
    extent = float(np.linalg.norm(mesh.get_max_bound()-mesh.get_min_bound()))
    ranked=[]
    for c in candidates:
        patch=c['patch'];v=np.asarray(patch['vertices']);f=np.asarray(patch['faces'])
        if len(f)==0 or not np.isfinite(v).all(): continue
        area=float(np.linalg.norm(np.cross(v[f[:,1]]-v[f[:,0]],v[f[:,2]]-v[f[:,0]]),axis=1).sum()/2)
        if area < extent**2*1e-6: continue
        residual=c['matched_surface_rmse']/max(extent,1e-12)
        # Same transparent ranking for all hypotheses. This is not confidence.
        c['support_score']=float(np.clip(.65*c['overlap_fraction']+.35*c['normal_agreement']-10*residual,0,1))
        c['assumptions']=c.get('assumptions',['The observed geometric repetition continues into this unobserved region.',
                                               'A scan hole may be occlusion, not damage.'])
        c['patch_area']=area
        c['checks']={'observed_alignment':'passed',
            'hidden_geometry':'unknown', 'image_reprojection':'not_evaluated_by_this_mesh_stage',
            'damage_vs_occlusion':'requires_review','volume_collision':'unknown_from_partial_surface'}
        ranked.append(c)
    ranked.sort(key=lambda c:(-c['support_score'],c['matched_surface_rmse']))
    # Keep methods with different explanations available, including continuation.
    selected=[]
    for kind in ['reflection','translation','rotation','planar_continuation']:
        item=next((c for c in ranked if c['pattern_kind']==kind),None)
        if item is not None:selected.append(item)
    selected += [c for c in ranked if all(c is not old for old in selected)][:max(0,max_candidates-len(selected))]
    selected.sort(key=lambda c:-c['support_score'])
    selected=selected[:max_candidates]
    return selected, {**evidence,'method':'ranked_repetition_symmetry_planar_continuation',
        'status':'provisional' if selected else 'no_supported_prediction',
        'seconds':time.monotonic()-started,'candidate_count':len(selected),
        'damage_confirmed':False,'physical_fit':'not_tested','printable':False,
        'ranking':'Observed overlap + normal agreement - normalized registration residual; not probability',
        'ambiguity':'Unknown regions may be occluded or intentional openings. Review is required.'}


def evaluate_patch(patch, truth, observed, samples=4000):
    """Independent two-way surface error; never rank using the held-out truth."""
    import trimesh
    import open3d as o3d
    def points(mesh):
        o3d.utility.random.seed(17)
        m=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices),o3d.utility.Vector3iVector(mesh.faces))
        return np.asarray(m.sample_points_uniformly(samples).points)
    def distances(p, mesh):
        scene=o3d.t.geometry.RaycastingScene()
        m=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices),o3d.utility.Vector3iVector(mesh.faces))
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(m))
        return scene.compute_distance(o3d.core.Tensor(p.astype(np.float32))).numpy()
    predicted=trimesh.Trimesh(patch['vertices'],patch['faces'],process=False)
    a=distances(points(predicted),truth); b=distances(points(truth),predicted)
    scale=float(np.linalg.norm(observed.extents))
    d=distances(points(predicted),observed)
    return {'prediction_to_truth_p95':float(np.percentile(a,95)),
            'truth_to_prediction_p95':float(np.percentile(b,95)),
            'symmetric_p95_fraction_of_extent':float(max(np.percentile(a,95),np.percentile(b,95))/scale),
            'near_existing_surface_fraction':float(np.mean(d < scale*.002)),
            'dimensional_extent_error_fraction':float(np.max(abs(predicted.extents-truth.extents))/scale)}
