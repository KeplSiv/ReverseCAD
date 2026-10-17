"""Photo-guided 3x3 cube exterior completion.

The photo establishes an outlier cell in a repeated visible face. It does not
establish millimeter scale or the hidden connector of the missing cubie.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


class CubeInputError(ValueError):
    pass


def _photo(raw: bytes) -> np.ndarray:
    if len(raw) > 700_000:
        raise CubeInputError("Use a photo under 700 KB; the phone can resize it before upload")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            if image.width < 240 or image.height < 240 or image.width * image.height > 24_000_000:
                raise CubeInputError("Photo resolution must be between 240 px and 24 megapixels")
            image.thumbnail((1500, 1500))
            return np.asarray(image)
    except CubeInputError:
        raise
    except Exception as exc:
        raise CubeInputError("Could not read the selected photo") from exc


def _face_corners(corners: list, width: int, height: int) -> np.ndarray:
    if not isinstance(corners, list) or len(corners) != 4:
        raise CubeInputError("Mark four corners of one visible 3×3 face, clockwise")
    try:
        points = np.asarray(corners, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise CubeInputError("Face corners must be normalized image coordinates") from exc
    if points.shape != (4, 2) or not np.isfinite(points).all() or (points < 0).any() or (points > 1).any():
        raise CubeInputError("Face corners must be four points inside the image")
    points = points * [width, height]
    contour = points.astype(np.float32)
    if not cv2.isContourConvex(contour) or cv2.contourArea(contour) < width * height * .005:
        raise CubeInputError("Marked corners do not enclose a usable cube face")
    if min(np.linalg.norm(points[(i + 1) % 4] - points[i]) for i in range(4)) < 40:
        raise CubeInputError("Move closer or mark a larger visible face")
    return contour


def analyze_cube_face(raw: bytes, corners: list | None = None) -> dict:
    image = _photo(raw)
    if corners is None or corners == []:
        result = _automatic_face(image)
    else:
        result = _analyze_face(image, corners)
    result["photo_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def _analyze_face(image: np.ndarray, corners: list) -> dict:
    height, width = image.shape[:2]
    face = _face_corners(corners, width, height)
    target = np.float32([[0, 0], [600, 0], [600, 600], [0, 600]])
    to_square = cv2.getPerspectiveTransform(face, target)
    rectified = cv2.warpPerspective(image, to_square, (600, 600))
    lab = cv2.cvtColor(rectified, cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(rectified, cv2.COLOR_RGB2HSV)
    values = []
    rgb_values = []
    brightness = []
    for row in range(3):
        for col in range(3):
            y, x = row * 200, col * 200
            patch_lab = lab[y + 65:y + 135, x + 65:x + 135]
            patch_rgb = rectified[y + 65:y + 135, x + 65:x + 135]
            patch_hsv = hsv[y + 65:y + 135, x + 65:x + 135]
            values.append(np.median(patch_lab.reshape(-1, 3), axis=0))
            rgb_values.append(np.median(patch_rgb.reshape(-1, 3), axis=0))
            brightness.append(float(np.median(patch_hsv[:, :, 2])))
    colors = np.asarray(values)
    reference = np.median(colors, axis=0)
    distances = np.linalg.norm(colors - reference, axis=1)
    order = np.argsort(distances)[::-1]
    index = int(order[0])
    best, second = float(distances[index]), float(distances[order[1]])
    difference = best - second
    brightness_drop = float(np.median(brightness) - brightness[index])
    confidence = ("high" if best >= 30 and difference >= 14 and second <= 28 and brightness_drop >= 25
                  else "medium" if best >= 18 and difference >= 7 and brightness_drop >= 10
                  else "needs_review")
    row, col = divmod(index, 3)
    if row == 1 and col == 1:
        kind = "center"
    elif row == 1 or col == 1:
        kind = "edge"
    else:
        kind = "corner"
    from_square = cv2.getPerspectiveTransform(target, face)
    square = np.float32([[[col * 200, row * 200], [(col + 1) * 200, row * 200],
                          [(col + 1) * 200, (row + 1) * 200], [col * 200, (row + 1) * 200]]])
    polygon = cv2.perspectiveTransform(square, from_square)[0] / [width, height]
    color = np.median(np.delete(np.asarray(rgb_values), index, axis=0), axis=0)
    return {
        "schema_version": 1,
        "face_corners": (face / [width, height]).round(6).tolist(),
        "detection_method": "manual_corners",
        "missing_cell": {"row": row, "column": col, "type": kind},
        "confidence": confidence,
        "outlier_score": round(best, 1),
        "score_margin": round(difference, 1),
        "brightness_drop": round(brightness_drop, 1),
        "cell_scores": [round(float(value), 1) for value in distances],
        "missing_polygon": polygon.round(6).tolist(),
        "face_color_rgb": [int(round(value)) for value in color],
        "exterior_details": _visible_details(rectified, index),
        "evidence": "Visible face colors and a user-marked 3×3 grid; no hidden connector or metric scale inferred",
        "measurement_status": "needs_independent_ruler_or_calipers",
    }


def _visible_details(rectified: np.ndarray, missing_index: int) -> dict:
    """Estimate visible tile outline proportions; these are not mechanical tolerances.

    Only accept a consistent set of center-connected outlines. Rounded face
    outlines do not prove a three-dimensional fillet, so rounding stays a prior.
    """
    lab = cv2.cvtColor(rectified, cv2.COLOR_RGB2LAB).astype(float)
    widths = []
    for index in range(9):
        if index == missing_index:
            continue
        row, col = divmod(index, 3)
        tile = lab[row*200:(row+1)*200, col*200:(col+1)*200]
        reference = np.median(tile[70:130, 70:130].reshape(-1, 3), axis=0)
        mask = (np.linalg.norm(tile-reference, axis=2) < 24).astype(np.uint8)
        _, labels = cv2.connectedComponents(mask)
        label = labels[100, 100]
        if label == 0:
            continue
        component = labels == label
        # Central cross-sections avoid mistaking a rounded corner for a gap.
        for profile in (component[80:120].mean(axis=0), component[:, 80:120].mean(axis=1)):
            locations = np.flatnonzero(profile > .8)
            if len(locations) and 150 <= locations[-1]-locations[0]+1 <= 198:
                widths.append(float(locations[-1]-locations[0]+1))
    if len(widths) >= 6 and np.median(np.abs(np.asarray(widths)-np.median(widths))) <= 6:
        return {"gap_face_fraction": round((200-float(np.median(widths)))/600, 6),
                "gap_source": "estimated_visible_outline_spacing", "outline_samples": len(widths),
                "radius_face_fraction": .02, "radius_source": "rounded_cubie_prior_not_measured"}
    return {"gap_face_fraction": .01, "gap_source": "cube_prior_not_resolved_in_photo",
            "outline_samples": len(widths), "radius_face_fraction": .02,
            "radius_source": "rounded_cubie_prior_not_measured"}


def _ordered_quad(points: np.ndarray) -> np.ndarray:
    points = points.reshape(4, 2).astype(np.float32)
    center = points.mean(axis=0)
    points = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
    return np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)


def _automatic_face(image: np.ndarray) -> dict:
    """Fit visible same-color face hulls, then validate the repeated 3x3 cells.

    Restricted to a mostly solved face with one dark missing cell. Never promote
    an arbitrary rectangle or a complete uniform face to a confident repair.
    """
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    hue, saturation, value = cv2.split(hsv)
    masks = [(saturation < sat) & (value > light)
             for sat in (65, 95) for light in (150, 180, 205)]
    masks += [((np.minimum(abs(hue.astype(float) - h), 180 - abs(hue.astype(float) - h)) < 13)
               & (saturation > 100) & (value > 90)) for h in (0, 20, 35, 60, 105, 120)]
    candidates = []
    target = np.float32([[0, 0], [300, 0], [300, 300], [0, 300]])
    for selected in masks:
        seen = set()
        mask = selected.astype(np.uint8) * 255
        for fraction in (.008, .025, .045):
            size = max(3, int(min(width, height) * fraction) | 1)
            closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
                hull = cv2.convexHull(contour)
                area = cv2.contourArea(hull)
                if not width * height * .025 < area < width * height * .85:
                    continue
                for epsilon in (.015, .025, .04, .06):
                    approx = cv2.approxPolyDP(hull, epsilon * cv2.arcLength(hull, True), True)
                    if len(approx) != 4:
                        continue
                    face = _ordered_quad(approx)
                    key = tuple((face.flatten() / 8).astype(int))
                    if key in seen:
                        continue
                    seen.add(key)
                    edges = np.linalg.norm(face - np.roll(face, 1, axis=0), axis=1)
                    if edges.min() < 60 or edges.max() / edges.min() > 3:
                        continue
                    corners = (face / [width, height]).tolist()
                    result = _analyze_face(image, corners)
                    if result["confidence"] != "high":
                        continue
                    warp = cv2.warpPerspective(mask, cv2.getPerspectiveTransform(face, target), (300, 300))
                    coverage = [float(np.mean(warp[r*100+30:r*100+70, c*100+30:c*100+70] > 0))
                                for r in range(3) for c in range(3)]
                    missing = result["missing_cell"]["row"] * 3 + result["missing_cell"]["column"]
                    intact = np.delete(coverage, missing)
                    if np.min(intact) < .65 or coverage[missing] > .4:
                        continue
                    score = float(np.mean(intact) - coverage[missing]) * 100 + result["score_margin"]
                    candidates.append((score, result))
    if not candidates:
        raise CubeInputError("Could not confidently find a missing piece. Show a mostly same-colored face with one gap, keep all four corners visible, and try again. You can also mark the face manually.")
    candidates.sort(key=lambda item: item[0], reverse=True)
    result = candidates[0][1]
    result["detection_method"] = "automatic_color_hull_grid"
    result["evidence"] = "Automatically detected color boundary and repeated 3×3 face; one dark outlier cell. No hidden connector or metric scale inferred."
    return result


def build_outer_cubie(face_width_mm: float, gap_mm: float, radius_mm: float, analysis: dict | None = None) -> list[dict]:
    """Return checksum-bound parametric-source, STEP and STL exterior mockups."""
    if not all(math.isfinite(v) for v in (face_width_mm, gap_mm, radius_mm)):
        raise CubeInputError("Dimensions must be finite")
    if not 30 <= face_width_mm <= 120 or not 0 <= gap_mm <= 3:
        raise CubeInputError("Cube width must be 30–120 mm and the piece gap 0–3 mm")
    side = face_width_mm / 3 - gap_mm
    if not 7 <= side <= 40 or not 0 <= radius_mm < side / 5:
        raise CubeInputError("Rounded corner radius must be less than one fifth of the cubie width")
    import cadquery as cq
    from .cad_program import cube_program, execute_cube_program
    evidence = {"scale_source": "user_measurement", "face_width_mm": face_width_mm,
                "gap_mm": gap_mm, "radius_mm": radius_mm,
                "detail_status": "visible_spacing_estimate_or_prior;_3d_rounding_prior"}
    if analysis is not None:
        if not isinstance(analysis, dict):
            raise CubeInputError("Analysis must be an object")
        cell = analysis.get("missing_cell", {})
        if not isinstance(cell, dict) or any(type(cell.get(key)) is not int or not 0 <= cell[key] <= 2 for key in ("row", "column")):
            raise CubeInputError("Analysis has an invalid missing cell")
        digest = analysis.get("photo_sha256", "")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CubeInputError("Analysis has an invalid photo hash")
        if analysis.get("confidence") not in ("high", "medium"):
            raise CubeInputError("Review the detection before generating a repair")
        details = analysis.get("exterior_details", {})
        if isinstance(details, dict):
            evidence["photo_detail_estimates"] = {key: details[key] for key in
                ("gap_source", "radius_source", "gap_face_fraction", "radius_face_fraction", "outline_samples")
                if key in details and isinstance(details[key], (int, float, str))}
        evidence.update({"photo_sha256": digest, "missing_cell": {k: cell[k] for k in ("row", "column")},
                         "detection_confidence": analysis["confidence"], "provenance": "analysis_forwarded_by_client"})
    program = cube_program(side, radius_mm, evidence)
    shape, validation = execute_cube_program(program)
    program["validation"] = validation
    source = (
        "import cadquery as cq\n"
        f"face_width_mm = {face_width_mm!r}\n"
        f"piece_gap_mm = {gap_mm!r}\n"
        f"corner_radius_mm = {radius_mm!r}\n"
        "side_mm = face_width_mm / 3 - piece_gap_mm\n"
        "part = cq.Workplane('XY').workplane(offset=-side_mm / 2).rect(side_mm, side_mm).extrude(side_mm)\n"
        "if corner_radius_mm: part = part.edges().fillet(corner_radius_mm)\n"
        "# Exterior envelope only. No hidden locking stem or physical fit claim.\n"
    )
    with tempfile.TemporaryDirectory(prefix="reversecad-cube-") as tmp:
        root = Path(tmp)
        local = {}
        if not shape.val().isValid():
            raise CubeInputError("Could not make a valid exterior solid")
        (root / "repair_plan.json").write_text(json.dumps(program, indent=2))
        (root / "outer_cubie.py").write_text(source)
        cq.exporters.export(shape, str(root / "outer_cubie.step"))
        cq.exporters.export(shape, str(root / "outer_cubie.stl"), tolerance=0.08, angularTolerance=0.18)
        (root / "measurements.json").write_text(json.dumps({
            "face_width_mm": face_width_mm, "piece_gap_mm": gap_mm,
            "corner_radius_mm": radius_mm, "outer_side_mm": side,
            "scope": "exterior_envelope_only", "physical_fit": "not_tested",
            "hidden_connector": "not_modeled",
            "detail_provenance": evidence.get("photo_detail_estimates", {"source": "caller_supplied_parameters"}),
        }, indent=2))
        for path in root.iterdir():
            content = path.read_bytes()
            local[path.name] = {"name": path.name, "sha256": hashlib.sha256(content).hexdigest(),
                                "size": len(content), "base64": base64.b64encode(content).decode("ascii")}
    return [local[name] for name in sorted(local)]
