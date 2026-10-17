"""One isolated process per job. Only trusted modules build CAD; no user code runs."""
from __future__ import annotations

import json
import os
import resource
import sys
from pathlib import Path

from .storage import atomic_json, digest


def run(input_path: Path) -> int:
    request = json.loads(input_path.read_text())
    directory = input_path.parent
    output = directory / "output"
    output.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CPU, (int(request.get("cpu_limit_s", 180)), int(request.get("cpu_limit_s", 180)) + 2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024*1024*1024, 1024*1024*1024))

    def progress(state, value, message):
        atomic_json(directory / "progress.json", {"state":state,"progress":value,"message":message})

    try:
        scan_dir = Path(request["scan_dir"])
        annotations = request.get("annotations", {})
        import hashlib
        atomic_json(output / "input_provenance.json", {
            "schema_version":1,"scan_id":request["scan_id"],
            "manifest_sha256":digest(scan_dir / "manifest.json"),
            "checksums_sha256":digest(scan_dir / "checksums.json"),
            "annotation_revision":request.get("annotation_revision",0),"annotations":annotations,
            "repair_id":request.get("repair_id"),"revision":request.get("revision"),
            "mode":request.get("repair",{}).get("mode"),"physical_fit":"not_tested",
        })
        progress("validating_input", 0.05, "Validated capture and immutable evidence snapshot")
        if request["kind"] == "reconstruction":
            from .reconstruction import reconstruct
            progress("reconstructing", 0.15, "Fusing calibrated RGB-D observations")
            result = reconstruct(scan_dir, output, annotations)
            if not isinstance(result, dict):
                raise ValueError("Reconstruction returned an invalid result")
            state = "needs_input" if result.get("status") == "needs_input" else "complete"
            result["annotations_revision"] = request.get("annotation_revision", 0)
        else:
            from .reasoning import propose
            from .cad import generate
            progress("planning", 0.1, "Resolving repair parameters and measurement provenance")
            reconstruction = request.get("reconstruction") or {}
            repair = request["repair"]
            preview = Path(request["reconstruction_preview"]) if request.get("reconstruction_preview") else None
            if preview and (not preview.is_file() or digest(preview) != request.get("reconstruction_preview_sha256")):
                raise ValueError("Reconstruction preview is missing or corrupt; reconstruct again")
            plan = propose(scan_dir, reconstruction, {**repair,"annotations":annotations}, preview_path=preview)
            atomic_json(output / "intent.json", plan)
            if plan.get("questions") or plan.get("status") == "needs_input":
                result = {"status":"needs_input","questions":plan.get("questions",[]),"intent":plan}
                atomic_json(directory / "result.json", {"state":"needs_input","result":result})
                return 0
            progress("generating_cad", 0.35, "Constructing deterministic parametric solid")
            points = []
            points_path = request.get("measurement_points_path")
            if points_path:
                import numpy as np
                point_file = Path(points_path)
                if not point_file.is_file() or point_file.stat().st_size > 64*1024*1024 or digest(point_file) != request.get("measurement_points_sha256"):
                    raise ValueError("Native measurement points are missing or corrupt; reconstruct again")
                with np.load(point_file,allow_pickle=False) as archive:
                    native = archive["points_m"]
                    if native.ndim != 2 or native.shape[1] != 3 or len(native)>2_000_000 or not np.isfinite(native).all():
                        raise ValueError("Native measurement point contract is invalid")
                    # Bounded deterministic sampling retains native observations; TSDF/preview are not measurements.
                    points = (native[::max(1,(len(native)+99_999)//100_000)]*1000).tolist()
            context = {
                "contacts":annotations.get("contacts",[]),
                "observed_points_mm":points,
                "primitives":reconstruction.get("primitives",{}),
                "manufacturing":repair.get("manufacturing",{}),
                "scan_revision":request.get("annotation_revision",0),
                "attachment_method":plan.get("attachment_method",repair["attachment_method"]),
                "saddle_approved":repair["attachment_method"] in {"saddle","saddle_pads","adhesive_saddle"},
                "acknowledge_uncertainty":repair.get("acknowledge_uncertainty",False),
                "measurements":annotations.get("measurements",[]) + reconstruction.get("measurements",[]) + repair.get("measurements",[]),
                "scan_id":request["scan_id"],"repair_id":request["repair_id"],"revision":request["revision"],
                "input_manifest_sha256":digest(scan_dir / "manifest.json"),
                "input_checksums_sha256":digest(scan_dir / "checksums.json"),
                "intent_sha256":digest(output / "intent.json"),
            }
            result = generate(plan.get("family", repair["family"]), plan.get("parameters",repair["parameters"]), output, context)
            progress("validating_cad", 0.9, "Checking geometry, exports and artifact hashes")
            if not isinstance(result, dict):
                raise ValueError("CAD generator returned an invalid result")
            validation_file = output / "validation.json"
            validation = json.loads(validation_file.read_text()) if validation_file.exists() else result.get("validation",{})
            if validation.get("valid") is False or validation.get("passed") is False or validation.get("status") in ("failed", "invalid"):
                raise ValueError("CAD validation rejected the proposed solid")
            required = ("part.step","part.stl","part.py","parameters.json","preview.json","validation.json","manifest.json")
            missing = [name for name in required if not (output / name).is_file() or not (output / name).stat().st_size]
            if missing:
                raise ValueError("CAD outputs missing: " + ", ".join(missing))
            result.update({"repair_id":request["repair_id"],"revision":request["revision"],"family":plan.get("family",repair["family"]),"parameters":result.get("parameters",plan.get("parameters",repair["parameters"])),"validation":validation,"intent":plan,"provider_status":plan.get("provider_status","unknown")})
            unresolved = validation.get("status") == "needs_input"
            result["prototype_export_acknowledged"] = repair.get("acknowledge_uncertainty",False)
            state = "needs_input" if unresolved and not result["prototype_export_acknowledged"] else "complete"
        result["worker_metrics"] = {"peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)}
        atomic_json(directory / "result.json", {"state":state,"result":result})
        return 0
    except Exception as exc:
        # Never echo payloads, environment values, images, or arbitrary provider exceptions.
        code = getattr(exc, "code", "invalid_geometry_or_evidence" if isinstance(exc, ValueError) else "worker_failure")
        message = str(exc)[:1000] if isinstance(exc, ValueError) else f"Processing failed ({type(exc).__name__}); scan retained for retry"
        atomic_json(directory / "result.json", {"state":"failed","error":{"code":code,"message":message}})
        return 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
