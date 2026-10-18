import io
import json
import hashlib
import httpx
import pytest
from PIL import Image
from reversecad.jev import classify, review_with_jev
from reversecad.cad_review import context_from_program
from reversecad.cad_program import cube_program

CONFIG = {'api_key':'test-typesafe', 'model':'jev-1.14.0', 'timeout':1}
GROK = {'enabled':True, 'api_key':'test-grok', 'model':'test', 'timeout':1}

def photo():
    b=io.BytesIO(); Image.new('RGB',(100,200),'white').save(b,format='JPEG'); return b.getvalue()

def answer():
    return {'model':'jev-1.14.0','answers':{
        'category':{'type':'choice','choice':'twisty_puzzle','confidence':.95},
        'present':{'type':'noul','noul':.99},
        'instances':{'type':'choice','choice':'one'},
        'target_box':{'type':'box','box':{'left':.1,'top':.2,'right':.9,'bottom':.8},'confidence':.95}}}

def transport(body):
    def send(request):
        assert request.url.host=='api.typesafe.ai'
        assert request.headers['TypeSafe-Danger-Zone-Images']=='true'
        payload=json.loads(request.content)
        assert payload['assets'][payload['state']['photo']]['data_base64']
        assert 'criteria' not in payload['questions']['target_box']
        return httpx.Response(200,json=body)
    return httpx.MockTransport(send)

def test_consent():
    with pytest.raises(ValueError):classify(photo(),config=CONFIG)

def test_missing_key_no_network():
    assert classify(photo(),consent=True,config={**CONFIG,'api_key':''})['status']=='missing_api_key'

def test_frame_bound_detection():
    image=photo(); result=classify(image,consent=True,config=CONFIG,transport=transport(answer()))
    assert result['status']=='classified'
    assert result['source_sha256']==hashlib.sha256(image).hexdigest()
    assert result['source_size']==[100,200]
    assert result['used_for_metric_geometry'] is False

@pytest.mark.parametrize('field,value',[('left',float('nan')),('right',-.2),('top',.9),('bottom',True)])
def test_bad_boxes(field,value):
    body=answer();body['answers']['target_box']['box'][field]=value
    if field=='left':
        # JSON wire representation that exercises nonfinite decoder input.
        t=httpx.MockTransport(lambda _:httpx.Response(200,content=json.dumps(body)))
    else:t=transport(body)
    assert classify(photo(),consent=True,config=CONFIG,transport=t)['status']=='rejected'

@pytest.mark.parametrize('condition',['absent','ambiguous','low_confidence'])
def test_uncertain_stops_before_grok(condition):
    body=answer()
    if condition=='absent':body['answers']['present']['noul']=.1
    elif condition=='ambiguous':body['answers']['instances']['choice']='several'
    else:body['answers']['category']['confidence']=.2
    result=review_with_jev({},[photo()],consent=True,jev_config=CONFIG,jev_transport=transport(body))
    assert result['grok_called'] is False
    assert result['classification']['box'] is None

def test_full_handoff_keeps_geometry_and_jev_evidence():
    context=context_from_program(cube_program(18,1)); before=json.dumps(context)
    def grok(request):
        payload=json.loads(request.content)
        evidence=json.loads(payload['input'][1]['content'][0]['text'])
        assert evidence['object_identification']['category']=='twisty_puzzle'
        assert evidence['object_identification']['source_sha256']==hashlib.sha256(photo()).hexdigest()
        review={'summary':'Check connector.', 'observations':[], 'concerns':[], 'proposed_changes':[], 'next_views':[]}
        return httpx.Response(200,json={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(review)}]}]})
    result=review_with_jev(context,[photo()],consent=True,jev_config=CONFIG,jev_transport=transport(answer()),grok_config=GROK,grok_transport=httpx.MockTransport(grok))
    assert result['status']=='reviewed'
    assert result['geometry_changed'] is False
    assert json.dumps(context)==before

def test_invalid_response_no_secret_leak():
    t=httpx.MockTransport(lambda _:httpx.Response(401,json={'error':'test-typesafe'}))
    result=classify(photo(),consent=True,config=CONFIG,transport=t)
    assert result['error_code']=='provider_http_401'
    assert 'test-typesafe' not in json.dumps(result)

def test_paired_route_stops_on_missing_jev_key(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    import reversecad.jev as jev
    import base64
    monkeypatch.setattr(jev,'settings',lambda:{**CONFIG,'api_key':''})
    with TestClient(create_app(tmp_path,'paired-test-token-123',workers_enabled=False)) as client:
        response=client.post('/v1/cad/review',
            headers={'Authorization':'Bearer paired-test-token-123'},
            json={'program':cube_program(18,1),'use_jev':True,'consent_to_send':True,
                  'reference_images_base64':[base64.b64encode(photo()).decode()]})
    assert response.status_code==200
    assert response.json()['classification']['status']=='missing_api_key'
    assert response.json()['grok_called'] is False
