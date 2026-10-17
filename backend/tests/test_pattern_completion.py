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
