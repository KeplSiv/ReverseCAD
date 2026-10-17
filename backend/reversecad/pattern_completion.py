"""Experimental geometry-only repetition proposals, independent of object class.

Uses Open3D robust ICP to test rotational, mirror, and translational self-similarity. Original donor
triangles are transformed unchanged. Missing scan coverage is NOT proof of a
broken part: candidates require review and are never called printable repairs.
Inspired by transformation-space repetition (Pauly et al., SIGGRAPH 2008).
This is a bounded baseline, not an implementation of SymmCompletion/DeepJoin.
"""
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from scipy.signal import find_peaks


def candidate_from_transform(vertices, faces, transform, tolerance, bounds=None, *, whole_components=False):
    """Extract only triangles absent from the observation, preserving relief."""
    xyz = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=int)
    t = np.asarray(transform, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all() or tolerance <= 0:
        raise ValueError('Invalid metric rigid transform or tolerance')
    if not np.allclose(t[:3,:3].T @ t[:3,:3], np.eye(3), atol=1e-5) or not np.isclose(abs(np.linalg.det(t[:3,:3])), 1, atol=1e-5):
        raise ValueError('Donor geometry may only undergo an isometry, without scaling')
    transformed = xyz @ t[:3,:3].T + t[:3,3]
    # Distance to triangles, not vertices: a point on a broad flat face is
    # observed even when the face has only a few vertices.
    import open3d as o3d
    observed = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(xyz),
                                        o3d.utility.Vector3iVector(faces))
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(observed))
    distances = scene.compute_distance(o3d.core.Tensor(
        transformed.astype(np.float32))).numpy()
    missing = distances > tolerance
    if bounds is not None:
        missing &= np.all((transformed >= bounds[0]) & (transformed <= bounds[1]), axis=1)
    selected = np.all(missing[faces], axis=1)
    if whole_components:
        # A feature already segmented by mesh connectivity is stronger evidence
        # than its farthest triangles. Transfer the complete observed donor,
        # including its ridges and contact boundary; no dimensions are invented.
        labels, counts, areas = observed.cluster_connected_triangles()
        labels=np.asarray(labels); counts=np.asarray(counts)
        for label,count in enumerate(counts):
            component_faces=np.flatnonzero(labels==label)
            used=np.unique(faces[component_faces])
            if count<4 or count>len(faces)*.40: continue
            if np.count_nonzero(selected[component_faces]) < 4: continue
            if np.mean(distances[used] > tolerance*.3) < .65: continue
            if bounds is not None and not np.all((transformed[used]>=bounds[0])&(transformed[used]<=bounds[1])):continue
            selected[component_faces]=True
    ids = np.flatnonzero(selected)
    if not len(ids): return None
    used, indices = np.unique(faces[ids], return_inverse=True)
    output_faces = indices.reshape(-1,3)
    if np.linalg.det(t[:3,:3]) < 0: output_faces = output_faces[:,::-1]
    return {'vertices': transformed[used], 'faces': output_faces,
            'source_vertex_indices': used, 'source_triangle_indices': ids}


