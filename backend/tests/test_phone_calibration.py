import json
import cv2
import numpy as np
import pytest

from reversecad.phone_calibration import fit_tracks, compatible, rectify_observations, calibration_for_scan


def observations(planar=False, bad_holdout=False):
    rng=np.random.default_rng(27)
    points=rng.uniform([-.13,-.1,.35],[.13,.1,.7],(180,3))
    if planar: points[:,2]=.5
    k=np.array([[760.,0.,320.],[0.,760.,240.],[0.,0.,1.]])
    truth=np.array([.013,-.032,.011])
    angle=np.array([.06,-.02,.01]);r=cv2.Rodrigues(angle)[0];t=np.array([.008,.003,.025])
    pose=np.eye(4);pose[:3,:3]=r;pose[:3,3]=t
    cloud=points@r.T+t
    camera_list=[];pixels=[];all_points=[];ids=[];held=[]
    for i,center in enumerate([[-.07,0,0],[0,.025,0],[.07,0,0]]):
        tc=np.eye(4);tc[:3,3]=-np.array(center)
        camera_list.append({'k':k,'camera_from_object':tc})
        q=cloud-np.array(center);xy=q[:,:2]/q[:,2,None];radius=(xy*xy).sum(1)
        distorted=xy*(1+truth[1]*radius+truth[2]*radius**2)[:,None]
        uv=distorted*(760*np.exp(truth[0]))+[320,240]
        hold=np.arange(len(points))%4==0
        if bad_holdout: uv[hold]+=rng.normal(0,18,(hold.sum(),2))
        else: uv+=rng.normal(0,.03,uv.shape)
        pixels.extend(uv);all_points.extend(points);ids.extend([i]*len(points));held.extend(hold)
    return np.array(all_points),np.array(ids),np.array(pixels),camera_list,np.array(held),pose,truth


def test_recovers_front_to_rear_rigid_pose_and_rejects_heldout_leakage():
    points,ids,uv,cams,hold,initial,truth=observations()
    result=fit_tracks(points,ids,uv,cams,hold,initial)
    assert result['candidate_image_pass']
    assert result['candidate_heldout']['median_px']<.15
    assert result['candidate_parameters'][6]==pytest.approx(truth[0],abs=.003)
    assert np.linalg.norm(result['candidate_parameters'][3:6]-initial[:3,3])<.002
    uv2=uv.copy();uv2[hold]+=35
    rejected=fit_tracks(points,ids,uv2,cams,hold,initial)
    assert not rejected['candidate_image_pass']
    # Changing held-out observations cannot change the fitted candidate.
    np.testing.assert_allclose(result['candidate_parameters'],rejected['candidate_parameters'],atol=1e-8)


def test_planar_scene_registers_without_inventing_lens_corrections():
    points,ids,uv,cams,hold,initial,_=observations(planar=True)
    result=fit_tracks(points,ids,uv,cams,hold,initial)
    assert not result['identifiable']
    assert result['candidate_parameters'] is None
    assert not result['candidate_image_pass']


def frame_and_profile():
    frame={'rgb_width':64,'rgb_height':48,'intrinsics_width':64,'intrinsics_height':48,
           'depth_calibration_mode':'native_arkit','intrinsics':[60.,0.,0.,0.,60.,0.,32.,24.,1.]}
    from reversecad.phone_calibration import signature
    profile={'schema_version':1,'correction_applied':True,'correction':[.01,-.02,.002],
             'camera_signature':signature(frame),'factory_intrinsics_range':[frame['intrinsics'],frame['intrinsics']]}
    return frame,profile


def test_configuration_mismatch_does_not_reuse_profile():
    frame,profile=frame_and_profile()
    assert compatible(profile,[frame])
    assert not compatible(profile,[{**frame,'rgb_width':128}])
    moved=dict(frame);moved['intrinsics']=[62.,0,0,0,62.,0,32,24,1]
    assert not compatible(profile,[moved])


def test_rectification_preserves_originals_and_depth_holes():
    frame,profile=frame_and_profile()
    depth=np.full((24,32),.5,np.float32);depth[10:14,13:17]=0
    valid=depth>0;original=depth.copy();rgb=np.zeros((48,64,3),np.uint8);color=np.zeros((24,32,3),np.uint8)
    output=rectify_observations(frame,depth,rgb,color,valid,valid,valid,profile)
    assert np.array_equal(depth,original)
    assert frame['intrinsics'][0]==60
    assert (output[1][10:14,13:17]==0).all()
    assert set(np.unique(output[1]))<={0.,.5}
    assert output[0]['intrinsics'][0]>60


