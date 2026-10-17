"""Bounded deterministic repair templates. All geometry/export numbers are millimeters.

`generate` executes trusted code only. Model output can supply finite bounded numbers,
never code. The exported part.py copies this exact generator so edits remain reproducible.
"""
from __future__ import annotations
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "1.0.0"
TESSELLATION_MM = 0.05
DEFAULTS = {
    "bridge_handle": {"span": 80., "standoff": 30., "grip_width": 12., "grip_depth": 9., "pad_width": 24., "pad_length": 24., "pad_thickness": 4., "hole_diameter": 4.},
    "cup_handle": {"cup_radius": 40., "contact_spacing": 55., "standoff": 32., "grip_width": 10., "grip_depth": 8., "pad_height": 16., "pad_thickness": 4., "contact_gap": 0.4},
    "bracket": {"width": 30., "length": 65., "thickness": 4., "leg_height": 25., "hole_diameter": 4., "hole_spacing": 35., "hole_offset": 0.},
}
BOUNDS = {
    "bridge_handle": {"span": (25., 200.), "standoff": (10., 90.), "grip_width": (4., 30.), "grip_depth": (4., 24.), "pad_width": (10., 60.), "pad_length": (10., 60.), "pad_thickness": (2., 15.), "hole_diameter": (0., 15.)},
    "cup_handle": {"cup_radius": (15., 90.), "cup_radius_top": (15., 90.), "contact_spacing": (20., 140.), "standoff": (10., 80.), "grip_width": (4., 24.), "grip_depth": (4., 20.), "pad_height": (8., 35.), "pad_thickness": (2., 12.), "contact_gap": (0., 3.)},
    "bracket": {"width": (12., 100.), "length": (20., 180.), "thickness": (2., 15.), "leg_height": (0., 100.), "hole_diameter": (0., 15.), "hole_spacing": (5., 150.), "hole_offset": (-40., 40.)},
}

def template_catalog() -> dict:
    return {family: {"defaults": defaults, "bounds": BOUNDS[family], "unit": "mm", "generator_version": GENERATOR_VERSION} for family, defaults in DEFAULTS.items()}


def normalize_parameters(family: str, supplied: dict) -> dict[str, float]:
    if family not in DEFAULTS:
        raise ValueError("unsupported_repair_type: choose bridge_handle, cup_handle, or bracket")
    if not isinstance(supplied, dict):
        raise ValueError("parameters must be an object")
    unknown = set(supplied) - set(BOUNDS[family])
    if unknown:
        raise ValueError(f"unknown parameters: {', '.join(sorted(unknown))}")
    p = {**DEFAULTS[family], **supplied}
    if family == "cup_handle":
        p.setdefault("cup_radius_top", p["cup_radius"])
    for key, val in p.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ValueError(f"{key} must be a finite number in mm")
        low, high = BOUNDS[family][key]
        if not low <= val <= high:
            raise ValueError(f"{key} must be between {low:g} and {high:g} mm")
        p[key] = float(val)
    if family == "bridge_handle":
        if p["span"] <= p["pad_width"] + 4:
            raise ValueError("span must exceed pad_width by more than 4 mm")
        if p["grip_depth"] >= min(p["span"] / 2, p["standoff"] * 1.5):
            raise ValueError("grip_depth leaves no usable curved handle opening")
        if p["grip_width"] > p["pad_length"] - 2:
            raise ValueError("pad_length must exceed grip_width by at least 2 mm")
        if p["hole_diameter"] and p["hole_diameter"] + 4 > min(p["pad_width"], p["pad_length"]):
            raise ValueError("mount hole needs at least 2 mm radial pad wall")
    elif family == "cup_handle":
        if p["contact_spacing"] <= p["pad_height"] + 4:
            raise ValueError("contact_spacing must exceed pad_height by more than 4 mm")
        if p["grip_depth"] >= min(p["standoff"] * 1.5, p["contact_spacing"] / 2):
            raise ValueError("grip_depth leaves no usable cup handle opening")
        if abs(p["cup_radius_top"] - p["cup_radius"]) / p["contact_spacing"] > .2:
            raise ValueError("cup taper exceeds supported mild taper; provide measured contact geometry")
    else:
        if p["leg_height"] and p["leg_height"] <= p["thickness"]:
            raise ValueError("leg_height must be zero (flat) or exceed thickness")
        if p["hole_diameter"]:
            edge = (p["length"] - p["hole_spacing"] - p["hole_diameter"]) / 2
            if edge < max(2., p["thickness"] if p["leg_height"] else 2.):
                raise ValueError("hole pattern overlaps end/leg or leaves less than 2 mm edge wall")
            if abs(p["hole_offset"]) + p["hole_diameter"] / 2 + 2 > p["width"] / 2:
                raise ValueError("hole_offset/hole_diameter leaves less than 2 mm side wall")
    return p


