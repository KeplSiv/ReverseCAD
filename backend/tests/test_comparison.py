import json
import numpy as np
import cv2
import pytest
from reversecad.planar_tracking import track_region
from reversecad.comparison import compare_reconstructions,copy_result,base_variant


def test_planar_tracking_recovers_known_perspective_transform():
    rng=np.random.default_rng(22)
    image=np.zeros((400,600),np.uint8)
    image[80:320,150:450]=rng.integers(20,235,(240,300),dtype=np.uint8)
    image=cv2.GaussianBlur(image,(3,3),.5)
    corners=np.float32([[150,80],[450,80],[450,320],[150,320]])
    target=corners+np.float32([[8,6],[11,9],[7,5],[6,3]])
    h=cv2.getPerspectiveTransform(corners,target)
    other=cv2.warpPerspective(image,h,(600,400))
    found,evidence=track_region(image,other,corners)
    np.testing.assert_allclose(found,target,atol=1)
    assert evidence['inliers']>=12 and evidence['coverage_fraction']>.20


def test_planar_tracking_rejects_uniform_images_and_unrelated_views():
    blank=np.zeros((400,600),np.uint8)
    corners=np.float32([[150,80],[450,80],[450,320],[150,320]])
    assert track_region(blank,blank,corners) is None
    rng=np.random.default_rng(23)
    a=rng.integers(0,255,blank.shape,dtype=np.uint8)
    b=rng.integers(0,255,blank.shape,dtype=np.uint8)
    assert track_region(a,b,corners) is None


def test_model_failure_preserves_other_comparison_results(tmp_path,monkeypatch):
    import reversecad.reconstruction as reconstruction
    import reversecad.comparison as comparison
    monkeypatch.setattr(reconstruction,'_load_package',lambda scan:({'scan_id':'same-scan'},[],{}))
    monkeypatch.setattr(reconstruction,'_prepare',lambda *args:([],[],[],[]))
    monkeypatch.setattr(comparison,'learned_outputs',lambda *args:(_ for _ in ()).throw(RuntimeError('model unavailable')))
    (tmp_path/'scan_preview.json').write_text(json.dumps({'vertices':[[0,0,0]],'triangles':[],'unit':'mm'}))
    result=compare_reconstructions(tmp_path,tmp_path,{'status':'needs_input','input_revision':{'manifest_sha256':'unchanged'},'counterpart':{'reason':'native failure'}})
    report=result['comparison']
    assert len(report['variants'])==6
    assert report['verified_winner'] is None
    assert report['scan_id']=='same-scan'
    assert report['variants'][0]['scan_preview']=='scan_preview.json'
    assert all(not v['printable'] for v in report['variants'])
    assert 'Model setup failed' in report['variants'][-1]['message']
    assert json.loads((tmp_path/'comparison.json').read_text())['input_revision']['manifest_sha256']=='unchanged'


def test_incomplete_print_files_do_not_become_publishable(tmp_path):
    import trimesh
    source=tmp_path/'source';source.mkdir()
    mesh=trimesh.creation.box([1,2,3]);mesh.export(source/'printable_edge.stl')
    variant=base_variant('example','Example','test')
    with pytest.raises((ValueError,OSError)):
        copy_result(source,tmp_path,variant,{'watertight_replacement':True})
    assert not variant['printable'] and not variant['print_files']


def test_comparison_request_is_part_of_idempotent_input(tmp_path):
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    from test_service import TOKEN,HEADERS,upload_package
    with TestClient(create_app(tmp_path,TOKEN,workers_enabled=False),headers=HEADERS) as client:
        scan=upload_package(client,path=__import__('pathlib').Path('fixtures/sample_scan'))
        assert client.post(f'/v1/scans/{scan}/commit').status_code==200
        url=f'/v1/scans/{scan}/reconstruction'
        first=client.post(url,json={'request_id':'compare-request','compare_methods':True})
        assert first.status_code==200
        assert client.post(url,json={'request_id':'compare-request','compare_methods':True}).json()['job_id']==first.json()['job_id']
        assert client.post(url,json={'request_id':'compare-request','compare_methods':False}).status_code==409