def test_missing_same_object_evidence_retains_session(tmp_path):
    root=tmp_path/'scan';out=tmp_path/'out';(root/'calibration').mkdir(parents=True);out.mkdir()
    (root/'calibration/setup.json').write_text(json.dumps({'same_object_required':True,'reference_archive_sha256':'a'*64}))
    result=calibration_for_scan(root,[],{},out)
    assert not result['reference_registered']
    assert not result['correction_applied']
    assert (root/'calibration/setup.json').is_file()
    assert (out/'phone-calibration.json').is_file()


def test_saved_capture_end_to_end_registration_and_hash_binding(tmp_path):
    import hashlib
    from reversecad.geometry import AR_TO_CV
    root=tmp_path/'scan';out=tmp_path/'out';front=root/'calibration/front'
    front.mkdir(parents=True);out.mkdir();(root/'rgb').mkdir();(root/'depth').mkdir()
    w,h=640,480;dw,dh=320,240
    rng=np.random.default_rng(4)
    texture=rng.integers(0,256,(h,w),dtype=np.uint8)
    texture=cv2.GaussianBlur(texture,(3,3),0)
    for _ in range(220):
        x,y=rng.integers([5,5],[w-5,h-5]);cv2.circle(texture,(int(x),int(y)),int(rng.integers(2,8)),int(rng.integers(0,256)),-1)
    cv2.imwrite(str(front/'front.png'),texture)
    yy,xx=np.mgrid[:dh,:dw];u=xx*2;v=yy*2;z=np.where(u<w/2,.45,.7)
    points=np.stack([(u-w/2)/500*z,(v-h/2)/500*z,z,np.full_like(z,.005)],axis=-1).astype('<f4')
    points.tofile(front/'points.f32')
    evidence={'schema_version':1,'depth_kind':'optical_axis_z','point_layout':'little_endian_float32_xyz_sigma_z',
              'width':dw,'height':dh,'rgb_width':w,'rgb_height':h,'points':'points.f32','rgb':'front.png',
              'assets':{n:hashlib.sha256((front/n).read_bytes()).hexdigest() for n in ['points.f32','front.png']}}
    (front/'reference-evidence.json').write_text(json.dumps(evidence))
    digest=hashlib.sha256((front/'reference-evidence.json').read_bytes()).hexdigest()
    (root/'calibration/setup.json').write_text(json.dumps({'same_object_required':True,'evidence_sha256':digest,'reference_archive_sha256':'a'*64}))
    (root/'calibration/object-link.json').write_text(json.dumps({'same_instance':True,'evidence_sha256':digest}))
    frames=[]
    yy,xx=np.mgrid[:h,:w]
    for i,center in enumerate([-.025,0.,.025,.045]):
        focal=507.5
        # Intersect rays with two static, differently distant textured half-planes.
        rx=(xx-w/2)/focal;ry=(yy-h/2)/focal
        plane=np.where(rx*.45+center<0,.45,.7)
        worldx=rx*plane+center;worldy=ry*plane
        mx=(worldx/plane*500+w/2).astype('float32');my=(worldy/plane*500+h/2).astype('float32')
        rgb=cv2.remap(texture,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        cv2.imwrite(str(root/f'rgb/{i}.png'),rgb)
        dep=plane[::2,::2].astype('<f4');dep.tofile(root/f'depth/{i}.f32')
        pose=np.eye(4);pose[0,3]=center;pose=pose@AR_TO_CV
        frames.append({'frame_id':str(i),'segment_id':'s','tracking_state':'normal','quality':{'accepted':True},
                       'depth_path':f'depth/{i}.f32','depth_width':dw,'depth_height':dh,'rgb_path':f'rgb/{i}.png',
                       'rgb_width':w,'rgb_height':h,'intrinsics_width':w,'intrinsics_height':h,'depth_calibration_mode':'native_arkit',
                       'intrinsics':[500.,0,0,0,500.,0,320.,240.,1.],'T_world_camera':pose.flatten(order='F').tolist()})
    result=calibration_for_scan(root,frames,{'s':np.eye(4)},out)
    assert result['reference_registered'],result
    assert result['heldout_observations']>=20
    assert result['factory_depth_agreement']['median_mm']<10
    assert hashlib.sha256((front/'reference-evidence.json').read_bytes()).hexdigest()==digest
    (front/'points.f32').write_bytes(b'changed')
    rejected=calibration_for_scan(root,frames,{'s':np.eye(4)},out)
    assert not rejected['reference_registered']
    assert 'checksum' in rejected['guidance'].lower()