def _cq():
    import cadquery as cq
    return cq


def _half_ellipse(rx: float, rz: float, depth: float, width: float, *, right: bool = False):
    """An actual conic annulus in XZ, extruded across Y. Not a canned mesh."""
    cq = _cq()
    outer = cq.Workplane("XZ").ellipse(rx + depth / 2, rz + depth / 2).extrude(width / 2, both=True)
    inner = cq.Workplane("XZ").ellipse(rx - depth / 2, rz - depth / 2).extrude(width, both=True)
    ring = outer.cut(inner)
    size = 4 * max(rx, rz, width, depth)
    cutter = cq.Workplane("XY").box(size, size, size)
    cutter = cutter.translate((-size / 2, 0, 0) if right else (0, 0, -size / 2))
    return ring.cut(cutter)


def _saddle(p: dict, z: float):
    cq = _cq()
    slope = (p["cup_radius_top"] - p["cup_radius"]) / p["contact_spacing"]
    mean = (p["cup_radius_top"] + p["cup_radius"]) / 2
    angle = math.atan(p["grip_width"] / min(p["cup_radius"], p["cup_radius_top"]))
    def wire(height):
        radius = mean + slope * height + p["contact_gap"]
        outer = radius + p["pad_thickness"]
        a = angle
        return (cq.Workplane("XY", origin=(0, 0, height)).moveTo(outer * math.cos(a), -outer * math.sin(a))
                .threePointArc((outer, 0), (outer * math.cos(a), outer * math.sin(a)))
                .lineTo(radius * math.cos(a), radius * math.sin(a))
                .threePointArc((radius, 0), (radius * math.cos(a), -radius * math.sin(a))).close().val())
    # Loft parallel annular sector wires, retaining the requested conical contact surface.
    lo = wire(z - p["pad_height"] / 2)
    hi = wire(z + p["pad_height"] / 2)
    return cq.Workplane("XY").add(lo).add(hi).toPending().loft(ruled=True)


def build_shape(family: str, parameters: dict):
    """Return (CadQuery workplane, normalized parameters); does not export or use evidence."""
    cq = _cq()
    p = normalize_parameters(family, parameters)
    if family == "bridge_handle":
        result = _half_ellipse(p["span"] / 2, p["standoff"], p["grip_depth"], p["grip_width"]).translate((0, 0, p["pad_thickness"] / 2))
        for x in (-p["span"] / 2, p["span"] / 2):
            pad = cq.Workplane("XY").box(p["pad_width"], p["pad_length"], p["pad_thickness"], centered=(True, True, False)).translate((x, 0, 0))
            result = result.union(pad)
        if p["hole_diameter"]:
            for x in (-p["span"] / 2, p["span"] / 2):
                cutter = cq.Workplane("XY").center(x, 0).circle(p["hole_diameter"] / 2).extrude(p["pad_thickness"] + p["standoff"] + p["grip_depth"])
                result = result.cut(cutter)
    elif family == "cup_handle":
        center_radius = (p["cup_radius"] + p["cup_radius_top"]) / 2 + p["contact_gap"] + p["pad_thickness"] / 2
        slope = (p["cup_radius_top"] - p["cup_radius"]) / p["contact_spacing"]
        result = _half_ellipse(p["standoff"], p["contact_spacing"] / 2, p["grip_depth"], p["grip_width"], right=True)
        if slope:
            matrix = cq.Matrix([[1., 0., slope, 0.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]])
            result = cq.Workplane("XY").newObject([result.val().transformGeometry(matrix)])
        result = result.translate((center_radius, 0, 0))
        for z in (-p["contact_spacing"] / 2, p["contact_spacing"] / 2):
            result = result.union(_saddle(p, z))
    else:
        result = cq.Workplane("XY").box(p["width"], p["length"], p["thickness"], centered=(True, True, False))
        if p["leg_height"]:
            leg = cq.Workplane("XY").box(p["width"], p["thickness"], p["leg_height"], centered=(True, True, False)).translate((0, -p["length"] / 2 + p["thickness"] / 2, 0))
            result = result.union(leg)
        if p["hole_diameter"]:
            for y in (-p["hole_spacing"] / 2, p["hole_spacing"] / 2):
                result = result.cut(cq.Workplane("XY").center(p["hole_offset"], y).circle(p["hole_diameter"] / 2).extrude(p["thickness"]))
    return result.clean(), p


