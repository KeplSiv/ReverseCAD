#!/usr/bin/env python3
"""Evaluate production reconstruction against separate analytic geometry oracles.

Each stage uses the identical capture bytes, runs in a fresh process, and receives
only the raw package path. Ground-truth dimensions never enter reconstruction.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
STAGES=("raw_depth_pose","filtered_fusion","rgb_assisted")


def box_sdf(points,shape):
    lo,hi=np.array(shape["min_m"]),np.array(shape["max_m"])
    q=np.abs(points-(lo+hi)/2)-(hi-lo)/2
    return np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(np.max(q,axis=1),0)


def cylinder_sdf(points,radius,ylo,yhi):
    q=np.column_stack([np.linalg.norm(points[:,[0,2]],axis=1)-radius,np.abs(points[:,1]-(yhi+ylo)/2)-(yhi-ylo)/2])
    return np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(np.max(q,axis=1),0)


def primitive_sdf(points,shape):
    if shape["kind"]=="box":return box_sdf(points,shape)
    outer=cylinder_sdf(points,shape["radius_m"],shape["bottom_y_m"],shape["top_y_m"])
    # Subtract an open-ended inner cylinder to model the hollow cup.
    inner=cylinder_sdf(points,shape["inner_radius_m"],shape["bottom_y_m"]+shape["bottom_thickness_m"],shape["top_y_m"]+1)
    return np.maximum(outer,-inner)


def signed_surface_distance(points,primitives):
    # Analytic CSG distance gives exact zero on true exposed surfaces. No ICP or
    # scale alignment is performed; axis/mirroring/scale mistakes remain visible.
    return np.min([primitive_sdf(points,p) for p in primitives],axis=0)


def sample_surface(primitives,spacing=.0015):
    samples=[]
    for index,shape in enumerate(primitives):
        chunks=[]
        if shape["kind"]=="box":
            lo,hi=np.asarray(shape["min_m"]),np.asarray(shape["max_m"])
            for axis in range(3):
                rest=[i for i in range(3) if i!=axis]
                arrays=[np.linspace(lo[i],hi[i],max(2,int(np.ceil((hi[i]-lo[i])/spacing)))) for i in rest]
                a,b=np.meshgrid(*arrays,indexing="ij")
                for edge in [lo[axis],hi[axis]]:
                    v=np.zeros((a.size,3));v[:,axis]=edge;v[:,rest[0]]=a.ravel();v[:,rest[1]]=b.ravel();chunks.append(v)
        else:
            ylo,yhi=shape["bottom_y_m"],shape["top_y_m"]
            r,ri=shape["radius_m"],shape["inner_radius_m"]
            angles=np.linspace(0,2*np.pi,max(64,int(2*np.pi*r/spacing)),endpoint=False)
            for radius,low in [(r,ylo),(ri,ylo+shape["bottom_thickness_m"])]:
                aa,yy=np.meshgrid(angles,np.linspace(low,yhi,max(2,int((yhi-low)/spacing))))
                chunks.append(np.column_stack([radius*np.cos(aa).ravel(),yy.ravel(),radius*np.sin(aa).ravel()]))
            for y,rmin,rmax in [(ylo,0,r),(ylo+shape["bottom_thickness_m"],0,ri),(yhi,ri,r)]:
                aa,rr=np.meshgrid(angles,np.linspace(rmin,rmax,max(2,int((rmax-rmin)/spacing))))
                chunks.append(np.column_stack([(rr*np.cos(aa)).ravel(),np.full(aa.size,y),(rr*np.sin(aa)).ravel()]))
        sampled=np.concatenate(chunks)
        exposed=np.ones(len(sampled),dtype=bool)
        for j,other in enumerate(primitives):
            if index!=j:exposed&=primitive_sdf(sampled,other)>=-1e-8
        samples.append(sampled[exposed])
    return np.concatenate(samples)


def evaluate(result,output:Path,oracle):
    points=None
    # Prefer stage's actual fused samples over the phone preview's bounded sample.
    choices=[output/"points_filtered.npz",output/"points_raw.npz"]
    for path in choices:
        if path.exists():
            data=np.load(path)
            if "points_m" in data:points=data["points_m"];break
    if points is None:
        preview=json.loads((output/"scan_preview.json").read_text())
        points=np.asarray(preview["vertices"],dtype=float)/1000
    points=np.asarray(points).reshape((-1,3))
    finite=np.isfinite(points).all(axis=1)
    points=points[finite]
    if not len(points):return {"evaluated_points":0,"dimension_gate_passed":False}
    if len(points)>50000:points=points[np.linspace(0,len(points)-1,50000,dtype=int)]
    errors=np.abs(signed_surface_distance(points,oracle["primitives"]))*1000
    reference=sample_surface(oracle["primitives"])
    distances=cKDTree(points).query(reference,workers=1)[0]*1000
    measured=np.asarray(result["bounds_mm"]["extent"])
    true=np.asarray(oracle["bounds_mm"]["extent"])
    error=np.abs(measured-true)
    position_errors={edge:np.abs(np.asarray(result["bounds_mm"][edge])-np.asarray(oracle["bounds_mm"][edge])) for edge in ("min","max")}
    limits=np.maximum(.5,true*.01)
    feature_checks=[]
    if oracle["scene"]=="cup":
        true_radius=next(p["radius_m"]*1000 for p in oracle["primitives"] if p["kind"]=="cup")
        cylinders=[p for p in result.get("primitives",[]) if p.get("type") in ("cylinder","frustum")]
        fitted=cylinders[0]["radius_mm"] if cylinders else None
        limit=max(.5,true_radius*.01)
        feature_checks.append({"feature":"exposed_cup_outer_radius","reference_mm":true_radius,"estimated_mm":fitted,"absolute_error_mm":abs(fitted-true_radius) if fitted is not None else None,"limit_mm":limit,"passed":fitted is not None and abs(fitted-true_radius)<=limit})
    return {"evaluated_points":len(points),"dimension_mm":measured.tolist(),"reference_dimension_mm":true.tolist(),
            "absolute_dimension_error_mm":error.tolist(),"bounds_min_error_mm":position_errors["min"].tolist(),"bounds_max_error_mm":position_errors["max"].tolist(),"relative_dimension_error_percent":(100*error/true).tolist(),"dimension_limits_mm":limits.tolist(),
            "dimension_gate_passed":bool(np.all(error<=limits)) and all(c["passed"] for c in feature_checks),"object_frame_position_gate_passed":all(bool(np.all(v<=limits)) for v in position_errors.values()),"primitive_dimension_checks":feature_checks,"surface_error_rms_mm":float(np.sqrt(np.mean(errors**2))),
            "surface_error_median_mm":float(np.median(errors)),"surface_error_p95_mm":float(np.quantile(errors,.95)),
            "full_analytic_surface_coverage_within_2mm":float(np.mean(distances<=2)),"full_analytic_surface_samples":len(reference),
            "alignment":"none", "scale_error_method":"100*(norm(measured_extent)/norm(reference_extent)-1); descriptive size-scale discrepancy, no geometry alignment or calibration fit", "scale_error_percent":float(100*(np.linalg.norm(measured)/np.linalg.norm(true)-1))}


def worker(package:Path,output:Path,stage):
    # Ground truth intentionally unavailable to this function.
    sys.path.insert(0,str(ROOT/"backend"))
    implementation_hashes={name:hashlib.sha256((ROOT/"backend"/"reversecad"/name).read_bytes()).hexdigest() for name in ("reconstruction.py","geometry.py")}
    from reversecad.reconstruction import reconstruct
    started=time.perf_counter()
    try:
        result=reconstruct(package,output,stage=stage)
        record={"state":"completed","result":result}
    except Exception as exc:
        record={"state":"rejected" if isinstance(exc,ValueError) else "failed","error_type":type(exc).__name__,"error":str(exc)}
    record["runtime_seconds"]=time.perf_counter()-started
    record["input_checksums_sha256"]=hashlib.sha256((package/"checksums.json").read_bytes()).hexdigest()
    record["implementation_sha256"]=implementation_hashes
    record["dependency_versions"]={name:importlib.metadata.version(name) for name in ("numpy","opencv-python-headless","open3d")}

    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    record["peak_resident_memory_bytes"]=rss if sys.platform=="darwin" else rss*1024
    output.mkdir(parents=True,exist_ok=True)
    (output/"worker_result.json").write_text(json.dumps(record,indent=2)+"\n")


def run_benchmark(fixtures:Path,oracles:Path,output:Path,names=None,stages=STAGES,resume=False):
    output.mkdir(parents=True,exist_ok=True)
    records=[]
    inputs=sorted(fixtures.iterdir())
    for package in inputs:
        if not package.is_dir() or (names and package.name not in names):continue
        oracle_path=oracles/f"{package.name}.json"
        if not oracle_path.exists():continue
        oracle=json.loads(oracle_path.read_text())
        for stage in stages:
            dest=output/"runs"/package.name/stage
            dest.mkdir(parents=True,exist_ok=True)
            start=time.perf_counter()
            env=dict(os.environ,OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1")
            existing=dest/"worker_result.json"
            saved=json.loads(existing.read_text()) if resume and existing.exists() else {}
            current_hashes={name:hashlib.sha256((ROOT/"backend"/"reversecad"/name).read_bytes()).hexdigest() for name in ("reconstruction.py","geometry.py")}
            reusable=(saved.get("implementation_sha256")==current_hashes and saved.get("input_checksums_sha256")==hashlib.sha256((package/"checksums.json").read_bytes()).hexdigest())
            if reusable:
                record=saved
            else:
              with (dest/"process.log").open("w") as log:
                try:
                    execution=subprocess.run([sys.executable,__file__,"--worker",str(package),str(dest),stage],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=120)
                    if (dest/"worker_result.json").exists():record=json.loads((dest/"worker_result.json").read_text())
                    else:record={"state":"process_failed","exit_code":execution.returncode}
                except subprocess.TimeoutExpired:record={"state":"timeout"}
            record.update({"fixture":package.name,"scene":oracle["scene"],"degradation":oracle["degradation"],"heldout_dimensions":oracle["heldout_dimensions"],"stage":stage,"wall_seconds_this_evaluation":time.perf_counter()-start,"reused_matching_result":reusable,"oracle_file":str(oracle_path.relative_to(ROOT)) if oracle_path.is_relative_to(ROOT) else str(oracle_path)})
            if record["state"]=="completed":
                result=record.pop("result")
                record["reconstruction_status"]=result["status"]
                record["warnings"]=result.get("warnings",[])
                record["reconstruction_metrics"]=result.get("metrics",{})
                try:record.update(evaluate(result,dest,oracle))
                except Exception as exc:record["evaluation_error"]=f"{type(exc).__name__}: {exc}"
            records.append(record)
            print(json.dumps({k:record.get(k) for k in ["fixture","stage","state","dimension_gate_passed","absolute_dimension_error_mm","runtime_seconds"]}),flush=True)
    clean=[r for r in records if r["degradation"]=="clean"]
    summary={"schema_version":1,"scope":"synthetic software validation only; not real iPhone accuracy or printed fit", "stage_comparison":"Identical raw input hashes across stages; separate process per stage. No similarity/rigid alignment.",
             "dimension_gate":"abs(error) <= max(0.5 mm, 1% reference length) on full clean exposed bounds; all axes must pass", "coverage_definition":"Fraction of all exposed analytic union-surface samples within 2mm of reconstructed points. Includes surfaces unseen by camera, so this is conservative full-object coverage, not a guarantee of hidden geometry.",
             "memory_definition":"Peak process resident memory including imported native libraries, per fresh process; runtime excludes import and includes reconstruction only.",
             "oracles":"Analytic primitive definitions outside scan packages; never passed to production reconstruction.",
             "process_completion_rate":sum(r["state"] in ("completed","rejected") for r in records)/max(1,len(records)),
             "reconstruction_ready_count":sum(r.get("reconstruction_status")=="ready" for r in records),
             "needs_input_count":sum(r.get("reconstruction_status")=="needs_input" for r in records),
             "explicit_rejection_count":sum(r["state"]=="rejected" for r in records),
             "process_failure_count":sum(r["state"] not in ("completed","rejected") for r in records),
             "evaluation_error_count":sum("evaluation_error" in r for r in records),
             "clean_stage_runs":len(clean),"clean_stage_passes":sum(r.get("dimension_gate_passed",False) for r in clean),"clean_all_pass":bool(clean) and all(r.get("dimension_gate_passed",False) for r in clean),"total_stage_runs":len(records),"records":records}
    (output/"benchmark.json").write_text(json.dumps(summary,indent=2)+"\n")
    write_summary(summary,output/"summary.md")
    return summary


def write_summary(summary,path):
    records=summary["records"]
    lines=["# Synthetic reconstruction benchmark", "", summary["scope"], "", f"Clean dimension gates: **{summary['clean_stage_passes']}/{summary['clean_stage_runs']} stage runs passed**. Total stage runs: {summary['total_stage_runs']}.", "", "No alignment or scale fitting was used. Both configured scene sizes are evaluated independently. Baseline, filtered fusion, and RGB-assisted checks receive identical input bytes.", "", "| Clean-stage metric | Raw depth/pose | Filtered fusion | RGB-assisted |", "| --- | ---: | ---: | ---: |"]
    subsets=[[r for r in records if r["degradation"]=="clean" and r["stage"]==s and r.get("evaluated_points",0)] for s in STAGES]
    specs=[("Largest absolute axis error (mm)",lambda rs:max(max(r["absolute_dimension_error_mm"]) for r in rs)),("Largest fitted primitive error (mm)",lambda rs:max((c["absolute_error_mm"] for r in rs for c in r.get("primitive_dimension_checks",[]) if c.get("absolute_error_mm") is not None),default=0)),("Mean surface RMS error (mm)",lambda rs:np.mean([r["surface_error_rms_mm"] for r in rs])),("Mean full-surface coverage within 2mm",lambda rs:np.mean([r["full_analytic_surface_coverage_within_2mm"] for r in rs])),("Mean runtime (s)",lambda rs:np.mean([r["runtime_seconds"] for r in rs])),("Maximum process RSS (MiB)",lambda rs:max(r["peak_resident_memory_bytes"] for r in rs)/2**20)]
    for label,operation in specs:
        values=[f"{operation(rs):.6f}" if rs else "not evaluated" for rs in subsets]
        lines.append("| "+label+" | "+" | ".join(values)+" |")
    lines += ["", "The raw synthetic clean observations already lie on the analytic surfaces. Filtering or RGB checks need not improve this idealized baseline; see measured values rather than assuming an improvement. Coverage includes occluded surfaces and is not a measured assurance of completeness.", "", "| Production RGB-assisted fixture | State | Largest axis error (mm) | Surface P95 (mm) |", "| --- | --- | ---: | ---: |"]
    for r in records:
        if r["stage"]!="rgb_assisted":continue
        error=f"{max(r['absolute_dimension_error_mm']):.4f}" if r.get("absolute_dimension_error_mm") else "—"
        p95=f"{r['surface_error_p95_mm']:.4f}" if "surface_error_p95_mm" in r else "—"
        lines.append(f"| {r['fixture']} | {r.get('reconstruction_status',r['state'])} | {error} | {p95} |")
    lines += ["", "Per-run errors, warnings, code/input hashes, dependency versions, timing, memory, and geometric metrics are in `benchmark.json`; original worker results and logs are under `runs`. Degradation errors are diagnostics, not an assertion that an unknown real sensor bias is detectable. No run verifies phone sensing, real dimensional accuracy, or printed fit.", ""]
    path.write_text("\n".join(lines))


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--worker":worker(Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4]);return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures",type=Path,default=ROOT/"fixtures"/"generated")
    parser.add_argument("--oracles",type=Path,default=ROOT/"fixtures"/"oracles")
    parser.add_argument("--output",type=Path,default=ROOT/"reports"/"benchmark")
    parser.add_argument("--names",nargs="*")
    parser.add_argument("--resume",action="store_true",help="Reuse recorded worker results only when code and input hashes are identical")
    parser.add_argument("--stages",nargs="*",default=list(STAGES),choices=STAGES)
    args=parser.parse_args()
    summary=run_benchmark(args.fixtures,args.oracles,args.output,args.names,args.stages,args.resume)
    print(json.dumps({k:v for k,v in summary.items() if k!="records"},indent=2))
    if summary["process_failure_count"] or summary["evaluation_error_count"] or (summary["clean_stage_runs"] and not summary["clean_all_pass"]):raise SystemExit(1)


if __name__=="__main__":main()
