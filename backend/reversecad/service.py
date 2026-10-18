"""Durable, authenticated local companion service. Start via scripts/start_service.sh."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .contracts import Annotations, CaptureFrame, CreateScan, RepairRequest, ScanManifest, ReconstructionRequest, CandidateRequest, LiveGeometryRequest, finite, identifier, safe_asset_path
from .storage import ACTIVE_STATES, Store, atomic_json, digest


def error(status: int, code: str, message: str):
    raise HTTPException(status, detail={"code":code,"message":message})


def validate_capture(root: Path, scan: dict, max_bytes: int):
    """Validate the exact capture contract before anything reaches a native library."""
    import numpy as np
    from PIL import Image
    actual = {p.relative_to(root).as_posix():p for p in root.rglob("*") if p.is_file()}
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Capture packages cannot contain symbolic links")
    for name in actual:
        safe_asset_path(name)
    required = {"manifest.json","frames.jsonl","checksums.json"}
    if required - actual.keys():
        raise ValueError("Upload manifest.json, frames.jsonl and checksums.json before committing")
    if sum(p.stat().st_size for p in actual.values()) > max_bytes:
        raise ValueError("Capture exceeds scan-size budget")
    if any(actual[n].stat().st_size > 16*1024*1024 for n in required):
        raise ValueError("Capture metadata exceeds size budget")
    manifest = ScanManifest.model_validate_json(actual["manifest.json"].read_text())
    if manifest.scan_id != scan["scan_id"] or manifest.source != scan["source"]:
        raise ValueError("Manifest identity/source disagrees with the upload")
    checksums = json.loads(actual["checksums.json"].read_text())
    if not isinstance(checksums, dict) or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch(r"[a-fA-F0-9]{64}",v) for k,v in checksums.items()):
        raise ValueError("checksums.json must map relative paths to SHA-256 strings")
    if set(checksums) != set(actual)-{"checksums.json"}:
        raise ValueError("Checksums must cover every capture asset exactly, excluding checksums.json itself")
    for name, expected in checksums.items():
        safe_asset_path(name)
        if not hmac.compare_digest(digest(actual[name]), expected.lower()):
            raise ValueError(f"Checksum mismatch for {name}")
    lines = actual["frames.jsonl"].read_text().splitlines()
    frames = [CaptureFrame.model_validate_json(line) for line in lines if line.strip()]
    if len(frames) != manifest.frame_count:
        raise ValueError("Manifest frame_count does not match frames.jsonl")
    segments = {segment.segment_id:segment for segment in manifest.segments}
    if len(segments) != len(manifest.segments):
        raise ValueError("Segment identifiers must be unique")

    def rigid(values):
        transform = np.asarray(values).reshape((4,4),order="F")
        if not np.allclose(transform[3],[0,0,0,1],atol=1e-5) or not np.allclose(transform[:3,:3].T @ transform[:3,:3],np.eye(3),atol=2e-3) or abs(np.linalg.det(transform[:3,:3])-1)>2e-3:
            raise ValueError("Pose must be a rigid, right-handed column-major transform")
    for segment in segments.values():
        rigid(segment.T_object_world)
    seen = set()
    stamps = {}
    for frame in frames:
        if frame.scan_id != manifest.scan_id or frame.segment_id not in segments:
            raise ValueError("Frame refers to another scan or an unknown segment")
        if frame.frame_id in seen:
            raise ValueError("Frame identifiers must be unique")
        seen.add(frame.frame_id)
        if frame.timestamp_s <= stamps.get(frame.segment_id,-1):
            raise ValueError("Frame timestamps must increase within each segment")
        stamps[frame.segment_id] = frame.timestamp_s
        rigid(frame.T_world_camera)
        if frame.rgb_path not in actual:
            raise ValueError("Missing RGB asset")
        with Image.open(actual[frame.rgb_path]) as image:
            if image.size != (frame.rgb_width,frame.rgb_height):
                raise ValueError("RGB dimensions disagree with CaptureFrame")
            if image.format not in {"JPEG","PNG"}:
                raise ValueError("RGB image must be JPEG or PNG")
            image.verify()
        if frame.depth_path:
            if frame.depth_path not in actual or actual[frame.depth_path].stat().st_size != frame.depth_row_bytes*frame.depth_height:
                raise ValueError("Depth payload does not match dimensions/stride")
            # Invalid depth samples (NaN/zero/negative) are legal raw observations; reconstruction filters them.
        for name in (frame.confidence_path,frame.mask_path):
            if name:
                sizes = {frame.depth_width*frame.depth_height}
                if name == frame.mask_path:
                    sizes.add(frame.rgb_width*frame.rgb_height)
                if name not in actual or actual[name].stat().st_size not in sizes:
                    raise ValueError("Confidence/mask payload does not match native dimensions")
    if "capture_diagnostics.json" in actual:
        diagnostic = actual["capture_diagnostics.json"]
        if diagnostic.stat().st_size > 1024*1024:
            raise ValueError("Capture diagnostics exceed metadata budget")
        value = finite(json.loads(diagnostic.read_text()))
        if not isinstance(value,dict):
            raise ValueError("Capture diagnostics must be a JSON object")
    if "annotations.json" in actual:
        Annotations.model_validate_json(actual["annotations.json"].read_text())
    from .sparse.capture import validate_extension
    validate_extension(root, manifest.model_dump(), frames)
    return manifest.model_dump()


class JobRunner:
    def __init__(self, store: Store, timeout_s: float, max_memory_bytes: int, comparison_timeout_s: float = 600, comparison_memory_bytes: int = 10*1024**3):
        self.store, self.timeout_s, self.max_memory_bytes = store,timeout_s,max_memory_bytes
        self.comparison_timeout_s, self.comparison_memory_bytes = comparison_timeout_s, comparison_memory_bytes
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.process = None
        self.job_id = None
        self.process_lock = threading.Lock()

    def start(self):
        self.store.recover()
        self.thread = threading.Thread(target=self.loop, name="reversecad-jobs", daemon=True)
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        self.wake.set()
        self.terminate()
        if self.thread:
            self.thread.join(timeout=8)

    def terminate(self, job_id=None):
        with self.process_lock:
            process = self.process
            if process and (job_id is None or self.job_id == job_id) and process.poll() is None:
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:
                    return
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def loop(self):
        while not self.stop.is_set():
            row = self.store.one("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1")
            if not row:
                self.wake.wait(0.3)
                self.wake.clear()
                continue
            try:
                self.execute(row)
            except Exception as exc:
                # Exception class only: avoid leaking user payloads or credential-bearing messages.
                self.terminate(row["job_id"])
                self.store.update_job(row["job_id"],"failed",message="Service worker supervision failed",error={"code":"supervisor_failure","message":f"Processing failed ({type(exc).__name__}); saved scan is available for retry"})

    def execute(self, row):
        job_id = row["job_id"]
        folder = self.store.root / "jobs" / job_id
        folder.mkdir(parents=True,exist_ok=True)
        payload = json.loads(row["request"])
        comparison = bool(payload.get("compare_methods"))
        timeout_s = self.comparison_timeout_s if comparison else self.timeout_s
        memory_bytes = self.comparison_memory_bytes if comparison else self.max_memory_bytes
        payload["cpu_limit_s"] = max(1,int(timeout_s))
        atomic_json(folder / "input.json",payload)
        self.store.update_job(job_id,"validating_input",0.01,"Starting isolated worker")
        env = os.environ.copy()
        env.update({"OMP_NUM_THREADS":"2","OPENBLAS_NUM_THREADS":"2","MKL_NUM_THREADS":"2","NUMEXPR_NUM_THREADS":"2","PYTHONUNBUFFERED":"1"})
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH","")
        log = (folder / "worker.log").open("wb")
        with self.process_lock:
            self.job_id = job_id
            self.process = subprocess.Popen([sys.executable,"-m","reversecad.workers",str(folder / "input.json")],stdout=log,stderr=log,env=env,start_new_session=True)
            process = self.process
        started = time.monotonic()
        last_progress = None
        failure = None
        while process.poll() is None:
            state = self.store.one("SELECT state FROM jobs WHERE job_id=?",(job_id,))
            if self.stop.is_set() or not state or state["state"] == "cancelled":
                self.terminate(job_id)
                break
            if time.monotonic()-started > timeout_s:
                failure = {"code":"worker_timeout","message":"Processing exceeded its time budget; reduce scan size and retry"}
                self.terminate(job_id)
                break
            try:
                rows = subprocess.check_output(["/bin/ps","-axo","pid=,ppid=,rss="],timeout=1,text=True)
                processes = [tuple(map(int,line.split())) for line in rows.splitlines() if line.strip()]
                children = {process.pid}
                for _ in range(10):
                    expanded = children | {pid for pid,ppid,rss in processes if ppid in children}
                    if expanded == children:break
                    children = expanded
                rss = sum(rss for pid,ppid,rss in processes if pid in children)
                if rss*1024 > memory_bytes:
                    failure = {"code":"worker_memory_limit","message":"Processing exceeded its memory budget; reduce scan size and retry"}
                    self.terminate(job_id)
                    break
            except (ValueError,subprocess.SubprocessError):
                pass
            progress_file = folder / "progress.json"
            if progress_file.is_file():
                try:
                    progress = json.loads(progress_file.read_text())
                    if progress != last_progress and progress.get("state") in ACTIVE_STATES:
                        self.store.update_job(job_id,progress["state"],progress.get("progress",0),progress.get("message",""))
                        last_progress = progress
                except (OSError,json.JSONDecodeError):
                    pass
            self.stop.wait(0.15)
        log.close()
        with self.process_lock:
            self.process = None
            self.job_id = None
        state = self.store.one("SELECT state FROM jobs WHERE job_id=?",(job_id,))
        if not state or state["state"] == "cancelled":
            return
        if self.stop.is_set():
            self.store.update_job(job_id,"failed",message="Interrupted by service shutdown",error={"code":"server_restarted","message":"Service stopped during processing; scan retained for retry"})
            return
        if failure:
            self.store.update_job(job_id,"failed",message=failure["message"],error=failure)
            return
        result_path = folder / "result.json"
        if not result_path.is_file():
            self.store.update_job(job_id,"failed",message="Worker exited before producing validated outputs",error={"code":"worker_exit","message":f"Worker exited ({process.returncode}); scan retained"})
            return
        outcome = json.loads(result_path.read_text())
        if outcome["state"] == "failed":
            self.store.update_job(job_id,"failed",message=outcome["error"]["message"],error=outcome["error"])
            return
        result = outcome["result"]
        artifacts = []
        for file in sorted((folder / "output").rglob("*")):
            if not file.is_file() or file.is_symlink():
                continue
            name = file.relative_to(folder / "output").as_posix()
            if row["kind"] == "repair" and outcome["state"] == "needs_input" and name not in {"preview.json","validation.json","report.txt","parameters.json","intent.json","input_provenance.json"}:
                continue
            artifact_id = uuid.uuid4().hex
            checksum,size = digest(file),file.stat().st_size
            with self.store.connect() as db:
                db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",(artifact_id,job_id,row["owner"],str(file),name,checksum,size))
            artifacts.append({"id":artifact_id,"name":name,"sha256":checksum,"size":size})
        result["artifacts"] = artifacts
        if outcome["state"] == "complete" and not artifacts:
            raise ValueError("Worker completed without artifacts")
        if row["kind"] == "reconstruction":
            with self.store.connect() as db:
                db.execute("UPDATE scans SET reconstruction=? WHERE scan_id=? AND annotation_revision=?",(json.dumps(result),row["scan_id"],payload.get("annotation_revision",0)))
        self.store.update_job(job_id,outcome["state"],1,"CAD checks passed; physical fit remains untested" if row["kind"] == "repair" and outcome["state"] == "complete" else "Reconstruction complete" if outcome["state"] == "complete" else "More measurements or views are required",result=result)


def create_app(data_dir: str | Path | None = None, pairing_token: str | None = None, *, worker_timeout_s: float = 240, max_scan_bytes: int = 512*1024*1024, max_asset_bytes: int = 128*1024*1024, max_memory_bytes: int = 4*1024*1024*1024, workers_enabled: bool = True, comparison_timeout_s: float = 600, comparison_memory_bytes: int = 10*1024**3):
    root = Path(data_dir or os.getenv("REVERSECAD_DATA_DIR",".reversecad-data")).resolve()
    store = Store(root)
    token = pairing_token or os.getenv("REVERSECAD_PAIRING_TOKEN")
    if not token:
        token_path = root / "pairing-token"
        if token_path.exists():
            token = token_path.read_text().strip()
        else:
            token = secrets.token_urlsafe(32)
            descriptor = os.open(token_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,"w") as stream:
                stream.write(token + "\n")
    if len(token) < 16:
        raise ValueError("Pairing token must contain at least 16 characters")
    owner = hashlib.sha256(token.encode()).hexdigest()
    runner = JobRunner(store,worker_timeout_s,max_memory_bytes,comparison_timeout_s,comparison_memory_bytes)
    upload_lock = asyncio.Lock()
    live_geometry_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        if workers_enabled:
            runner.start()
        else:
            store.recover()
        yield
        if workers_enabled:
            runner.shutdown()

    app = FastAPI(title="Reverse CAD companion",version="1.0.0",lifespan=lifespan)
    app.state.store,app.state.runner = store,runner

    @app.middleware("http")
    async def request_metadata(request,call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            if request.method in {"POST","PUT","PATCH"} and "/assets/" not in request.url.path:
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 1024*1024:
                        response = JSONResponse({"error":{"code":"request_too_large","message":"JSON request exceeds the 1 MiB metadata budget"},"request_id":request.state.request_id},status_code=413)
                        response.headers["X-Request-ID"] = request.state.request_id
                        return response
                    body.extend(chunk)
                request._body = bytes(body)
            response = await call_next(request)
        except Exception:
            response = JSONResponse({"error":{"code":"internal_error","message":"Request failed; saved data was preserved"},"request_id":request.state.request_id},status_code=500)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        detail = exc.detail if isinstance(exc.detail,dict) else {"code":"request_error","message":str(exc.detail)}
        return JSONResponse({"error":detail,"request_id":request.state.request_id},status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse({"error":{"code":"invalid_request","message":"Request does not satisfy the versioned API schema","fields":[{"path":".".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors()]},"request_id":request.state.request_id},status_code=422)

    def authorize(authorization: str | None = Header(default=None)):
        if authorization is None or not authorization.startswith("Bearer ") or not hmac.compare_digest(authorization[7:],token):
            error(401,"unauthorized","Enter the companion service pairing token")
        return owner

    def scan_for(scan_id):
        try:
            identifier(scan_id)
        except ValueError as exc:
            error(400,"invalid_identifier",str(exc))
        scan = store.one("SELECT * FROM scans WHERE scan_id=? AND owner=?",(scan_id,owner))
        if not scan:
            error(404,"scan_not_found","Scan was not found for this paired client")
        return scan

    def job_for(job_id):
        job = store.one("SELECT * FROM jobs WHERE job_id=? AND owner=?",(job_id,owner))
        if not job:
            error(404,"job_not_found","Job was not found for this paired client")
        return job

    def view_job(job):
        value = {k:job[k] for k in ("job_id","state","progress","message","repair_id","revision")}
        value.update({k:json.loads(job[k]) if job[k] else None for k in ("result","error")})
        return value

    def assets(scan_id):
        folder = store.scan_dir(scan_id)
        return [{"path":p.relative_to(folder).as_posix(),"sha256":digest(p),"size":p.stat().st_size} for p in sorted(folder.rglob("*")) if p.is_file() and not p.name.startswith(".")]

    @app.get("/v1/health")
    def health():
        return {"status":"ok","api_version":1,"service":"Reverse CAD","physical_fit_validated":False}

    @app.get("/v1/capabilities",dependencies=[Depends(authorize)])
    def capabilities():
        from .cad import template_catalog
        return {"schema_version":1,"families":["bridge_handle","cup_handle","bracket"],"cube_face_exterior_demo":True,"sparse_range_rgb":{"schema_version":1,"capture_requires":"Debug research target with observed BackSparseTimeOfFlight packets","reconstruction":"COLMAP fixed calibration plus timed sparse scale","fallback":"separately labelled raw_depth_pose diagnostic"},"templates":template_catalog(),"limits":{"scan_bytes":max_scan_bytes,"asset_bytes":max_asset_bytes,"frames":240,"worker_seconds":worker_timeout_s,"worker_memory_bytes":max_memory_bytes},"provider":{"live_configured":bool(os.getenv("OPENAI_API_KEY")),"modes":["manual","fixture","live"]},"units":{"capture":"m","cad":"mm"}}

    @app.post("/v1/geometry/live",dependencies=[Depends(authorize)])
    def live_geometry(body: LiveGeometryRequest):
        # One bounded isolated worker per service. Never retain snapshots as
        # observations or mix coordinates from different AR sessions.
        from tempfile import TemporaryDirectory
        if not live_geometry_lock.acquire(blocking=False):
            error(429,"live_geometry_busy","A live proposal is already being evaluated")
        try:
            with TemporaryDirectory(prefix="reversecad-live-") as scratch:
                source=Path(scratch)/"request.json"; target=Path(scratch)/"response.json"
                source.write_text(body.model_dump_json())
                env=os.environ.copy();env.update(OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2")
                process=subprocess.Popen([sys.executable,"-m","reversecad.live_prediction",str(source),str(target)],
                    env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                try: process.wait(timeout=22)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()
                    error(504,"live_geometry_timeout","Live prediction reached its time budget; scanning remains available")
                if process.returncode or not target.is_file():
                    error(422,"live_geometry_unresolved","Live geometry could not be evaluated; capture more views")
                return json.loads(target.read_text())
        finally: live_geometry_lock.release()

    @app.post("/v1/cube/analyze",dependencies=[Depends(authorize)])
    def analyze_cube(body: dict[str, Any]):
        from .cube import CubeInputError
        from .face_first import analyze_photo_geometry
        encoded = body.get("photo_base64")
        if not isinstance(encoded, str):
            error(422,"invalid_photo","Select a cube photo before analyzing")
        try:
            photo = base64.b64decode(encoded, validate=True)
            return analyze_photo_geometry(photo, body.get("corners"))
        except (ValueError, binascii.Error, CubeInputError) as exc:
            error(422,"cube_analysis_needs_input",str(exc))

    @app.post("/v1/cube/exterior",dependencies=[Depends(authorize)])
    def make_cube_exterior(body: dict[str, Any]):
        from .cube import CubeInputError, build_outer_cubie
        try:
            width = float(body["face_width_mm"])
            analysis = body.get("analysis")
            details = analysis.get("exterior_details", {}) if isinstance(analysis, dict) else {}
            if not isinstance(details, dict):
                raise CubeInputError("Invalid exterior detail estimates")
            gap = float(body["piece_gap_mm"]) if "piece_gap_mm" in body else width * float(details.get("gap_face_fraction", .01))
            radius = float(body["corner_radius_mm"]) if "corner_radius_mm" in body else width * float(details.get("radius_face_fraction", .02))
            artifacts = build_outer_cubie(width, gap, radius, analysis)
        except (KeyError, TypeError, ValueError, CubeInputError) as exc:
            error(422,"cube_dimensions_need_input",str(exc))
        return {"schema_version":1,"scope":"exterior_envelope_only","physical_fit":"not_tested","artifacts":artifacts}

    @app.post("/v1/scans",dependencies=[Depends(authorize)])
    def create_scan(body: CreateScan):
        scan_id = body.scan_id or uuid.uuid4().hex
        project_id = body.project_id or scan_id
        with store.connect() as db:
            existing = db.execute("SELECT * FROM scans WHERE scan_id=?",(scan_id,)).fetchone()
            if existing:
                if existing["owner"] != owner:
                    error(404,"scan_not_found","Scan was not found")
                if existing["source"] != body.source or (body.project_id is not None and existing["project_id"] != project_id):
                    error(409,"scan_conflict","This scan identifier already has different metadata")
                project_id = existing["project_id"]
            else:
                db.execute("INSERT INTO scans(scan_id,project_id,owner,source,created_at) VALUES(?,?,?,?,?)",(scan_id,project_id,owner,body.source,time.time()))
        store.scan_dir(scan_id).mkdir(parents=True,exist_ok=True)
        return {"scan_id":scan_id,"project_id":project_id,"assets":assets(scan_id)}

    @app.get("/v1/scans/{scan_id}",dependencies=[Depends(authorize)])
    def inspect_scan(scan_id: str):
        scan = scan_for(scan_id)
        return {"scan_id":scan_id,"project_id":scan["project_id"],"committed":bool(scan["committed"]),"source":scan["source"],"assets":assets(scan_id),"annotation_revision":scan["annotation_revision"],"annotations":store.annotations(scan),"reconstruction":json.loads(scan["reconstruction"]) if scan["reconstruction"] else None}

    @app.put("/v1/scans/{scan_id}/assets/{asset_path:path}",dependencies=[Depends(authorize)])
    async def upload(scan_id: str,asset_path: str,request: Request,x_content_sha256: str | None = Header(default=None)):
        scan = scan_for(scan_id)
        try:
            safe_asset_path(asset_path)
        except ValueError as exc:
            error(400,"invalid_asset_path",str(exc))
        if not x_content_sha256 or not re.fullmatch(r"[a-fA-F0-9]{64}",x_content_sha256):
            error(400,"checksum_required","Provide X-Content-SHA256 for this asset")
        checksum = x_content_sha256.lower()
        target = store.scan_dir(scan_id) / asset_path
        async with upload_lock:
            scan = scan_for(scan_id)
            # Lock covers conflicting and aggregate-size checks through the atomic rename.
            if target.is_file():
                if hmac.compare_digest(digest(target),checksum):
                    return {"path":asset_path,"sha256":checksum,"size":target.stat().st_size,"already_present":True}
                error(409,"asset_conflict","An asset with this path already exists with different content; use a new scan")
            if scan["committed"]:
                error(409,"scan_committed","Committed capture observations are immutable")
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > max_asset_bytes):
                error(413,"asset_too_large","Asset exceeds configured upload size")
            stored_files = [p for p in store.scan_dir(scan_id).rglob("*") if p.is_file()]
            if len(stored_files) >= 1600:
                error(413,"asset_count_limit","Capture exceeds its file-count budget")
            used = sum(p.stat().st_size for p in stored_files)
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary = target.with_name(".upload-" + uuid.uuid4().hex)
            total = 0
            sha = hashlib.sha256()
            try:
                with temporary.open("wb") as output:
                    async for chunk in request.stream():
                        total += len(chunk)
                        if total > max_asset_bytes or used+total > max_scan_bytes:
                            error(413,"upload_limit","Asset or scan exceeds configured storage budget")
                        sha.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if not hmac.compare_digest(sha.hexdigest(),checksum):
                    error(422,"checksum_mismatch","Uploaded bytes do not match X-Content-SHA256; retry the original asset")
                os.replace(temporary,target)
            finally:
                temporary.unlink(missing_ok=True)
        return {"path":asset_path,"sha256":checksum,"size":total,"already_present":False}

    @app.post("/v1/scans/{scan_id}/commit",dependencies=[Depends(authorize)])
    def commit(scan_id: str):
        scan = scan_for(scan_id)
        try:
            manifest = validate_capture(store.scan_dir(scan_id),scan,max_scan_bytes)
        except (ValueError,OSError,ValidationError) as exc:
            error(422,"invalid_capture_package",str(exc)[:1000])
        with store.connect() as db:
            db.execute("UPDATE scans SET committed=1 WHERE scan_id=?",(scan_id,))
        return {"scan_id":scan_id,"committed":True,"complete":manifest["complete"],"frame_count":manifest["frame_count"],"warnings":[] if manifest["complete"] else ["Capture was interrupted; only committed keyframes will be processed"]}

    @app.put("/v1/scans/{scan_id}/annotations",dependencies=[Depends(authorize)])
    def annotations(scan_id: str,body: Annotations):
        scan = scan_for(scan_id)
        if not scan["committed"]:
            error(409,"scan_not_committed","Commit the validated capture before annotating")
        prior_annotations = store.annotations(scan)
        reconstruction = json.loads(scan["reconstruction"]) if scan["reconstruction"] else {}
        observations = {m["id"]:m for m in reconstruction.get("measurements",[]) if isinstance(m,dict) and "id" in m}
        # A client may confirm an existing observation, but cannot fabricate one or
        # replace its value/uncertainty. A new physical reading must be labeled manual.
        for measurement in body.measurements:
            if measurement.source in {"depth_fit","multiview","multiview_estimate"}:
                original = observations.get(measurement.id)
                if original is None or original.get("source") != measurement.source or original.get("unit") != measurement.unit or original.get("value") != measurement.value or original.get("uncertainty_mm") != measurement.uncertainty_mm:
                    error(422,"untrusted_observation","Observed dimensions must match an immutable reconstruction measurement; label a new ruler or caliper reading manual")
        normalized = body.model_dump(exclude_none=True)
        if Annotations.model_validate(prior_annotations).model_dump(exclude_none=True) == normalized:
            return {"scan_id":scan_id,"annotation_revision":scan["annotation_revision"],"annotations":normalized}
        changed_geometry = any(prior_annotations.get(key) != body.model_dump().get(key) for key in ("crop_min_m","crop_max_m","scale_reference"))
        with store.connect() as db:
            revision = db.execute("SELECT annotation_revision FROM scans WHERE scan_id=?",(scan_id,)).fetchone()[0]+1
            atomic_json(root / "scans" / scan_id / "annotations" / f"{revision}.json",body.model_dump(exclude_none=True))
            db.execute("UPDATE scans SET annotation_revision=?,reconstruction=? WHERE scan_id=?",(revision,None if changed_geometry else scan["reconstruction"],scan_id))
        return {"scan_id":scan_id,"annotation_revision":revision,"annotations":body.model_dump(exclude_none=True)}

    def enqueue(scan,kind,repair=None,repair_id=None,reconstruction_request_id=None,compare_methods=False):
        if not scan["committed"]:
            error(409,"scan_not_committed","Commit a complete, validated upload before processing")
        payload = {"kind":kind,"scan_id":scan["scan_id"],"scan_dir":str(store.scan_dir(scan["scan_id"])),"annotations":store.annotations(scan),"annotation_revision":scan["annotation_revision"]}
        payload["compare_methods"] = bool(compare_methods)
        request_id = repair.get("request_id") if repair else reconstruction_request_id
        hash_input={"kind":kind,"scan_id":scan["scan_id"],"repair":repair,"repair_id":repair_id,"annotation_revision":scan["annotation_revision"]}
        if compare_methods:hash_input["compare_methods"]=True
        request_hash = hashlib.sha256(json.dumps(hash_input,sort_keys=True).encode()).hexdigest()
        with store.connect() as db:
            if request_id:
                previous = db.execute("SELECT * FROM jobs WHERE owner=? AND request_id=?",(owner,request_id)).fetchone()
                if previous:
                    if previous["request_hash"] != request_hash:
                        error(409,"request_conflict","This request_id was already used for different inputs")
                    return view_job(dict(previous))
            if repair:
                reconstruction = json.loads(scan["reconstruction"]) if scan["reconstruction"] else None
                if reconstruction is None:
                    error(409,"reconstruction_required","Reconstruct the current annotated scan before requesting a repair")
                if repair_id:
                    prev = db.execute("SELECT scan_id,MAX(revision) AS latest FROM jobs WHERE repair_id=? AND owner=? GROUP BY scan_id",(repair_id,owner)).fetchone()
                    if not prev:
                        error(404,"repair_not_found","Repair was not found for this paired client")
                    if prev["scan_id"] != scan["scan_id"]:
                        error(409,"repair_scan_conflict","A repair revision cannot silently change its source scan")
                    revision = prev["latest"]+1
                else:
                    repair_id,revision = uuid.uuid4().hex,1
                if repair.get("candidate_id"):
                    from .candidates import propose_candidates
                    candidates = propose_candidates(reconstruction,payload["annotations"],repair["family"],repair["attachment_method"])
                    candidate = next((c for c in candidates["candidates"] if c["id"] == repair["candidate_id"]),None)
                    if candidate is None:
                        error(409,"candidate_stale","The candidate no longer matches current evidence; request candidates again")
                    repair = {**repair,"measurements":candidates.get("derived_measurements",[]),"selected_candidate":candidate}
                else:
                    # Clients cannot inject observations through arbitrary extra request fields.
                    repair = {k:v for k,v in repair.items() if k not in {"measurements","selected_candidate","annotations","reconstruction"}}
                preview = next((a for a in reconstruction.get("artifacts",[]) if a["name"] == "scan_preview.json"),None)
                stored_preview = db.execute("SELECT path,sha256 FROM artifacts WHERE artifact_id=? AND owner=?",(preview["id"],owner)).fetchone() if preview else None
                points = next((a for a in reconstruction.get("artifacts",[]) if a["name"] == "points_measurement.npz"),None)
                stored_points = db.execute("SELECT path,sha256 FROM artifacts WHERE artifact_id=? AND owner=?",(points["id"],owner)).fetchone() if points else None
                payload.update({"repair":repair,"repair_id":repair_id,"revision":revision,"reconstruction":reconstruction,"reconstruction_preview":stored_preview["path"] if stored_preview else None,"reconstruction_preview_sha256":stored_preview["sha256"] if stored_preview else None,"measurement_points_path":stored_points["path"] if stored_points else None,"measurement_points_sha256":stored_points["sha256"] if stored_points else None})
            else:
                revision = None
            job_id = uuid.uuid4().hex
            now = time.time()
            db.execute("INSERT INTO jobs(job_id,scan_id,project_id,owner,kind,state,request,repair_id,revision,request_id,request_hash,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?,?)",(job_id,scan["scan_id"],scan["project_id"],owner,kind,json.dumps(payload),repair_id,revision,request_id,request_hash,now,now))
        runner.wake.set()
        return view_job(job_for(job_id))

    @app.post("/v1/scans/{scan_id}/reconstruction",dependencies=[Depends(authorize)])
    def reconstruction(scan_id: str, body: ReconstructionRequest | None = Body(default=None)):
        return enqueue(scan_for(scan_id),"reconstruction",reconstruction_request_id=body.request_id if body else None,compare_methods=body.compare_methods if body else False)

    @app.post("/v1/scans/{scan_id}/candidates",dependencies=[Depends(authorize)])
    def candidates(scan_id: str,body: CandidateRequest):
        from .candidates import propose_candidates
        scan = scan_for(scan_id)
        if not scan["committed"] or not scan["reconstruction"]:
            error(409,"reconstruction_required","Reconstruct the current scan before requesting repair candidates")
        try:
            return propose_candidates(json.loads(scan["reconstruction"]),store.annotations(scan),body.family,body.attachment_method)
        except ValueError as exc:
            error(422,"invalid_candidate_evidence",str(exc)[:1000])

    @app.post("/v1/repairs",dependencies=[Depends(authorize)])
    def repair(body: RepairRequest):
        return enqueue(scan_for(body.scan_id),"repair",body.model_dump())

    @app.post("/v1/repairs/{repair_id}/revisions",dependencies=[Depends(authorize)])
    def revise(repair_id: str,body: RepairRequest):
        return enqueue(scan_for(body.scan_id),"repair",body.model_dump(),repair_id)

    @app.get("/v1/jobs/{job_id}",dependencies=[Depends(authorize)])
    def inspect_job(job_id: str):
        job = job_for(job_id)
        if job["state"] == "complete":
            for item in store.all("SELECT * FROM artifacts WHERE job_id=? AND owner=?",(job_id,owner)):
                file = Path(item["path"])
                if not file.is_file() or file.stat().st_size != item["size"] or digest(file) != item["sha256"]:
                    store.update_job(job_id,"failed",message="A verified artifact is missing or corrupt",error={"code":"artifact_corrupt","message":"Artifact verification failed; regenerate this revision"})
                    job = job_for(job_id)
                    break
        return view_job(job)

    @app.post("/v1/jobs/{job_id}/cancel",dependencies=[Depends(authorize)])
    def cancel(job_id: str):
        job = job_for(job_id)
        if job["state"] in ACTIVE_STATES:
            with store.connect() as db:
                db.execute("UPDATE jobs SET state='cancelled',message='Cancelled; saved capture preserved',updated_at=? WHERE job_id=?",(time.time(),job_id))
            runner.terminate(job_id)
        return view_job(job_for(job_id))

    @app.get("/v1/artifacts/{artifact_id}",dependencies=[Depends(authorize)])
    def artifact(artifact_id: str):
        item = store.one("SELECT * FROM artifacts WHERE artifact_id=? AND owner=?",(artifact_id,owner))
        if not item:
            error(404,"artifact_not_found","Artifact was not found for this paired client")
        file = Path(item["path"])
        if not file.is_file() or file.stat().st_size != item["size"] or digest(file) != item["sha256"]:
            error(409,"artifact_corrupt","Artifact verification failed; regenerate this revision")
        return FileResponse(file,filename=Path(item["name"]).name,headers={"X-Content-SHA256":item["sha256"]})

    @app.delete("/v1/projects/{project_id}",dependencies=[Depends(authorize)])
    def delete_project(project_id: str):
        rows = store.all("SELECT * FROM scans WHERE project_id=? AND owner=?",(project_id,owner))
        if not rows:
            error(404,"project_not_found","Project was not found for this paired client")
        jobs = store.all("SELECT * FROM jobs WHERE project_id=? AND owner=?",(project_id,owner))
        for job in jobs:
            cancel(job["job_id"])
        with store.connect() as db:
            for job in jobs:
                db.execute("DELETE FROM artifacts WHERE job_id=?",(job["job_id"],))
                shutil.rmtree(root / "jobs" / job["job_id"],ignore_errors=True)
            db.execute("DELETE FROM jobs WHERE project_id=? AND owner=?",(project_id,owner))
            for scan in rows:
                shutil.rmtree(root / "scans" / scan["scan_id"],ignore_errors=True)
            db.execute("DELETE FROM scans WHERE project_id=? AND owner=?",(project_id,owner))
        return {"project_id":project_id,"deleted":True,"scans_deleted":len(rows)}

    return app


app = create_app()
