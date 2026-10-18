import numpy as np
import pytest
from reversecad.scan_reasoning import observed_context

def preview():
    x,y=np.meshgrid(np.linspace(-10,10,15),np.linspace(-10,10,15))
    return {'unit':'mm','vertices':np.column_stack([x.ravel(),y.ravel(),np.zeros(x.size)]).tolist(),'triangles':[]}

def test_empty_never_substitutes_replacement():
    with pytest.raises(ValueError,match='no usable'):observed_context({}, {'unit':'mm','vertices':[]})

def test_observed_context_planes_and_provenance():
    r={'scan_id':'test','warnings':['inconsistent depth'],'status':'needs_input'}
    context,views=observed_context(r,preview())
    assert context['input_kind']=='observed_scan'
    assert context['geometry']['cad_valid'] is False
    assert context['geometry']['faces'][0]['surface']=='observed_plane_fit'
    assert abs(context['geometry']['faces'][0]['normal'][2])>.99
    assert context['warnings']==['inconsistent depth']
    assert 'cadquery_source' not in context
    assert len(views)==3

def test_bad_units_and_coordinates():
    p=preview();p['unit']='m'
    with pytest.raises(ValueError):observed_context({},p)
    p=preview();p['vertices'][0][0]=float('nan')
    with pytest.raises(ValueError):observed_context({},p)

def test_relations_come_from_actual_normals():
    r={'primitives':[{'id':'a','type':'plane','center_m':[0,0,0],'normal':[0,0,1]},
                     {'id':'b','type':'plane','center_m':[.01,0,0],'normal':[1,0,0]}]}
    context,_=observed_context(r,preview())
    rel=context['relationships'][0]
    assert rel['perpendicular_hypothesis']
    assert rel['center_distance_mm']==10
    assert rel['verified_symmetry'] is False

def test_endpoint_requires_owned_scan_and_consent(tmp_path):
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    with TestClient(create_app(tmp_path,'test-pair-token-123',workers_enabled=False)) as c:
        assert c.get('/v1/observed-scans').status_code==401
        h={'Authorization':'Bearer test-pair-token-123'}
        assert c.get('/v1/observed-scans',headers=h).json()=={'scans':[]}
        assert c.post('/v1/scans/unknown/reason',headers=h,json={'consent_to_send':True}).status_code==404