def propose_patterns(mesh, max_candidates=3, *, fast=False):
    import open3d as o3d
    if len(mesh.triangles) < 100: return [], {'status':'insufficient_surface'}
    extent = np.linalg.norm(mesh.get_max_bound()-mesh.get_min_bound())
    if not np.isfinite(extent) or extent <= 0: raise ValueError('Invalid mesh extent')
    # Registration scale derives from the observed object, never a preset part size.
    voxel = extent / 160
    o3d.utility.random.seed(0)
    points = mesh.sample_points_uniformly(3000 if fast else 12000).voxel_down_sample(voxel)
    points.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*5,max_nn=40))
    xyz = np.asarray(points.points)
    _, vectors = np.linalg.eigh(np.cov(xyz.T))
    local = xyz @ vectors
    center = ((local.min(0)+local.max(0))/2) @ vectors.T
    target_tree = cKDTree(xyz)
    normals = np.asarray(points.normals)
    reg = o3d.pipelines.registration
    estimator = reg.TransformationEstimationPointToPlane(reg.TukeyLoss(k=voxel*3))
    seeds = []
    for axis in vectors.T:
        for order in range(2,5 if fast else 9):
            for direction in [-1,1]:
                rotation = Rotation.from_rotvec(axis * (direction*2*np.pi/order)).as_matrix()
                initial = np.eye(4);initial[:3,:3]=rotation;initial[:3,3]=center-rotation@center
                if not any(np.allclose(initial, old[1], atol=1e-7) for old in seeds):
                    seeds.append(('rotation', initial, None))
        reflection = np.eye(3)-2*np.outer(axis,axis)
        initial=np.eye(4);initial[:3,:3]=reflection;initial[:3,3]=center-reflection@center
        seeds.append(('reflection',initial,None))
    # Repeated edges/corners produce peaks in the autocorrelation of normal
    # variation. A flat slab alone should not supply a translation period.
    neighbors=target_tree.query(xyz,k=min(16,len(xyz)))[1]
    nn=normals[neighbors]
    tensor=np.einsum('nki,nkj->nij',nn,nn)/nn.shape[1]
    variation=1-np.linalg.eigvalsh(tensor)[:,-1]
    for axis in vectors.T:
        projection=xyz@axis
        if np.ptp(projection) < voxel*8: continue
        bins=max(12,int(np.ptp(projection)/voxel))
        hist,edges=np.histogram(projection,bins=bins,weights=np.maximum(0,variation-.04))
        if hist.sum() <= 0: continue
        correlation=np.correlate(hist,hist,mode='full')[bins-1:]
        peaks,_=find_peaks(correlation,distance=3)
        peaks=[i for i in peaks if max(4,bins*.08)<i<bins*.45]
        peaks=sorted(peaks,key=lambda i:correlation[i],reverse=True)[:3]
        for lag in peaks:
            for sign in [-1,1]:
                initial=np.eye(4);initial[:3,3]=axis*lag*(edges[1]-edges[0])*sign
                # Only fill gaps inside the measured footprint; never extend
                # a finite rail indefinitely by repeating its end element.
                bounds=(xyz.min(0)-voxel,xyz.max(0)+voxel)
                seeds.append(('translation',initial,bounds))
    candidates = []
    for kind,initial,bounds in seeds:
        rough=xyz@initial[:3,:3].T+initial[:3,3]
        if np.mean(target_tree.query(rough)[0]<voxel*8)<.35: continue
        fitted = reg.registration_icp(points,points,voxel*5,initial,estimator,
            reg.ICPConvergenceCriteria(max_iteration=15 if fast else 35))
        t = fitted.transformation
        transformed = xyz @ t[:3,:3].T+t[:3,3]
        d, nearest = target_tree.query(transformed)
        overlap = d < voxel*2
        fraction = float(overlap.mean())
        relevant=np.ones(len(xyz),dtype=bool) if bounds is None else np.all((transformed>=bounds[0])&(transformed<=bounds[1]),axis=1)
        novel = float(np.mean((d > voxel*5)&relevant))
        if fraction < .70 or not .005 < novel < .28: continue
        agreement = abs(np.sum((normals@t[:3,:3].T)*normals[nearest],axis=1))
        if np.median(agreement[overlap]) < .85: continue
        motion = np.median(np.linalg.norm(transformed-xyz,axis=1))
        if motion < voxel*10: continue
        if any(np.median(np.linalg.norm(transformed-c['mapped'],axis=1))<voxel*4 for c in candidates):continue
        patch = candidate_from_transform(mesh.vertices,mesh.triangles,t,voxel*5,bounds=bounds,whole_components=True)
        if patch is None or len(patch['faces'])<4:continue
        candidates.append({'transform':t,'patch':patch,'mapped':transformed,'pattern_kind':kind,
            'overlap_fraction':fraction,'novel_fraction':novel,
            'matched_surface_rmse':float(np.sqrt(np.mean(d[overlap]**2))),
            'normal_agreement':float(np.median(agreement[overlap]))})
    candidates.sort(key=lambda c:(-c['overlap_fraction'],c['matched_surface_rmse']))
    for c in candidates: c.pop('mapped',None)
    return candidates[:max_candidates], {'status':'hypotheses_need_review' if candidates else 'no_supported_repetition',
        'method':'geometric_self_similarity_open3d_robust_icp',
        'candidate_count':len(candidates),'tolerance_in_mesh_units':float(voxel*5),
        'geometry_preserved':'Original donor triangles; no primitive fitting or smoothing',
        'physical_fit':'unverified','hidden_geometry_reconstructed':False,'printable':False,
        'limitations':['A missing scan region can be an occlusion, not damage.',
            'Principal-axis rotation/reflection and translation periods; arbitrary local symmetries remain unsupported.',
            'Registration agreement is not dimensional accuracy. Any planar closure is reported separately; connectors are not inferred.',
            'Candidates need camera visibility checks and damage-region confirmation before use.']}


def export_pattern_hypotheses(mesh, output_dir, scale=1.0):
    """Save reviewable alternatives without selecting or declaring a repair."""
    import json
    from pathlib import Path
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    from .geometry_prediction import predict_geometry
    candidates, report = predict_geometry(mesh)
    report['candidates'] = []
    for index, candidate in enumerate(candidates):
        patch = candidate['patch']
        name = f"pattern_candidate_{index + 1}.json"
        preview = {'vertices': (patch['vertices'] * scale * 1000).tolist(),
                   'triangles': patch['faces'].tolist(), 'unit': 'mm',
                   'source_vertex_indices': patch['source_vertex_indices'].tolist(),
                   'source_triangle_indices': patch['source_triangle_indices'].tolist()}
        (output_dir / name).write_text(json.dumps(preview))
        report['candidates'].append({
            'preview': name, 'pattern_kind': candidate['pattern_kind'],
            'transform_in_mesh_units': candidate['transform'].tolist(),
            'overlap_fraction': candidate['overlap_fraction'],
            'matched_surface_rmse': candidate['matched_surface_rmse'],
            'normal_agreement': candidate['normal_agreement'],
            'support_score': candidate.get('support_score'), 'assumptions': candidate.get('assumptions', []),
            'checks': candidate.get('checks', {})})
        item = report['candidates'][-1]
        item['id'] = f'pattern_{index + 1}'
        from .printable_pattern import export_printable_pattern, PatternClosureUnavailable
        try:
            solid_preview, validation = export_printable_pattern(patch, output_dir, item['id'], scale)
            item['print_preview'] = item['id'] + '_solid.json'
            (output_dir / item['print_preview']).write_text(json.dumps(solid_preview))
            item['validation'] = validation
        except PatternClosureUnavailable as exc:
            item['validation'] = {'status': 'needs_more_views', 'watertight': False,
                                  'reason': str(exc), 'files': []}

    (output_dir / 'pattern_hypotheses.json').write_text(json.dumps(report, indent=2))
    return report
