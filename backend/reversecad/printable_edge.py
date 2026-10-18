"""Close an observed two-face cubie exterior with explicitly inferred flat caps.

This bounded height-field model cannot represent overhangs or hidden mechanisms.
The closure is a printable exterior prototype, never a mechanical-fit claim.
"""
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from .geometry import dot


class ClosureUnavailable(ValueError):
    pass


def close_edge(surface, geometry, missing, output_dir, scale=1, *, inferred_points=None, observed_points=None):
    pitch = geometry['width']/3*1000*scale
    half = pitch/2
    target = np.array([missing['column']-1, missing['row']-1, 0.])
    outward = geometry['basis'] @ target
    up = geometry['basis'][:, 2]
    tangent = np.cross(up, outward)
    basis = np.column_stack((outward, tangent, up))
    center = geometry['center'] + geometry['basis'] @ (target*geometry['width']/3) - up*geometry['width']/6
    import open3d as o3d
    o3d.utility.random.seed(19)
    # Validated stereo samples remain useful even when sparse connectivity
    # prevents TSDF from producing a complete donor triangle patch.
    observed = (np.asarray(observed_points).reshape(-1,3) if observed_points is not None else
                np.vstack([np.asarray(surface.vertices), np.asarray(surface.sample_points_uniformly(12000).points)]))
    local = dot(observed-center, basis)*1000*scale
    inferred_local = (dot(np.asarray(inferred_points).reshape(-1,3)-center,basis)*1000*scale
                      if inferred_points is not None else np.empty((0,3)))
    if not np.isfinite(local).all() or not 10 <= pitch <= 40:
        raise ClosureUnavailable('Invalid cubie scale or surface coordinates')
    # Assign points to the nearer exterior plane. A z-only band also selects
    # the vertical face near the shared edge and incorrectly carves its samples
    # into the top height field, creating spurious ridges and pinched solids.
    top_distance = abs(local[:, 2]-half)
    side_distance = abs(local[:, 0]-half)
    top = local[(top_distance <= side_distance) & (top_distance < 2)]
    side = local[(side_distance < top_distance) & (side_distance < 2)]
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
    def height(points, interpolated, horizontal, vertical):
        tree = cKDTree(points[:, horizontal])
        distances, indices = tree.query(queries, k=min(6, len(points)))
        weights = 1/np.maximum(distances, .02)**2
        heights = (points[indices, vertical]*weights).sum(axis=1)/weights.sum(axis=1)
        face = np.all(abs(queries) < half-.5, axis=1)
        observed_coverage = float(np.mean(distances[face, 0] < 1.5))
        coverage = observed_coverage
        nearest = distances[:,0]
        if len(interpolated):
            inferred_tree = cKDTree(interpolated[:,horizontal])
            d, ids = inferred_tree.query(queries)
            fill = (nearest >= 1.5) & (d < 1.5)
            heights[fill] = interpolated[ids[fill],vertical]
            nearest = np.minimum(nearest,d)
            coverage = float(np.mean(nearest[face] < 1.5))
            if observed_coverage < .15:
                raise ClosureUnavailable('Too little observed donor geometry to support planar interpolation.')
        if coverage < .85:
            raise ClosureUnavailable(f'Exterior face support is {coverage:.0%} ({observed_coverage:.0%} observed); need 85% supported coverage. Show both faces of the intact edge.')
        # Unsupported borders use a labeled flat closure; no texture-based relief.
        heights[nearest >= 1.5] = half
        return heights.reshape(a.shape), observed_coverage, coverage
    inferred_top=inferred_local[inferred_local[:,2] > half-2]
    inferred_side=inferred_local[(inferred_local[:,0] > half-2)&(inferred_local[:,2] < half-2)]
    top_height, top_coverage, top_model = height(top, inferred_top, [0, 1], 2)
    side_height, side_coverage, side_model = height(side, inferred_side, [1, 2], 0)
    # A single radial surface prevents separate top/side interpolants from
    # crossing at the shared crease. Each positive radius belongs to one ray
    # from the cubie's interior; the closed cube triangulation supplies topology.
    # Only exterior samples may displace the exterior. Interior/recess samples
    # inside the donor's selection volume are not surface relief on these faces.
    local = np.vstack([top,side])
    observed_radii = np.linalg.norm(local, axis=1)
    directions = local / observed_radii[:, None]
    observed_offsets = observed_radii - half/np.max(abs(directions),axis=1)
    tree = cKDTree(directions)
    inferred_radii = np.linalg.norm(inferred_local, axis=1)
    inferred_offsets = (inferred_radii-half/np.max(abs(inferred_local/inferred_radii[:,None]),axis=1)
                        if len(inferred_local) else np.empty(0))
    inferred_tree = cKDTree(inferred_local / inferred_radii[:, None]) if len(inferred_local) else None
    count = int(np.ceil(pitch/step))
    vertices, triangles, indices = [], [], {}
    def vertex(key):
        if key not in indices:
            indices[key] = len(vertices)
            vertices.append(np.array(key)/count*pitch-half)
        return indices[key]
    for fixed in range(3):
        other = [i for i in range(3) if i != fixed]
        for side_index in [0, count]:
            for i in range(count):
                for j in range(count):
                    corners=[]
                    for u,v in [(i,j),(i+1,j),(i+1,j+1),(i,j+1)]:
                        key=[0,0,0];key[fixed]=side_index;key[other[0]]=u;key[other[1]]=v
                        corners.append(vertex(tuple(key)))
                    triangles.extend([[corners[0],corners[1],corners[2]],
                                      [corners[0],corners[2],corners[3]]])
    vertices=np.asarray(vertices)
    # Inner/bottom/lateral caps stay flat. Blend only their narrow boundary
    # rims into the captured exterior; the shared two-face crease is free.
    exterior=(np.isclose(vertices[:,0],half)|np.isclose(vertices[:,2],half))
    ids=np.flatnonzero(exterior);q=vertices[ids];r=np.linalg.norm(q,axis=1);direction=q/r[:,None]
    distance,neighbors=tree.query(direction,k=min(6,len(local)))
    weights=1/np.maximum(distance,.001)**2
    # Interpolate displacement from the nominal envelope, not absolute radius:
    # cube radius changes with angle even for a perfectly flat face.
    radius=r+(observed_offsets[neighbors]*weights).sum(1)/weights.sum(1)
    nearest=distance[:,0]*half
    if inferred_tree is not None:
        d,near=inferred_tree.query(direction)
        fill=(nearest>=1.5)&(d*half<1.5)
        radius[fill]=r[fill]+inferred_offsets[near[fill]]
        nearest=np.minimum(nearest,d*half)
    radius[nearest>=1.5]=r[nearest>=1.5]
    rim=np.minimum.reduce([q[:,0]+half,half-abs(q[:,1]),q[:,2]+half])
    blend=np.clip(rim/.5,0,1)
    vertices[ids]=direction*(r+blend*(radius-r))[:,None]
    solid=trimesh.Trimesh(vertices=vertices,faces=np.asarray(triangles),process=False)
    solid.fix_normals()
    discarded_volume = 0.0
    if solid.body_count > 1:
        components = sorted(solid.split(only_watertight=False), key=lambda m: abs(m.volume), reverse=True)
        rest = components[1:]
        # Intersecting sampled height fields can create isolated numerical
        # specks. Never discard a substantial separate part to force success.
        if all(m.is_watertight and abs(m.volume) < abs(components[0].volume)*.001
               and np.max(m.extents) < pitch*.15 for m in rest):
            discarded_volume = float(sum(abs(m.volume) for m in rest))
            solid = components[0]
    if not solid.is_watertight or not solid.is_winding_consistent or solid.body_count != 1 or solid.volume <= 0:
        raise ClosureUnavailable(f'Closure failed solid validation (closed={solid.is_watertight}, oriented={solid.is_winding_consistent}, bodies={solid.body_count}, volume={solid.volume:.2f} mm3)')
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
              'discarded_isolated_volume_mm3': discarded_volume,
              'bounds_mm': print_mesh.bounds.tolist(), 'sampling_pitch_mm': step,
              'sampling_pitch_is_accuracy': False, 'top_observed_support_fraction': top_coverage,
              'side_observed_support_fraction': side_coverage,
              'top_supported_fraction_including_planar_inference': top_model,
              'side_supported_fraction_including_planar_inference': side_model,
              'planar_inference_used': bool(len(inferred_local)),
              'closure': 'Flat inner, bottom and lateral caps; unsupported exterior borders use the nominal cubie envelope.',
              'surface_method': 'Radial donor exterior; textureless interiors use fitted planes and 0.5 mm cap rims are inferred',
              'limitations': ['Height-field exterior only; overhangs and hidden mechanisms are not reconstructed.',
                             'No mechanical clearance, internal lock, printed fit or minute-feature accuracy has been validated.'],
              'physical_fit': 'not_tested', 'hidden_geometry_reconstructed': False,
              'print_orientation': 'Flat inferred bottom on z=0', 'files': ['printable_edge.stl', 'printable_edge.3mf']}
    return preview, report
