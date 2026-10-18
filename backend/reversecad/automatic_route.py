"""Conservative selection of existing repair paths, using only guided imagery.

This selects a hypothesis to verify, not a new general object classifier.
Conflicting or absent evidence asks the user instead of inventing a repair.
"""
from pathlib import Path

import cv2
import numpy as np


def decide_route(cube_views, planar_views):
    if cube_views >= 2 and planar_views < 2:
        return "cube_exterior"
    if planar_views >= 1 and cube_views == 0:
        return "rectangular_planar"
    return None


def select_route(scan_dir, frames):
    from .face_first import lattice_candidates
    from .planar_repair import analyze_frame

    valid = [f for f in frames if f.get("rgb_path") and f.get("capture_region") is not None]
    selected = [valid[i] for i in np.unique(np.linspace(0, len(valid)-1, min(10, len(valid))).astype(int))] if valid else []
    evidence = []
    for frame in selected:
        raw = cv2.imread(str(Path(scan_dir)/frame["rgb_path"]))
        if raw is None:
            continue
        scale = min(1., 800/max(raw.shape[:2]))
        gray = cv2.cvtColor(cv2.resize(raw, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
        lattice = lattice_candidates(gray, frame["capture_region"])
        flat = False
        if frame.get("depth_path"):
            try:
                fit = analyze_frame(Path(scan_dir), frame)
                flat = fit["plane_inlier_fraction"] >= .8
            except ValueError:
                pass
        evidence.append({"frame_id": frame["frame_id"], "repeated_grid": bool(lattice), "supported_rectangle": flat})
    cube = sum(e["repeated_grid"] for e in evidence)
    planar = sum(e["supported_rectangle"] for e in evidence)
    scope = decide_route(cube, planar)
    return {"schema_version": 1, "scope": scope, "needs_choice": scope is None,
            "evidence": evidence, "color_used": False,
            "reason": "Repeated face outlines" if scope == "cube_exterior" else
                      "Flat surface with four supported edges" if scope else
                      "The scan does not clearly distinguish a flat part from a repeated 3D shape. Choose the shape to continue with this saved scan.",
            "assumption_requires_review": True}
