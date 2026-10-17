"""Editable trusted parametric source. Run with ReverseCAD pinned Python environment.
Edit parameters.json, then: python part.py. Regeneration writes edited.step/stl/3mf.
For complete independent validation, regenerate the revision through the service.
"""
import json
from pathlib import Path
import numpy as np
import cadquery as cq
from generator import build_shape, apply_transform, export_model
root = Path(__file__).resolve().parent
data = json.loads((root / "parameters.json").read_text())
part, normalized = build_shape(data["family"], data["parameters"])
matrix = np.asarray(data["T_object_part_mm"]).reshape((4, 4), order="F")
part = apply_transform(part, matrix)
for extension in ("step", "stl", "3mf"):
    export_model(part, root / ("edited." + extension))
