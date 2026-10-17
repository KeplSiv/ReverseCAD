import numpy as np
import cv2
import open3d as o3d
from reversecad.photo_detail import stereo_pair
from reversecad.cube_counterpart import face_frame, transfer_edge


def stereo_observations(textured=True):
    h, w, focal = 320, 480, 600.
    k = np.array([[focal, 0, (w-1)/2], [0, focal, (h-1)/2], [0, 0, 1.]])
    rng = np.random.default_rng(42)
    texture = cv2.GaussianBlur(rng.integers(0, 256, (1200, 1200), dtype=np.uint8), (7, 7), 1.2)
    yy, xx = np.indices((h, w))
    frames = []
    for position in (0, .018):
        # Independent analytic ray intersections with a 2 mm raised patch.
        x_top = (xx-k[0, 2])/focal*.238+position
        y_top = (yy-k[1, 2])/focal*.238
        top = (abs(x_top)<.018) & (abs(y_top)<.018)
        z = np.where(top, .238, .24)
        x = (xx-k[0, 2])/focal*z+position
        y = (yy-k[1, 2])/focal*z
        gray = cv2.remap(texture, (x*4000+600).astype(np.float32), (y*4000+600).astype(np.float32), cv2.INTER_LINEAR)
        if not textured:
            gray[:] = 120
        pose = np.eye(4); pose[0, 3] = position
        frames.append({'frame_id': str(position), 'image': np.repeat(gray[:, :, None], 3, axis=2),
                       'image_k': k, 'k': k, 'depth': np.full((h, w), .24), 'pose': pose})
    return frames


def test_photos_recover_two_mm_step_missing_from_native_depth():
    result = stereo_pair(*stereo_observations())
    assert result is not None
    depth = result['depth']
    assert np.count_nonzero(depth) > 500
    top = depth[140:180, 220:260]; top = top[top>0]
    base = depth[140:180, 320:360]; base = base[base>0]
    assert len(top)>100 and len(base)>100
    assert abs(np.median(top)-.238)<.0008
    assert abs(np.median(base)-.24)<.0008
    assert np.median(base)-np.median(top) > .0012


def test_uniform_photos_do_not_invent_detail():
    assert stereo_pair(*stereo_observations(False)) is None


def test_wrong_native_scale_rejects_photo_geometry():
    a, b = stereo_observations()
    b['depth'][:] = .3
    assert stereo_pair(a, b) is None


def donor_mesh():
    vertices, triangles = [], []
    def patch(points):
        offset = len(vertices)
        vertices.extend(points.reshape(-1, 3))
        h, w = points.shape[:2]
        for row in range(h-1):
            for col in range(w-1):
                i = offset+row*w+col
                triangles.extend([[i,i+1,i+w], [i+1,i+w+1,i+w]])
    x, y = np.meshgrid(np.linspace(.0102,.03,25), np.linspace(-.0098,.0098,25))
    # Asymmetric bump ensures a generic box cannot satisfy the oracle.
    z = .001*np.exp(-((x-.023)**2+(y-.004)**2)/.000004)
    patch(np.stack((x,y,z),axis=2))
    y,z = np.meshgrid(np.linspace(-.0098,.0098,25),np.linspace(-.0195,0,25))
    patch(np.stack((.03+.0008*np.exp(-(y*y+(z+.01)**2)/.000004),y,z),axis=2))
    mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices),o3d.utility.Vector3iVector(triangles))
    mesh.compute_vertex_normals()
    return mesh


def test_counterpart_transfers_actual_bump_without_filling_unseen_geometry():
    mesh = donor_mesh()
    result = transfer_edge(mesh, {'center':np.zeros(3),'basis':np.eye(3),'width':.06},
                           {'row':1,'column':0,'type':'edge'})
    assert result is not None
    proposal, provenance = result
    assert provenance['source_cell'] == {'row':1,'column':2,'type':'edge'}
    assert len(proposal.triangles) == len(mesh.triangles)
    expected = np.asarray(mesh.vertices)*[-1,-1,1]
    np.testing.assert_allclose(np.asarray(proposal.vertices),expected,atol=1e-10)
    assert np.max(np.asarray(proposal.vertices)[:,2]) > .0009
    assert not proposal.is_watertight()


