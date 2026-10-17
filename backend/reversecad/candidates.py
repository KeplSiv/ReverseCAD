"""Evidence-linked, deterministic repair hypotheses. These are not fit approvals.

Only selected interfaces or existing fits supply observed dimensions. Missing
material remains design inference. This engine never edits immutable observations,
silently adjusts measured values to satisfy CAD, or chooses an attachment method.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

from .cad import BOUNDS, DEFAULTS, normalize_parameters


def _vector(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} requires three coordinates")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{name} must be finite")
    return result


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _unit(value, name):
    vector = _vector(value, name)
    length = math.sqrt(_dot(vector, vector))
    if length < 1e-8:
        raise ValueError(f"{name} must be nonzero")
    return [v / length for v in vector]


def _id(prefix, value):
    return prefix + "_" + hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()[:12]


def propose_candidates(reconstruction: dict, annotations: dict, family: str,
                       attachment_method: str) -> dict:
    """Return bounded proposals, immutable derived measurements, and open questions.

    Coordinates in annotations and reconstruction must use the same object frame.
    Candidate IDs bind parameters and evidence. Callers must recompute candidates
    server-side if they use their derived measurement IDs for a repair request.
    """
    result = {"schema_version": 1, "family": family, "attachment_method": attachment_method,
              "status": "needs_input", "candidates": [], "questions": [],
              "evidence_notes": [], "derived_measurements": [],
              "provider_status": "deterministic_evidence_candidates",
              "physical_fit": "not_tested"}
    questions = result["questions"]
    notes = result["evidence_notes"]
    if family not in DEFAULTS:
        result["status"] = "unsupported"
        questions.append("Choose a supported bridge handle, cup handle, or flat/L-shaped bracket.")
        return result
    if not attachment_method:
        questions.append("Confirm how the replacement attaches before requesting candidates.")
        return result
    if family == "cup_handle" and attachment_method not in {"saddle", "saddle_pads", "adhesive_saddle"}:
        questions.append("The supported cup repair uses curved saddle pads. Explicitly approve that attachment or provide a supported measured stub design; no method has been changed.")
        return result

    state = annotations.get("evidence_state", "missing_part")
    if state == "fragment":
        notes.append("A fragment is available. Its selected observations may constrain interfaces; no missing fragment shape is reconstructed automatically.")
    elif state == "matching_part":
        notes.append("A matching intact part is available. Select and measure its relevant interfaces before treating it as dimensional evidence.")
    else:
        notes.append("Missing-part geometry is inferred from surviving selected interfaces and explicit design dimensions.")
    symmetry = annotations.get("symmetry", {})
    if isinstance(symmetry, dict) and symmetry.get("confirmed"):
        axis = symmetry.get("axis", "unspecified")
        notes.append(f"User-confirmed symmetry normal {axis} is an assumption. Candidates do not relabel reflected or unseen dimensions as measured.")
    if reconstruction.get("status") == "needs_input":
        questions.append("The scan still needs additional views or measurements; these are provisional design hypotheses.")

    params = deepcopy(DEFAULTS[family])
    provenance = {key: {"source": "design_inference", "measurement_id": None,
                        "observation_ids": [], "confirmed": False,
                        "uncertainty_status": "design_choice", "unit": "mm"}
                  for key in params}
    records = {}
    for item in reconstruction.get("measurements", []) + annotations.get("measurements", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            records[item["id"]] = item
    confirmed = {}
    for item in records.values():
        name = item.get("parameter", item.get("name"))
        if item.get("confirmed") and item.get("unit") == "mm" and name in BOUNDS[family]:
            value = float(item["value"])
            if not math.isfinite(value):
                raise ValueError("Confirmed measurements must be finite")
            if name in confirmed and not math.isclose(confirmed[name]["value"], value, abs_tol=1e-6):
                questions.append(f"Resolve conflicting confirmed {name} measurements before proposing a repair.")
                return result
            confirmed[name] = item

    accepted_frames = reconstruction.get("observations", {}).get("accepted_frames", [])
    observation_ids = [v for v in accepted_frames if isinstance(v, str)][:240]
    contacts = annotations.get("contacts", [])
    if not isinstance(contacts, list) or len(contacts) > 32:
        raise ValueError("Use at most 32 selected contact patches")
    primitives = reconstruction.get("primitives", [])
    if not isinstance(primitives, list):
        primitives = []

    def measured(parameter, value, origin, references, *, unit="mm"):
        """Preserve a confirmed manual constraint while retaining discrepant evidence."""
        if not math.isfinite(value):
            raise ValueError("Derived dimensions must be finite")
        record = {"id": _id("candidate_" + parameter, [value, origin, references, contacts]),
                  "name": parameter, "parameter": parameter, "value": value, "unit": unit,
                  "source": "depth_fit", "confirmed": False, "critical": True,
                  "observation_ids": references, "uncertainty_mm": None,
                  "uncertainty_status": "not_calibrated", "derivation": origin,
                  "selection_provenance": "user-selected interfaces; approximate clicks need independent confirmation"}
        result["derived_measurements"].append(record)
        if unit == "mm":
            params[parameter] = value
            provenance[parameter] = {"source": "measurement", "measurement_id": record["id"],
                                     "observation_ids": references, "confirmed": False,
                                     "uncertainty_status": "not_calibrated", "unit": "mm"}
        return record

    if family in {"bridge_handle", "cup_handle"} and len(contacts) != 2:
        questions.append("Select exactly two attachment patches, in lower-to-upper order for a cup, before proposing a handle.")
        return result
    if family == "bracket" and not 1 <= len(contacts) <= 2:
        questions.append("Select one mating plane for a flat bracket, or two mating planes for a flat/L-shaped bracket.")
        return result
    points = [_vector(c.get("point_m"), "Contact point") for c in contacts]
    normals = [_unit(c.get("normal"), "Contact normal") for c in contacts]
    contacts_ids = [str(c.get("id", "contact")) for c in contacts]
    notes.append("Contact locations and normals are selected scan evidence; their accuracy is not calibrated and mounting centers require confirmation.")

    if family == "bridge_handle":
        delta = _sub(points[1], points[0])
        if _dot(normals[0], normals[1]) < math.cos(math.radians(5)):
            questions.append("Bridge pads require approximately parallel outward mating normals; select compatible patches or use a supported alternative.")
            return result
        normal = _unit([a + b for a, b in zip(normals[0], normals[1])], "Mean contact normal")
        offset_mm = abs(_dot(delta, normal)) * 1000
        if offset_mm > 2:
            questions.append(f"Selected pads differ in mating-plane height by {offset_mm:.1f} mm. This bridge requires coplanar pads; measure or change the selected interface.")
            return result
        span = math.sqrt(max(0, _dot(delta, delta) - _dot(delta, normal) ** 2)) * 1000
        measured("span", span, {"method": "selected_contact_spacing_projected_onto_mating_plane",
                                 "contact_ids": contacts_ids, "normal_offset_mm": offset_mm}, observation_ids)
        params["pad_width"] = min(params["pad_width"], span - 5)
        notes.append("Grip curvature, standoff, section and pad size are new design choices; the missing original grip is not measured.")
    elif family == "cup_handle":
        profile = next((p for p in primitives if p.get("id") == "body_profile" and p.get("type") in {"cylinder", "frustum"}), None)
        if profile is None:
            questions.append("No supported cylinder/frustum fit is available. Capture the cup from more sides or supply independently confirmed radii at both contact heights.")
            return result
        center = _vector(profile.get("center_m"), "Cup profile center")
        axis = _unit(profile.get("axis"), "Cup profile axis")
        radius = float(profile["radius_mm"])
        taper = float(profile.get("taper", 0))
        if not math.isfinite(radius) or not math.isfinite(taper) or abs(taper) > .2:
            questions.append("The fitted cup taper exceeds the supported mild-taper range; more contact geometry is required.")
            return result
        heights = [_dot(_sub(point, center), axis) * 1000 for point in points]
        spacing = abs(heights[1] - heights[0])
        if spacing < 1:
            questions.append("Choose contact patches at distinct heights along the fitted cup axis.")
            return result
        height_range = profile.get("height_range_mm")
        if isinstance(height_range, list) and len(height_range) == 2 and any(h < height_range[0] - 2 or h > height_range[1] + 2 for h in heights):
            questions.append("A selected contact lies outside the observed cup-profile height range; do not extrapolate unseen curvature.")
            return result
        radial_units = []
        for point, height, normal in zip(points, heights, normals):
            relative = _sub(point, center)
            radial = [d - height / 1000 * a for d, a in zip(relative, axis)]
            radial_norm = math.sqrt(_dot(radial, radial))
            fitted_radius = radius + taper * height
            if abs(radial_norm * 1000 - fitted_radius) > max(2, float(profile.get("fit_residual_mm", 0)) * 3):
                questions.append("A selected contact is not supported by the fitted cup surface; select a body contact or measure the surviving stub separately.")
                return result
            radial_unit = _unit(radial, "Contact radial direction")
            if _dot(radial_unit, normal) < .85:
                questions.append("Contact normals must point out from the fitted cup body; review the selected side.")
                return result
            radial_units.append(radial_unit)
        if _dot(radial_units[0], radial_units[1]) < math.cos(math.radians(5)):
            questions.append("Select two cup contacts on the same radial side; the supported grip does not wrap between different sides.")
            return result
        refs = profile.get("observation_ids", observation_ids)
        for key, value, detail in [("contact_spacing", spacing, "axial separation"),
                                   ("cup_radius", radius + taper * heights[0], "first selected contact radius"),
                                   ("cup_radius_top", radius + taper * heights[1], "second selected contact radius")]:
            measured(key, value, {"method": detail, "profile_id": "body_profile", "contact_ids": contacts_ids,
                                  "contact_heights_mm": heights, "profile_radius_mm": radius, "profile_taper": taper}, refs)
        params["pad_height"] = min(params["pad_height"], spacing - 5)
        notes.append("Curvature follows the measured body profile at the two selected heights. Grip outline and adhesive clearance remain design inference; no fracture shape or adhesive strength is inferred.")
    else:
        if len(normals) == 1:
            params["leg_height"] = 0
            notes.append("One selected mating plane supports a flat bracket hypothesis only; add a second orthogonal plane for an L bracket.")
        else:
            angle = math.degrees(math.acos(max(-1, min(1, _dot(normals[0], normals[1])))))
            if angle <= 5:
                normal_offset = abs(_dot(_sub(points[1], points[0]), normals[0])) * 1000
                if normal_offset > 2:
                    questions.append("Selected parallel mating planes have a nonzero offset. The supported flat bracket cannot silently bridge that offset.")
                    return result
                params["leg_height"] = 0
                notes.append(f"Selected mating planes are approximately parallel ({angle:.1f} degrees); a flat bracket is proposed.")
            elif abs(angle - 90) <= 5:
                notes.append(f"Selected mating planes are approximately perpendicular ({angle:.1f} degrees); an L bracket is proposed. Confirm leg length and installation path.")
            else:
                questions.append(f"Selected mating-plane angle is {angle:.1f} degrees. Only flat or right-angle brackets are supported; do not force a different angle.")
                return result
        questions.append("Confirm bracket width, length, thickness, mating offsets, hole centers and diameters. The scan does not establish an unseen fastener pattern.")

    # Holes may be disabled as an explicitly unresolved design state, never invented.
    if "hole_diameter" in params:
        params["hole_diameter"] = 0
        if attachment_method in {"screws", "fasteners", "bolts"} and "hole_diameter" not in confirmed:
            questions.append("Enter and confirm mounting-hole diameter and pattern. Candidate holes are disabled (0 mm) until measured; this is not an alternate attachment method.")
    for name, item in confirmed.items():
        if name in params and provenance.get(name, {}).get("source") == "measurement" and abs(params[name] - float(item["value"])) > 2:
            questions.append(f"Confirmed {name} differs from the selected scan evidence by more than 2 mm; the confirmed value is retained for review.")
        params[name] = float(item["value"])
        provenance[name] = {"source": "measurement", "measurement_id": item["id"],
                            "observation_ids": item.get("observation_ids", []), "confirmed": True,
                            "uncertainty_status": "manual_bound" if item.get("uncertainty_mm") is not None else "not_calibrated",
                            "unit": "mm"}
    if family == "cup_handle":
        for key in ("cup_radius", "cup_radius_top", "contact_spacing"):
            if key not in confirmed:
                questions.append(f"Independently confirm {key.replace('_', ' ')} before claiming contact fit.")
    elif family == "bridge_handle" and "span" not in confirmed:
        questions.append("Confirm the selected mounting-center span with an independent measurement.")

    variants = [("compact", "Compact repair", {})]
    if family == "bracket":
        if "thickness" not in confirmed:
            variants += [("thicker", "Thicker repair", {"thickness": min(15, params["thickness"] + 1.5)})]
        elif "width" not in confirmed:
            variants += [("wider", "Wider repair", {"width": min(100, params["width"] + 8)})]
    else:
        if "standoff" not in confirmed:
            variants += [("roomier", "More hand clearance", {"standoff": min(70, params["standoff"] + 12)})]
        elif "grip_width" not in confirmed:
            width_limit = min(BOUNDS[family]["grip_width"][1], params.get("pad_length", 100) - 2)
            variants += [("wider_grip", "Wider grip section", {"grip_width": min(width_limit, params["grip_width"] + 3)})]
    for variant_id, title, edits in variants:
        values = dict(params)
        edits = {key: value for key, value in edits.items() if key not in confirmed}
        values.update(edits)
        try:
            values = normalize_parameters(family, values)
        except ValueError as exc:
            questions.append(f"Selected dimensions cannot form this template: {exc}. Confirm measurements or choose a supported repair.")
            continue
        differences = [f"{name.replace('_', ' ')}: {params[name]:g} → {value:g} mm (design inference)" for name, value in edits.items() if value != params[name]]
        if result["candidates"] and not differences:
            continue
        candidate = {"id": _id(family + "_" + variant_id, [values, provenance, contacts]), "title": title,
                     "explanation": "Supported parametric hypothesis constrained by selected surviving interfaces; physical fit remains untested.",
                     "parameters": values, "provenance": deepcopy(provenance),
                     "measurement_refs": sorted({p["measurement_id"] for p in provenance.values() if p.get("measurement_id")}),
                     "differences": differences or ["Baseline inferred grip/section dimensions; measured constraints retained."],
                     "questions": [], "attachment_method": attachment_method}
        result["candidates"].append(candidate)
    result["questions"] = list(dict.fromkeys(questions))
    for candidate in result["candidates"]:
        candidate["questions"] = result["questions"].copy()
    result["status"] = "needs_input" if questions or not result["candidates"] else "candidates"
    return result
