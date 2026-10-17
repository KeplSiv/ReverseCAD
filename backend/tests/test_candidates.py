"""Independent analytic interface examples; no rendered ground truth enters inputs."""
import copy
import math

import pytest

from reversecad.candidates import propose_candidates


def contact(point, normal=(0, 0, 1), name="c"):
    return {"id": name, "point_m": point, "normal": list(normal), "radius_mm": 8}


def reconstruction(**kwargs):
    return {"status": "ready", "observations": {"accepted_frames": ["f1", "f2", "f3"]},
            "primitives": [], "measurements": [], **kwargs}


def bridge(span=83):
    return {"contacts": [contact([-.5 * span / 1000, 0, 0], name="left"),
                         contact([.5 * span / 1000, 0, 0], name="right")]}


def measured(name, value):
    return {"id": "manual_" + name, "name": name, "value": value, "unit": "mm",
            "source": "manual", "confirmed": True, "critical": True, "uncertainty_mm": .1}


def cup():
    # At z=-20mm, r=35 + .1*(-20)=33mm. At z=40mm, r=39mm.
    profile = {"id": "body_profile", "type": "frustum", "center_m": [.01, .02, .03],
               "axis": [0, 0, 1], "radius_mm": 35, "taper": .1,
               "height_range_mm": [-30, 50], "fit_residual_mm": .2,
               "observation_ids": ["f1", "f2", "f3"]}
    annotation = {"contacts": [contact([.043, .02, .01], (1, 0, 0), "lower"),
                               contact([.049, .02, .07], (1, 0, 0), "upper")]}
    return reconstruction(primitives=[profile]), annotation


@pytest.mark.parametrize("span", [31.5, 83, 147.25, 198])
def test_bridge_uses_selected_spacing_and_two_explicit_design_variants(span):
    rec, ann = reconstruction(), bridge(span)
    snapshot = copy.deepcopy((rec, ann))
    result = propose_candidates(rec, ann, "bridge_handle", "screws")
    assert len(result["candidates"]) == 2
    first, second = result["candidates"]
    assert first["parameters"]["span"] == pytest.approx(span, abs=1e-9)
    assert second["parameters"]["span"] == pytest.approx(span, abs=1e-9)
    assert second["parameters"]["standoff"] > first["parameters"]["standoff"]
    assert first["parameters"]["hole_diameter"] == 0
    assert first["provenance"]["span"]["source"] == "measurement"
    assert first["provenance"]["span"]["confirmed"] is False
    assert first["provenance"]["standoff"]["source"] == "design_inference"
    assert result["status"] == "needs_input" and any("hole" in q for q in result["questions"])
    assert result["physical_fit"] == "not_tested"
    assert (rec, ann) == snapshot


def test_confirmed_constraints_are_retained_and_candidates_remain_editable():
    ann = bridge(83)
    ann["measurements"] = [measured("span", 85.5), measured("hole_diameter", 4.3)]
    result = propose_candidates(reconstruction(), ann, "bridge_handle", "screws")
    assert result["candidates"][0]["parameters"]["span"] == 85.5
    assert result["candidates"][0]["parameters"]["hole_diameter"] == 4.3
    assert result["candidates"][0]["provenance"]["span"]["measurement_id"] == "manual_span"
    assert any("differs" in q for q in result["questions"])
    assert result["derived_measurements"][0]["value"] == pytest.approx(83)


def test_no_silent_resize_of_out_of_bounds_measured_span():
    result = propose_candidates(reconstruction(), bridge(230), "bridge_handle", "adhesive")
    assert result["candidates"] == []
    assert result["derived_measurements"][0]["value"] == pytest.approx(230)
    assert any("between" in q for q in result["questions"])


def test_unknown_or_unresolved_geometry_requests_evidence():
    assert propose_candidates({}, {}, "knob", "screws")["status"] == "unsupported"
    assert propose_candidates({}, {}, "bridge_handle", "screws")["candidates"] == []
    assert propose_candidates({}, {}, "cup_handle", "stubs")["candidates"] == []
    ann = bridge()
    ann["contacts"][1]["point_m"][2] = .02
    assert propose_candidates(reconstruction(), ann, "bridge_handle", "screws")["candidates"] == []
    ann = bridge()
    ann["contacts"][1]["normal"] = [0, 1, 0]
    assert propose_candidates(reconstruction(), ann, "bridge_handle", "screws")["candidates"] == []


def test_cup_uses_fit_at_each_selected_height_not_default_radius():
    rec, ann = cup()
    result = propose_candidates(rec, ann, "cup_handle", "saddle")
    assert len(result["candidates"]) == 2
    for candidate in result["candidates"]:
        assert candidate["parameters"]["cup_radius"] == pytest.approx(33)
        assert candidate["parameters"]["cup_radius_top"] == pytest.approx(39)
        assert candidate["parameters"]["contact_spacing"] == pytest.approx(60)
        assert candidate["parameters"]["contact_gap"] == .4
        assert len(candidate["measurement_refs"]) == 3
        assert candidate["provenance"]["contact_gap"]["source"] == "design_inference"
    assert all(m["source"] == "depth_fit" and not m["confirmed"] for m in result["derived_measurements"])


