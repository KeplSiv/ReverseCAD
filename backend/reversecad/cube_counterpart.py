"""Transfer an observed intact edge's exterior surface using a cube symmetry.

The observed patch is retained; supported exteriors also receive inferred flat
closure surfaces for a printable prototype. Hidden connectors are not modeled.
"""
import copy
import cv2
import numpy as np
from .cube import analyze_cube_face, CubeInputError
from .geometry import fit_plane, dot, transform_points


def face_frame(frame, analysis):
    """Fit the visible grid plane from intact native depth, intersect its corner rays."""
    h, w = frame['depth'].shape
    ys, xs = np.nonzero(frame['depth'] > 0)
    if len(xs) < 80:
        return None
    rays = dot(np.column_stack((xs, ys, np.ones(len(xs)))), np.linalg.inv(frame['k']).T)
    pixels = dot(rays, frame['image_k'].T)
    pixels = pixels[:, :2]/pixels[:, 2, None]
    iw, ih = frame['image_size']
    corners = np.array(analysis['face_corners'], dtype=np.float32)*[iw, ih]
    homography = cv2.getPerspectiveTransform(corners.astype(np.float32), np.float32([[0, 0], [3, 0], [3, 3], [0, 3]]))
    grid = cv2.perspectiveTransform(pixels.astype(np.float32)[None], homography)[0]
    missing = analysis['missing_cell']
    cells = np.floor(grid).astype(int)
    fractional = grid-cells
    keep = (grid[:, 0] > 0) & (grid[:, 0] < 3) & (grid[:, 1] > 0) & (grid[:, 1] < 3)
    keep &= np.all((fractional > .18) & (fractional < .82), axis=1)
    keep &= ~((cells[:, 0] == missing['column']) & (cells[:, 1] == missing['row']))
    world = transform_points(rays[keep]*frame['depth'][ys[keep], xs[keep], None], frame['pose'])
    plane = fit_plane(world, threshold_m=.0012)
    if plane is None or np.count_nonzero(plane['inliers']) < 50 or plane['residual_mm'] > .8:
        return None
    normal = plane['normal']; center = plane['center_m']
    origin = frame['pose'][:3, 3]
    if np.dot(normal, origin-center) < 0:
        normal = -normal
    rays = dot(np.column_stack((corners, np.ones(4))), np.linalg.inv(frame['image_k']).T)
    directions = dot(rays, frame['pose'][:3, :3].T)
    denominator = dot(directions, normal)
    if np.any(abs(denominator) < .2):
        return None
    distances = np.dot(center-origin, normal)/denominator
    if np.any(distances <= 0):
        return None
    vertices = origin+directions*distances[:, None]
    u = (vertices[1]-vertices[0]+vertices[2]-vertices[3])/2
    v = (vertices[3]-vertices[0]+vertices[2]-vertices[1])/2
    widths = [np.linalg.norm(u), np.linalg.norm(v)]
    width = float(np.mean(widths))
    if not .03 <= width <= .12 or abs(widths[0]-widths[1])/width > .12:
        return None
    u /= np.linalg.norm(u)
    if abs(np.dot(u, v/np.linalg.norm(v))) > .12:
        return None
    v -= u*np.dot(u, v); v /= np.linalg.norm(v)
    return {'center': vertices.mean(axis=0), 'basis': np.column_stack((u, v, normal)),
            'width': width, 'plane_residual_mm': float(plane['residual_mm'])}


