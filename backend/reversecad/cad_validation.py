"""Independent export, sampled thickness and observed-obstacle geometry validation."""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import trimesh


def mesh_checks(mesh: trimesh.Trimesh, expected_components: int = 1) -> dict:
    import open3d as o3d
    # Open3D triangle-triangle checks supplement edge-incidence and winding checks.
    independent = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(mesh.vertices), o3d.utility.Vector3iVector(mesh.faces))
    intersection = independent.is_self_intersecting()
    components = len(mesh.split(only_watertight=False))
    degenerate = int(np.count_nonzero(mesh.area_faces < 1e-10))
    valid = bool(mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0 and components == expected_components and degenerate == 0 and not intersection)
    return {"passed": valid, "watertight": bool(mesh.is_watertight), "winding_consistent": bool(mesh.is_winding_consistent), "self_intersecting": bool(intersection), "degenerate_faces": degenerate, "components": components, "expected_components": expected_components, "vertices": len(mesh.vertices), "triangles": len(mesh.faces), "volume_mm3": float(mesh.volume)}


def export_checks(shape, output: Path, tolerance_mm: float, stem: str = "part") -> tuple[dict, trimesh.Trimesh]:
    import cadquery as cq
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    def precise_bounds(s):
        box = Bnd_Box()
        # Generic cached tessellation bounds can inflate B-spline extrema enough
        # to look like an export error. Compare true geometry on both sides.
        BRepBndLib.AddOptimal_s(s.val().wrapped, box, False, False)
        values = box.Get()
        return np.asarray(values).reshape((2, 3))
    expected = precise_bounds(shape)
    step = cq.importers.importStep(str(output / f"{stem}.step"))
    step_bounds = precise_bounds(step)
    step_error = float(np.max(np.abs(step_bounds - expected)))
    step_unit_mm = "SI_UNIT(.MILLI.,.METRE.)" in (output / f"{stem}.step").read_text()
    stl = trimesh.load_mesh(str(output / f"{stem}.stl"), process=True)
    stl_error = float(np.max(np.abs(stl.bounds - expected)))
    mf = trimesh.load(str(output / f"{stem}.3mf"), force="mesh", process=True)
    mf_error = float(np.max(np.abs(mf.bounds - expected)))
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(output / f"{stem}.3mf") as archive:
        model_path = next(name for name in archive.namelist() if name.endswith(".model"))
        mf_unit = ET.fromstring(archive.read(model_path)).get("unit")
    stl_check, mf_check = mesh_checks(stl), mesh_checks(mf)
    report = {
        "step": {"passed": bool(step.val().isValid() and len(step.solids().vals()) == 1 and step_error <= .1 and step_unit_mm), "valid_brep": bool(step.val().isValid()), "solids": len(step.solids().vals()), "max_bound_error_mm": step_error, "tolerance_mm": .1, "declares_millimeters": step_unit_mm},
        "stl": {**stl_check, "max_bound_error_mm": stl_error, "tolerance_mm": tolerance_mm + .1, "unit": "mm (documented; STL has no unit field)"},
        "3mf": {**mf_check, "max_bound_error_mm": mf_error, "tolerance_mm": tolerance_mm + .1, "unit": mf_unit},
    }
    report["stl"]["passed"] &= stl_error <= tolerance_mm + .1
    report["3mf"]["passed"] &= mf_error <= tolerance_mm + .1 and mf_unit == "millimeter"
    report["passed"] = all(report[k]["passed"] for k in ("step", "stl", "3mf"))
    return report, stl


def sampled_thickness(mesh: trimesh.Trimesh, minimum_mm: float, samples: int = 256) -> dict:
    # Area-stratified deterministic samples. Inward rays originate at triangle centers.
    cumulative = np.cumsum(mesh.area_faces)
    ids = np.unique(np.searchsorted(cumulative, np.linspace(0, cumulative[-1], samples, endpoint=False) + cumulative[-1] / (2 * samples)))
    origins = mesh.triangles_center[ids] - mesh.face_normals[ids] * 1e-4
    directions = -mesh.face_normals[ids]
    locations, rays, _ = mesh.ray.intersects_location(origins, directions, multiple_hits=True)
    distances = np.linalg.norm(locations - origins[rays], axis=1) + 1e-4
    valid = distances > .001
    per_ray = {}
    for idx, distance in zip(rays[valid], distances[valid]):
        per_ray[int(idx)] = min(float(distance), per_ray.get(int(idx), math.inf))
    smallest = min(per_ray.values()) if per_ray else None
    return {"passed": smallest is not None and smallest >= minimum_mm - .1, "minimum_sampled_mm": smallest, "required_mm": minimum_mm, "rays_cast": len(ids), "rays_with_exit": len(per_ray), "method": "Independent STL inward surface-normal ray intersections; area-stratified triangle centers", "scope": "Sampled chords, not a proof of global minimum wall thickness; template checks also required. No strength estimate."}


