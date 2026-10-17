from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reversecad.service import create_app

TOKEN = "service-test-token-keep-local-only"
HEADERS = {"Authorization":"Bearer " + TOKEN}
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "generated"


def upload_package(client, source="calibration_block_clean", path=None):
    path = Path(path) if path else FIXTURES / source
    manifest = json.loads((path / "manifest.json").read_text())
    scan_id = manifest["scan_id"]
    response = client.post("/v1/scans",json={"scan_id":scan_id,"source":manifest["source"],"project_id":"test-project"})
    assert response.status_code == 200,response.text
    for file in sorted(path.rglob("*")):
        if file.is_file():
            data = file.read_bytes()
            response = client.put(f"/v1/scans/{scan_id}/assets/{file.relative_to(path).as_posix()}",content=data,headers={"X-Content-SHA256":hashlib.sha256(data).hexdigest()})
            assert response.status_code == 200,response.text
    return scan_id


def wait_job(client,job_id,timeout=180):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        response = client.get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200,response.text
        job = response.json()
        if job["state"] in {"complete","failed","needs_input","cancelled"}:
            return job
        time.sleep(.15)
    pytest.fail(f"Timed out waiting for {job_id}")


def rehash(path):
    mapping = {p.relative_to(path).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file() and p.name != "checksums.json"}
    (path / "checksums.json").write_text(json.dumps(mapping))


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "service",TOKEN,workers_enabled=False),headers=HEADERS) as client:
        yield client


def test_auth_and_owner_scoping(tmp_path):
    app = create_app(tmp_path,TOKEN,workers_enabled=False)
    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200
        assert client.get("/v1/capabilities").status_code == 401
        assert client.post("/v1/scans",json={"source":"synthetic"},headers={"Authorization":"Bearer wrong"}).status_code == 401
        client.headers.update(HEADERS)
        scan = client.post("/v1/scans",json={"source":"synthetic","scan_id":"private-scan"})
        assert scan.status_code == 200
    # A separately paired principal may not access an earlier principal's data.
    other = "different-pairing-token-for-tests"
    with TestClient(create_app(tmp_path,other,workers_enabled=False),headers={"Authorization":"Bearer " + other}) as client:
        assert client.get("/v1/scans/private-scan").status_code == 404
        assert client.post("/v1/scans",json={"source":"synthetic","scan_id":"private-scan"}).status_code == 404


def test_upload_resume_hash_conflict_and_commit(client):
    scan = upload_package(client)
    status = client.get(f"/v1/scans/{scan}").json()
    assert not status["committed"] and len(status["assets"]) > 10
    data = (FIXTURES / "calibration_block_clean" / "manifest.json").read_bytes()
    url = f"/v1/scans/{scan}/assets/manifest.json"
    assert client.put(url,content=data,headers={"X-Content-SHA256":hashlib.sha256(data).hexdigest()}).json()["already_present"]
    assert client.put(url,content=b"conflict",headers={"X-Content-SHA256":hashlib.sha256(b"conflict").hexdigest()}).status_code == 409
    assert client.post(f"/v1/scans/{scan}/commit").json()["committed"]
    assert client.put(f"/v1/scans/{scan}/assets/video/late.mov",content=b"late",headers={"X-Content-SHA256":hashlib.sha256(b"late").hexdigest()}).status_code == 409
    before = client.get(f"/v1/scans/{scan}").json()["assets"]
    result = client.put(f"/v1/scans/{scan}/annotations",json={"attachment_method":"mechanical","measurements":[{"id":"span","name":"span","value":80,"unit":"mm","source":"manual","confirmed":True,"critical":True,"uncertainty_mm":.1,"observation_ids":[]}]})
    assert result.status_code == 200
    assert client.get(f"/v1/scans/{scan}").json()["assets"] == before
    assert client.put(f"/v1/scans/{scan}/annotations",json={"crop_min_m":[1,1,1],"crop_max_m":[0,0,0]}).status_code == 422


