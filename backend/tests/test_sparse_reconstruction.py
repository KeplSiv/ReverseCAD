"""Physics/byte/integration checks; synthetic tests are not device acceptance."""
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
import pytest
from reversecad.sparse.capture import camera_point, decoded_records, load_packets, validate_extension, WIDE, PRIMARY_SHA256
from reversecad.sparse.decoder import decode_packet, FormatError, FIELDS, load_recording
from reversecad.sparse.registration import interpolate_pose, select_scale, build_constraints

SOURCE=Path('/Users/pranav/prelude/build/LiDARResearch/quick-tests/2026-10-18T09-43-59Z_arRulerBlack_B3C530')


def packet_bytes(xyz=(30.,40.,0.),confidence=1.,echo=0):
    values={'points':[(*xyz,0.)],'confidences':[confidence],'cameraPixels':[(2.,3.)],
        'undistortedCameraPixels':[(2.,3.)],'euclideanDistances':[float(np.linalg.norm(xyz))],
        'intensities':[2.],'signalToNoiseRatios':[10.],'bankIds':[1],'spotIds':[2],'echoIds':[echo],'flags':[0x10030]}
    offsets=[];chunks=[];offset=128
    for name,fmt,w in FIELDS:
        offsets.append(offset);v=values[name][0];chunk=struct.pack('<'+fmt*w,*(v if w>1 else [v]));chunks.append(chunk);offset+=len(chunk)
    h=[2,1,*offsets,0,offset,77]
    return struct.pack('<16Q',*h)+b''.join(chunks)


def test_decoder_preserves_unknown_bytes_and_radial_range():
    raw=packet_bytes();p=decode_packet(raw)
    assert p.to_bytes()==raw and p.fields['euclideanDistances']==(50.,)
    assert p.fields['points'][0][2]==0  # radial distance is not Z
    assert p.header[-1]==77
    with pytest.raises(FormatError):decode_packet(raw[:-1])
    corrupt=bytearray(raw);struct.pack_into('<Q',corrupt,16,8)
    with pytest.raises(FormatError):decode_packet(corrupt)


def test_original_recording_hashes_and_invalid_echoes():
    if not SOURCE.exists():pytest.skip('Original private recording is not on this machine')
    assert hashlib.sha256((SOURCE/'origin-packets.bin').read_bytes()).hexdigest()==PRIMARY_SHA256
    packets=load_recording(SOURCE)
    assert len(packets)==118
    assert all(p.to_bytes()==p.raw and p.count==84 for e,p in packets)
    records=list(decoded_records(packets))
    assert len(records)==9912
    assert not any(r['valid_for_geometry'] for r in records if r['fields']['echoIds']==2)
    assert all('flags' in r['fields'] for r in records)


def test_transform_direction_units_and_handedness():
    # camera->native rotates +90 about Z then translates [10,20,30] mm.
    T=np.array([[0,-1,0,10],[1,0,0,20],[0,0,1,30],[0,0,0,1]],float)
    cal={'T_sparse_camera':T.flatten(order='F').tolist()}
    assert np.allclose(camera_point([-190,120,330],cal),[.1,.2,.3])
    assert np.allclose(camera_point([0,0,0],cal),[-.02,.01,-.03])


def test_pose_times_forbid_extrapolation_and_long_gaps():
    poses=np.tile(np.eye(4),(2,1,1));poses[1,0,3]=.4
    p,age,_=interpolate_pose(np.array([0.,.4]),poses,.2)
    assert p[0,3]==pytest.approx(.2) and age==pytest.approx(.2)
    assert interpolate_pose([0.,.4],poses,.5)[0] is None
    assert interpolate_pose([0.,.4],poses,-.01)[0] is None
    assert interpolate_pose([0.,2.],poses,1.)[0] is None


