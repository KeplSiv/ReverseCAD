"""CAD gates use analytic bounds/sections and independently loaded export meshes."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import cadquery as cq
import numpy as np
import pytest
import trimesh

from reversecad.cad import DEFAULTS, BOUNDS, build_shape, generate, normalize_parameters, placement_transform
from reversecad.cad_validation import export_checks, fit_checks, mesh_checks, print_checks, sampled_thickness


@pytest.mark.parametrize("family,overrides,expected", [
    ("bridge_handle", {}, [104., 24., 36.5]),
    ("bridge_handle", {"span": 117., "standoff": 43., "grip_width": 15., "grip_depth": 11., "pad_width": 29., "pad_length": 27., "pad_thickness": 5., "hole_diameter": 5.5}, [146., 27., 51.]),
    ("bridge_handle", {"span": 41., "standoff": 17., "grip_width": 7., "grip_depth": 5., "pad_width": 16., "pad_length": 13., "pad_thickness": 3., "hole_diameter": 0}, [57., 13., 21.]),
    ("bracket", {"leg_height": 0}, [30., 65., 4.]),
    ("bracket", {"width": 47., "length": 92., "leg_height": 37., "thickness": 5., "hole_spacing": 55., "hole_offset": 7., "hole_diameter": 6}, [47., 92., 37.]),
    ("bracket", {"width": 17., "length": 28., "leg_height": 0, "thickness": 2.5, "hole_spacing": 13., "hole_diameter": 3}, [17., 28., 2.5]),
])
def test_held_out_dimensions_and_real_roundtrip(tmp_path, family, overrides, expected):
    result = generate(family, overrides, tmp_path)
    # Constants here independently specified, not derived by the generator.
    original = cq.importers.importStep(str(tmp_path / "part.step"))
    bb = original.val().BoundingBox()
    assert [bb.xlen, bb.ylen, bb.zlen] == pytest.approx(expected, abs=.1)
    for suffix in ("stl", "3mf"):
        mesh = trimesh.load(str(tmp_path / f"part.{suffix}"), force="mesh", process=True)
        assert mesh.extents == pytest.approx(expected, abs=.15)
        assert mesh.is_watertight and len(mesh.split()) == 1
    assert result["validation"]["exports"]["passed"]
    assert result["validation"]["physical_fit"] == "not_tested"
    assert result["validation"]["status"] == "needs_input"
    assert all(a["sha256"] == hashlib.sha256((tmp_path / a["name"]).read_bytes()).hexdigest() for a in result["artifacts"])
    assert all((tmp_path / name).stat().st_size > 100 for name in ("part.step", "part.stl", "part.3mf", "coupon.step", "coupon.stl", "coupon.3mf", "preview.json", "report.txt", "generator.py", "part.py"))


@pytest.mark.parametrize("p", [
    {},
    {"cup_radius": 28., "cup_radius_top": 32., "contact_spacing": 44., "standoff": 23., "grip_width": 7., "grip_depth": 6., "pad_height": 12., "pad_thickness": 3., "contact_gap": .65},
    {"cup_radius": 61., "cup_radius_top": 56., "contact_spacing": 77., "standoff": 42., "grip_width": 14., "grip_depth": 10., "pad_height": 20., "pad_thickness": 5., "contact_gap": .2},
])
def test_cup_curved_saddle_and_mild_taper(tmp_path, p):
    r = generate("cup_handle", p, tmp_path, {"attachment_method": "saddle", "saddle_approved": True})
    assert r["validation"]["exports"]["passed"]
    assert r["validation"]["dimensions"]["passed"]
    assert len(r["validation"]["dimensions"]["cup_contact_radius_probes"]) == 6
    p = r["parameters"]
    solid = cq.importers.importStep(str(tmp_path / "part.step")).solids().val()
    # Independent radial section test at an angle outside the grip.
    a = .11
    for z, radius in [(-p["contact_spacing"] / 2, p["cup_radius"]), (p["contact_spacing"] / 2, p["cup_radius_top"])]:
        inside_r = radius + p["contact_gap"] + p["pad_thickness"] / 2
        void_r = radius + p["contact_gap"] - .2
        assert solid.isInside((inside_r * np.cos(a), inside_r * np.sin(a), z))
        assert not solid.isInside((void_r * np.cos(a), void_r * np.sin(a), z))
    coupon = json.loads((tmp_path / "coupon.json").read_text())
    assert coupon["type"] == "saddle_radius_contact_gap"
    assert coupon["validation"]["passed"]


@pytest.mark.parametrize("family,p,match", [
    ("unknown", {}, "unsupported_repair_type"),
    ("bridge_handle", {"span": float("nan")}, "finite"),
    ("bridge_handle", {"span": True}, "finite"),
    ("bridge_handle", {"span": 24}, "between"),
    ("bridge_handle", {"__code__": "import os"}, "unknown"),
    ("bridge_handle", {"span": 30, "pad_width": 29}, "span"),
    ("bridge_handle", {"grip_width": 28}, "pad_length"),
    ("bridge_handle", {"hole_diameter": 13, "pad_width": 12}, "wall"),
    ("cup_handle", {"contact_spacing": 20, "pad_height": 20}, "spacing"),
    ("cup_handle", {"cup_radius_top": 70}, "taper"),
    ("bracket", {"hole_spacing": 64}, "hole pattern"),
    ("bracket", {"hole_offset": 14}, "side wall"),
    ("bracket", {"leg_height": 3}, "leg_height"),
])
def test_invalid_parameters_rejected_without_changes(family, p, match):
    before = dict(p)
    with pytest.raises(ValueError, match=match):
        normalize_parameters(family, p)
    assert p == before


def test_cup_never_silently_changes_attachment_method(tmp_path):
    for context in ({}, {"attachment_method": "stub"}, {"attachment_method": "saddle", "saddle_approved": False}):
        with pytest.raises(ValueError, match="explicit user approval"):
            generate("cup_handle", {}, tmp_path, context)
    assert not list(tmp_path.iterdir())


def test_editable_source_reproduces_dimensions_and_units(tmp_path):
    result = generate("bracket", {"width": 33, "leg_height": 0}, tmp_path)
    completed = subprocess.run([sys.executable, str(tmp_path / "part.py")], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    bb = cq.importers.importStep(str(tmp_path / "edited.step")).val().BoundingBox()
    assert bb.xlen == pytest.approx(33, abs=.1)
    parameters = json.loads((tmp_path / "parameters.json").read_text())
    parameters["parameters"]["width"] = 39
    (tmp_path / "parameters.json").write_text(json.dumps(parameters))
    subprocess.run([sys.executable, str(tmp_path / "part.py")], check=True, capture_output=True, timeout=30)
    assert cq.importers.importStep(str(tmp_path / "edited.step")).val().BoundingBox().xlen == pytest.approx(39, abs=.1)
    assert result["validation"]["exports"]["3mf"]["unit"] == "millimeter"


def test_alignment_uses_contact_frames_without_scaling_dimensions(tmp_path):
    contacts = [
        {"id": "a", "point_m": [.01, -.04, .02], "normal": [0, 0, 1], "radius_mm": 12},
        {"id": "b", "point_m": [.01, .04, .02], "normal": [0, 0, 1], "radius_mm": 12},
    ]
    p = normalize_parameters("bridge_handle", {})
    matrix, report = placement_transform("bridge_handle", p, {"contacts": contacts})
    assert matrix @ np.array([-40, 0, 0, 1]) == pytest.approx([10, -40, 20, 1])
    assert matrix @ np.array([40, 0, 0, 1]) == pytest.approx([10, 40, 20, 1])
    assert report["status"] == "aligned"
    result = generate("bridge_handle", {}, tmp_path, {"contacts": contacts})
    assert result["parameters"]["span"] == 80
    mesh = trimesh.load_mesh(tmp_path / "part.stl")
    assert mesh.extents == pytest.approx([24, 104, 36.5], abs=.15)
    p["span"] = 90
    _, report = placement_transform("bridge_handle", p, {"contacts": contacts})
    assert report["residuals_mm"] == [10, 0]
    assert report["status"] == "needs_input"


def test_nonrigid_placement_rejected(tmp_path):
    transform = np.diag([2, 2, 2, 1]).flatten(order="F").tolist()
    with pytest.raises(ValueError, match="rigid"):
        generate("bracket", {}, tmp_path, {"T_object_part_mm": transform})


def test_mesh_validator_rejects_holes_and_self_intersection():
    box = trimesh.creation.box([10, 10, 10])
    assert mesh_checks(box)["passed"]
    damaged = trimesh.Trimesh(box.vertices, box.faces[:-1], process=True)
    assert not mesh_checks(damaged)["passed"]
    second = box.copy()
    second.apply_translation([4, 4, 4])
    overlap = trimesh.util.concatenate([box, second])
    report = mesh_checks(overlap)
    assert report["self_intersecting"]
    assert not report["passed"]


def test_sampled_mesh_thickness_independent_thin_wall():
    thin = trimesh.creation.box([20, 20, .6])
    report = sampled_thickness(thin, 1.2)
    assert report["minimum_sampled_mm"] == pytest.approx(.6, abs=.001)
    assert not report["passed"]
    good = trimesh.creation.box([20, 20, 3])
    assert sampled_thickness(good, 1.2)["passed"]
    assert not print_checks(good, "bracket", {}, {"build_volume_mm": [10, 10, 10]})["passed"]


def test_contact_collision_and_path_are_separate_checks():
    part = trimesh.creation.box([10, 10, 4])
    part.apply_translation([0, 0, 2])
    contact = {"id": "base", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 3}
    identity = np.eye(4)
    result = fit_checks(part, {"observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 8]], "contacts": [contact]}, identity, "bracket", {})
    assert result["collision"]["status"] == "no_sampled_interference"
    assert result["intentional_contacts"]["surface_points"] == 3
    assert result["assembly"]["status"] == "blocked"
    assert result["status"] == "needs_input"
    interference = fit_checks(part, {"observed_points_mm": [[0, 0, 2]], "contacts": [contact]}, identity, "bracket", {})
    assert interference["collision"]["excessive_contact_penetration_points"] == 1
    assert interference["status"] == "needs_input"
    clear = fit_checks(part, {"observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [12, 0, 8]], "contacts": [contact]}, identity, "bracket", {})
    assert clear["assembly"]["status"] == "sampled_path_clear"
    assert clear["status"] == "observed_geometry_checks_passed"


def test_no_observations_never_claim_fit():
    mesh = trimesh.creation.box([10, 10, 10])
    result = fit_checks(mesh, {}, np.eye(4), "bracket", {})
    assert result["status"] == "needs_input"
    assert result["assembly"]["status"] == "not_evaluated"


def test_remote_patch_does_not_pass_contact_or_fit():
    mesh = trimesh.creation.box([10, 10, 4])
    mesh.apply_translation([0, 0, 2])
    remote = {"id": "remote", "point_m": [.05, 0, 0], "normal": [0, 0, 1], "radius_mm": 3}
    result = fit_checks(mesh, {"contacts": [remote], "observed_points_mm": [[20, 0, 0]]}, np.eye(4), "bracket", {})
    assert result["intentional_contacts"]["status"] == "needs_input"
    assert result["intentional_contacts"]["patches"][0]["supported_probes"] == 0
    assert result["status"] == "needs_input"


def test_contact_gap_is_not_unbounded_tolerance():
    mesh = trimesh.creation.box([10, 10, 4])
    mesh.apply_translation([0, 0, 3])  # contact face is z=1 mm
    contact = {"id": "pad", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 3}
    context = {"contacts": [contact], "observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "contact_tolerance_mm": .1}
    correct = fit_checks(mesh, context, np.eye(4), "cup_handle", {"contact_gap": 1})
    wrong = fit_checks(mesh, context, np.eye(4), "cup_handle", {"contact_gap": .3})
    assert correct["intentional_contacts"]["status"] == "passed"
    assert wrong["intentional_contacts"]["status"] == "needs_input"


def test_critical_confirmations_match_current_dimension(tmp_path):
    contact = {"id": "base", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 10}
    context = {"contacts": [contact], "observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "measurements": [
        {"id": "hole_diameter", "value": 4, "unit": "mm", "source": "manual", "confirmed": True, "critical": True, "uncertainty_mm": .05},
        {"id": "hole_spacing", "value": 35, "unit": "mm", "source": "manual", "confirmed": True, "critical": True, "uncertainty_mm": .1},
    ]}
    correct = generate("bracket", {"leg_height": 0}, tmp_path / "correct", context)
    assert correct["validation"]["ready_for_test_print"]
    edited = generate("bracket", {"leg_height": 0, "hole_diameter": 5}, tmp_path / "edited", context)
    assert not edited["validation"]["ready_for_test_print"]
    assert any("hole_diameter" in text for text in edited["validation"]["unresolved"])


def test_unsupported_contact_plane_offsets_and_angles_need_input():
    bridge_contacts = [
        {"point_m": [-.04, 0, 0], "normal": [0, 0, 1]},
        {"point_m": [.04, 0, .02], "normal": [0, 0, 1]},
    ]
    _, report = placement_transform("bridge_handle", DEFAULTS["bridge_handle"], {"contacts": bridge_contacts})
    assert report["status"] == "needs_input"
    assert report["residuals_mm"] == [0, 20]
    parallel = [{"point_m": [0, 0, 0], "normal": [0, 0, 1]}, {"point_m": [0, .1, .02], "normal": [0, 0, 1]}]
    _, report = placement_transform("bracket", DEFAULTS["bracket"], {"contacts": parallel})
    assert report["status"] == "needs_input"
    assert report["plane_angle_error_deg"] == 90
    _, report = placement_transform("bracket", DEFAULTS["bracket"], {"contacts": parallel[:1]})
    assert report["status"] == "needs_input"
    orthogonal = [{"point_m": [0, 0, 0], "normal": [0, 0, 1]}, {"point_m": [0, -.0325, .015], "normal": [0, 1, 0]}]
    matrix, report = placement_transform("bracket", DEFAULTS["bracket"], {"contacts": orthogonal})
    assert report["status"] == "aligned"
    assert matrix == pytest.approx(np.eye(4))


def test_missing_critical_measurements_block_print_readiness(tmp_path):
    context = {"contacts": [{"id": "base", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 8}], "observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]]}
    result = generate("bracket", {"leg_height": 0}, tmp_path, context)
    assert result["validation"]["placement"]["status"] == "aligned"
    assert result["validation"]["fit"]["status"] == "observed_geometry_checks_passed"
    assert result["validation"]["status"] == "needs_input"
    assert not result["validation"]["ready_for_test_print"]
    assert any("hole_diameter" in text for text in result["validation"]["unresolved"])


def test_annotation_alone_without_nearby_observations_is_not_fit_evidence():
    mesh = trimesh.creation.box([10, 10, 10])
    contact = {"id": "invented", "point_m": [0, 0, .005], "normal": [0, 0, 1], "radius_mm": 2}
    context = {"contacts": [contact], "observed_points_mm": [[100, 0, 0], [100, 1, 0], [101, 0, 0]]}
    result = fit_checks(mesh, context, np.eye(4), "bracket", {})
    assert result["intentional_contacts"]["patches"][0]["supported_probes"] == 5
    assert result["intentional_contacts"]["patches"][0]["nearby_observed_support_points"] == 0
    assert result["intentional_contacts"]["status"] == "needs_input"
    assert result["status"] == "needs_input"


@pytest.mark.parametrize("source,uncertainty", [("design_inference", .01), ("manual", None), ("manual", 1.0)])
def test_inferred_or_uncertain_dimensions_cannot_become_verified_fit(tmp_path, source, uncertainty):
    context = {"contacts": [{"id": "base", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 8}], "observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "measurements": [
        {"id": "hole_diameter", "value": 4, "unit": "mm", "source": source, "confirmed": True, "critical": True, "uncertainty_mm": uncertainty},
        {"id": "hole_spacing", "value": 35, "unit": "mm", "source": "manual", "confirmed": True, "critical": True, "uncertainty_mm": .1},
    ]}
    result = generate("bracket", {"leg_height": 0}, tmp_path, context)
    assert not result["validation"]["ready_for_test_print"]
    assert any("hole_diameter" in unresolved for unresolved in result["validation"]["unresolved"])


@pytest.mark.parametrize("with_profile", [False, True])
def test_tapered_cup_contact_normals_do_not_tilt_axis(with_profile):
    p = normalize_parameters("cup_handle", {"cup_radius": 38, "cup_radius_top": 42, "contact_spacing": 50})
    n = np.array([1, 0, -.08]); n /= np.linalg.norm(n)
    context = {"contacts": [{"point_m": [.038, 0, -.025], "normal": n.tolist()}, {"point_m": [.042, 0, .025], "normal": n.tolist()}]}
    if with_profile:
        context["primitives"] = [{"id": "body_profile", "axis": [0, 0, 1], "center_m": [0, 0, 0], "radius_mm": 40, "taper": .08}]
    transform, report = placement_transform("cup_handle", p, context)
    assert transform == pytest.approx(np.eye(4), abs=1e-9)
    assert report["status"] == "aligned"


def test_input_hashes_and_identifiers_bind_revision(tmp_path):
    context = {"scan_id": "scan-evidence", "scan_revision": 3, "repair_id": "repair-abc", "revision": 2, "input_manifest_sha256": "a" * 64, "input_checksums_sha256": "b" * 64, "intent_sha256": "c" * 64}
    result = generate("bracket", {"leg_height": 0}, tmp_path, context)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["input_hashes"]["intent_sha256"] == "c" * 64
    assert manifest["scan_id"] == "scan-evidence"
    assert manifest["repair_revision"] == 2
    assert json.loads((tmp_path / "parameters.json").read_text())["revision_id"] == result["revision_id"]


@pytest.mark.parametrize("attachment", ["screws", "fasteners", "bolts"])
def test_fastener_attachment_cannot_silently_have_no_holes(tmp_path, attachment):
    context = {"attachment_method": attachment, "contacts": [{"id": "base", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 8}], "observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]]}
    result = generate("bracket", {"leg_height": 0, "hole_diameter": 0}, tmp_path, context)
    assert result["validation"]["fit"]["status"] == "observed_geometry_checks_passed"
    assert result["validation"]["status"] == "needs_input"
    assert not result["validation"]["ready_for_test_print"]
    assert any("fastener attachment" in text for text in result["validation"]["unresolved"])


def test_contract_multiview_measurement_source_retains_confirmation(tmp_path):
    context = {"contacts": [{"id": "base", "point_m": [0, 0, 0], "normal": [0, 0, 1], "radius_mm": 8}], "observed_points_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "measurements": [
        {"id": "hole_diameter", "value": 4, "unit": "mm", "source": "multiview", "confirmed": True, "critical": True, "uncertainty_mm": .1},
        {"id": "hole_spacing", "value": 35, "unit": "mm", "source": "multiview", "confirmed": True, "critical": True, "uncertainty_mm": .1},
    ]}
    result = generate("bracket", {"leg_height": 0}, tmp_path, context)
    assert result["validation"]["ready_for_test_print"]
    params = json.loads((tmp_path / "parameters.json").read_text())
    assert params["parameter_provenance"]["hole_diameter"]["source"] == "multiview"
    assert params["parameter_provenance"]["hole_diameter"]["confirmed"]


def test_native_ui_rotated_contacts_preserve_stl_topology_and_precision(tmp_path):
    fixture = json.loads((Path(__file__).resolve().parents[2] / "fixtures/cad/rotated-contact-precision.json").read_text())
    result = generate("bridge_handle", fixture["parameters"], tmp_path, fixture)
    assert result["parameters"] == fixture["parameters"]
    assert result["validation"]["exports"]["passed"]
    assert not result["validation"]["exports"]["stl"]["self_intersecting"]
    assert (tmp_path / "part.stl").read_text().startswith("solid ReverseCAD_mm")
    assert (tmp_path / "coupon.stl").read_text().startswith("solid ReverseCAD_mm")
    mesh = trimesh.load(tmp_path / "part.stl", force="mesh", process=True)
    independent = trimesh.load(tmp_path / "part.3mf", force="mesh", process=True)
    assert mesh.bounds == pytest.approx(independent.bounds, abs=1e-10)
    subprocess.run([sys.executable, str(tmp_path / "part.py")], check=True, capture_output=True, timeout=30)
    edited = trimesh.load(tmp_path / "edited.stl", force="mesh", process=True)
    assert mesh_checks(edited)["passed"]
    assert edited.bounds == pytest.approx(mesh.bounds, abs=1e-10)