def build_coupon(family: str, p: dict):
    cq = _cq()
    if family == "cup_handle":
        coupon = _saddle(p, -p["contact_spacing"] / 2)
        return coupon, {"type": "saddle_radius_contact_gap", "radius_mm": p["cup_radius"], "contact_gap_mm": p["contact_gap"], "printed_measurements_required": True}
    if family == "bridge_handle":
        w, length, thick, hole = p["pad_width"], p["pad_length"], p["pad_thickness"], p["hole_diameter"]
    else:
        w, length, thick, hole = p["width"], min(p["length"], max(18., p["hole_diameter"] + 10)), p["thickness"], p["hole_diameter"]
    coupon = cq.Workplane("XY").box(w, length, thick, centered=(True, True, False))
    if hole:
        coupon = coupon.cut(cq.Workplane("XY").circle(hole / 2).extrude(thick))
    return coupon, {"type": "mounting_hole" if hole else "contact_thickness", "hole_diameter_mm": hole, "thickness_mm": thick, "printed_measurements_required": True}


def placement_transform(family: str, p: dict, context: dict):
    """Rigid CAD-to-object transform; translations are mm, rotations dimensionless."""
    import numpy as np
    explicit = context.get("T_object_part_mm")
    if explicit is not None:
        matrix = np.asarray(explicit, dtype=float).reshape((4, 4), order="F")
        if not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8) or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(matrix[:3, :3]), 1):
            raise ValueError("T_object_part_mm must be a finite rigid right-handed transform")
        return matrix, {"source": "explicit_contact_frame", "status": "aligned", "residuals_mm": []}
    contacts = context.get("contacts", [])
    matrix = np.eye(4)
    if not contacts:
        return matrix, {"source": "canonical_template_frame", "status": "needs_input", "reason": "Select contact patches to align repair with measured object"}
    def point(c):
        v = np.asarray(c["point_m"], dtype=float) * 1000
        if v.shape != (3,) or not np.isfinite(v).all():
            raise ValueError("contact point_m must contain three finite meter coordinates")
        return v
    def normal(c):
        v = np.asarray(c["normal"], dtype=float)
        if v.shape != (3,) or not np.isfinite(v).all() or np.linalg.norm(v) < .1:
            raise ValueError("contact normal must be finite and nonzero")
        return v / np.linalg.norm(v)
    origin = point(contacts[0])
    n = normal(contacts[0])
    residuals = []
    angular_residual_deg = 0.
    if family in ("bridge_handle", "cup_handle") and len(contacts) >= 2:
        a, b = point(contacts[0]), point(contacts[1])
        axis = b - a
        if np.linalg.norm(axis) < 1:
            raise ValueError("contact points must be at least 1 mm apart")
        n2 = normal(contacts[1])
        if np.dot(n, n2) < .85:
            raise ValueError("selected contact normals diverge; supported handles need compatible contact frames")
        n = n + n2
        n /= np.linalg.norm(n)
        axis -= n * np.dot(axis, n)
        if np.linalg.norm(axis) < 1:
            raise ValueError("contact spacing is parallel to contact normals")
        axis /= np.linalg.norm(axis)
        origin = (a + b) / 2
        if family == "bridge_handle":
            x, z = axis, n
            y = np.cross(z, x)
            z = np.cross(x, y)
            desired = p["span"]
        else:
            profiles = context.get("primitives", [])
            profile = next((candidate for candidate in profiles if isinstance(candidate, dict) and candidate.get("id") == "body_profile" and "axis" in candidate), None)
            if profile is not None:
                z = np.asarray(profile["axis"], dtype=float)
                if z.shape != (3,) or not np.isfinite(z).all() or np.linalg.norm(z) < .1:
                    raise ValueError("fitted cup axis must be a finite nonzero vector")
                z = z / np.linalg.norm(z)
                if np.dot(z, b - a) < 0:
                    z = -z
                x = n - z * np.dot(n, z)
                if np.linalg.norm(x) < .1:
                    raise ValueError("selected cup normals are incompatible with fitted cup axis")
                x /= np.linalg.norm(x)
            else:
                # On a frustum the surface normal is tilted; treating it as a
                # radial axis would rotate an otherwise valid tapered repair.
                chord = (b - a) / np.linalg.norm(b - a)
                perpendicular = n - chord * np.dot(n, chord)
                if np.linalg.norm(perpendicular) < .1:
                    raise ValueError("cup contact normals do not establish a radial direction")
                perpendicular /= np.linalg.norm(perpendicular)
                slope = (p["cup_radius_top"] - p["cup_radius"]) / p["contact_spacing"]
                z = (chord - slope * perpendicular) / math.sqrt(1 + slope * slope)
                x = (perpendicular + slope * chord) / math.sqrt(1 + slope * slope)
            y = np.cross(z, x)
            x = np.cross(y, z)
            origin -= x * (p["cup_radius"] + p["cup_radius_top"]) / 2
            axis, n = z, x
            desired = p["contact_spacing"]
        normal_offset = float(np.dot(b - a, n))
        expected_offset = 0. if family == "bridge_handle" else p["cup_radius_top"] - p["cup_radius"]
        residuals = [abs(float(np.dot(b - a, axis)) - desired), abs(normal_offset - expected_offset)]
    else:
        z = n
        x = np.array([1., 0., 0.]) if abs(n[0]) < .9 else np.array([0., 1., 0.])
        if len(contacts) >= 2:
            proposed = point(contacts[1]) - origin
            second_normal = normal(contacts[1])
            measured_angle = math.degrees(math.acos(float(np.clip(np.dot(z, second_normal), -1, 1))))
            expected_angle = 90. if family == "bracket" and p["leg_height"] else 0.
            angular_residual_deg = abs(measured_angle - expected_angle)
            if np.linalg.norm(proposed - z * np.dot(proposed, z)) > 1:
                x = proposed.copy()
        x -= z * np.dot(x, z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        if family == "bracket" and len(contacts) >= 2:
            if p["leg_height"] and angular_residual_deg <= 5:
                # First selected plane is local Z=0; second plane is Y=-length/2.
                # Their normals establish a right angle, and translating within
                # the first plane aligns the second without changing dimensions.
                y = second_normal - z * np.dot(second_normal, z)
                y /= np.linalg.norm(y)
                x = np.cross(y, z)
                origin += y * (np.dot(proposed, y) + p["length"] / 2)
                relative = point(contacts[1]) - origin
                residuals = [max(0., abs(float(np.dot(relative, x))) - p["width"] / 2), max(0., -float(np.dot(relative, z)), float(np.dot(relative, z)) - p["leg_height"])]
            elif not p["leg_height"]:
                residuals = [abs(float(np.dot(proposed, z)))]
    matrix[:3, :3] = np.column_stack([x, y, z])
    matrix[:3, 3] = origin
    enough = (family == "bracket" and p["leg_height"] == 0) or len(contacts) >= 2
    # Contact clicks are observations, not permission to rewrite the user's dimensions.
    status = "aligned" if enough and angular_residual_deg <= 5 and not any(r > 2 for r in residuals) else "needs_input"
    return matrix, {"source": "selected_contact_frames", "status": status, "residuals_mm": residuals, "plane_angle_error_deg": angular_residual_deg, "note": "Entered dimensions retained unchanged; residuals check selected contact spacing, normal offsets and supported plane angle."}


def apply_transform(shape, matrix):
    cq = _cq()
    from OCP.gp import gp_Trsf
    # Construct the rigid OCC type directly: generic GTrsf initialized from a list
    # is not marked orthogonal by OCCT even when its entries are the identity.
    trsf = gp_Trsf()
    trsf.SetValues(*[float(v) for v in matrix[:3, :4].flatten()])
    return cq.Workplane("XY").newObject([shape.val().located(cq.Location(trsf))])


def _dimension_checks(shape, family: str, p: dict) -> dict:
    """Check analytic dimensions independently using BREP bounds and hole circles."""
    bb = shape.val().BoundingBox()
    actual = [bb.xlen, bb.ylen, bb.zlen]
    if family == "bridge_handle":
        expected = [p["span"] + max(p["pad_width"], p["grip_depth"]), max(p["pad_length"], p["grip_width"]), max(p["pad_thickness"], p["pad_thickness"] / 2 + p["standoff"] + p["grip_depth"] / 2)]
    elif family == "bracket":
        expected = [p["width"], p["length"], max(p["leg_height"], p["thickness"])]
    else:
        expected = None  # Contact radii checked via solid probes below, not inferred from bbox.
    errors = [abs(a - b) for a, b in zip(actual, expected)] if expected else []
    radius_checks = []
    solids = shape.solids().vals()
    if family == "cup_handle":
        for z, radius in ((-p["contact_spacing"] / 2, p["cup_radius"]), (p["contact_spacing"] / 2, p["cup_radius_top"])):
            for angle in (-.08, 0, .08):
                # Analytically specified contact surface must separate empty cup interior
                # from saddle material on both sides of the two requested contact heights.
                r = radius + p["contact_gap"]
                outside = ((r - .05) * math.cos(angle), (r - .05) * math.sin(angle), z)
                inside = ((r + .05) * math.cos(angle), (r + .05) * math.sin(angle), z)
                passed = not any(s.isInside(outside) for s in solids) and any(s.isInside(inside) for s in solids)
                radius_checks.append({"z_mm": z, "angle_rad": angle, "radius_mm": r, "passed": passed})
    hole = p.get("hole_diameter", 0)
    hole_checks = []
    if hole:
        radius_matches = []
        for edge in shape.edges().vals():
            if edge.geomType() == "CIRCLE" and abs(edge.radius() * 2 - hole) <= .1:
                radius_matches.append(edge.arcCenter().toTuple())
        expected_centers = [(-p["span"] / 2, 0), (p["span"] / 2, 0)] if family == "bridge_handle" else [(p["hole_offset"], -p["hole_spacing"] / 2), (p["hole_offset"], p["hole_spacing"] / 2)]
        for x, y in expected_centers:
            hole_checks.append({"center_xy_mm": [x, y], "diameter_mm": hole, "passed": any(math.hypot(c[0] - x, c[1] - y) <= .1 for c in radius_matches)})
    return {"passed": all(error <= .1 for error in errors) and all(c["passed"] for c in radius_checks + hole_checks), "bounds_mm": actual, "analytic_expected_bounds_mm": expected, "max_bound_error_mm": max(errors, default=0), "tolerance_mm": .1, "cup_contact_radius_probes": radius_checks, "mounting_holes": hole_checks}


def _json(path: Path, obj: Any):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def generate(family: str, parameters: dict, output_dir: Path, context: dict | None = None) -> dict:
    """Generate verified exports and honest geometry/fit reports for one revision.

    Fit needs_input is distinct from invalid CAD. Service may allow a prototype
    after explicit acknowledgment, but must never label it physically verified.
    """
    import numpy as np
    from .cad_validation import export_checks, fit_checks, print_checks, mesh_checks
    import trimesh
    context = dict(context or {})
    output = Path(output_dir)
    if family == "cup_handle" and not (context.get("attachment_method") == "saddle" and context.get("saddle_approved") is True):
        raise ValueError("needs_input: cup saddle attachment requires explicit user approval; surviving-stub reconstruction is unsupported")
    shape, p = build_shape(family, parameters)
    dimension = _dimension_checks(shape, family, p)
    solid_valid = shape.val().isValid() and len(shape.solids().vals()) == 1 and shape.val().Volume() > 0
    if not solid_valid or not dimension["passed"]:
        raise ValueError("invalid_cad: solid or analytic mating dimensions failed; requested dimensions were not changed")
    transform, placement = placement_transform(family, p, context)
    positioned = apply_transform(shape, transform)
    output.mkdir(parents=True, exist_ok=True)
    cq = _cq()
    for suffix in ("step", "stl", "3mf"):
        cq.exporters.export(positioned, str(output / f"part.{suffix}"), tolerance=TESSELLATION_MM, angularTolerance=.12)
    export_report, mesh = export_checks(positioned, output, TESSELLATION_MM)
    if not export_report["passed"]:
        _json(output / "validation.json", {"status": "invalid_cad", "exports": export_report})
        raise ValueError("invalid_export: reimported solid/mesh failed topology, unit or dimension checks")
    fit = fit_checks(mesh, context, transform, family, p)
    manufacturing = print_checks(mesh, family, p, context.get("manufacturing", {}))
    # Use original local orientation for dimensional/editability checks; preview and exports
    # both carry the same recorded placement. Nothing is scaled to avoid intersections.
    preview = {"schema_version": 1, "unit": "mm", "vertices": mesh.vertices.tolist(), "triangles": mesh.faces.tolist(), "normals": mesh.vertex_normals.tolist(), "material_groups": [{"name": "replacement", "first_triangle": 0, "triangle_count": len(mesh.faces)}]}
    _json(output / "preview.json", preview)
    revision_payload = {"generator_version": GENERATOR_VERSION, "family": family, "parameters": p, "scan_id": context.get("scan_id"), "scan_revision": context.get("scan_revision"), "repair_id": context.get("repair_id"), "repair_revision": context.get("revision"), "attachment_method": context.get("attachment_method"), "T_object_part_mm": transform.flatten(order="F").tolist()}
    provenance_hashes = {name: context.get(name) for name in ("input_manifest_sha256", "input_checksums_sha256", "intent_sha256")}
    for name, value in provenance_hashes.items():
        if value is not None and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError(f"{name} must be a SHA-256 hex digest")
    revision_payload["input_hashes"] = provenance_hashes
    evidence = context.get("measurements", [])
    provenance = {}
    for name, value in p.items():
        matches = [m for m in evidence if m.get("id") == name or str(m.get("name", "")).lower().replace(" ", "_") == name]
        confirmed = [m for m in matches if m.get("confirmed") and m.get("source") in ("manual", "depth_fit", "multiview_estimate") and m.get("unit") == "mm" and isinstance(m.get("value"), (int, float)) and abs(m["value"] - value) <= .1]
        selected = confirmed[-1] if confirmed else matches[-1] if matches else None
        provenance[name] = {"source": selected.get("source", "design_inference") if selected else "design_inference", "measurement_id": selected.get("id") if selected else None, "confirmed": bool(confirmed), "uncertainty_mm": selected.get("uncertainty_mm") if selected else None, "observation_ids": selected.get("observation_ids", []) if selected else []}
    revision_payload["parameter_provenance"] = provenance
    revision = hashlib.sha256(json.dumps(revision_payload, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]
    _json(output / "parameters.json", {**revision_payload, "revision_id": revision, "unit": "mm"})
    coupon, coupon_info = build_coupon(family, p)
    for suffix in ("step", "stl", "3mf"):
        cq.exporters.export(coupon, str(output / f"coupon.{suffix}"), tolerance=TESSELLATION_MM, angularTolerance=.12)
    coupon_check, coupon_mesh = export_checks(coupon, output, TESSELLATION_MM, stem="coupon")
    if not coupon_check["passed"] or not coupon.val().isValid():
        raise ValueError("invalid_coupon: generated fit coupon failed validation")
    _json(output / "coupon.json", {**coupon_info, "unit": "mm", "validation": coupon_check, "revision_id": revision})
    shutil.copyfile(Path(__file__), output / "generator.py")
    # Static source file. Data is loaded from JSON, never interpolated as Python code.
    (output / "part.py").write_text('''"""Editable trusted parametric source. Run with ReverseCAD pinned Python environment.
Edit parameters.json, then: python part.py. Regeneration writes edited.step/stl/3mf.
For complete independent validation, regenerate the revision through the service.
"""
import json
from pathlib import Path
import numpy as np
import cadquery as cq
from generator import build_shape, apply_transform
root = Path(__file__).resolve().parent
data = json.loads((root / "parameters.json").read_text())
part, normalized = build_shape(data["family"], data["parameters"])
matrix = np.asarray(data["T_object_part_mm"]).reshape((4, 4), order="F")
part = apply_transform(part, matrix)
for extension in ("step", "stl", "3mf"):
    cq.exporters.export(part, str(root / ("edited." + extension)), tolerance=0.05, angularTolerance=0.12)
''')
    needs = []
    if placement["status"] == "needs_input":
        needs.append("Confirm selected contact frames and alignment")
    if fit["status"] == "needs_input":
        needs.append("Resolve collision/contact/path evidence before claiming fit")
    if not manufacturing["passed"]:
        needs.append("Review wall thickness or build volume against printer profile")
    unconfirmed = [m.get("id", m.get("name", "dimension")) for m in context.get("measurements", []) if m.get("critical") and not m.get("confirmed")]
    critical = {"bridge_handle": ["span"], "cup_handle": ["cup_radius", "contact_spacing"], "bracket": []}[family]
    if family == "cup_handle" and p["cup_radius_top"] != p["cup_radius"]:
        critical.append("cup_radius_top")
    if p.get("hole_diameter", 0):
        critical.append("hole_diameter")
        if family == "bracket":
            critical.append("hole_spacing")
    unconfirmed.extend(name for name in critical if not provenance[name]["confirmed"])
    if unconfirmed:
        needs.append("Confirm critical dimensions: " + ", ".join(sorted(set(unconfirmed))))
    uncertainty_limit = float(context.get("fit_tolerance_mm", .75))
    if not math.isfinite(uncertainty_limit) or not .05 <= uncertainty_limit <= 5:
        raise ValueError("fit_tolerance_mm must be between 0.05 and 5 mm")
    uncertain = [name for name in critical if provenance[name]["confirmed"] and (not isinstance(provenance[name]["uncertainty_mm"], (float, int)) or not math.isfinite(provenance[name]["uncertainty_mm"]) or provenance[name]["uncertainty_mm"] < 0 or provenance[name]["uncertainty_mm"] + TESSELLATION_MM > uncertainty_limit)]
    if uncertain:
        needs.append("Critical uncertainty is unknown or exceeds fit tolerance: " + ", ".join(uncertain))
    validation = {"schema_version": 1, "revision_id": revision, "status": "needs_input" if needs else "cad_checks_passed", "cad_valid": True, "passed": True, "ready_for_test_print": not needs, "physical_fit": "not_tested", "sensor_accuracy": "not_validated_by_cad", "solid": {"valid": True, "count": 1, "volume_mm3": float(shape.val().Volume())}, "dimensions": dimension, "exports": export_report, "placement": {**placement, "T_object_part_mm": transform.flatten(order="F").tolist()}, "fit": fit, "manufacturing": manufacturing, "unresolved": needs, "coupon": coupon_info, "unit": "mm"}
    _json(output / "validation.json", validation)
    lines = [f"Reverse CAD revision {revision}", f"Family: {family}; generator {GENERATOR_VERSION}; all dimensions mm", f"CAD/exports: passed. Fit status: {validation['status']}.", "Physical sensing, printed fit, material strength and attachment strength: NOT TESTED.", "", "Parameters:"]
    lines += [f"  {key}: {value:g} mm" for key, value in p.items()]
    lines += ["", "Provenance: measurements/observations remain in scan report. The generator proposes replacement shape; it does not measure missing material.", "Tessellation tolerance: 0.05 mm; this is not sensor accuracy.", "", "Unresolved:"] + ["  " + s for s in needs or ["Perform independent measurement and coupon/physical fit trial"]]
    lines += ["", "Assembly: " + fit["assembly"]["status"], "Thickness: " + manufacturing["thickness"]["scope"], "Support needed in current orientation: " + str(manufacturing["support_required_in_current_z_orientation"])]
    (output / "report.txt").write_text("\n".join(lines) + "\n")
    artifacts = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name not in ("manifest.json",):
            artifacts.append({"name": path.name, "path": path.name, "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"schema_version": 1, "revision_id": revision, "family": family, "unit": "mm", "scan_id": context.get("scan_id"), "scan_revision": context.get("scan_revision"), "repair_id": context.get("repair_id"), "repair_revision": context.get("revision"), "generator_version": GENERATOR_VERSION, "parameters_sha256": hashlib.sha256((output / "parameters.json").read_bytes()).hexdigest(), "artifacts": artifacts}
    manifest["input_hashes"] = provenance_hashes
    _json(output / "manifest.json", manifest)
    return {"family": family, "parameters": p, "revision_id": revision, "validation": validation, "artifacts": artifacts, "preview_path": "preview.json", "manifest": manifest}