def test_path_archive_checksum_and_upload_bounds(client,tmp_path):
    scan = client.post("/v1/scans",json={"source":"synthetic","scan_id":"limits"}).json()["scan_id"]
    base = f"/v1/scans/{scan}/assets/"
    checksum = {"X-Content-SHA256":hashlib.sha256(b"data").hexdigest()}
    assert client.put(base+"rgb/a.jpg",content=b"data").status_code == 400
    assert client.put(base+"rgb/a.jpg",content=b"bad",headers=checksum).status_code == 422
    assert client.get(f"/v1/scans/{scan}").json()["assets"] == []
    for path in ("archive.zip","rgb/%2E%2E/escape","rgb%5Cescape",".hidden","rgb//double.jpg","rgb/%00bad"):
        assert client.put(base+path,content=b"data",headers=checksum).status_code in (400,404),path
    assert client.post(f"/v1/scans/{scan}/commit").status_code == 422
    with TestClient(create_app(tmp_path / "limits",TOKEN,workers_enabled=False,max_asset_bytes=8,max_scan_bytes=12),headers=HEADERS) as limited:
        limited.post("/v1/scans",json={"source":"synthetic","scan_id":"bounded"})
        assert limited.put("/v1/scans/bounded/assets/rgb/a.jpg",content=b"123456789",headers={"X-Content-SHA256":hashlib.sha256(b"123456789").hexdigest()}).status_code == 413
        assert limited.get("/v1/scans/bounded").json()["assets"] == []


@pytest.mark.parametrize("failure",["checksum","dimensions","stride","pose","nan","duplicate","count","extra"])
def test_corrupt_packages_rejected(client,tmp_path,failure):
    package = tmp_path / failure
    shutil.copytree(FIXTURES / "calibration_block_clean",package)
    frames = [json.loads(line) for line in (package / "frames.jsonl").read_text().splitlines()]
    if failure == "checksum":
        (package / "rgb/0000.jpg").write_bytes(b"broken")
    elif failure == "dimensions": frames[0]["rgb_width"] += 1
    elif failure == "stride": frames[0]["depth_row_bytes"] += 4
    elif failure == "pose": frames[0]["T_world_camera"][0] = 2
    elif failure == "nan": frames[0]["timestamp_s"] = float("nan")
    elif failure == "duplicate": frames[1]["frame_id"] = frames[0]["frame_id"]
    elif failure == "count": frames.pop()
    elif failure == "extra": (package / "rgb/orphan.jpg").write_bytes(b"undeclared")
    if failure not in ("checksum","extra"):
        (package / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames))
        rehash(package)
    scan = upload_package(client,path=package)
    response = client.post(f"/v1/scans/{scan}/commit")
    assert response.status_code == 422,response.text
    assert response.json()["error"]["code"] == "invalid_capture_package"
    assert not client.get(f"/v1/scans/{scan}").json()["committed"]


def test_queued_cancel_and_project_delete(client):
    scan = upload_package(client)
    assert client.post(f"/v1/scans/{scan}/commit").status_code == 200
    job = client.post(f"/v1/scans/{scan}/reconstruction").json()
    assert job["state"] == "queued"
    assert client.post(f"/v1/jobs/{job['job_id']}/cancel").json()["state"] == "cancelled"
    assert client.get(f"/v1/scans/{scan}").json()["committed"]
    assert client.delete("/v1/projects/test-project").json()["deleted"]
    assert client.get(f"/v1/scans/{scan}").status_code == 404
    assert client.get(f"/v1/jobs/{job['job_id']}").status_code == 404


