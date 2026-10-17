#!/usr/bin/env python3
"""Exercise the real authenticated service from raw capture to downloaded CAD.

This is a software replay, never a physical measurement or fit result.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",default="http://127.0.0.1:8767")
    p.add_argument("--token-file",type=Path,default=ROOT/"var/service/pairing-token")
    p.add_argument("--scan",type=Path,default=ROOT/"fixtures/sample_scan")
    p.add_argument("--output",type=Path,default=ROOT/"reports/http-integration")
    p.add_argument("--family",choices=["all","bridge_handle","cup_handle","bracket"],default="all")
    p.add_argument("--live",action="store_true",help="Explicitly send selected sample RGB evidence to OpenAI using configured server key")
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((a.scan/"manifest.json").read_text());sid=manifest["scan_id"]
    with httpx.Client(base_url=a.url,headers={"Authorization":"Bearer "+a.token_file.read_text().strip()},timeout=45) as c:
        def call(method,path,**kw):
            r=c.request(method,path,**kw)
            if not r.is_success: raise RuntimeError(f"{method} {path}: {r.status_code} {r.text}")
            return r.json()
        def wait(job):
            until=time.monotonic()+300
            while time.monotonic()<until:
                j=call("GET",f"/v1/jobs/{job['job_id']}")
                if j["state"] in ["complete","needs_input","failed","cancelled"]:
                    (a.output/f"job-{j['job_id']}.json").write_text(json.dumps(j,indent=2))
                    if j["state"] in ["failed","cancelled"]: raise RuntimeError(j)
                    return j
                time.sleep(.3)
            raise TimeoutError("Job exceeded CLI wait limit")
        caps=call("GET","/v1/capabilities")
        call("POST","/v1/scans",json={"scan_id":sid,"source":manifest["source"]})
        existing={f["path"]:f["sha256"] for f in call("GET",f"/v1/scans/{sid}")["assets"]}
        for file in sorted(a.scan.rglob("*")):
            if not file.is_file():continue
            relative=file.relative_to(a.scan).as_posix();checksum=sha(file)
            if existing.get(relative)!=checksum:
                with file.open("rb") as f:
                    call("PUT",f"/v1/scans/{sid}/assets/{relative}",content=f,headers={"X-Content-SHA256":checksum})
        call("POST",f"/v1/scans/{sid}/commit")
        recon=wait(call("POST",f"/v1/scans/{sid}/reconstruction"))
        results=[]
        families=caps["families"] if a.family=="all" else [a.family]
        for family in families:
            # Explicit manually chosen design dimensions. They are not recovered measurements.
            request={"scan_id":sid,"family":family,"parameters":caps["templates"][family]["defaults"],"attachment_method":"saddle" if family=="cup_handle" else "screws","mode":"live" if a.live else "manual","provider_consent":a.live,"acknowledge_uncertainty":True}
            job=wait(call("POST","/v1/repairs",json=request))
            if job["state"]!="complete":raise RuntimeError(f"Repair needs input: {job}")
            folder=a.output/family;folder.mkdir(exist_ok=True)
            for asset in job["result"]["artifacts"]:
                dest=folder/asset["name"];dest.parent.mkdir(parents=True,exist_ok=True)
                response=c.get(f"/v1/artifacts/{asset['id']}");response.raise_for_status()
                dest.write_bytes(response.content)
                if sha(dest)!=asset["sha256"]:raise RuntimeError("Artifact hash mismatch")
            import cadquery as cq
            import trimesh
            solid=cq.importers.importStep(str(folder/"part.step")).val()
            mesh=trimesh.load(folder/"part.stl",force="mesh")
            if not solid.isValid() or len(solid.Solids())!=1 or not mesh.is_watertight:raise RuntimeError("Downloaded CAD failed independent reimport")
            results.append({"family":family,"job_id":job["job_id"],"artifacts_downloaded":len(job["result"]["artifacts"]),"step_valid":True,"stl_watertight":True,"provider_status":job["result"].get("provider_status"),"physical_fit":"not_tested"})
        report={"source":"real HTTP service with synthetic raw RGB-D replay","reconstruction_state":recon["state"],"scan_id":sid,"results":results}
        (a.output/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,indent=2))
if __name__=="__main__":main()
