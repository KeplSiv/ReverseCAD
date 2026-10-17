"""Experimental geometry-only repetition proposals, independent of object class.

Uses Open3D robust ICP to test rotational self-similarity. Original donor
triangles are transformed unchanged. Missing scan coverage is NOT proof of a
broken part: candidates require review and are never called printable repairs.
Inspired by transformation-space repetition (Pauly et al., SIGGRAPH 2008).
This is a bounded baseline, not an implementation of SymmCompletion/DeepJoin.
"""
import copy
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


def candidate_from_transform(vertices, faces, transform, tolerance):
    """Extract only triangles absent from the observation, preserving relief."""
    xyz = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=int)
    t = np.asarray(transform, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all() or tolerance <= 0:
        raise ValueError('Invalid metric rigid transform or tolerance')
    if not np.allclose(t[:3,:3].T @ t[:3,:3], np.eye(3), atol=1e-5) or np.linalg.det(t[:3,:3]) < .999:
        raise ValueError('Donor geometry may only undergo a rigid rotation and translation')
    transformed = xyz @ t[:3,:3].T + t[:3,3]
    distances = cKDTree(xyz).query(transformed)[0]
    selected = np.all(distances[faces] > tolerance, axis=1)
    ids = np.flatnonzero(selected)
    if not len(ids): return None
    used, indices = np.unique(faces[ids], return_inverse=True)
    return {'vertices': transformed[used], 'faces': indices.reshape(-1,3),
            'source_vertex_indices': used, 'source_triangle_indices': ids}


def propose_patterns(mesh, max_candidates=3):
    import open3d as o3d
    if len(mesh.triangles) < 100: return [], {'status':'insufficient_surface'}
    extent = np.linalg.norm(mesh.get_max_bound()-mesh.get_min_bound())
    if not np.isfinite(extent) or extent <= 0: raise ValueError('Invalid mesh extent')
    # Registration scale derives from the observed object, never a preset part size.
    voxel = extent / 160
    o3d.utility.random.seed(0)
    points = mesh.sample_points_uniformly(12000).voxel_down_sample(voxel)
    points.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*5,max_nn=40))
    xyz = np.asarray(points.points)
    _, vectors = np.linalg.eigh(np.cov(xyz.T))
    center = (xyz.min(0)+xyz.max(0))/2
    target_tree = cKDTree(xyz)
    reg = o3d.pipelines.registration
    estimator = reg.TransformationEstimationPointToPlane(reg.TukeyLoss(k=voxel*3))
    candidates = []
    for axis in vectors.T:
        for order in range(2,9):
            for direction in [-1,1]:
                rotation = Rotation.from_rotvec(axis * (direction*2*np.pi/order)).as_matrix()
                initial = np.eye(4);initial[:3,:3]=rotation;initial[:3,3]=center-rotation@center
                fitted = reg.registration_icp(points,points,voxel*5,initial,estimator,
                    reg.ICPConvergenceCriteria(max_iteration=35))
                t = fitted.transformation
                transformed = xyz @ t[:3,:3].T+t[:3,3]
                d, nearest = target_tree.query(transformed)
                overlap = d < voxel*2
                fraction = float(overlap.mean())
                novel = float(np.mean(d > voxel*5))
                if fraction < .70 or not .005 < novel < .28: continue
                normals = np.asarray(points.normals)
                agreement = abs(np.sum((normals@t[:3,:3].T)*normals[nearest],axis=1))
                if np.median(agreement[overlap]) < .85: continue
                # Reject identity convergence and duplicate transforms.
                motion = np.median(np.linalg.norm(transformed-xyz,axis=1))
                if motion < voxel*10: continue
                if any(np.median(np.linalg.norm(transformed-c['mapped'],axis=1))<voxel*4 for c in candidates):continue
                patch = candidate_from_transform(mesh.vertices,mesh.triangles,t,voxel*5)
                if patch is None or len(patch['faces'])<20:continue
                candidates.append({'transform':t,'patch':patch,'mapped':transformed,
                    'overlap_fraction':fraction,'novel_fraction':novel,
                    'matched_surface_rmse':float(np.sqrt(np.mean(d[overlap]**2))),
                    'normal_agreement':float(np.median(agreement[overlap]))})
    candidates.sort(key=lambda c:(-c['overlap_fraction'],c['matched_surface_rmse']))
    for c in candidates: c.pop('mapped',None)
    return candidates[:max_candidates], {'status':'hypotheses_need_review' if candidates else 'no_supported_repetition',
        'method':'rotational_self_similarity_open3d_robust_icp',
        'candidate_count':len(candidates),'tolerance_in_mesh_units':float(voxel*5),
        'geometry_preserved':'Original donor triangles; no primitive fitting or smoothing',
        'physical_fit':'unverified','hidden_geometry_reconstructed':False,'printable':False,
        'limitations':['A missing scan region can be an occlusion, not damage.',
            'Principal-axis rotations only; translation, reflection and arbitrary local symmetries remain unsupported.',
            'Registration agreement is not dimensional accuracy. No inferred closure or connector.',
            'Candidates need camera visibility checks and damage-region confirmation before use.']}