def test_cup_rotated_axis_and_translated_origin_preserve_metric_radii():
    rec, ann = cup()
    # Independent 90-degree Y rotation maps (x,y,z) to (z,y,-x).
    rotate = lambda p: [p[2], p[1], -p[0]]
    profile = rec["primitives"][0]
    profile["center_m"] = rotate(profile["center_m"])
    profile["axis"] = rotate(profile["axis"])
    for c in ann["contacts"]:
        c["point_m"] = rotate(c["point_m"])
        c["normal"] = rotate(c["normal"])
    candidate = propose_candidates(rec, ann, "cup_handle", "saddle")["candidates"][0]
    assert [candidate["parameters"][k] for k in ("cup_radius", "cup_radius_top", "contact_spacing")] == pytest.approx([33, 39, 60])


@pytest.mark.parametrize("mutation", ["missing_profile", "different_side", "outside_height", "wrong_normal", "unobserved_stub", "steep_taper"])
def test_cup_rejects_unresolved_contacts(mutation):
    rec, ann = cup()
    if mutation == "missing_profile": rec["primitives"] = []
    elif mutation == "different_side": ann["contacts"][1].update(point_m=[.01, .059, .07], normal=[0, 1, 0])
    elif mutation == "outside_height": ann["contacts"][1]["point_m"][2] = .2
    elif mutation == "wrong_normal": ann["contacts"][0]["normal"] = [-1, 0, 0]
    elif mutation == "unobserved_stub": ann["contacts"][0]["point_m"][0] += .01
    else: rec["primitives"][0]["taper"] = .3
    result = propose_candidates(rec, ann, "cup_handle", "saddle")
    assert result["status"] == "needs_input" and result["candidates"] == [] and result["questions"]


def test_cup_confirmed_upper_radius_is_preserved():
    rec, ann = cup()
    ann["measurements"] = [measured("cup_radius_top", 40.2)]
    candidate = propose_candidates(rec, ann, "cup_handle", "saddle")["candidates"][0]
    assert candidate["parameters"]["cup_radius_top"] == 40.2
    assert candidate["provenance"]["cup_radius_top"]["measurement_id"] == "manual_cup_radius_top"


@pytest.mark.parametrize("second_normal,expected_height", [([0, 0, 1], 0), ([0, 1, 0], 25)])
def test_bracket_plane_angle_selects_flat_or_l(second_normal, expected_height):
    ann = {"contacts": [contact([0, 0, 0]), contact([.01, 0, 0], second_normal)]}
    result = propose_candidates(reconstruction(), ann, "bracket", "screws")
    assert len(result["candidates"]) == 2
    a, b = result["candidates"]
    assert a["parameters"]["leg_height"] == expected_height
    assert b["parameters"]["thickness"] > a["parameters"]["thickness"]
    assert any("hole centers" in q for q in result["questions"])


def test_bracket_unsupported_angle_does_not_substitute_right_angle():
    ann = {"contacts": [contact([0, 0, 0]), contact([.01, 0, 0], [0, math.sqrt(.5), math.sqrt(.5)])]}
    result = propose_candidates(reconstruction(), ann, "bracket", "screws")
    assert result["candidates"] == []
    assert "45.0" in result["questions"][0]


def test_fragment_symmetry_remain_labeled_assumptions():
    ann = {**bridge(), "evidence_state": "fragment", "symmetry": {"confirmed": True, "axis": "x"}}
    result = propose_candidates(reconstruction(), ann, "bridge_handle", "adhesive")
    assert any("fragment" in note.lower() for note in result["evidence_notes"])
    assert any("assumption" in note for note in result["evidence_notes"])
    assert all(p["source"] != "symmetry" for p in result["candidates"][0]["provenance"].values())


def test_candidate_ids_are_reproducible_and_change_with_inputs():
    first = propose_candidates(reconstruction(), bridge(80), "bridge_handle", "screws")
    again = propose_candidates(reconstruction(), bridge(80), "bridge_handle", "screws")
    changed = propose_candidates(reconstruction(), bridge(82), "bridge_handle", "screws")
    assert first == again
    assert first["candidates"][0]["id"] != changed["candidates"][0]["id"]


def test_nonfinite_contact_is_rejected():
    ann = bridge()
    ann["contacts"][0]["point_m"][0] = math.nan
    with pytest.raises(ValueError, match="finite"):
        propose_candidates(reconstruction(), ann, "bridge_handle", "screws")


@pytest.mark.parametrize("family", ["bridge_handle", "cup_handle", "bracket"])
def test_actual_candidate_parameters_build_valid_single_brep(family):
    from reversecad.cad import build_shape
    if family == "cup_handle":
        rec, ann = cup()
    elif family == "bridge_handle":
        rec, ann = reconstruction(), bridge(83)
    else:
        rec = reconstruction()
        ann = {"contacts": [contact([0, 0, 0]), contact([0, -.03, .02], [0, 1, 0])]}
    result = propose_candidates(rec, ann, family, "saddle" if family == "cup_handle" else "screws")
    assert len(result["candidates"]) == 2
    for candidate in result["candidates"]:
        shape, _ = build_shape(family, candidate["parameters"])
        assert shape.val().isValid()
        assert len(shape.solids().vals()) == 1
        assert shape.val().Volume() > 0