def transfer_edge(mesh, geometry, missing, minimum_triangles=80):
    """Choose a supported donor edge and rotate it into the missing grid location."""
    center, basis, width = geometry['center'], geometry['basis'], geometry['width']
    pitch = width/3
    xyz = np.asarray(mesh.vertices)
    triangles = np.asarray(mesh.triangles)
    local = dot(xyz-center, basis)
    target = np.array([missing['column']-1, missing['row']-1])
    if tuple(target) not in [(0, -1), (-1, 0), (1, 0), (0, 1)]:
        return None
    best = None
    for source in [(0, -1), (-1, 0), (1, 0), (0, 1)]:
        if np.array_equal(source, target):
            continue
        source = np.array(source)
        offset = local[:, :2]-source*pitch
        radial = dot(offset, source)
        tangential = dot(offset, np.array([-source[1], source[0]]))
        # Keep outward relief, while excluding neighboring cubies tangentially.
        in_cell = (abs(tangential) < pitch*.5) & (radial > -pitch*.5) & (radial < pitch*.5+.003)
        in_cell &= (local[:, 2] > -pitch*.98) & (local[:, 2] < .003)
        selected = np.flatnonzero(np.all(in_cell[triangles], axis=1))
        if len(selected) < minimum_triangles:
            continue
        # Require support on both exterior faces. A single flat sticker is not a cubie.
        centers = local[triangles[selected]].mean(axis=1)
        top = np.count_nonzero(abs(centers[:, 2]) < .0015)
        lateral = np.count_nonzero((dot(centers[:, :2], source) > width/2-.0025) & (centers[:, 2] < -.003))
        if min(top, lateral) < 20:
            continue
        score = min(top, lateral)
        if best is None or score > best[0]:
            best = (score, source, selected)
    if best is None:
        return None
    _, source, selected = best
    angle = np.arctan2(target[1], target[0])-np.arctan2(source[1], source[0])
    c, s = np.cos(angle), np.sin(angle)
    rotation = basis @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]]) @ basis.T
    proposal = copy.deepcopy(mesh)
    proposal.remove_triangles_by_mask(~np.isin(np.arange(len(triangles)), selected))
    proposal.remove_unreferenced_vertices()
    transform = np.eye(4); transform[:3, :3] = rotation; transform[:3, 3] = center-rotation@center
    proposal.transform(transform)
    proposal.compute_vertex_normals()
    return proposal, {'source_cell': {'row': int(source[1]+1), 'column': int(source[0]+1), 'type': 'edge'},
                      'target_cell': missing, 'transform_world_m': transform.tolist(), 'triangles': len(proposal.triangles)}


def propose_counterpart(frames, scan_dir, mesh, output_dir, scale=1):
    import open3d as o3d
    report = {'status': 'needs_more_evidence', 'method': 'observed_intact_edge_rotated_by_cube_symmetry',
              'assumption': 'The intact and missing edges have the same exterior shape.',
              'scope': 'exterior_surface_patch_only', 'watertight_replacement': False,
              'hidden_geometry_reconstructed': False, 'physical_fit': 'not_tested'}
    if mesh is None or not len(mesh.triangles):
        return report
    candidates = []
    for frame in frames[::max(1, len(frames)//12)][:12]:
        image = cv2.imread(str(scan_dir/frame['rgb_path']))
        if image is None:
            continue
        factor = min(1, 1200/max(image.shape[:2]))
        image = cv2.resize(image, None, fx=factor, fy=factor)
        _, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 65])
        try:
            analysis = analyze_cube_face(encoded.tobytes())
        except CubeInputError:
            continue
        if analysis['confidence'] == 'needs_review' or analysis['missing_cell']['type'] != 'edge':
            continue
        geometry = face_frame(frame, analysis)
        if geometry is None:
            continue
        transferred = transfer_edge(mesh, geometry, analysis['missing_cell'])
        if transferred is not None:
            candidates.append((analysis['score_margin'], frame, geometry, transferred))
    if not candidates:
        report['reason'] = 'Need a clearly visible mostly solved face with one missing edge, plus both exterior faces of an intact edge.'
        return report
    _, frame, geometry, (proposal, provenance) = max(candidates, key=lambda x: x[0])
    from .printable_edge import close_edge, ClosureUnavailable
    import json
    closed_preview = None
    try:
        closed_preview, closure = close_edge(proposal, geometry, provenance['target_cell'], output_dir, scale)
        report.update(scope='closed_exterior_prototype', watertight_replacement=True, closure=closure)
        (output_dir/'printable_edge.json').write_text(json.dumps(closure, indent=2))
    except ClosureUnavailable as exc:
        report['closure'] = {'status': 'needs_more_evidence', 'reason': str(exc)}
    proposal.scale(1000*scale, center=(0, 0, 0))
    proposal.compute_vertex_normals()
    if not o3d.io.write_triangle_mesh(str(output_dir/'counterpart_surface.stl'), proposal):
        raise ValueError('Could not export counterpart surface')
    report.update(status='proposal_needs_review', detection_frame=frame['frame_id'],
                  observed_frame_ids=[f['frame_id'] for f in frames], width_mm=geometry['width']*1000*scale,
                  plane_residual_mm=geometry['plane_residual_mm'], **provenance)
    preview = {'vertices': np.asarray(proposal.vertices).tolist(), 'triangles': np.asarray(proposal.triangles).tolist(),
               'colors': [], 'normals': np.asarray(proposal.vertex_normals).tolist(), 'unit': 'mm'}
    return {**report, 'preview': closed_preview or preview}
