import hashlib
import numpy as np
import pytest
from reversecad.object_selection import selection_mask, consistent_views, remove_support_plane
from reversecad.reconstruction import _mask


def fixture(tmp_path):
    (tmp_path/'rgb').mkdir(); (tmp_path/'masks/objects').mkdir(parents=True)
    (tmp_path/'rgb/0.jpg').write_bytes(b'original-image')
    mask=np.zeros((20,30),np.uint8); mask[2:18,2:28]=255
    (tmp_path/'masks/objects/0.u8').write_bytes(mask.tobytes())
    frame={'frame_id':'0','rgb_path':'rgb/0.jpg','capture_region':[1/3,1/3,1/3,1/3]}
    record={'mask_path':'masks/objects/0.u8','rgb_sha256':hashlib.sha256(b'original-image').hexdigest(),'mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest()}
    target={'workflow':'capture_first_v1','confirmed':True,'frames':{'0':record}}
    return frame,target,mask


def test_object_silhouette_can_extend_outside_framing_guide(tmp_path):
    frame,target,expected=fixture(tmp_path)
    mask,source=_mask(tmp_path,frame,np.ones((20,30)),{'object_target':target})
    assert np.array_equal(mask,expected>0)
    assert mask[2,2] and not mask[0,0]
    assert 'same_instance' in source


def test_unconfirmed_view_never_falls_back_to_table_or_center(tmp_path):
    frame,target,_=fixture(tmp_path); target['frames']={}
    mask,_=selection_mask(tmp_path,frame,(20,30),target)
    assert not mask.any()
    target['confirmed']=False
    with pytest.raises(ValueError,match='Confirm'): selection_mask(tmp_path,frame,(20,30),target)


def test_mismatched_image_and_mask_hashes_fail_closed(tmp_path):
    frame,target,_=fixture(tmp_path)
    (tmp_path/'rgb/0.jpg').write_bytes(b'different-instance')
    with pytest.raises(ValueError,match='saved capture'): selection_mask(tmp_path,frame,(20,30),target)


def test_disjoint_same_category_object_is_excluded():
    rng=np.random.default_rng(3)
    cloud=rng.uniform(0,.03,(100,3))
    frames=[{'frame_id':'0','points':cloud},{'frame_id':'1','points':cloud+.001},{'frame_id':'2','points':cloud+1}]
    accepted,rejected=consistent_views(frames)
    assert [f['frame_id'] for f in accepted]==['0','1']
    assert [f['frame_id'] for f in rejected]==['2']


def test_support_plane_is_removed_without_filling_missing_contact():
    depth=np.ones((40,60)); selected=np.zeros_like(depth,dtype=bool); selected[12:28,20:40]=True
    # World Y is camera Z: all surrounding samples are a horizontal support plane.
    pose=np.eye(4); pose[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
    k=np.array([[60,0,30],[0,60,20],[0,0,1]],float)
    assert not remove_support_plane(depth,selected,k,pose).any()
    depth[15:25,23:37]=.9
    result=remove_support_plane(depth,selected,k,pose)
    assert result[18,28] and not result[12,20]


@pytest.mark.timeout(180)
def test_capture_first_package_upload_reconstruction_and_exports(tmp_path):
    import json,shutil
    from pathlib import Path
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    from test_service import upload_package,wait_job,TOKEN,HEADERS
    root=Path(__file__).resolve().parents[2]
    capture=tmp_path/'capture'
    shutil.copytree(root/'fixtures/generated/calibration_block_clean',capture)
    original_frames=(capture/'frames.jsonl').read_bytes()
    original_hashes={p.relative_to(capture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in capture.rglob('*') if p.is_file() and p.name!='checksums.json'}
    target={'workflow':'capture_first_v1','confirmed':True,'category':'other','frames':{}}
    derived=capture/'masks/objects/test';derived.mkdir(parents=True)
    for frame in map(json.loads,original_frames.splitlines()):
        name=f"masks/objects/test/{frame['frame_id']}.u8"
        mask=(np.frombuffer((capture/frame['mask_path']).read_bytes(),dtype=np.uint8)>0).astype(np.uint8)*255
        (capture/name).write_bytes(mask.tobytes())
        target['frames'][frame['frame_id']]={'mask_path':name,'mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest(),'rgb_sha256':original_hashes[frame['rgb_path']]}
    checksums={p.relative_to(capture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in capture.rglob('*') if p.is_file() and p.name!='checksums.json'}
    (capture/'checksums.json').write_text(json.dumps(checksums))
    with TestClient(create_app(tmp_path/'service',TOKEN),headers=HEADERS) as client:
        assert client.get("/v1/capabilities").json()["capture_first_masks"] is True
        scan=upload_package(client,path=capture)
        assert client.post(f'/v1/scans/{scan}/commit').status_code==200
        assert client.put(f'/v1/scans/{scan}/annotations',json={'repair_scope':'standalone_scan','object_target':target}).status_code==200
        job=client.post(f'/v1/scans/{scan}/reconstruction').json()
        result=wait_job(client,job['job_id'])
        assert result['state']=='complete',result
        artifacts={a['name']:a for a in result['result']['artifacts']}
        assert {'observed_object.stl','observed_points_mm.ply','measurements.json','scan_export.json'}<=artifacts.keys()
        for name in ['observed_object.stl','observed_points_mm.ply','measurements.json']:
            a=artifacts[name];raw=client.get('/v1/artifacts/'+a['id']).content
            assert hashlib.sha256(raw).hexdigest()==a['sha256']
    assert (capture/'frames.jsonl').read_bytes()==original_frames
    assert all(hashlib.sha256((capture/p).read_bytes()).hexdigest()==v for p,v in original_hashes.items())