def candidate(i,scale=2.,echo=0):
    return {'id':f'p{i}:{echo}','group':f'{i}:1:2','timestamp_s':i*.05,
       'bank':i%8,'spot':i%14,'echo':echo,'frame_ids':[f'f{i//4}',f'f{i//4+1}'],
       'scale_m_per_unit':scale,'range_m':scale*.2,'plane_unscaled':.2,
       'origin_dot_normal_m':0.,'incidence':1.,'weight':1.}


def test_geometric_consensus_does_not_pick_highest_score_or_nearest():
    rows=[candidate(i,2.+(-1)**i*.005) for i in range(40)]
    # A minority of addresses has a high score, far echo; preserve then reject it geometrically.
    rows += [{**candidate(i,20.,1),'weight':1000} for i in range(8)]
    # A near echo is equally wrong; nearest-return sorting would fail.
    rows += [candidate(i,.2,2) for i in range(8,16)]
    scale,chosen,report=select_scale(rows)
    assert scale==pytest.approx(2.,abs=.01)
    assert len(chosen)==40 and {r['echo'] for r in chosen}=={0}
    assert report['heldout_time_block']['count']>0


def test_competing_echo_models_abstain():
    with pytest.raises(ValueError,match='Competing'):
        select_scale([candidate(i,s,e) for i in range(40) for e,s in enumerate([2.,10.])])
    with pytest.raises(ValueError,match='ambiguous'):
        select_scale([candidate(i,2.,e) for i in range(40) for e in (0,1)])


def test_surface_constraint_respects_timing_and_object_mask():
    xx,yy=np.meshgrid(np.linspace(-.2,.2,41),np.linspace(-.2,.2,41))
    points=np.c_[xx.ravel(),yy.ravel(),np.ones(xx.size)]
    poses=np.tile(np.eye(4),(3,1,1));poses[:,0,3]=[-.01,0,.01]
    K=np.tile(np.array([[200,0,100],[0,200,100],[0,0,1.]]),(3,1,1))
    masks={f:np.ones((200,200),bool) for f in ['a','b','c']}
    p=decode_packet(packet_bytes((0.,0.,2000.)))
    row=list(decoded_records([({'sequence':1,'pts':.2},p)]))[0]
    args=({'T_sparse_camera':np.eye(4).flatten(order='F').tolist()},points,[0,.2,.4],poses,K,['a','b','c'],[(200,200)]*3,masks)
    result,rejected=build_constraints([row],*args)
    assert result[0]['scale_m_per_unit']==pytest.approx(2.)
    result,rejected=build_constraints([{**row,'timestamp_s':3.}],*args)
    assert not result and rejected['no_bracketed_pose_or_surface']==1
    masks['b'][:]=False
    result,rejected=build_constraints([row],*args)
    assert not result and rejected['outside_object']==1


def test_sparse_extension_not_disguised_as_depth(tmp_path):
    from reversecad.contracts import safe_asset_path
    assert safe_asset_path('sparse/origin-packets.bin')=='sparse/origin-packets.bin'
    with pytest.raises(ValueError):safe_asset_path('sparse/../secret')
    assert validate_extension(tmp_path,{},[]) is None
    with pytest.raises(ValueError,match='Unsupported'):
        validate_extension(tmp_path,{'sparse_capture':{'schema_version':2}},[])


def test_real_package_commit_and_corruption(tmp_path):
    if not SOURCE.exists():pytest.skip('Original private recording unavailable')
    from reversecad.sparse.import_prelude import import_recording
    from reversecad.service import validate_capture
    package=tmp_path/'package';import_recording(SOURCE,package)
    manifest=json.loads((package/'manifest.json').read_text())
    assert validate_capture(package,manifest,512*1024**2)['sparse_capture']['schema_version']==1
    frames=[json.loads(x) for x in (package/'frames.jsonl').read_text().splitlines()]
    assert all(f['depth_path'] and f['confidence_path'] for f in frames)
    assert all(f['sensor_observation']['arrival_timestamp_s'] is None for f in frames)
    assert all(f['tracking_state']=='limited' for f in frames)  # archived black-input diagnostic
    with (package/'sparse/origin-packets.bin').open('r+b') as file:file.write(b'corrupt!')
    with pytest.raises(ValueError,match='Checksum mismatch'):
        validate_capture(package,manifest,512*1024**2)