def _safe_points(points) -> np.ndarray:
    array = np.asarray(points, dtype=float)
    if array.size == 0:
        return np.empty((0, 3))
    if array.ndim != 2 or array.shape[1] != 3 or not np.isfinite(array).all():
        raise ValueError("observed_points_mm must be finite Nx3 object-frame millimeters")
    return array


def fit_checks(mesh: trimesh.Trimesh, context: dict, transform: np.ndarray, family: str, parameters: dict) -> dict:
    observed = _safe_points(context.get("observed_points_mm", []))
    contacts = context.get("contacts", [])
    if len(observed) == 0:
        return {"status": "needs_input", "collision": {"status": "not_evaluated", "reason": "No observed geometry supplied"}, "intentional_contacts": {"status": "needs_input", "count": len(contacts)}, "assembly": {"status": "not_evaluated"}, "limitations": ["Physical fit requires contact observations, independent dimensions and a printed coupon."]}
    total = len(observed)
    if total > 4000:
        observed = observed[np.linspace(0, total - 1, 4000).astype(int)]
    low, high = mesh.bounds
    candidates = observed[np.all((observed >= low - .2) & (observed <= high + .2), axis=1)]
    contact_mask = np.zeros(len(candidates), dtype=bool)
    contact_results = []
    expected_gap = parameters.get("contact_gap", 0.) if family == "cup_handle" else 0.
    gap_tolerance = float(context.get("contact_tolerance_mm", .75))
    if not math.isfinite(gap_tolerance) or not 0.05 <= gap_tolerance <= 2.:
        raise ValueError("contact_tolerance_mm must be between 0.05 and 2 mm")
    for contact in contacts:
        center = np.asarray(contact["point_m"], dtype=float) * 1000
        radius = float(contact.get("radius_mm", 5))
        if not np.isfinite(center).all() or center.shape != (3,) or not 0 < radius <= 100:
            raise ValueError("contact point/radius is invalid")
        contact_mask |= np.linalg.norm(candidates - center, axis=1) <= radius
        _, gap, _ = trimesh.proximity.closest_point(mesh, center.reshape(1, 3))
        normal = np.asarray(contact.get("normal", [0, 0, 1]), dtype=float)
        if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) < .1:
            raise ValueError("contact normal must be finite and nonzero")
        normal /= np.linalg.norm(normal)
        tangent = np.cross(normal, [1, 0, 0] if abs(normal[0]) < .9 else [0, 1, 0])
        tangent /= np.linalg.norm(tangent)
        tangent2 = np.cross(normal, tangent)
        probes = center + np.array([np.zeros(3), tangent, -tangent, tangent2, -tangent2]) * radius * .5
        distances = trimesh.proximity.signed_distance(mesh, probes)
        # Selected point may be a hole center. Require contact around its patch,
        # rather than asserting the deliberately empty hole center must touch.
        supported = (distances <= .2) & (np.abs(-distances - expected_gap) <= gap_tolerance)
        nearby = observed[np.linalg.norm(observed - center, axis=1) <= radius]
        nearby = nearby[np.abs((nearby - center) @ normal) <= max(1., radius * .2)]
        support_count = 0
        support_spread = 0.
        if len(nearby):
            observed_distances = trimesh.proximity.signed_distance(mesh, nearby)
            supported_observed = nearby[(observed_distances <= .2) & (np.abs(-observed_distances - expected_gap) <= gap_tolerance)]
            support_count = len(supported_observed)
            if support_count >= 3:
                singular = np.linalg.svd(supported_observed - np.mean(supported_observed, axis=0), compute_uv=False)
                support_spread = float(singular[1])
        evidence_supported = support_count >= 3 and support_spread >= min(.5, radius * .1)
        passed = int(supported.sum()) >= 3 and evidence_supported
        contact_results.append({"id": contact.get("id", "contact"), "distance_to_part_mm": float(gap[0]), "radius_mm": radius, "expected_gap_mm": expected_gap, "gap_tolerance_mm": gap_tolerance, "patch_probe_distances_mm": (-distances).tolist(), "supported_probes": int(supported.sum()), "probe_count": 5, "nearby_observed_support_points": support_count, "observed_patch_second_axis_spread_mm": support_spread, "observed_evidence_supported": evidence_supported, "passed": passed})
    signed = trimesh.proximity.signed_distance(mesh, candidates) if len(candidates) else np.empty(0)
    # Positive signed distance is inside. Surface points within 0.2 mm are tolerance contacts.
    collision_count = int(np.count_nonzero((signed > .2) & ~contact_mask))
    excessive_contact_penetration = int(np.count_nonzero((signed > .2) & contact_mask))
    contact_touches = int(np.count_nonzero((signed >= -.2) & (signed <= .2) & contact_mask))
    direction = np.asarray(context.get("assembly_direction", [1, 0, 0] if family == "cup_handle" else [0, 0, 1]), dtype=float)
    if direction.shape != (3,) or not np.isfinite(direction).all() or np.linalg.norm(direction) < 1e-8:
        raise ValueError("assembly_direction must be a nonzero finite part-frame vector")
    direction = transform[:3, :3] @ (direction / np.linalg.norm(direction))
    travel = min(240., float(np.max(mesh.extents)) + 20.)
    steps = max(2, min(120, int(math.ceil(travel / 2))))
    blocked = []
    # Translate obstacles in the opposite direction, keeping mesh and ray tree fixed.
    for offset in np.linspace(travel / steps, travel, steps):
        shifted = observed - direction * offset
        relevant = shifted[np.all((shifted > low + .2) & (shifted < high - .2), axis=1)]
        if len(relevant):
            inside = mesh.contains(relevant)
            if np.any(inside):
                blocked.append(float(offset))
                break
    final_collision = collision_count + excessive_contact_penetration > 0
    return {
        "status": "needs_input" if final_collision or blocked or not contacts or not all(c["passed"] for c in contact_results) else "observed_geometry_checks_passed",
        "collision": {"status": "interference" if final_collision else "no_sampled_interference", "noncontact_inside_points": collision_count, "excessive_contact_penetration_points": excessive_contact_penetration, "allowed_penetration_mm": .2, "observed_points": total, "checked_points": len(observed)},
        "intentional_contacts": {"status": "passed" if contacts and all(c["passed"] for c in contact_results) else "needs_input", "surface_points": contact_touches, "patches": contact_results},
        "assembly": {"status": "blocked" if blocked else "sampled_path_clear", "direction_object": direction.tolist(), "travel_mm": travel, "step_mm": travel / steps, "first_blocked_offset_mm": blocked[0] if blocked else None},
        "limitations": ["Only observed points checked; unobserved and thin between-sample obstacles remain unknown.", "Straight translation sampled at up to 2 mm; flexible assembly, screw/tool access and rotational assembly are not certified.", "Contact distances include scan uncertainty and do not certify bond area or strength."],
    }


