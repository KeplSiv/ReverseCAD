"""Small explicit CAD programs with per-operation geometry validation.

Original implementation: references VideoCAD's state/action representation and
CADFit's operation validation concept, without importing either project's code.
This first executor intentionally supports only the cube exterior sequence.
"""
from __future__ import annotations
import math


def cube_program(side_mm: float, radius_mm: float, evidence: dict | None = None) -> dict:
    operations = [
        {"id": "profile", "op": "rectangle", "width": "side_mm", "height": "side_mm", "plane": "XY"},
        {"id": "body", "op": "extrude", "distance": "side_mm", "centered": True},
    ]
    if radius_mm:
        operations.append({"id": "rounding", "op": "fillet", "radius": "radius_mm", "edges": "all"})
    return {"schema_version": 1, "units": "mm", "scope": "exterior_envelope_only",
            "parameters": {"side_mm": side_mm, "radius_mm": radius_mm},
            "operations": operations, "evidence": evidence or {},
            "assumptions": ["Equal cubie dimensions follow the 3×3 cube prior",
                            "Gap and fillet radius are user-adjustable assumptions",
                            "Hidden connector excluded; physical fit untested"]}


def execute_cube_program(program: dict):
    """Execute a bounded typed recipe, never arbitrary source or expressions."""
    import cadquery as cq
    parameters = program["parameters"]
    side, radius = float(parameters["side_mm"]), float(parameters["radius_mm"])
    if not all(math.isfinite(v) for v in (side, radius)) or not 7 <= side <= 40 or not 0 <= radius < side / 5:
        raise ValueError("Invalid cube program dimensions")
    expected = cube_program(side, radius)["operations"]
    if program.get("schema_version") != 1 or program.get("units") != "mm" or program.get("operations") != expected:
        raise ValueError("Unsupported CAD program; expected rectangle, centered extrusion, optional fillet")
    shape = cq.Workplane("XY").workplane(offset=-side / 2)
    validation = []
    for operation in expected:
        if operation["op"] == "rectangle":
            shape = shape.rect(side, side)
            if len(shape.wires().vals()) != 1 or not shape.val().isValid():
                raise ValueError("Rectangle profile did not produce one valid wire")
            validation.append({"operation": operation["id"], "valid": True, "kind": "closed_profile"})
        else:
            shape = shape.extrude(side) if operation["op"] == "extrude" else shape.edges().fillet(radius)
            solids = shape.solids().vals()
            if len(solids) != 1 or not solids[0].isValid() or solids[0].Volume() <= 0:
                raise ValueError(f"CAD operation {operation['id']} failed single-solid validation")
            bounds = solids[0].BoundingBox()
            dimensions = [bounds.xlen, bounds.ylen, bounds.zlen]
            if any(abs(d - side) > .001 for d in dimensions):
                raise ValueError("CAD operation changed the requested exterior dimensions")
            validation.append({"operation": operation["id"], "valid": True, "solid_count": 1,
                               "volume_mm3": round(solids[0].Volume(), 5),
                               "bounds_mm": [round(d, 5) for d in dimensions]})
    return shape, validation
