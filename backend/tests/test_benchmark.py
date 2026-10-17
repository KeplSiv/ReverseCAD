"""Independent fixture/benchmark contracts and held-out reconstruction gates."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
from generate_fixtures import generate_package, intersect_box, intersect_cup, render
from benchmark import evaluate, signed_surface_distance, sample_surface


def test_renderer_known_camera_ray_not_round_trip():
    # Camera at (0,0,.3), looking along -z. A 40mm box front is z=.02:
    # center ray depth must therefore be .28 meters; x=1px/f=10 has x=.028.
    pose=np.eye(4);pose[2,3]=.3
    shape={"kind":"box","min_m":[-.05,-.03,-.02],"max_m":[.05,.03,.02]}
    depth,rgb,mask=render([shape],pose,3,3,10,10,1,1)
    assert depth[1,1]==pytest.approx(.28,abs=1e-8)
    assert depth[1,2]==pytest.approx(.28,abs=1e-8)
    assert mask[1,2]
    assert signed_surface_distance(np.array([[.028,0,.02]]),[shape])[0]==pytest.approx(0,abs=1e-12)


def test_analytic_oracle_catches_scale_and_mirroring():
    shape={"kind":"box","min_m":[.02,.03,.04],"max_m":[.08,.06,.09]}
    on_surface=np.array([[.08,.05,.06]])
    assert signed_surface_distance(on_surface,[shape])[0]==pytest.approx(0)
    assert signed_surface_distance(on_surface*1.1,[shape])[0]>.0079
    mirrored=on_surface.copy();mirrored[:,0]*=-1
    assert signed_surface_distance(mirrored,[shape])[0]>.099


def test_hollow_cup_oracle_and_rays():
    cup={"kind":"cup","radius_m":.04,"inner_radius_m":.037,"bottom_y_m":-.05,"top_y_m":.05,"bottom_thickness_m":.004}
    points=np.array([[.04,0,0],[.037,0,0],[0,-.046,0],[0,0,0]])
    distances=signed_surface_distance(points,[cup])
    assert distances[:3]==pytest.approx([0,0,0],abs=1e-10)
    assert distances[3]>.03 # Empty interior, not a solid cylinder.
    depth=intersect_cup(np.array([0,.2,0]),np.array([[[0,-1,0]]],float),cup)
    assert depth[0,0]==pytest.approx(.246)


def test_package_has_no_ground_truth_and_has_exact_hashes(tmp_path):
    oracle=generate_package(tmp_path/"scan",name="asymmetric",heldout=True)
    package=tmp_path/"scan"
    checksums=json.loads((package/"checksums.json").read_text())
    assert all(hashlib.sha256((package/name).read_bytes()).hexdigest()==digest for name,digest in checksums.items())
    assert "primitives" not in (package/"manifest.json").read_text()
    assert not any("oracle" in p.name or "truth" in p.name for p in package.rglob("*"))
    frame=json.loads((package/"frames.jsonl").read_text().splitlines()[0])
    assert frame["depth_width"]*4==frame["depth_row_bytes"]
    assert frame["rgb_width"]==2*frame["depth_width"]
    assert len(frame["T_world_camera"])==16
    assert oracle["heldout_dimensions"] is True
    assert oracle["bounds_mm"]["extent"][0]==pytest.approx(93)


def test_origin_reset_requires_distinct_segment(tmp_path):
    generate_package(tmp_path/"scan",degradation="origin_reset")
    manifest=json.loads((tmp_path/"scan"/"manifest.json").read_text())
    frames=[json.loads(line) for line in (tmp_path/"scan"/"frames.jsonl").read_text().splitlines()]
    assert len(manifest["segments"])==2
    assert manifest["segments"][1]["registered"] is False
    assert frames[0]["segment_id"]!=frames[-1]["segment_id"]


def test_oracle_samples_only_exposed_union_faces():
    left={"kind":"box","min_m":[0,0,0],"max_m":[.01,.01,.01]}
    right={"kind":"box","min_m":[.005,0,0],"max_m":[.015,.01,.01]}
    samples=sample_surface([left,right])
    assert not np.any((np.abs(samples[:,0]-.005)<1e-12)&(samples[:,1]>.001)&(samples[:,1]<.009)&(samples[:,2]>.001)&(samples[:,2]<.009))


@pytest.mark.parametrize("name,heldout",[("calibration_block",False),("calibration_block",True),("broken_bridge",True),("cup",True),("bracket",True),("asymmetric",True)])
def test_clean_heldout_production_reconstruction_gate(tmp_path,name,heldout):
    from reversecad.reconstruction import reconstruct
    package=tmp_path/"scan"
    oracle=generate_package(package,name=name,heldout=heldout)
    output=tmp_path/"output"
    result=reconstruct(package,output)
    report=evaluate(result,output,oracle)
    assert report["dimension_gate_passed"],report
    assert report["surface_error_p95_mm"]<=.5,report
    assert all(m.get("source")!="ground_truth" for m in result["measurements"])


@pytest.mark.parametrize("degradation",["origin_reset","missing_depth","blur","mismatched_image_sizes","partial_coverage","incomplete","pose_drift"])
def test_degraded_inputs_never_claim_verified_fit(tmp_path,degradation):
    from reversecad.reconstruction import reconstruct
    package=tmp_path/"scan"
    generate_package(package,degradation=degradation)
    try:result=reconstruct(package,tmp_path/"output")
    except ValueError:return
    assert result["status"]=="needs_input"
    assert not result.get("verified_fit",False)


@pytest.mark.parametrize("degradation",["padded_stride","portrait_raw","registered_reset","missing_confidence","depth_holes","invalid_depth","unmasked","timestamp_gap"])
def test_capture_contract_variations_preserve_metric_geometry(tmp_path,degradation):
    from reversecad.reconstruction import reconstruct
    package=tmp_path/"scan"
    oracle=generate_package(package,degradation=degradation)
    output=tmp_path/"output"
    result=reconstruct(package,output)
    report=evaluate(result,output,oracle)
    assert report["dimension_gate_passed"],report


def test_textured_multiview_uses_real_metric_triangulation(tmp_path):
    from reversecad.reconstruction import reconstruct
    package=tmp_path/"scan"
    oracle=generate_package(package,degradation="rgb_textured")
    output=tmp_path/"output"
    result=reconstruct(package,output)
    rgb=result["metrics"]["rgb"]
    assert rgb["status"]=="supported",rgb
    assert rgb["triangulated_metric_anchors"]>=100,rgb
    assert rgb["median_reprojection_error_px"]<3,rgb
    assert rgb["pose_refinement"]=="none; fixed metric poses"
    assert evaluate(result,output,oracle)["dimension_gate_passed"]
