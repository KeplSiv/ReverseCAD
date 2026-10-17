"""Production isolated-process integration; only external AI uses labeled fixtures."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reversecad.cad import DEFAULTS
from reversecad.service import create_app
from test_service import FIXTURES,HEADERS,TOKEN,upload_package,wait_job


@pytest.mark.parametrize("family,fixture",[("bridge_handle","broken_bridge_clean"),("cup_handle","cup_clean"),("bracket","bracket_clean")])
def test_full_uploaded_scan_to_reimported_cad(tmp_path,family,fixture):
    app = create_app(tmp_path,TOKEN)
    with TestClient(app,headers=HEADERS) as client:
        scan = upload_package(client,fixture)
        assert client.post(f"/v1/scans/{scan}/commit").status_code == 200
        reconstruction = client.post(f"/v1/scans/{scan}/reconstruction").json()
        completed = wait_job(client,reconstruction["job_id"])
        assert completed["state"] == "complete",completed
        assert completed["result"]["point_count"] > 100
        assert any(a["name"] == "scan_preview.json" for a in completed["result"]["artifacts"])
        # Measured independently by a person at trial time; explicit synthetic manual entries here.
        annotations = {"contacts":[],"measurements":[{"id":"confirmed-hole","name":"hole_diameter","value":4,"unit":"mm","source":"manual","confirmed":True,"critical":True,"uncertainty_mm":.1,"observation_ids":[]}]} if family != "cup_handle" else {"contacts":[],"measurements":[]}
        assert client.put(f"/v1/scans/{scan}/annotations",json=annotations).status_code == 200
        payload = {"scan_id":scan,"family":family,"parameters":DEFAULTS[family],"attachment_method":"saddle" if family == "cup_handle" else "mechanical","mode":"fixture","acknowledge_uncertainty":True,"request_id":"first-revision"}
        response = client.post("/v1/repairs",json=payload)
        assert response.status_code == 200,response.text
        job = response.json()
        duplicate = client.post("/v1/repairs",json=payload).json()
        assert duplicate["job_id"] == job["job_id"] and duplicate["revision"] == 1
        conflict = client.post("/v1/repairs",json={**payload,"parameters":{**payload["parameters"],"standoff":45}})
        assert conflict.status_code == 409
        completed = wait_job(client,job["job_id"])
        assert completed["state"] == "complete",completed
        result = completed["result"]
        assert result["provider_status"] == "offline_fixture"
        assert result["validation"]["passed"] is True
        assert result["validation"]["physical_fit"] == "not_tested"
        assert result["prototype_export_acknowledged"] is True
        artifacts = {a["name"]:a for a in result["artifacts"]}
        assert {"part.step","part.stl","part.3mf","parameters.json","part.py","generator.py","preview.json","validation.json","coupon.stl","input_provenance.json"} <= artifacts.keys()
        downloads = tmp_path / "downloaded"
        downloads.mkdir()
        for name in ("part.step","part.stl","part.3mf","parameters.json"):
            item = artifacts[name]
            download = client.get(f"/v1/artifacts/{item['id']}")
            assert download.status_code == 200
            assert hashlib.sha256(download.content).hexdigest() == item["sha256"]
            (downloads / name).write_bytes(download.content)
        import cadquery as cq
        import trimesh
        shape = cq.importers.importStep(str(downloads / "part.step"))
        assert shape.val().isValid() and len(shape.solids().vals()) == 1
        stl = trimesh.load_mesh(downloads / "part.stl",process=True)
        assert stl.is_watertight and len(stl.split()) == 1
        from_mf = trimesh.load(downloads / "part.3mf",force="mesh",process=True)
        assert from_mf.is_watertight
        assert max(abs(stl.extents-from_mf.extents)) < .1
        # Revision editing preserves original evidence and the already confirmed hole.
        editable = "standoff" if family != "bracket" else "length"
        edited = {**payload,"parameters":{**payload["parameters"],editable:payload["parameters"][editable]+2},"request_id":"second-revision"}
        revised = client.post(f"/v1/repairs/{job['repair_id']}/revisions",json=edited).json()
        assert revised["revision"] == 2
        revision_result = wait_job(client,revised["job_id"])
        assert revision_result["state"] == "complete",revision_result
        assert revision_result["result"]["parameters"][editable] == edited["parameters"][editable]
        assert client.get(f"/v1/artifacts/{artifacts['part.step']['id']}").status_code == 200
        # Success is revoked if verified output disappears; no stale green job.
        stored = app.state.store.one("SELECT path FROM artifacts WHERE artifact_id=?",(artifacts["part.step"]["id"],))
        Path(stored["path"]).unlink()
        assert client.get(f"/v1/artifacts/{artifacts['part.step']['id']}").status_code == 409
        broken = client.get(f"/v1/jobs/{job['job_id']}").json()
        assert broken["state"] == "failed" and broken["error"]["code"] == "artifact_corrupt"


def test_active_cancellation_and_time_budget(tmp_path):
    app = create_app(tmp_path / "cancel",TOKEN)
    with TestClient(app,headers=HEADERS) as client:
        scan = upload_package(client)
        client.post(f"/v1/scans/{scan}/commit")
        job = client.post(f"/v1/scans/{scan}/reconstruction").json()
        deadline = time.monotonic()+10
        while app.state.runner.process is None and time.monotonic()<deadline:
            time.sleep(.01)
        process = app.state.runner.process
        assert process is not None
        assert client.post(f"/v1/jobs/{job['job_id']}/cancel").json()["state"] == "cancelled"
        assert process.poll() is not None
        assert client.get(f"/v1/scans/{scan}").json()["committed"]
    with TestClient(create_app(tmp_path / "timeout",TOKEN,worker_timeout_s=.02),headers=HEADERS) as client:
        scan = upload_package(client)
        client.post(f"/v1/scans/{scan}/commit")
        job = client.post(f"/v1/scans/{scan}/reconstruction").json()
        result = wait_job(client,job["job_id"])
        assert result["state"] == "failed" and result["error"]["code"] == "worker_timeout"
        assert client.get(f"/v1/scans/{scan}").json()["committed"]


def test_real_job_restart_retry_and_memory_budget(tmp_path):
    directory = tmp_path / "restart"
    app = create_app(directory,TOKEN)
    with TestClient(app,headers=HEADERS) as client:
        scan = upload_package(client)
        client.post(f"/v1/scans/{scan}/commit")
        job = client.post(f"/v1/scans/{scan}/reconstruction").json()
        deadline = time.monotonic()+10
        while app.state.runner.process is None and time.monotonic()<deadline:
            time.sleep(.01)
        assert app.state.runner.process is not None
    with TestClient(create_app(directory,TOKEN),headers=HEADERS) as client:
        interrupted = client.get(f"/v1/jobs/{job['job_id']}").json()
        assert interrupted["state"] == "failed" and interrupted["error"]["code"] == "server_restarted"
        retry = client.post(f"/v1/scans/{scan}/reconstruction").json()
        assert wait_job(client,retry["job_id"])["state"] == "complete"
    with TestClient(create_app(tmp_path / "memory",TOKEN,max_memory_bytes=1024),headers=HEADERS) as client:
        scan = upload_package(client)
        client.post(f"/v1/scans/{scan}/commit")
        job = client.post(f"/v1/scans/{scan}/reconstruction").json()
        result = wait_job(client,job["job_id"])
        assert result["state"] == "failed" and result["error"]["code"] == "worker_memory_limit"


@pytest.mark.parametrize("family,fixture",[("bridge_handle","broken_bridge_clean"),("cup_handle","cup_clean")])
def test_authoritative_candidate_generation_and_acknowledgement(tmp_path,family,fixture):
    """Raw RGB-D -> measured geometry -> selected contacts -> candidate -> real CAD."""
    with TestClient(create_app(tmp_path,TOKEN),headers=HEADERS) as client:
        scan = upload_package(client,fixture)
        client.post(f"/v1/scans/{scan}/commit")
        job = client.post(f"/v1/scans/{scan}/reconstruction",json={"request_id":"candidate-reconstruction"}).json()
        reconstruction = wait_job(client,job["job_id"])
        assert reconstruction["state"] == "complete",reconstruction
        def measured(name,value):
            return {"id":"manual_"+name,"name":name,"value":value,"unit":"mm","source":"manual","confirmed":True,"critical":True,"uncertainty_mm":.1,"observation_ids":[]}
        def contact(name,point,normal):
            return {"id":name,"point_m":point,"normal":normal,"radius_mm":8}
        # Explicit synthetic user measurements, not hidden evaluation data supplied to reconstruction.
        if family == "bridge_handle":
            selected = [contact("left",[-.04,0,.012],[0,0,1]),contact("right",[.04,0,.012],[0,0,1])]
            measurements = [measured("span",80),measured("hole_diameter",4)]
            method = "mechanical"
        else:
            selected = [contact("lower",[0,-.025,.035],[0,0,1]),contact("upper",[0,.025,.035],[0,0,1])]
            measurements = [measured("cup_radius",35),measured("cup_radius_top",35),measured("contact_spacing",50)]
            method = "saddle"
        annotations = {"contacts":selected,"measurements":measurements,"attachment_method":method}
        assert client.put(f"/v1/scans/{scan}/annotations",json=annotations).status_code == 200
        candidates = client.post(f"/v1/scans/{scan}/candidates",json={"family":family,"attachment_method":method})
        assert candidates.status_code == 200,candidates.text
        result = candidates.json()
        assert len(result["candidates"]) >= 1,result
        candidate = result["candidates"][0]
        request = {"scan_id":scan,"family":family,"parameters":candidate["parameters"],"candidate_id":candidate["id"],"attachment_method":method,"mode":"fixture","acknowledge_uncertainty":True,"request_id":"candidate-repair"}
        submitted = client.post("/v1/repairs",json=request)
        assert submitted.status_code == 200,submitted.text
        result = wait_job(client,submitted.json()["job_id"])
        assert result["state"] == "complete",result
        assert result["result"]["validation"]["cad_valid"]
        assert result["result"]["validation"]["physical_fit"] == "not_tested"
        assert result["result"]["intent"]["measurement_refs"]
        assert result["result"]["intent"]["provider_status"] == "offline_fixture"


def test_prototype_exports_require_explicit_acknowledgement(tmp_path):
    with TestClient(create_app(tmp_path,TOKEN),headers=HEADERS) as client:
        scan = upload_package(client,"broken_bridge_clean")
        client.post(f"/v1/scans/{scan}/commit")
        job = client.post(f"/v1/scans/{scan}/reconstruction").json()
        assert wait_job(client,job["job_id"])["state"] == "complete"
        request = {"scan_id":scan,"family":"bridge_handle","parameters":DEFAULTS["bridge_handle"],"attachment_method":"mechanical","mode":"manual","acknowledge_uncertainty":False}
        job = client.post("/v1/repairs",json=request).json()
        outcome = wait_job(client,job["job_id"])
        assert outcome["state"] == "needs_input",outcome
        names = {item["name"] for item in outcome["result"]["artifacts"]}
        assert "preview.json" in names and "validation.json" in names
        assert not {"part.step","part.stl","part.3mf","coupon.stl","part.py"} & names
        request["acknowledge_uncertainty"] = True
        revised = client.post(f"/v1/repairs/{job['repair_id']}/revisions",json=request).json()
        acknowledged = wait_job(client,revised["job_id"])
        assert acknowledged["state"] == "complete",acknowledged
        assert acknowledged["result"]["validation"]["status"] == "needs_input"
        assert acknowledged["result"]["prototype_export_acknowledged"]
