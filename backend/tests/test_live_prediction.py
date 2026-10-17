import numpy as np
import pytest
from pydantic import ValidationError
from reversecad.contracts import LiveGeometryRequest
from reversecad.live_prediction import predict_live
from reversecad.prediction_cases import make_case


def snapshot(broken=True):
    m,_=make_case('planar',broken,scale=.001)
    return {'session_id':'session-1','sequence':3,'unit':'m','vertices':m.vertices.tolist(),'triangles':m.faces.tolist(),
        'camera_positions':[[.1,-.2,.6],[.3,-.2,.5],[.1,0,.5]]}


def test_live_prediction_is_in_exact_ar_world_frame_and_provisional():
    body=snapshot();response=predict_live(body)
    assert response['session_id']=='session-1' and response['sequence']==3
    assert response['status']=='provisional' and not response['damage_confirmed']
    candidate=next(c for c in response['candidates'] if c['method']=='planar_continuation')
    vertices=np.asarray(candidate['mesh']['vertices'])/1000
    original=np.asarray(body['vertices'])
    from scipy.spatial import cKDTree
    assert cKDTree(original).query(vertices)[0].max()<1e-8
    assert response['physical_fit']=='not_tested'


def test_single_view_and_complete_plane_do_not_show_live_repair():
    body=snapshot();body['camera_positions']=[body['camera_positions'][0]]*3
    assert predict_live(body)['candidates']==[]
    assert predict_live(snapshot(False))['candidates']==[]


@pytest.mark.parametrize('mutation',[
    lambda b:b.update(unit='mm'),lambda b:b['vertices'][0].__setitem__(0,float('nan')),
    lambda b:b['triangles'][0].__setitem__(0,-1),lambda b:b['triangles'][0].__setitem__(0,100000),
    lambda b:b.update(vertices=b['vertices']*20),lambda b:b.update(session_id='../other'),
])
def test_live_contract_rejects_invalid_or_unbounded_geometry(mutation):
    body=snapshot();mutation(body)
    with pytest.raises(ValidationError):LiveGeometryRequest.model_validate(body)


def test_authenticated_live_route_uses_isolated_real_worker(tmp_path):
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    token='live-test-token-123456789'
    with TestClient(create_app(tmp_path,token,workers_enabled=False)) as client:
        assert client.post('/v1/geometry/live',json=snapshot()).status_code==401
        response=client.post('/v1/geometry/live',headers={'Authorization':'Bearer '+token},json=snapshot())
        assert response.status_code==200,response.text
        assert response.json()['status']=='provisional'
        assert response.json()['session_id']=='session-1'
