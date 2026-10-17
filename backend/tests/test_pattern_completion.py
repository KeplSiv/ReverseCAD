import numpy as np
import pytest
from reversecad.pattern_completion import candidate_from_transform


def test_transfer_preserves_small_ridge_and_visible_recess_in_arbitrary_orientation():
    # A non-cubic donor patch with a 0.2 mm ridge and a 0.4 mm recess.
    v=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,.2],[2,0,0],[2,1,-.4]])
    f=np.array([[0,1,2],[1,3,2],[1,4,3],[4,5,3]])
    theta=.71;r=np.array([[np.cos(theta),0,np.sin(theta)],[0,1,0],[-np.sin(theta),0,np.cos(theta)]])
    t=np.eye(4);t[:3,:3]=r;t[:3,3]=[10,3,2]
    patch=candidate_from_transform(v,f,t,.05)
    recovered=(patch['vertices']-t[:3,3])@r
    np.testing.assert_allclose(recovered,v[patch['source_vertex_indices']],atol=1e-12)
    assert len(patch['faces'])==len(f)
    assert recovered[:,2].max()==pytest.approx(.2)
    assert recovered[:,2].min()==pytest.approx(-.4)


def test_existing_geometry_not_returned_and_scale_changes_rejected():
    v=np.array([[0,0,0],[1,0,0],[0,1,.1]])
    assert candidate_from_transform(v,[[0,1,2]],np.eye(4),.01) is None
    t=np.eye(4);t[0,0]=2
    with pytest.raises(ValueError):candidate_from_transform(v,[[0,1,2]],t,.01)


def test_discovers_missing_ridged_stud_without_object_category_or_size_template():
    import trimesh
    import open3d as o3d
    from reversecad.pattern_completion import propose_patterns
    base=trimesh.creation.cylinder(radius=10,height=2,sections=96)
    parts=[base];expected=None
    for i in range(8):
     stud=trimesh.util.concatenate([trimesh.creation.cylinder(radius=1.2,height=3,sections=24),trimesh.creation.cylinder(radius=1.6,height=.4,sections=24)])
     stud.apply_translation([12*np.cos(i*np.pi/4),12*np.sin(i*np.pi/4),0])
     if i==0:expected=stud
     else:parts.append(stud)
    mesh=trimesh.util.concatenate(parts)
    o=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices),o3d.utility.Vector3iVector(mesh.faces))
    c,report=propose_patterns(o);assert report['status']=='hypotheses_need_review'
    from scipy.spatial import cKDTree
    assert c,'No repeated part proposal found'
    assert min(np.percentile(cKDTree(expected.vertices).query(p['patch']['vertices'])[0],90) for p in c)<.5


import trimesh

def box(size,at):
 m=trimesh.creation.box(size);m.apply_translation(at);v,f=trimesh.remesh.subdivide(m.vertices,m.faces);v,f=trimesh.remesh.subdivide(v,f);return trimesh.Trimesh(v,f)
def case(kind,broken=True):
 if kind=='rail':
  base=box([60,10,2],[0,0,0]);features=[box([2,8,5],[x,0,3]) for x in [-24,-12,0,12,24]];missing=2
 elif kind=='bracket':
  base=trimesh.util.concatenate([box([40,8,2],[0,0,0]),box([8,4,8],[0,-2,5]),box([4,4,3],[0,3,2])]);features=[]
  for x in [-15,15]:
   m=trimesh.creation.cylinder(radius=3,height=5,sections=32);m.apply_translation([x,1,3]);features.append(m)
  missing=1
 else:
  base=trimesh.creation.cylinder(radius=10,height=2,sections=64);features=[]
  for i in range(8):
   m=trimesh.util.concatenate([trimesh.creation.cylinder(radius=1.2,height=3,sections=24),trimesh.creation.cylinder(radius=1.6,height=.4,sections=24)]);m.apply_translation([12*np.cos(i*np.pi/4),12*np.sin(i*np.pi/4),0]);features.append(m)
  missing=0
 return trimesh.util.concatenate([base]+[m for i,m in enumerate(features) if not broken or i!=missing]),features[missing]


@pytest.mark.parametrize("kind", ["radial", "rail", "bracket"])
@pytest.mark.parametrize("broken", [True, False])
def test_general_patterns_and_complete_object_negatives(kind, broken):
    import open3d as o3d
    from scipy.spatial import cKDTree
    from reversecad.pattern_completion import propose_patterns
    mesh, truth = case(kind, broken)
    # Rotate, scale, and translate all cases: no axis or fixed size template.
    from scipy.spatial.transform import Rotation
    rotation = Rotation.from_rotvec([.3, -.5, .2]).as_matrix()
    mesh.vertices = (mesh.vertices @ rotation.T) * .007 + [.1, -.2, .3]
    truth.vertices = (truth.vertices @ rotation.T) * .007 + [.1, -.2, .3]
    native = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices),
                                     o3d.utility.Vector3iVector(mesh.faces))
    candidates, report = propose_patterns(native)
    assert report['printable'] is False
    if not broken:
        assert not candidates
    else:
        assert candidates
        errors = [np.percentile(cKDTree(truth.vertices).query(c['patch']['vertices'])[0], 90)
                  for c in candidates]
        assert min(errors) < .007 * .5


def test_triangle_interior_is_observed_even_without_nearby_vertices():
    v = np.array([[0,0,0], [10,0,0], [0,10,0], [1,1,0], [2,1,0], [1,2,0]])
    t = np.eye(4); t[:3,3] = [1,1,0]
    patch = candidate_from_transform(v, [[0,1,2], [3,4,5]], t, .01)
    assert patch is None  # translated small triangle lies on the large face


def test_reflection_reverses_winding_and_preserves_relief():
    v = np.array([[0,0,0], [1,0,0], [0,1,.2]])
    t = np.eye(4); t[0,0] = -1; t[0,3] = 10
    patch = candidate_from_transform(v, [[0,1,2]], t, .01)
    np.testing.assert_array_equal(patch['faces'], [[2,1,0]])
    np.testing.assert_allclose(patch['vertices'], v @ t[:3,:3].T + t[:3,3])


def test_hypothesis_export_preserves_units_and_donor_provenance(tmp_path, monkeypatch):
    import json
    import reversecad.pattern_completion as module
    candidate = {'patch': {'vertices': np.array([[.001,0,0],[0,.002,0],[0,0,.003]]),
                           'faces': np.array([[0,1,2]]),
                           'source_vertex_indices': np.array([3,4,5]),
                           'source_triangle_indices': np.array([7])},
                 'transform': np.eye(4), 'pattern_kind': 'reflection',
                 'overlap_fraction': .9, 'matched_surface_rmse': .0001,
                 'normal_agreement': .99}
    monkeypatch.setattr(module, 'propose_patterns', lambda mesh: ([candidate], {'printable': False}))
    report = module.export_pattern_hypotheses(None, tmp_path, scale=2)
    preview = json.loads((tmp_path / report['candidates'][0]['preview']).read_text())
    assert preview['unit'] == 'mm'
    np.testing.assert_allclose(preview['vertices'], [[2,0,0],[0,4,0],[0,0,6]])
    assert preview['source_triangle_indices'] == [7]
    assert report['printable'] is False