def print_checks(mesh: trimesh.Trimesh, family: str, parameters: dict, profile: dict) -> dict:
    nozzle = float(profile.get("nozzle_diameter_mm", .4))
    layer = float(profile.get("layer_height_mm", .2))
    build = np.asarray(profile.get("build_volume_mm", [220., 220., 250.]), dtype=float)
    wall = float(profile.get("minimum_wall_mm", 1.2))
    if not all(math.isfinite(v) for v in (nozzle, layer, wall)) or not .1 <= nozzle <= 2 or not .03 <= layer <= nozzle or not .3 <= wall <= 10 or build.shape != (3,) or not np.isfinite(build).all() or np.any(build <= 0):
        raise ValueError("invalid manufacturing profile: check nozzle, layer, wall and build volume")
    thickness = sampled_thickness(mesh, max(wall, 2 * nozzle))
    fits = bool(np.all(np.sort(mesh.extents) <= np.sort(build)))
    # XY is documented default print bed; normals identify downward surfaces above bed.
    above_bed = mesh.triangles_center[:, 2] > mesh.bounds[0, 2] + layer
    overhang = (mesh.face_normals[:, 2] < -math.cos(math.radians(45))) & above_bed
    overhang_area = float(np.sum(mesh.area_faces[overhang]))
    return {"passed": bool(thickness["passed"] and fits), "profile": {"nozzle_diameter_mm": nozzle, "layer_height_mm": layer, "minimum_wall_mm": wall, "build_volume_mm": build.tolist(), "material": profile.get("material", "unspecified")}, "fits_build_volume_under_axis_permutation": fits, "thickness": thickness, "support_required_in_current_z_orientation": overhang_area > 1., "downward_overhang_area_mm2": overhang_area, "strength": "not_evaluated", "note": "Review orientation/supports in slicer. Geometric checks do not establish material, adhesive or load performance."}