@pytest.mark.timeout(180)
def test_sparse_real_algorithms_through_service_and_cad(tmp_path):
    import subprocess,sys
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    from reversecad.cad import DEFAULTS
    from test_service import upload_package,wait_job,TOKEN,HEADERS
    root=Path(__file__).resolve().parents[2];package=tmp_path/'synthetic-sparse'
    subprocess.run([sys.executable,str(root/'scripts/generate_sparse_fixture.py'),str(package)],check=True,capture_output=True)
    with TestClient(create_app(tmp_path/'service',TOKEN),headers=HEADERS) as client:
        scan=upload_package(client,path=package)
        response=client.post(f'/v1/scans/{scan}/commit');assert response.status_code==200,response.text
        job=client.post(f'/v1/scans/{scan}/reconstruction').json()
        result=wait_job(client,job['job_id'])
        assert result['state']=='complete',result
        reconstruction=result['result']
        assert reconstruction['source']=='sparse_range_rgb'
        assert reconstruction['metrics']['sfm']['ARKit_pose_used'] is False
        assert reconstruction['metrics']['scale']['heldout_time_block']['count']>=4
        assert reconstruction['point_count']>100 and reconstruction['metrics']['camera_baseline_m']>.01
        assert reconstruction['metrics']['dense'].get('retained_object_points',0)>0
        assert max(reconstruction['bounds_mm']['extent']) < 130  # 100 x 60 x 40 mm analytic object, in rotated camera axes
        assets={a['name']:a for a in reconstruction['artifacts']}
        assert {'points_measurement.npz','scan_preview.json','point_support.json','camera_poses.json'}<=assets.keys()
        preview=client.get('/v1/artifacts/'+assets['scan_preview.json']['id']).json()
        assert preview['unit']=='mm' and len(preview['vertices'])>100
        # A selected mating surface comes from the actual reconstruction.
        plane=next(p for p in reconstruction['primitives'] if p['type']=='plane')
        contact={'id':'observed-face','point_m':plane['center_m'],'normal':plane['normal'],'radius_mm':8}
        assert client.put(f'/v1/scans/{scan}/annotations',json={'contacts':[contact]}).status_code==200
        hypotheses=client.post(f'/v1/scans/{scan}/candidates',json={'family':'bracket','attachment_method':'mechanical'})
        assert hypotheses.status_code==200,hypotheses.text
        assert hypotheses.json()['candidates'][0]['parameters']['leg_height']==0
        assert hypotheses.json()['questions']  # hidden mounting dimensions stay unresolved
        observations={'measurements':[{'id':'fixture-hole','name':'hole_diameter','value':4,'unit':'mm','source':'manual','confirmed':True,'critical':True,'uncertainty_mm':.1,'observation_ids':[]}]}
        assert client.put(f'/v1/scans/{scan}/annotations',json=observations).status_code==200
        request={'scan_id':scan,'family':'bracket','parameters':DEFAULTS['bracket'],'attachment_method':'mechanical',
            'mode':'manual','acknowledge_uncertainty':True,'request_id':'sparse-to-cad'}
        response=client.post('/v1/repairs',json=request);assert response.status_code==200,response.text
        complete=wait_job(client,response.json()['job_id']);assert complete['state']=='complete',complete
        assert complete['result']['validation']['physical_fit']=='not_tested'
        assert complete['result']['validation']['fit']['collision']['observed_points'] > 100
        artifacts={a['name']:a for a in complete['result']['artifacts']}
        assert {'part.step','part.stl','part.3mf','part.py','parameters.json'}<=artifacts.keys()
        for name in ['part.step','part.stl','part.3mf']:
            artifact=artifacts[name];raw=client.get('/v1/artifacts/'+artifact['id']).content
            assert hashlib.sha256(raw).hexdigest()==artifact['sha256']