def test_flat_sticker_alone_is_not_a_counterpart():
    mesh = donor_mesh()
    mesh.remove_triangles_by_mask(np.arange(len(mesh.triangles))>=1152)
    mesh.remove_unreferenced_vertices()
    assert transfer_edge(mesh, {'center':np.zeros(3),'basis':np.eye(3),'width':.06},
                         {'row':1,'column':0,'type':'edge'}) is None


def test_grid_plane_has_metric_width_from_depth():
    k = np.array([[400.,0,199.5],[0,400.,199.5],[0,0,1.]])
    pose = np.diag([1.,-1.,-1.,1.]); pose[2,3]=.15
    frame={'depth':np.full((400,400),.15), 'k':k, 'image_k':k,'image_size':(400,400),'pose':pose}
    result=face_frame(frame, {'face_corners':[[.3,.3],[.7,.3],[.7,.7],[.3,.7]],
                              'missing_cell':{'row':1,'column':0}})
    assert result is not None
    assert abs(result['width']-.06)<1e-8
    assert result['basis'][2,2]>.99


def test_fused_mesh_preserves_photo_relief_and_native_measurements(tmp_path):
    from reversecad.photo_detail import integration_frames
    from reversecad.reconstruction import _tsdf
    originals = stereo_observations()
    detail = stereo_pair(*originals)
    # Actual native LiDAR is coarser than RGB. Independently downsample its plane.
    native = []
    for frame in originals:
        small = cv2.resize(frame['depth'].astype(np.float32), (120,80))
        resize = np.array([[.25,0,-.375],[0,.25,-.375],[0,0,1.]])
        native.append({**frame, 'depth':small, 'k':resize@frame['k'],
                       'color':cv2.resize(frame['image'],(120,80))})
    integrated, removed = integration_frames(native, [detail])
    assert removed > 100
    assert all(np.all(f['depth']==np.float32(.24)) for f in native)
    mesh = _tsdf(integrated,.00035,tmp_path)
    xyz = np.asarray(mesh.vertices)
    top = xyz[(abs(xyz[:,0])<.007) & (abs(xyz[:,1])<.007)]
    base = xyz[(xyz[:,0]>.032) & (xyz[:,0]<.04) & (abs(xyz[:,1])<.007)]
    assert len(top)>100 and len(base)>100
    assert np.median(base[:,2])-np.median(top[:,2])>.0012


def test_closed_edge_is_printable_preserves_bump_and_exports_in_mm(tmp_path):
    import trimesh
    from reversecad.printable_edge import close_edge
    geometry = {'center':np.zeros(3),'basis':np.eye(3),'width':.06}
    missing = {'row':1,'column':0,'type':'edge'}
    surface, _ = transfer_edge(donor_mesh(), geometry, missing)
    preview, report = close_edge(surface, geometry, missing, tmp_path)
    solid = trimesh.load_mesh(tmp_path/'printable_edge.stl',process=True)
    assert solid.is_watertight and solid.is_winding_consistent
    assert solid.body_count == 1 and 7000 < solid.volume < 9000
    assert abs(solid.bounds[0,2]) < 1e-6
    assert solid.extents[0] > 20.5
    assert solid.bounds[1,2] > 20.6  # donor's asymmetric 1 mm bump survives
    assert (tmp_path/'printable_edge.3mf').stat().st_size > 1000
    three_mf = trimesh.load(tmp_path/'printable_edge.3mf',force='mesh')
    np.testing.assert_allclose(three_mf.extents,solid.extents,atol=.001)
    assert report['hidden_geometry_reconstructed'] is False
    assert report['sampling_pitch_is_accuracy'] is False
    assert np.max(np.asarray(preview['vertices'])[:,2]) > .6


def test_closure_rejects_insufficient_donor_support(tmp_path):
    import pytest
    from reversecad.printable_edge import close_edge, ClosureUnavailable
    geometry = {'center':np.zeros(3),'basis':np.eye(3),'width':.06}
    missing = {'row':1,'column':0,'type':'edge'}
    surface, _ = transfer_edge(donor_mesh(),geometry,missing)
    surface.remove_vertices_by_mask(np.asarray(surface.vertices)[:,1] > -.005)
    with pytest.raises(ClosureUnavailable):
        close_edge(surface,geometry,missing,tmp_path)
    assert not (tmp_path/'printable_edge.stl').exists()
