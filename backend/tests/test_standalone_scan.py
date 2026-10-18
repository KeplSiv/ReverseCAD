import json
import numpy as np
import pytest
from reversecad.jev import interpret, JevError
from reversecad.scan_export import export_observed_scan
from reversecad.contracts import Annotations


def reply(present=.99, count='one', box=None):
    return {'model':'jev-1.14.0','answers':{'present':{'noul':present},'instances':{'choice':count,'confidence':.98},'category':{'choice':'mechanical_part'},'target':{'box': box or {'top':.1,'bottom':.8,'left':.2,'right':.7},'confidence':.9}}}


def test_absent_ambiguous_and_invalid_targets_are_not_locked():
    assert interpret(reply())['status']=='confirm_target'
    for r in [reply(present=.1),reply(count='several'),reply(count='none')]:
        assert interpret(r)['box'] is None
    with pytest.raises(JevError): interpret(reply(box={'top':.8,'bottom':.1,'left':.2,'right':.7}))
    with pytest.raises(JevError): interpret(reply(present=float('nan')))
    assert Annotations(repair_scope='standalone_scan').repair_scope=='standalone_scan'


def test_open_observed_surface_roundtrips_as_mm_cad(tmp_path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    vertices=[[0,0,0],[100,0,0],[100,60,0],[0,60,0]]
    np.savez(tmp_path/'points_measurement.npz',points_m=np.asarray(vertices)/1000)
    (tmp_path/'scan_preview.json').write_text(json.dumps({'vertices':vertices,'triangles':[[0,1,2],[0,2,3]],'unit':'mm'}))
    report=export_observed_scan(tmp_path,{'status':'ready','scan_id':'test','measurements':[]})
    assert report['status']=='ready' and not report['watertight']
    reader=STEPControl_Reader();assert reader.ReadFile(str(tmp_path/'observed_object.step'))==IFSelect_RetDone
    reader.TransferRoots();bounds=Bnd_Box();BRepBndLib.Add_s(reader.OneShape(),bounds)
    low_high=bounds.Get()
    assert low_high[3]-low_high[0]==pytest.approx(100,abs=1e-5)
    assert low_high[4]-low_high[1]==pytest.approx(60,abs=1e-5)
    assert low_high[5]-low_high[2]<1e-5
    assert (tmp_path/'observed_points_mm.ply').is_file()
    assert not (tmp_path/'part.step').exists()


def test_insufficient_scan_cannot_be_exported_as_measured_cad(tmp_path):
    result=export_observed_scan(tmp_path,{'status':'needs_input','scan_id':'test'})
    assert result['files']==[]
    assert not (tmp_path/'observed_object.step').exists()


@pytest.mark.timeout(180)
@pytest.mark.parametrize("sparse", [False, True])
def test_standalone_service_produces_scan_exports_without_repair(tmp_path, sparse):
    import subprocess,sys,hashlib
    from pathlib import Path
    from fastapi.testclient import TestClient
    from reversecad.service import create_app
    from test_service import upload_package,wait_job,TOKEN,HEADERS
    root=Path(__file__).resolve().parents[2];package=tmp_path/'capture'
    if sparse:
        subprocess.run([sys.executable,str(root/'scripts/generate_sparse_fixture.py'),str(package)],check=True,capture_output=True)
    else:
        package = root/'fixtures/generated/calibration_block_clean'
    with TestClient(create_app(tmp_path/'service',TOKEN),headers=HEADERS) as client:
        scan=upload_package(client,path=package)
        assert client.post(f'/v1/scans/{scan}/commit').status_code==200
        response=client.put(f'/v1/scans/{scan}/annotations',json={'repair_scope':'standalone_scan'})
        assert response.status_code==200,response.text
        job=client.post(f'/v1/scans/{scan}/reconstruction').json()
        result=wait_job(client,job['job_id'])
        assert result['state']=='complete',result
        artifacts={a['name']:a for a in result['result']['artifacts']}
        assert {'observed_object.stl','observed_points_mm.ply','measurements.json','scan_export.json'}<=artifacts.keys()
        if sparse:
            assert 'observed_object.step' in artifacts
        elif 'observed_object.step' not in artifacts:
            report=client.get('/v1/artifacts/'+artifacts['scan_export.json']['id']).json()
            approximation=report['cad_approximation']
            assert approximation['triangles']>30000 or approximation['sampled_bidirectional_max_deviation_mm']>.5
            assert 'reason' in report
        assert not any(name.startswith(('part.','counterpart','pattern_')) for name in artifacts)
        for name in [name for name in ['observed_object.step','observed_object.stl','measurements.json'] if name in artifacts]:
            artifact=artifacts[name];raw=client.get('/v1/artifacts/'+artifact['id']).content
            assert hashlib.sha256(raw).hexdigest()==artifact['sha256']
