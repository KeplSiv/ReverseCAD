import base64
import json
import cv2
import httpx
import numpy as np
import pytest
from reversecad.visual_adviser import GrokAdviser, VisualPlan, candidate_images, env_values


@pytest.fixture
def config():
    return {'enabled':True,'api_key':'test-secret-do-not-log','model':'test-vision-model','timeout':2}


@pytest.fixture
def option(tmp_path):
    image=np.full((400,600,3),[20,70,120],np.uint8)
    cv2.imwrite(str(tmp_path/'photo.png'),image)
    frame={'frame_id':'1','rgb_path':'photo.png','capture_region':[.2,.2,.6,.6],
           'orientation':'portrait','pose':np.eye(4)}
    annotation={'face_corners':[[.3,.3],[.7,.3],[.7,.7],[.3,.7]]}
    return {'views':[(frame,annotation)],'seed':{'missing_cells':[(0,0),(0,1)]},
            'donor_pools':{'corner':[{'source_cell':{'column':2,'row':0,'type':'corner'},'frame_ids':['1','2']}],
                           'edge':[{'source_cell':{'column':2,'row':1,'type':'edge'},'frame_ids':['1','2']}]}}


def plan(**changes):
    return {'selected_candidate_id':'C1','donor_choices':[{'target_id':'C1.F1','donor_id':'C1.F3'},
                                                        {'target_id':'C1.F4','donor_id':'C1.F6'}],
            'concerns':[],'next_view':'below','explanation':'Two possible gaps; inspect their lower boundaries.',**changes}


def provider_response(advice):
    return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(advice)}]}]}


def test_valid_plan_is_structured_bounded_and_has_no_measurement_or_execution_tools(config,option,tmp_path):
    requests=[]
    def respond(request):
        requests.append(request);return httpx.Response(200,json=provider_response(plan()))
    adviser=GrokAdviser(config,httpx.MockTransport(respond));result=adviser.choose(tmp_path,[option])
    assert result['status']=='available'
    body=json.loads(requests[0].content)
    assert body['store'] is False and 'tools' not in body
    assert body['text']['format']['strict'] and body['max_output_tokens']<=2000
    assert 'dimensions' not in body['text']['format']['schema']['properties']
    assert config['api_key'] not in json.dumps(result)


@pytest.mark.parametrize('changes',[
    {'selected_candidate_id':'C99'},
    {'donor_choices':[{'target_id':'C1.F1','donor_id':'C1.F6'},{'target_id':'C1.F4','donor_id':'C1.F3'}]},
    {'donor_choices':[{'target_id':'C1.F1','donor_id':'C1.F3'}]*2},
    {'selected_candidate_id':None},
])
def test_invented_or_incompatible_references_cannot_control_geometry(config,option,tmp_path,changes):
    adviser=GrokAdviser(config,httpx.MockTransport(lambda r:httpx.Response(200,json=provider_response(plan(**changes)))))
    result=adviser.choose(tmp_path,[option])
    assert result['status']=='invalid_response' and 'advice' not in result


def test_grayscale_upload_contains_only_pixels_inside_capture_box(option,tmp_path):
    def encoded():return candidate_images(tmp_path,option,'C1')[1]['image_url']
    first=encoded()
    image=cv2.imread(str(tmp_path/'photo.png'));image[:80,:]=[250,20,200];image[:,480:]=[200,255,20]
    cv2.imwrite(str(tmp_path/'photo.png'),image)
    assert encoded()==first
    data=base64.b64decode(first.split(',',1)[1]);gray=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_UNCHANGED)
    assert gray.ndim==2 and max(gray.shape)<=768


@pytest.mark.parametrize('enabled,key,status',[(False,'test','disabled'),(True,'','missing_api_key')])
def test_disabled_or_missing_key_never_calls_provider(config,option,tmp_path,enabled,key,status):
    def forbidden(r):pytest.fail('Unexpected network request')
    config.update(enabled=enabled,api_key=key)
    adviser=GrokAdviser(config,httpx.MockTransport(forbidden))
    assert adviser.choose(tmp_path,[option])['status']==status


def test_auth_failure_is_redacted_and_not_retried_for_review(config,option,tmp_path):
    count=[]
    def respond(r):
        count.append(1);return httpx.Response(400,json={'error':'Incorrect API key provided '+config['api_key']})
    adviser=GrokAdviser(config,httpx.MockTransport(respond))
    result=adviser.choose(tmp_path,[option])
    second=adviser.request('review',VisualPlan,{},[])
    assert result['error_code']==second['error_code']=='provider_authentication_failed'
    assert len(count)==1 and config['api_key'] not in json.dumps([result,second])


def test_timeout_preserves_no_provider_exception_text(config,option,tmp_path):
    def timeout(r):raise httpx.ReadTimeout(config['api_key'])
    adviser=GrokAdviser(config,httpx.MockTransport(timeout))
    result=adviser.choose(tmp_path,[option])
    assert result['error_code']=='provider_timeout' and config['api_key'] not in json.dumps(result)


