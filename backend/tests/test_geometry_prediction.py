import numpy as np
import open3d as o3d
import pytest
from reversecad.geometry_prediction import planar_continuations,predict_geometry,evaluate_patch
from reversecad.prediction_cases import make_case


def native(m):
    return o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(m.vertices),o3d.utility.Vector3iVector(m.faces))


@pytest.mark.parametrize('orientation,scale',[(0,.007),(1,.003)])
def test_continuation_recovers_held_out_surface_at_arbitrary_pose_and_scale(orientation,scale):
    observed,truth=make_case('planar',True,orientation,scale)
    candidates=planar_continuations(native(observed))
    assert len(candidates)==1
    score=evaluate_patch(candidates[0]['patch'],truth,observed)
    assert score['symmetric_p95_fraction_of_extent']<1e-5
    assert score['dimensional_extent_error_fraction']<1e-5
    # No thickness or closed replacement fabricated from a single planar patch.
    assert 'No thickness' in candidates[0]['assumptions'][1]


def test_complete_plane_outer_boundary_is_not_damage():
    m,_=make_case('planar',False)
    assert planar_continuations(native(m))==[]


def test_prediction_and_evaluation_do_not_hide_missing_surface():
    import trimesh
    truth=trimesh.creation.box([2,3,4]);observed=trimesh.creation.box([20,20,2])
    patch={'vertices':truth.vertices[:3],'faces':np.array([[0,1,2]])}
    result=evaluate_patch(patch,truth,observed)
    assert result['truth_to_prediction_p95']>1
    assert result['symmetric_p95_fraction_of_extent']>.03
