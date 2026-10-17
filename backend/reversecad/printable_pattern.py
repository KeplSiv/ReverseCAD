"""Conservative solid export of observed donor patches; no object templates."""
import json
from pathlib import Path
import numpy as np
import trimesh


class PatternClosureUnavailable(ValueError):
    pass


def close_planar_boundaries(vertices, faces):
    """Preserve original triangles; cap only simple, planar boundary loops.

    Caps are inferred, not measurements of hidden surfaces. No hull, smoothing,
    voxel dilation, or invented connector is used to force a successful solid.
    """
    from shapely.geometry import Polygon
    from shapely.ops import triangulate
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise PatternClosureUnavailable('No finite donor surface was recovered.')
    if mesh.body_count != 1:
        raise PatternClosureUnavailable('The donor has disconnected surfaces. Scan overlapping views between them.')
    extent = float(np.linalg.norm(mesh.extents))
    if extent <= 0:
        raise PatternClosureUnavailable('The donor has no measurable extent.')
    counts = np.bincount(mesh.edges_unique_inverse)
    if np.any(counts > 2):
        raise PatternClosureUnavailable('The donor has non-manifold edges. Capture sharper overlapping views.')
    boundary = mesh.edges_unique[counts == 1]
    adjacency = {}
    for a, b in boundary:
        adjacency.setdefault(int(a), []).append(int(b))
        adjacency.setdefault(int(b), []).append(int(a))
    if any(len(n) != 2 for n in adjacency.values()):
        raise PatternClosureUnavailable('The open boundary branches. Scan around the donor boundary again.')
    remaining = set(adjacency)
    loops = []
    while remaining:
        start = min(remaining); loop = [start]; previous = None; current = start
        while True:
            following = next(n for n in adjacency[current] if n != previous)
            if following == start:
                break
            if following in loop:
                raise PatternClosureUnavailable('The donor boundary intersects itself.')
            loop.append(following); previous, current = current, following
        remaining.difference_update(loop); loops.append(loop)
    caps = []
    # Tight, scale-relative numerical allowance, not a physical accuracy claim.
    tolerance = max(extent * 1e-5, 1e-9)
    for loop in loops:
        points = mesh.vertices[loop]; center = points.mean(axis=0)
        _, _, basis = np.linalg.svd(points - center, full_matrices=True)
        if np.max(abs((points - center) @ basis[-1])) > tolerance:
            raise PatternClosureUnavailable('An open boundary is curved or incomplete. Scan its underside and adjoining faces; a flat cap would change the shape.')
        xy = (points-center) @ basis[:2].T
        polygon = Polygon(xy)
        if not polygon.is_valid or polygon.area <= tolerance**2:
            raise PatternClosureUnavailable('The donor boundary cannot form a simple cap.')
        triangles = [t for t in triangulate(polygon) if polygon.covers(t)]
        if not np.isclose(sum(t.area for t in triangles), polygon.area, rtol=1e-6, atol=tolerance**2):
            raise PatternClosureUnavailable('The cap could not be triangulated without crossing its boundary.')
        for triangle in triangles:
            indices = []
            for point in np.asarray(triangle.exterior.coords)[:3]:
                distances = np.linalg.norm(xy-point, axis=1)
                if distances.min() > tolerance:
                    raise PatternClosureUnavailable('The cap triangulation changed the observed boundary.')
                indices.append(loop[int(distances.argmin())])
            caps.append(indices)
    solid = trimesh.Trimesh(vertices=mesh.vertices.copy(),
        faces=np.vstack([mesh.faces, np.asarray(caps).reshape(-1,3)]), process=False)
    solid.fix_normals()
    validate_solid(solid)
    return solid, {'inferred_cap_triangles': len(caps), 'observed_triangles': len(mesh.faces),
                   'closure': 'Planar caps at observed open boundaries' if caps else 'Already closed observed donor',
                   'boundary_planarity_tolerance_mm': tolerance}


def validate_solid(mesh):
    import open3d as o3d
    if (not mesh.is_watertight or not mesh.is_winding_consistent or mesh.body_count != 1
            or not np.isfinite(mesh.volume) or mesh.volume <= 0):
        raise PatternClosureUnavailable('The piece failed closed-solid validation.')
    check = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices),
                                     o3d.utility.Vector3iVector(mesh.faces))
    if not check.is_vertex_manifold() or not check.is_edge_manifold(allow_boundary_edges=False):
        raise PatternClosureUnavailable('The piece has non-manifold surface connections.')
    if check.is_self_intersecting():
        raise PatternClosureUnavailable('The piece contains intersecting surfaces.')


def export_printable_pattern(patch, output_dir, stem, scale=1.0):
    if not np.isfinite(scale) or scale <= 0:
        raise PatternClosureUnavailable('Metric scale is unavailable.')
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    solid, report = close_planar_boundaries(np.asarray(patch['vertices'])*1000*scale, patch['faces'])
    preview = {'vertices': solid.vertices.tolist(), 'triangles': solid.faces.tolist(),
               'colors': [], 'normals': [], 'unit': 'mm'}
    printable = solid.copy()
    printable.apply_translation(-printable.bounds[0]); printable.units = 'mm'
    names = [stem+'.stl', stem+'.3mf']
    try:
        for name in names:
            printable.export(output_dir/name)
            reopened = trimesh.load(output_dir/name, force='mesh', process=True)
            validate_solid(reopened)
            if not np.allclose(reopened.extents, printable.extents, rtol=1e-5, atol=1e-5):
                raise PatternClosureUnavailable('Export changed the piece dimensions.')
    except Exception:
        for name in names:
            (output_dir/name).unlink(missing_ok=True)
        raise
    report.update(status='closed_exterior_prototype', watertight=True, connected_solids=1,
                  self_intersections=False, volume_mm3=float(solid.volume), unit='mm',
                  files=names, physical_fit='not_tested', hidden_geometry_reconstructed=False,
                  requires_review=True, limits=['Planar closures are inferred.',
                  'A missing scan area may be occluded rather than broken.',
                  'Clearance, material strength, minimum wall thickness, and physical fit are unverified.'])
    (output_dir/(stem+'_validation.json')).write_text(json.dumps(report, indent=2))
    return preview, report