def test_restart_preserves_scan_and_fails_interrupted_job(tmp_path):
    app = create_app(tmp_path,TOKEN,workers_enabled=False)
    with TestClient(app,headers=HEADERS) as client:
        scan = upload_package(client)
        client.post(f"/v1/scans/{scan}/commit")
        queued = client.post(f"/v1/scans/{scan}/reconstruction").json()
        interrupted = client.post(f"/v1/scans/{scan}/reconstruction").json()
        app.state.store.update_job(interrupted["job_id"],"reconstructing",.5,"Working")
    with TestClient(create_app(tmp_path,TOKEN,workers_enabled=False),headers=HEADERS) as resumed:
        assert resumed.get(f"/v1/scans/{scan}").json()["committed"]
        assert resumed.get(f"/v1/jobs/{queued['job_id']}").json()["state"] == "queued"
        failed = resumed.get(f"/v1/jobs/{interrupted['job_id']}").json()
        assert failed["state"] == "failed" and failed["error"]["code"] == "server_restarted"


def test_server_side_hash_tamper_detected_at_commit(client):
    scan = upload_package(client)
    path = client.app.state.store.scan_dir(scan) / "depth/0000.f32"
    path.write_bytes(b"corrupt")
    assert client.post(f"/v1/scans/{scan}/commit").status_code == 422


def test_invalid_api_numbers_and_identifiers(client):
    assert client.post("/v1/scans",json={"source":"synthetic","scan_id":"../escape"}).status_code == 422
    assert client.post("/v1/repairs",json={"scan_id":"x","family":"arbitrary_python","parameters":{},"attachment_method":"saddle"}).status_code == 422
    assert client.post("/v1/repairs",content='{"scan_id":"x","family":"bracket","parameters":{"width":NaN},"attachment_method":"mechanical"}',headers={"Content-Type":"application/json"}).status_code == 422


def test_phone_diagnostics_and_native_calibration_contract(client,tmp_path):
    package = tmp_path / "native-compatible"
    shutil.copytree(FIXTURES / "calibration_block_clean",package)
    frames = [json.loads(line) for line in (package / "frames.jsonl").read_text().splitlines()]
    for frame in frames:
        frame["depth_calibration_mode"] = "native_arkit"
    (package / "frames.jsonl").write_text("\n".join(json.dumps(frame) for frame in frames))
    (package / "capture_diagnostics.json").write_text(json.dumps({"accepted_frames":12,"rejected_frames":0,"tracking_events":[],"source":"synthetic native-contract test; not device evidence"}))
    rehash(package)
    scan = upload_package(client,path=package)
    assert client.post(f"/v1/scans/{scan}/commit").status_code == 200
    # App resume need not resend the project's identifier.
    resumed = client.post("/v1/scans",json={"scan_id":scan,"source":"synthetic"})
    assert resumed.status_code == 200 and resumed.json()["project_id"] == "test-project"


def test_annotation_and_reconstruction_idempotence(client):
    scan = upload_package(client)
    client.post(f"/v1/scans/{scan}/commit")
    body = {"attachment_method":"mechanical","contacts":[{"id":"a","point_m":[0,0,0],"normal":[0,0,1],"radius_mm":5}]}
    first = client.put(f"/v1/scans/{scan}/annotations",json=body).json()
    second = client.put(f"/v1/scans/{scan}/annotations",json=body).json()
    assert first["annotation_revision"] == second["annotation_revision"]
    first_job = client.post(f"/v1/scans/{scan}/reconstruction",json={"request_id":"lost-network-response"}).json()
    second_job = client.post(f"/v1/scans/{scan}/reconstruction",json={"request_id":"lost-network-response"}).json()
    assert first_job["job_id"] == second_job["job_id"]
    client.put(f"/v1/scans/{scan}/annotations",json={**body,"crop_min_m":[-.1,-.1,-.1],"crop_max_m":[.1,.1,.1]})
    assert client.post(f"/v1/scans/{scan}/reconstruction",json={"request_id":"lost-network-response"}).status_code == 409


def test_metadata_body_budget(client):
    body = '{"source":"synthetic","extra":"' + "x"*(1024*1024) + '"}'
    response = client.post("/v1/scans",content=body,headers={"Content-Type":"application/json"})
    assert response.status_code == 413 and response.json()["error"]["code"] == "request_too_large"