def test_incomplete_or_malformed_answer_is_not_a_plan(config,option,tmp_path):
    adviser=GrokAdviser(config,httpx.MockTransport(lambda r:httpx.Response(200,json={'status':'incomplete','output':[]})))
    assert adviser.choose(tmp_path,[option])['status']=='invalid_response'


def test_review_cannot_invent_target_ids(config,tmp_path):
    for name in ['cube_original.jpg','cube_overlay.jpg']:cv2.imwrite(str(tmp_path/name),np.zeros((30,30),np.uint8))
    response={'verdict':'mismatch','problematic_target_ids':['invented'],'next_view':'left','explanation':'Mismatch.'}
    adviser=GrokAdviser(config,httpx.MockTransport(lambda r:httpx.Response(200,json=provider_response(response))))
    assert adviser.review(tmp_path,['C1.F1'])['status']=='invalid_response'


def test_model_selection_cannot_bypass_failed_solid_validation(tmp_path,monkeypatch):
    from reversecad import face_first
    baseline={'seed':{'missing_cells':[(0,0)]},'profiles':[],'donor_pools':{},'face':{}}
    selected={**baseline,'face':{'bad':True}}
    class Adviser:
        config={'apply_selections':True}
        def choose(self,*args):return {'status':'available','advice':plan(selected_candidate_id='C2',donor_choices=[])}
    def rejected(*args):raise ValueError('Not a closed solid')
    monkeypatch.setattr(face_first,'make_pieces',rejected)
    chosen,report=face_first.select_visual_candidate(Adviser(),[baseline,selected],tmp_path,tmp_path/'out')
    assert chosen is baseline and not report['selection_applied']
    assert report['status']=='geometry_rejected_selection'


def test_dotenv_is_data_and_accepts_xai_without_shell_evaluation(tmp_path):
    env=tmp_path/'.env';env.write_text('XAI_API_KEY="$(do-not-run)"\nREVERSECAD_GROK_ENABLED=true\n')
    assert env_values(env)['XAI_API_KEY']=='$(do-not-run)'
    env.write_text('PATH=/bad\n')
    with pytest.raises(ValueError):env_values(env)


def test_model_cannot_silently_drop_a_supported_repair_on_another_face(tmp_path):
    from reversecad.face_first import select_visual_candidate
    baseline={'seed':{'missing_cells':[(0,0),(0,1)]},'profiles':[{},{}]}
    alternate={'seed':{'missing_cells':[(0,0)]},'profiles':[{}]}
    class Adviser:
        def choose(self,*args):return {'status':'available','advice':plan(selected_candidate_id='C2',donor_choices=[])}
    chosen,report=select_visual_candidate(Adviser(),[baseline,alternate],tmp_path,tmp_path/'out')
    assert chosen is baseline and report['error_code']=='would_drop_supported_repairs'


def test_model_concerns_keep_geometry_baseline(tmp_path):
    from reversecad.face_first import select_visual_candidate
    baseline={'seed':{'missing_cells':[(0,0)]},'profiles':[{}]}
    alternate={'seed':{'missing_cells':[(2,2)]},'profiles':[{}]}
    class Adviser:
        def choose(self,*args):return {'status':'available','advice':plan(selected_candidate_id='C2',donor_choices=[],concerns=['Donor does not match.'])}
    chosen,report=select_visual_candidate(Adviser(),[baseline,alternate],tmp_path,tmp_path/'out')
    assert chosen is baseline and report['error_code']=='model_selection_has_unresolved_concerns'


def test_advisory_default_does_not_replace_geometry(tmp_path):
    from reversecad.face_first import select_visual_candidate
    baseline={'seed':{'missing_cells':[(0,0)]},'profiles':[{}]}
    alternate={'seed':{'missing_cells':[(2,2)]},'profiles':[{}]}
    class Adviser:
        config={'apply_selections':False}
        def choose(self,*args):return {'status':'available','advice':plan(selected_candidate_id='C2',donor_choices=[])}
    chosen,report=select_visual_candidate(Adviser(),[baseline,alternate],tmp_path,tmp_path/'out')
    assert chosen is baseline and report['suggestion_only'] and not report['selection_applied']


def test_long_prose_is_bounded_without_changing_feature_ids(config,option,tmp_path):
    adviser=GrokAdviser(config,httpx.MockTransport(lambda r:httpx.Response(200,json=provider_response(plan(explanation='x'*1000)))))
    result=adviser.choose(tmp_path,[option])
    assert result['status']=='available' and len(result['advice']['explanation'])==400
    assert result['advice']['donor_choices']==plan()['donor_choices']


def test_request_budget_never_sends_a_third_call(config):
    calls=[]
    def respond(r):calls.append(1);return httpx.Response(200,json=provider_response(plan()))
    adviser=GrokAdviser(config,httpx.MockTransport(respond))
    assert adviser.request('plan',VisualPlan,{},[])['status']=='available'
    assert adviser.request('review',VisualPlan,{},[])['status']=='available'
    assert adviser.request('retry',VisualPlan,{},[])['status']=='budget_exhausted'
    assert len(calls)==2
