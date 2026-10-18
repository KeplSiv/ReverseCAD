import copy
import json
from pathlib import Path
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from reversecad.multicamera import Trajectory, extrinsic, validate_frame
from reversecad.contracts import CaptureFrame, ScanManifest, safe_asset_path
from reversecad.service import validate_capture


def test_factory_baseline_units_and_direction():
    e=np.eye(4)[:3];e[0,3]=20
    c={'tele':{'from_wide_extrinsics_column_major_mm':e.T.ravel().tolist()}}
    actual=extrinsic(c,'tele')
    assert actual[0,3]==pytest.approx(.02)
    assert (np.linalg.inv(actual)@np.array([0,0,.5,1]))[0]==pytest.approx(-.02)
    c['tele']['from_wide_extrinsics_column_major_mm'][-3]=2000
    with pytest.raises(ValueError):extrinsic(c,'tele')


def test_exposure_pose_interpolation_never_extrapolates_or_crosses_tracking_gaps():
    a=np.eye(4);b=np.eye(4);b[:3,:3]=Rotation.from_euler('y',.1).as_matrix();b[0,3]=.02
    rows=[{'tracked':True,'time_s':t,'pose':p.T.ravel().tolist()} for t,p in [(0,a),(.2,b)]]
    trajectory=Trajectory(rows)
    assert trajectory.at(.1)[0,3]==pytest.approx(.01)
    assert trajectory.at(-.001) is None
    assert trajectory.at(.201) is None
    rows[-1]['time_s']=1
    assert Trajectory(rows).at(.1) is None


def test_capture_first_assets_allowed_without_allowing_arbitrary_uploads():
    for p in ['calibration/front/points.bin','identification-pass/sensors/000001.jpg','sensors/frame.bin','capture-hardware.json','pass-provenance.json']:
        assert safe_asset_path(p)==p
    for p in ['secrets/key.txt','calibration/../secret','sensors/.private','/tmp/a']:
        with pytest.raises(ValueError):safe_asset_path(p)


def test_actual_phone_package_when_available():
    root=Path('var/phone-validation/multicam-1-final')
    if not root.exists():pytest.skip('Optional local phone evidence is not in Git')
    actual={p.relative_to(root).as_posix():p for p in root.rglob('*') if p.is_file()}
    manifest=json.loads((root/'manifest.json').read_text())
    assert manifest['complete'] is True
    assert manifest['source']=='multicam_rgbd'
    for line in (root/'frames.jsonl').read_text().splitlines():
        raw=json.loads(line);frame=CaptureFrame.model_validate(raw)
        validate_frame(root,frame.model_dump(),actual)
        bad=copy.deepcopy(raw);bad['multi_camera']['cameras']['tele']['offset_from_primary_s']=1
        with pytest.raises(ValueError):validate_frame(root,bad,actual)
    validate_capture(root,{'scan_id':manifest['scan_id'],'source':manifest['source']},512*1024*1024)