def test_cancel_cannot_be_overwritten_by_delayed_worker(client):
    scan = upload_package(client)
    client.post(f"/v1/scans/{scan}/commit")
    job = client.post(f"/v1/scans/{scan}/reconstruction").json()
    client.post(f"/v1/jobs/{job['job_id']}/cancel")
    for state in ("reconstructing","complete","failed"):
        client.app.state.store.update_job(job["job_id"],state,.8,"Late worker callback",result={"bad":"must not resurrect"})
        assert client.get(f"/v1/jobs/{job['job_id']}").json()["state"] == "cancelled"


def test_candidates_bind_latest_authoritative_evidence(client):
    scan = upload_package(client)
    client.post(f"/v1/scans/{scan}/commit")
    url = f"/v1/scans/{scan}/candidates"
    assert client.post(url,json={"family":"bridge_handle","attachment_method":"mechanical"}).status_code == 409
    # Focused endpoint contract test: production reconstruction itself is exercised by integration suite.
    recon = {"status":"ready","measurements":[],"primitives":[],"observations":{"accepted_frames":["0000","0001"]},"artifacts":[]}
    with client.app.state.store.connect() as db:
        db.execute("UPDATE scans SET reconstruction=? WHERE scan_id=?",(json.dumps(recon),scan))
    annotations = {"contacts":[{"id":"a","point_m":[-.04,0,0],"normal":[0,0,1],"radius_mm":10},{"id":"b","point_m":[.04,0,0],"normal":[0,0,1],"radius_mm":10}],"attachment_method":"mechanical"}
    client.put(f"/v1/scans/{scan}/annotations",json=annotations)
    result = client.post(url,json={"family":"bridge_handle","attachment_method":"mechanical"})
    assert result.status_code == 200,result.text
    candidates = result.json()
    assert candidates["candidates"]
    candidate = candidates["candidates"][0]
    assert candidate["parameters"]["span"] == 80
    payload = {"scan_id":scan,"family":"bridge_handle","parameters":candidate["parameters"],"candidate_id":candidate["id"],"attachment_method":"mechanical","acknowledge_uncertainty":True,"measurements":[{"id":"forged","value":999}]}
    submitted = client.post("/v1/repairs",json=payload)
    assert submitted.status_code == 200,submitted.text
    stored = client.app.state.store.one("SELECT request FROM jobs WHERE job_id=?",(submitted.json()["job_id"],))
    saved = json.loads(stored["request"])
    assert saved["repair"]["measurements"] == candidates["derived_measurements"]
    annotations["contacts"][1]["point_m"][0] = .05
    client.put(f"/v1/scans/{scan}/annotations",json=annotations)
    assert client.post("/v1/repairs",json=payload).status_code == 409


def test_clients_cannot_invent_observed_dimensions(client):
    scan = upload_package(client)
    client.post(f"/v1/scans/{scan}/commit")
    measurement = {"id":"observed-span","name":"span","value":80,"unit":"mm","source":"depth_fit","confirmed":False,"critical":True,"uncertainty_mm":None,"observation_ids":["0000"]}
    target = f"/v1/scans/{scan}/annotations"
    assert client.put(target,json={"measurements":[measurement]}).status_code == 422
    with client.app.state.store.connect() as db:
        db.execute("UPDATE scans SET reconstruction=? WHERE scan_id=?",(json.dumps({"measurements":[measurement]}),scan))
    assert client.put(target,json={"measurements":[{**measurement,"confirmed":True}]}).status_code == 200
    assert client.put(target,json={"measurements":[{**measurement,"value":81}]}).status_code == 422
    assert client.put(target,json={"measurements":[{**measurement,"uncertainty_mm":.01}]}).status_code == 422
    assert client.put(target,json={"measurements":[{**measurement,"source":"manual","value":81,"confirmed":True,"uncertainty_mm":.1}]}).status_code == 200
