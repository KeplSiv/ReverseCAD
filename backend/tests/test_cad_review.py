import json
import httpx
import pytest
from reversecad.cad_review import context_from_program, context_from_step, describe_shape, review_context
from reversecad.cad_program import cube_program

CONFIG={'enabled':True,'api_key':'test-key','model':'test-model','timeout':2.}


def output(ids=None):
    return {'summary':'A rounded exterior with an unresolved connector.',
            'observations':[{'feature_ids':ids or ['F1'],'claim':'A CAD surface is present.','evidence_source':'cad_geometry'}],
            'concerns':['Connector is not modeled.'],'proposed_changes':[], 'next_views':['Show the underside.']}


def transport(value,status=200):
    def respond(request):
        payload=json.loads(request.content)
        assert payload['store'] is False
        assert payload['text']['format']['strict'] is True
        assert request.url.host=='api.x.ai'
        return httpx.Response(status,json={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]})
    return httpx.MockTransport(respond)


@pytest.fixture(scope='module')
def context():return context_from_program(cube_program(18.,1.))


def test_program_is_compiled_and_measured(context):
    assert context['geometry']['cad_valid']
    assert context['geometry']['solid_count']==1
    assert 0<context['geometry']['volume_mm3']<18**3
    assert 'rect(side_mm, side_mm)' in context['cadquery_source']
    assert context['geometry']['physical_fit']=='not_tested'
    assert len(context['operation_validation'])==3


def test_arbitrary_operation_not_executed():
    p=cube_program(18,1);p['operations'].append({'op':'exec','source':'raise Exception()'})
    with pytest.raises(ValueError,match='Unsupported'):context_from_program(p)


def test_step_extracts_real_hole_topology(tmp_path):
    import cadquery as cq
    shape=cq.Workplane('XY').box(20,20,10).faces('>Z').workplane().hole(4)
    path=tmp_path/'part.step';cq.exporters.export(shape,str(path))
    context=context_from_step(path);g=context['geometry']
    assert g['volume_mm3']==pytest.approx(4000-3.141592653589793*4*10,abs=.001)
    cylinders=[f for f in g['faces'] if f['surface']=='CYLINDER']
    assert len(cylinders)==1 and cylinders[0]['radius_mm']==pytest.approx(2)
    assert all(len(e['faces'])>=1 for e in g['shared_edges'])
    assert g['construction_history_recovered'] is False


def test_consent_required_before_network(context):
    with pytest.raises(ValueError,match='consent'):review_context(context,config=CONFIG)


def test_review_preserves_geometry_and_binds_input(context):
    before=json.dumps(context)
    result=review_context(context,consent=True,config=CONFIG,transport=transport(output()))
    assert result['status']=='reviewed'
    assert result['geometry_changed'] is False
    assert len(result['context_sha256'])==64
    assert json.dumps(context)==before


def test_unknown_face_is_rejected(context):
    result=review_context(context,consent=True,config=CONFIG,transport=transport(output(['F9999'])))
    assert result['status']=='rejected'


def test_provider_errors_do_not_leak_body_or_key(context):
    result=review_context(context,consent=True,config=CONFIG,transport=transport({'secret':'test-key'},401))
    assert result['error_code']=='provider_http_401'
    assert 'test-key' not in json.dumps(result)


def test_missing_key_does_not_call_provider(context):
    assert review_context(context,consent=True,config={**CONFIG,'api_key':''})['status']=='missing_api_key'


def test_route_requires_pairing_and_consent(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    import reversecad.cad_review as module
    monkeypatch.setattr(module,'settings',lambda:{**CONFIG,'enabled':False})
    with TestClient(create_app(tmp_path,'test-pairing-secret-123',workers_enabled=False)) as client:
        data={'program':cube_program(18,1),'consent_to_send':True}
        assert client.post('/v1/cad/review',json=data).status_code==401
        headers={'Authorization':'Bearer test-pairing-secret-123'}
        assert client.post('/v1/cad/review',json={**data,'consent_to_send':False},headers=headers).status_code==422
        r=client.post('/v1/cad/review',json=data,headers=headers)
        assert r.status_code==200 and r.json()['status']=='disabled'


def test_unsupported_numerical_proposal_is_withheld(context):
    reply=output();reply['proposed_changes']=[{'action':'pocket','feature_ids':['F1'],'parameter':'depth','value_mm':5,'rationale':'Invented depth'}]
    result=review_context(context,consent=True,config=CONFIG,transport=transport(reply))
    assert result['numeric_proposals_withheld']==1
    assert result['review']['proposed_changes'][0]['value_mm'] is None
    assert result['review_verified'] is False


def test_model_views_render_from_actual_geometry():
    import cadquery as cq
    from reversecad.cad_review import render_shape
    from PIL import Image
    import io
    images=render_shape(cq.Workplane('XY').box(10,20,30).val())
    assert len(images)==3
    assert all(Image.open(io.BytesIO(b)).size==(768,768) for b in images)
