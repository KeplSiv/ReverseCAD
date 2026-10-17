"""Close an observed two-face cubie exterior with explicitly inferred flat caps.

This bounded height-field model cannot represent overhangs or hidden mechanisms.
The closure is a printable exterior prototype, never a mechanical-fit claim.
"""
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from skimage.measure import marching_cubes
from .geometry import dot


class ClosureUnavailable(ValueError):
    pass


def close_edge(surface, geometry, missing, output_dir, scale=1):
    pitch = geometry['width']/3*1000*scale
    half = pitch/2
    target = np.array([missing['column']-1, missing['row']-1, 0.])
    outward = geometry['basis'] @ target
    up = geometry['basis'][:, 2]
    tangent = np.cross(up, outward)
    basis = np.column_stack((outward, tangent, up))
    center = geometry['center'] + geometry['basis'] @ (target*geometry['width']/3) - up*geometry['width']/6
    local = dot(np.asarray(surface.vertices)-center, basis)*1000*scale
    if not np.isfinite(local).all() or not 10 <= pitch <= 40:
        raise ClosureUnavailable('Invalid cubie scale or surface coordinates')
    top = local[local[:, 2] > half-2]
    side = local[(local[:, 0] > half-2) & (local[:, 2] < half-2)]
    if min(len(top), len(side)) < 40:
        raise ClosureUnavailable('Scan both exposed faces of the intact edge more closely')
    step = .25
    extent = max(half, float(local[:, [0, 2]].max()))+.75
    if extent > half+4:
        raise ClosureUnavailable('Donor geometry extends beyond the supported exterior envelope')
    # Offset the lattice from the inferred cap planes to avoid exact-zero
    # cells degenerating at coincident plane intersections.
    axis = np.arange(-half-.75-step*.137, extent+step, step)
    a, b = np.meshgrid(axis, axis, indexing='ij')
    queries = np.column_stack((a.ravel(), b.ravel()))
    def height(points, horizontal, vertical):
        tree = cKDTree(points[:, horizontal])
        distances, indices = tree.query(queries, k=min(6, len(points)))
        weights = 1/np.maximum(distances, .02)**2
        heights = (points[indices, vertical]*weights).sum(axis=1)/weights.sum(axis=1)
        face = np.all(abs(queries) < half-.5, axis=1)
        coverage = float(np.mean(distances[face, 0] < 1.5))
        if coverage < .85:
            raise ClosureUnavailable('Less than 85% of an exterior face has nearby observed support; scan the donor from more angles')
        # Unsupported borders use a labeled flat closure; no texture-based relief.
        heights[distances[:, 0] >= 1.5] = half
        return heights.reshape(a.shape), coverage
    top_height, top_coverage = height(top, [0, 1], 2)
    side_height, side_coverage = height(side, [1, 2], 0)
    x, y, z = axis[:, None, None], axis[None, :, None], axis[None, None, :]
    field = np.maximum(x-side_height[None, :, :], z-top_height[:, :, None])
    for plane in (-x-half, abs(y)-half, -z-half):
        field = np.maximum(field, plane)
    vertices, faces, _, _ = marching_cubes(field.astype(np.float32), level=0,
        spacing=(step, step, step), gradient_direction='ascent', allow_degenerate=False)
    vertices += axis[0]
    solid = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    solid.fix_normals()
    if not solid.is_watertight or not solid.is_winding_consistent or solid.body_count != 1 or solid.volume <= 0:
        raise ClosureUnavailable('Closure failed manifold, orientation or connected-solid validation')
    import open3d as o3d
    check = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(solid.vertices), o3d.utility.Vector3iVector(solid.faces))
    if check.is_self_intersecting():
        raise ClosureUnavailable('Closure has intersecting surfaces')
    # Print coordinates: flat inferred bottom on the build plate, millimeters.
    print_mesh = solid.copy()
    print_mesh.apply_translation([0, 0, -print_mesh.bounds[0, 2]])
    print_mesh.units = 'mm'
    output_dir.mkdir(parents=True, exist_ok=True)
    stl = output_dir/'printable_edge.stl'
    print_mesh.export(stl)
    reopened = trimesh.load_mesh(stl, process=True)
    if not reopened.is_watertight or reopened.body_count != 1 or reopened.volume <= 0:
        stl.unlink(missing_ok=True)
        raise ClosureUnavailable('Exported STL failed solid validation')
    print_mesh.export(output_dir/'printable_edge.3mf')
    world_vertices = dot(solid.vertices/(1000*scale), basis.T)+center
    preview = {'vertices': (world_vertices*1000*scale).tolist(), 'triangles': solid.faces.tolist(), 'colors': [], 'normals': [], 'unit': 'mm'}
    report = {'status': 'closed_exterior_prototype', 'unit': 'mm', 'watertight': True,
              'connected_solids': 1, 'self_intersections': False, 'volume_mm3': float(solid.volume),
              'bounds_mm': print_mesh.bounds.tolist(), 'sampling_pitch_mm': step,
              'sampling_pitch_is_accuracy': False, 'top_observed_support_fraction': top_coverage,
              'side_observed_support_fraction': side_coverage,
              'closure': 'Flat inner, bottom and lateral caps; unsupported exterior borders use the nominal cubie envelope.',
              'surface_method': 'Interpolated observed donor top and outer-face relief',
              'limitations': ['Height-field exterior only; overhangs and hidden mechanisms are not reconstructed.',
                             'No mechanical clearance, internal lock, printed fit or minute-feature accuracy has been validated.'],
              'physical_fit': 'not_tested', 'hidden_geometry_reconstructed': False,
              'print_orientation': 'Flat inferred bottom on z=0', 'files': ['printable_edge.stl', 'printable_edge.3mf']}
    return preview, report
