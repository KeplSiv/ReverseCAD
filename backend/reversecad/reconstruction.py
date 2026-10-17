"""Bounded RGB-D reconstruction of observed surfaces (no completion or GT access).

The public entry point is also used by service workers and offline benchmarks.
Camera poses remain metric and fixed. TSDF is a visualization surface; dimensions
come from confidence-filtered native observations, never from voxel pitch claims.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import cv2
import numpy as np

from .geometry import (AR_TO_CV, dot, fit_cylinder_frustum, fit_plane, project,
                       rigid_transform, scaled_intrinsics, transform_points, unproject)

VERSION = "rgbd-1.0.0"
MAX_FRAMES = 240
MAX_SCAN_BYTES = 512 * 1024 * 1024
MAX_DEPTH_PIXELS = 640 * 480
MAX_POINTS_PER_FRAME = 8000
MAX_PREVIEW_POINTS = 30000


def _json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
    temporary.replace(path)


def _asset(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Invalid capture asset path")
    unresolved = root / relative
    if any(p.is_symlink() for p in [unresolved, *unresolved.parents] if p.is_relative_to(root)):
        raise ValueError("Capture assets must not contain symbolic links")
    path = unresolved.resolve()
    if Path(relative).is_absolute() or ".." in Path(relative).parts or not path.is_relative_to(root.resolve()):
        raise ValueError("Capture asset path must remain inside its scan package")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing capture asset: {relative}")
    return path


def _load_package(scan_dir: Path):
    manifest = json.loads(_asset(scan_dir, "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported capture schema version")
    frames_path = _asset(scan_dir, "frames.jsonl")
    if frames_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Capture metadata exceeds the bounded frame budget")
    frames = [json.loads(line) for line in frames_path.read_text().splitlines() if line.strip()]
    if len(frames) > MAX_FRAMES or len(frames) != manifest.get("frame_count"):
        raise ValueError("Capture frame count is invalid or exceeds the 240-frame budget")
    if len({f.get("frame_id") for f in frames}) != len(frames):
        raise ValueError("Duplicate capture frame identifiers")
    if any(f.get("scan_id") != manifest.get("scan_id") for f in frames):
        raise ValueError("Frame scan identifier disagrees with manifest")
    assets = {"manifest.json", "frames.jsonl"}
    for f in frames:
        for name in ("rgb_path", "depth_path", "confidence_path", "mask_path"):
            if f.get(name):
                assets.add(f[name])
    if sum(_asset(scan_dir, p).stat().st_size for p in assets) > MAX_SCAN_BYTES:
        raise ValueError("Scan exceeds the 512 MiB resource budget")
    checksums_path = scan_dir / "checksums.json"
    if checksums_path.exists():
        checksums = json.loads(checksums_path.read_text())
        for name, expected in checksums.items():
            asset = _asset(scan_dir, name)
            if asset.stat().st_size > MAX_SCAN_BYTES:
                raise ValueError("Capture asset exceeds the resource budget")
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()
            if digest != expected:
                raise ValueError(f"Capture checksum mismatch: {name}")
    segments = {}
    for segment in manifest.get("segments", []):
        if not segment.get("registered"):
            raise ValueError("Unregistered scan segment: register its origin with overlap evidence before merging")
        sid = segment.get("segment_id")
        if sid in segments:
            raise ValueError("Duplicate scan segment")
        segments[sid] = rigid_transform(segment["T_object_world"])
    if not segments:
        raise ValueError("Capture has no registered coordinate frame")
    return manifest, frames, segments


def _read_depth(scan_dir: Path, frame: dict) -> np.ndarray:
    width, height = int(frame["depth_width"]), int(frame["depth_height"])
    if min(width, height) < 1 or width * height > MAX_DEPTH_PIXELS:
        raise ValueError("Unsupported native depth resolution/resource limit")
    stride = int(frame.get("depth_row_bytes", width * 4))
    if stride < width * 4 or stride > width * 4 + 8192 or stride % 4:
        raise ValueError("Invalid native depth row stride")
    order = frame.get("depth_byte_order", "little")
    if order not in ("little", "big"):
        raise ValueError("Unsupported depth byte order")
    data = _asset(scan_dir, frame["depth_path"]).read_bytes()
    if len(data) != height * stride:
        raise ValueError("Depth asset byte count does not match dimensions and row stride")
    return np.ndarray((height, width), dtype="<f4" if order == "little" else ">f4",
                      buffer=data, strides=(stride, 4)).astype(np.float32, copy=True)


def _mask(scan_dir: Path, frame: dict, depth: np.ndarray, annotations: dict) -> tuple[np.ndarray, str]:
    height, width = depth.shape
    if frame.get("mask_path"):
        raw = np.frombuffer(_asset(scan_dir, frame["mask_path"]).read_bytes(), dtype=np.uint8)
        if raw.size == width * height:
            selected = raw.reshape(height, width) > 0
        elif raw.size == frame["rgb_width"] * frame["rgb_height"]:
            selected = cv2.resize(raw.reshape(frame["rgb_height"], frame["rgb_width"]),
                                  (width, height), interpolation=cv2.INTER_NEAREST) > 0
        else:
            raise ValueError("Foreground mask size must match native depth or calibrated RGB")
        source = "capture_foreground_mask"
    elif "crop_min_m" in annotations:
        selected, source = np.ones_like(depth, dtype=bool), "user_3d_crop"
    else:
        # Depth-connected center seed keeps narrow connected handles. This is an
        # initial region proposal, not an assertion that the table was excluded.
        valid = np.isfinite(depth) & (depth > .04) & (depth < 3)
        coordinates = np.column_stack(np.nonzero(valid))
        selected = np.zeros_like(depth, dtype=bool)
        if len(coordinates):
            distance = np.sum(((coordinates - [height / 2, width / 2]) / [height, width]) ** 2, axis=1)
            y, x = coordinates[np.argmin(distance)]
            flood = np.where(valid, depth, -100).astype(np.float32)
            floodmask = np.zeros((height + 2, width + 2), dtype=np.uint8)
            cv2.floodFill(flood, floodmask, (int(x), int(y)), 0,
                         loDiff=.018, upDiff=.018,
                         flags=4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8))
            selected = (floodmask[1:-1, 1:-1] > 0) & valid
        source = "depth_connected_proposal_needs_confirmation"
    override = annotations.get("mask_corrections", {}).get(frame["frame_id"], {})
    for mode, fill in (("include_polygons", 1), ("exclude_polygons", 0)):
        for polygon in override.get(mode, []):
            polygon = np.asarray(polygon, dtype=float)
            if polygon.ndim != 2 or polygon.shape[1] != 2 or not np.isfinite(polygon).all():
                raise ValueError("Mask correction polygon requires finite raw depth pixel coordinates")
            raster = selected.astype(np.uint8)
            cv2.fillPoly(raster, [np.round(polygon).astype(np.int32)], fill)
            selected = raster > 0
            source = "user_mask_correction"
    return selected, source


def _prepare(scan_dir: Path, frames: list[dict], segments: dict, annotations: dict, stage: str):
    accepted, rejected, warnings = [], [], []
    previous_time: dict[str, float] = {}
    timestamps_gaps = []
    crop = None
    scale = _scale_factor(annotations)
    if "crop_min_m" in annotations or "crop_max_m" in annotations:
        crop = np.asarray([annotations.get("crop_min_m"), annotations.get("crop_max_m")], dtype=float)
        if crop.shape != (2, 3) or not np.isfinite(crop).all() or np.any(crop[1] <= crop[0]):
            raise ValueError("Object crop must have finite ordered minimum and maximum corners")
    for frame in frames:
        fid = frame.get("frame_id", "unknown")
        if frame.get("schema_version") != 1 or frame.get("orientation", "up") != "up":
            raise ValueError("Frames must use schema v1 and calibrated raw orientation 'up'")
        if frame.get("segment_id") not in segments:
            raise ValueError("Frame references an unknown/unregistered segment")
        timestamp = float(frame["timestamp_s"])
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Capture timestamps must be finite")
        prior = previous_time.get(frame["segment_id"])
        if prior is not None and timestamp <= prior:
            raise ValueError("Capture timestamps must increase within each segment")
        if prior is not None and timestamp - prior > 2:
            timestamps_gaps.append({"frame_id": fid, "gap_s": timestamp - prior})
        previous_time[frame["segment_id"]] = timestamp
        quality = frame.get("quality", {})
        reason = None
        if not frame.get("depth_path"):
            reason = "missing_native_depth"
        elif frame.get("tracking_state") != "normal":
            reason = "tracking_not_normal"
        elif quality.get("accepted") is False:
            reason = "capture_quality_rejected"
        elif float(quality.get("blur_score", 100)) < 8:
            reason = "blurred_view"
        if reason:
            rejected.append({"frame_id": fid, "reason": reason})
            continue
        depth = _read_depth(scan_dir, frame)
        height, width = depth.shape
        if not (0 < frame["rgb_width"] <= 4096 and 0 < frame["rgb_height"] <= 4096):
            raise ValueError("RGB metadata exceeds reconstruction resource limit")
        rgb = cv2.imread(str(_asset(scan_dir, frame["rgb_path"])), cv2.IMREAD_COLOR)
        if rgb is None or rgb.shape[:2] != (frame["rgb_height"], frame["rgb_width"]):
            raise ValueError("RGB dimensions disagree with calibrated frame metadata")
        if rgb.size > 4096 * 4096 * 3:
            raise ValueError("RGB image exceeds reconstruction resource limit")
        rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
        calibration_mode = frame.get("depth_calibration_mode", "pixel_center")
        if calibration_mode == "native_arkit":
            xx, yy = np.meshgrid(np.arange(width) * (rgb.shape[1] / width),
                                 np.arange(height) * (rgb.shape[0] / height))
            color_depth = cv2.remap(rgb, xx.astype(np.float32), yy.astype(np.float32), interpolation=cv2.INTER_LINEAR)
        else:
            color_depth = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
        selected, mask_source = _mask(scan_dir, frame, depth, annotations)
        valid = np.isfinite(depth) & (depth > .04) & (depth < 3) & selected
        raw_valid = valid.copy()
        if frame.get("confidence_path"):
            confidence = np.frombuffer(_asset(scan_dir, frame["confidence_path"]).read_bytes(), dtype=np.uint8)
            if confidence.size != width * height or np.any(confidence > 2):
                raise ValueError("Confidence must be native-size ARKit labels 0, 1, or 2")
            if stage != "raw_depth_pose":
                valid &= confidence.reshape(height, width) >= 1
        else:
            warnings.append("missing_confidence: native confidence unavailable; uncertainty remains uncalibrated")
        k = scaled_intrinsics(frame["intrinsics"], frame["intrinsics_width"],
                              frame["intrinsics_height"], width, height, mode=calibration_mode)
        if frame.get("depth_intrinsics") is not None:
            k = scaled_intrinsics(frame["depth_intrinsics"], width, height, width, height)
        pose = dot(dot(segments[frame["segment_id"]], rigid_transform(frame["T_world_camera"])), AR_TO_CV)
        # Crop in the registered metric frame, never in a display orientation.
        if crop is not None:
            points, pixels = unproject(depth, k, pose, raw_valid)
            inside = np.all((points * scale >= crop[0]) & (points * scale <= crop[1]), axis=1)
            keep = np.zeros_like(valid)
            keep[pixels[inside, 1], pixels[inside, 0]] = True
            valid &= keep
            raw_valid &= keep
        points, pixels = unproject(depth, k, pose, valid)
        raw_points, raw_pixels = unproject(depth, k, pose, raw_valid)
        if len(points) < 30:
            rejected.append({"frame_id": fid, "reason": "insufficient_foreground_depth"})
            continue
        # Limit retained points without changing the native integration image.
        indices = np.linspace(0, len(points) - 1, min(len(points), MAX_POINTS_PER_FRAME), dtype=int)
        raw_indices = np.linspace(0, len(raw_points) - 1, min(len(raw_points), MAX_POINTS_PER_FRAME), dtype=int)
        feature_scale = min(1, 640 / max(rgb.shape[:2]))
        fw, fh = round(rgb.shape[1] * feature_scale), round(rgb.shape[0] * feature_scale)
        feature_rgb = cv2.resize(rgb, (fw, fh), interpolation=cv2.INTER_AREA)
        feature_k = scaled_intrinsics(frame["intrinsics"], frame["intrinsics_width"],
                                      frame["intrinsics_height"], fw, fh)
        accepted.append({"frame_id": fid, "segment_id": frame["segment_id"], "depth": np.where(valid, depth, 0),
                         "color": color_depth, "k": k, "pose": pose, "feature_rgb": feature_rgb,
                         "feature_k": feature_k, "mask_source": mask_source,
                         "depth_calibration_mode": calibration_mode,
                         "points": points[indices], "colors": color_depth[pixels[indices, 1], pixels[indices, 0]] / 255.,
                         "raw_points": raw_points[raw_indices],
                         "raw_colors": color_depth[raw_pixels[raw_indices, 1], raw_pixels[raw_indices, 0]] / 255.,
                         "valid_depth_fraction": float(np.count_nonzero(valid) / valid.size),
                         "native_foreground_samples": len(points)})
    if timestamps_gaps:
        warnings.append("timestamp_gaps: recorded views contain gaps over 2 seconds; inspect missing coverage")
    return accepted, rejected, warnings, timestamps_gaps


def _voxel_fuse(points: np.ndarray, colors: np.ndarray, voxel_m: float):
    indices = np.floor(points / voxel_m).astype(np.int64)
    _, inverse, counts = np.unique(indices, axis=0, return_inverse=True, return_counts=True)
    summed = np.zeros((len(counts), 3))
    summed_color = np.zeros_like(summed)
    for axis in range(3):
        summed[:, axis] = np.bincount(inverse, weights=points[:, axis])
        summed_color[:, axis] = np.bincount(inverse, weights=colors[:, axis])
    return summed / counts[:, None], summed_color / counts[:, None]


def _registration_evidence(frames: list[dict]) -> list[dict]:
    """Validate explicitly supplied segment transforms against metric overlap.

    This does not guess an alignment or optimize scale. A reset without a known
    transform must be registered by the user/relocalization route before retry.
    """
    from scipy.spatial import cKDTree

    groups = {}
    for frame in frames:
        groups.setdefault(frame["segment_id"], []).append(frame["points"])
    if len(groups) < 2:
        return []
    first, *rest = groups
    reference = np.concatenate(groups[first])
    reports = []
    for identifier in rest:
        source = np.concatenate(groups[identifier])
        step_a, step_b = max(1, len(source) // 5000), max(1, len(reference) // 5000)
        forward = cKDTree(reference).query(source[::step_a], workers=1)[0]
        backward = cKDTree(source).query(reference[::step_b], workers=1)[0]
        distances = np.r_[forward, backward]
        inlier = distances < .004
        overlap = float(np.mean(inlier))
        rms = float(np.sqrt(np.mean(distances[inlier] ** 2)) * 1000) if np.any(inlier) else None
        if overlap < .12 or rms is None or rms > 3:
            raise ValueError("Registered segment transform failed overlap/residual checks; recapture overlap or register the segment")
        reports.append({"segment_id": identifier, "reference_segment_id": first,
                        "bidirectional_overlap_within_4mm": overlap, "inlier_rms_mm": rms,
                        "alignment": "supplied proper rigid transform; no scale optimization"})
        reference = np.concatenate((reference, source))
    return reports


def _depth_consistency(frames: list[dict]) -> dict:
    """Cross-view free-space violations detect inconsistency without fitting it away."""
    violations, residuals = [], []
    offsets = sorted({1, max(2, len(frames) // 3), max(3, len(frames) // 2)})
    pairs = [(frames[i], frames[i + offset]) for offset in offsets for i in range(len(frames) - offset)]
    for source, target in pairs[::max(1, math.ceil(len(pairs) / 48))]:
        points = source["points"][::max(1, len(source["points"]) // 2000)]
        uv, z = project(points, target["k"], target["pose"])
        inside = (np.isfinite(uv).all(axis=1) & (z > .04)
                  & (uv[:, 0] >= 1) & (uv[:, 0] < target["depth"].shape[1] - 2)
                  & (uv[:, 1] >= 1) & (uv[:, 1] < target["depth"].shape[0] - 2))
        uv = np.round(uv[inside]).astype(int)
        predicted = z[inside]
        measured = target["depth"][uv[:, 1], uv[:, 0]]
        valid = measured > 0
        delta = predicted[valid] - measured[valid]
        # Points substantially behind a foreground surface can simply be occluded.
        visible = delta <= .004
        residuals.extend(np.abs(delta[visible]).tolist())
        violations.extend((delta[visible] < -.005).tolist())
    return {"compared_visible_samples": len(residuals),
            "median_visible_residual_mm": float(np.median(residuals) * 1000) if residuals else None,
            "free_space_violation_fraction": float(np.mean(violations)) if violations else None,
            "method": "fixed-pose native-depth reprojection; behind-surface occlusions excluded"}


def _rgb_consistency(frames: list[dict]) -> tuple[dict, np.ndarray, np.ndarray]:
    """Fixed-metric-pose ORB reprojection and bounded triangulation.

    No bundle adjustment/similarity fit can hide a depth-scale error. RGB anchors
    are retained separately and only fuse if consistent with native metric depth.
    """
    orb = cv2.ORB_create(nfeatures=700, edgeThreshold=12, fastThreshold=12)
    selected = frames[::max(1, math.ceil(len(frames) / 24))]
    for frame in selected:
        im = frame["feature_rgb"]
        mask = cv2.resize((frame["depth"] > 0).astype(np.uint8) * 255,
                          (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
        frame["keypoints"], frame["descriptors"] = orb.detectAndCompute(cv2.cvtColor(im, cv2.COLOR_RGB2GRAY), mask)
    total_matches, errors, depth_errors, anchors, anchor_colors, pairs = 0, [], [], [], [], []
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    for a, b in zip(selected, selected[1:]):
        if a["descriptors"] is None or b["descriptors"] is None:
            continue
        baseline = float(np.linalg.norm(a["pose"][:3, 3] - b["pose"][:3, 3]))
        if not .003 < baseline < .8:
            continue
        forward = matcher.knnMatch(a["descriptors"], b["descriptors"], k=2)
        backward = matcher.match(b["descriptors"], a["descriptors"])
        reverse = {match.queryIdx: match.trainIdx for match in backward}
        matches = [row[0] for row in forward if len(row) == 2 and row[0].distance < .7 * row[1].distance
                   and reverse.get(row[0].trainIdx) == row[0].queryIdx]
        if len(matches) < 12:
            continue
        uv_a = np.array([a["keypoints"][m.queryIdx].pt for m in matches])
        uv_b = np.array([b["keypoints"][m.trainIdx].pt for m in matches])
        # Independent robust image geometry rejects repeated-texture descriptor
        # aliases before they are used to accuse a metric pose of drift. No pose
        # is adjusted by this fundamental-matrix consistency filter.
        _, image_inliers = cv2.findFundamentalMat(uv_a, uv_b, cv2.FM_RANSAC, 1.5, .995)
        if image_inliers is None or np.count_nonzero(image_inliers) < 12 or np.mean(image_inliers) < .6:
            continue
        good_image = image_inliers.ravel().astype(bool)
        uv_a, uv_b = uv_a[good_image], uv_b[good_image]
        matches = [m for m, keep in zip(matches, good_image) if keep]
        total_matches += len(matches)
        # Native depth mapping uses pixel centers; nearest sampling is explicit.
        # Use each calibration matrix directly, including native_arkit rather
        # than assuming all native depth has a resized-image pixel-center offset.
        feature_rays = dot(np.column_stack((uv_a, np.ones(len(matches)))), np.linalg.inv(a["feature_k"]).T)
        depth_uv_h = dot(feature_rays, a["k"].T)
        depth_uv = np.round(depth_uv_h[:, :2] / depth_uv_h[:, 2, None]).astype(int)
        depth_uv = np.clip(depth_uv, 0, [a["depth"].shape[1] - 1, a["depth"].shape[0] - 1])
        depths = a["depth"][depth_uv[:, 1], depth_uv[:, 0]]
        rays = dot(np.column_stack((uv_a, np.ones(len(matches)))), np.linalg.inv(a["feature_k"]).T)
        metric_points = transform_points(rays * depths[:, None], a["pose"])
        reprojected, target_z = project(metric_points, b["feature_k"], b["pose"])
        error = np.linalg.norm(reprojected - uv_b, axis=1)
        supported = (depths > 0) & (target_z > 0)
        errors.extend(error[supported].tolist())
        p1 = dot(a["feature_k"], np.linalg.inv(a["pose"])[:3])
        p2 = dot(b["feature_k"], np.linalg.inv(b["pose"])[:3])
        homogeneous = cv2.triangulatePoints(p1, p2, uv_a.T, uv_b.T).T
        with np.errstate(divide="ignore", invalid="ignore"):
            xyz = homogeneous[:, :3] / homogeneous[:, 3, None]
        proj1, z1 = project(xyz, a["feature_k"], a["pose"])
        proj2, z2 = project(xyz, b["feature_k"], b["pose"])
        angle = np.linalg.norm(np.cross(xyz - a["pose"][:3, 3], xyz - b["pose"][:3, 3]), axis=1)
        denom = np.linalg.norm(xyz - a["pose"][:3, 3], axis=1) * np.linalg.norm(xyz - b["pose"][:3, 3], axis=1)
        parallax = np.arcsin(np.clip(angle / np.maximum(denom, 1e-12), 0, 1))
        delta = np.linalg.norm(xyz - metric_points, axis=1)
        good = (supported & np.isfinite(xyz).all(axis=1) & (z1 > 0) & (z2 > 0)
                & (error < 3) & (np.linalg.norm(proj1 - uv_a, axis=1) < 2)
                & (np.linalg.norm(proj2 - uv_b, axis=1) < 2) & (parallax > np.deg2rad(1))
                & (delta < np.maximum(.003, depths * .01)))
        depth_errors.extend(delta[supported & np.isfinite(delta)].tolist())
        if np.any(good):
            # Combine only independent RGB triangulation agreeing with depth.
            anchors.extend(((xyz[good] + metric_points[good]) / 2).tolist())
            uv = np.clip(np.round(uv_a[good]).astype(int), 0,
                         [a["feature_rgb"].shape[1] - 1, a["feature_rgb"].shape[0] - 1])
            anchor_colors.extend((a["feature_rgb"][uv[:, 1], uv[:, 0]] / 255.).tolist())
        pairs.append({"from": a["frame_id"], "to": b["frame_id"], "matches": len(matches),
                      "metric_consistent": int(np.count_nonzero(good)), "baseline_m": baseline})
    result = {"status": "supported" if len(anchors) >= 12 else "insufficient_texture_or_baseline",
              "matched_features": total_matches, "triangulated_metric_anchors": len(anchors),
              "median_reprojection_error_px": float(np.median(errors)) if errors else None,
              "inconsistent_fraction": float(np.mean(np.asarray(errors) > 5)) if errors else None,
              "median_depth_disagreement_mm": float(np.median(depth_errors) * 1000) if depth_errors else None,
              "pose_refinement": "none; fixed metric poses", "pairs": pairs}
    return result, np.asarray(anchors).reshape(-1, 3), np.asarray(anchor_colors).reshape(-1, 3)


def _tsdf(frames: list[dict], voxel_m: float, output_dir: Path):
    import open3d as o3d

    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel_m, sdf_trunc=max(voxel_m * 4, .004),
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
        volume_unit_resolution=16, depth_sampling_stride=2)
    for frame in frames:
        depth = frame["depth"].astype(np.float32)
        k = frame["k"]
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.ascontiguousarray(frame["color"])),
            o3d.geometry.Image(np.ascontiguousarray(depth)), depth_scale=1.0,
            depth_trunc=3.0, convert_rgb_to_intensity=False)
        intrinsic = o3d.camera.PinholeCameraIntrinsic(depth.shape[1], depth.shape[0],
                                                     k[0, 0], k[1, 1], k[0, 2], k[1, 2])
        volume.integrate(rgbd, intrinsic, np.linalg.inv(frame["pose"]))
    mesh = volume.extract_triangle_mesh()
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_unreferenced_vertices()
    if len(mesh.triangles) > 60000:
        mesh = mesh.simplify_quadric_decimation(60000)
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(output_dir / "observed_surface.ply"), mesh)
    return mesh


def _measurement(identifier: str, name: str, value: float, frames: list[str],
                 repeatability_mm: float | None = None, critical: bool = False):
    return {"id": identifier, "name": name, "value": float(value), "unit": "mm", "source": "depth_fit",
            "confirmed": False, "critical": critical, "uncertainty_mm": None,
            "uncertainty_status": "not_calibrated", "uncertainty_method":
            "No real-device error calibration; fit residual/repeatability do not bound systematic sensor error",
            "repeatability_mm": repeatability_mm, "observation_ids": frames}


def _scale_factor(annotations: dict) -> float:
    reference = annotations.get("scale_reference")
    if not reference:
        return 1.
    measured, observed = float(reference["measured_mm"]), float(reference["observed_mm"])
    uncertainty = reference.get("uncertainty_mm")
    if not math.isfinite(measured) or not math.isfinite(observed) or min(measured, observed) <= 0:
        raise ValueError("Scale reference requires finite positive measured and observed lengths")
    if uncertainty is not None and (not math.isfinite(float(uncertainty)) or float(uncertainty) < 0):
        raise ValueError("Scale reference uncertainty must be finite and nonnegative")
    factor = measured / observed
    if not .5 <= factor <= 2:
        raise ValueError("Scale factor outside 0.5–2; check units/calibration instead of hiding a large scale error")
    return factor


def _features(points: np.ndarray, frames: list[dict], annotations: dict):
    primitives, measurements = [], []
    frame_ids = [f["frame_id"] for f in frames]
    remaining = points
    for index in range(6):
        plane = fit_plane(remaining)
        if plane is None or np.mean(plane["inliers"]) < .12 or np.count_nonzero(plane["inliers"]) < 80:
            break
        view_support, view_offsets = [], []
        for frame in frames:
            signed_distances = dot(frame["points"] - plane["center_m"], plane["normal"])
            accepted = np.abs(signed_distances) < .0015
            if np.count_nonzero(accepted) >= 12:
                view_support.append(frame["frame_id"])
                view_offsets.append(float(np.median(signed_distances[accepted]) * 1000))
        primitives.append({"id": f"plane_{index}", "type": "plane", "center_m": plane["center_m"].tolist(),
                           "normal": plane["normal"].tolist(), "fit_residual_mm": plane["residual_mm"],
                           "inlier_count": int(np.count_nonzero(plane["inliers"])),
                           "degenerate": plane["degenerate"], "source": "depth_fit",
                           "observation_ids": view_support, "view_support_count": len(view_support),
                           "view_offset_range_mm": [min(view_offsets), max(view_offsets)] if view_offsets else None,
                           "uncertainty_status": "not_calibrated"})
        remaining = remaining[~plane["inliers"]]
        if len(remaining) < 100:
            break
    cylinder = fit_cylinder_frustum(points)
    if cylinder:
        cylinder.update({"id": "body_profile", "observation_ids": frame_ids})
        axis, center = np.asarray(cylinder["axis"]), np.asarray(cylinder["center_m"])
        view_radius = []
        view_support = []
        for frame in frames:
            delta = frame["points"] - center
            height = dot(delta, axis)
            radius = np.linalg.norm(delta - height[:, None] * axis, axis=1) - cylinder["taper"] * height
            selected = np.abs(radius * 1000 - cylinder["radius_mm"]) < 1.5
            if np.count_nonzero(selected) >= 20:
                view_radius.append(float(np.median(radius[selected]) * 1000))
                view_support.append(frame["frame_id"])
        repeatability = None
        if len(view_radius) >= 3:
            rng = np.random.default_rng(711)
            boot = np.mean(rng.choice(view_radius, (500, len(view_radius)), replace=True), axis=1)
            interval = np.quantile(boot, [.025, .975]).tolist()
            repeatability = float(max(interval) - min(interval))
            cylinder["view_bootstrap_radius_interval_mm"] = interval
            cylinder["view_radius_range_mm"] = [min(view_radius), max(view_radius)]
            cylinder["repeatability_method"] = "500 bootstrap resamples of per-view radius medians; excludes uncalibrated systematic error"
        cylinder["observation_ids"] = view_support
        primitives.append(cylinder)
        measurements.append(_measurement("body_radius", "Observed body radius at profile origin",
                                         cylinder["radius_mm"], view_support, repeatability, critical=True))
    contacts = annotations.get("contacts", [])
    for contact in contacts:
        center = np.asarray(contact.get("point_m"), dtype=float)
        radius = float(contact.get("radius_mm", 8)) / 1000
        if center.shape != (3,) or not np.isfinite(center).all() or not .001 <= radius <= .1:
            raise ValueError("Contact patch requires a finite location and 1–100 mm radius")
        patch = points[np.linalg.norm(points - center, axis=1) <= radius]
        plane = fit_plane(patch, threshold_m=.001)
        if plane is None or len(patch) < 30:
            primitives.append({"id": contact["id"], "type": "contact_patch", "status": "needs_measurement",
                               "point_m": center.tolist(), "reason": "Insufficient observed patch support"})
            continue
        # Contact normal follows the user's side selection, never an arbitrary TLS sign.
        user_normal = np.asarray(contact.get("normal", plane["normal"]), dtype=float)
        if user_normal.shape != (3,) or not np.isfinite(user_normal).all() or np.linalg.norm(user_normal) < 1e-8:
            raise ValueError("Contact normal must be a finite nonzero vector")
        normal = plane["normal"] * (1 if np.dot(plane["normal"], user_normal) >= 0 else -1)
        view_support = [f["frame_id"] for f in frames if np.count_nonzero(
            np.linalg.norm(f["points"] - center, axis=1) <= radius) >= 8]
        primitives.append({"id": contact["id"], "type": "contact_patch", "status":
                           "observed_unconfirmed" if len(view_support) >= 2 else "needs_measurement",
                           "point_m": plane["center_m"].tolist(), "normal": normal.tolist(),
                           "radius_mm": radius * 1000, "fit_residual_mm": plane["residual_mm"],
                           "inlier_count": int(np.count_nonzero(plane["inliers"])),
                           "observation_ids": view_support, "uncertainty_status": "not_calibrated",
                           "curvature_profile_id": "body_profile" if cylinder else None})
    if len(contacts) >= 2:
        # Selected points are user annotations, not scan-discovered mounting centers.
        distance = np.linalg.norm(np.asarray(contacts[0]["point_m"]) - np.asarray(contacts[1]["point_m"])) * 1000
        measurement = _measurement("contact_spacing", "Selected contact center spacing", distance, frame_ids, critical=True)
        measurement["selection_provenance"] = "user-selected points on observed surfaces; confirm mounting centers"
        measurements.append(measurement)
    return primitives, measurements


def reconstruct(scan_dir: Path, output_dir: Path, annotations: dict | None = None,
                stage: str = "rgb_assisted") -> dict:
    """Reconstruct immutable input and write traceable metric outputs.

    stage is an evaluator hook. Production always uses rgb_assisted. No evaluator
    ground truth is read. Inadequate evidence returns needs_input, never a solid.
    """
    start = time.monotonic()
    scan_dir, output_dir = Path(scan_dir), Path(output_dir)
    if stage not in ("raw_depth_pose", "filtered_fusion", "rgb_assisted"):
        raise ValueError("Unknown reconstruction stage")
    output_dir.mkdir(parents=True, exist_ok=True)
    if annotations is None:
        annotations = json.loads((scan_dir / "annotations.json").read_text()) if (scan_dir / "annotations.json").exists() else {}
    # Independent finite serialization check before annotations affect geometry.
    json.dumps(annotations, allow_nan=False)
    manifest, capture_frames, segments = _load_package(scan_dir)
    frames, rejected, warnings, gaps = _prepare(scan_dir, capture_frames, segments, annotations, stage)
    if not manifest.get("complete"):
        warnings.append("incomplete_capture: committed views recovered; capture was not ended normally")
    if not (scan_dir / "checksums.json").exists():
        warnings.append("checksum_manifest_absent: import lacks end-to-end asset checksums")
    if any(f["mask_source"].endswith("needs_confirmation") for f in frames):
        warnings.append("foreground_unconfirmed: confirm/correct depth-connected object region or apply a 3D crop")
    base = {"schema_version": 1, "algorithm_version": VERSION, "scan_id": manifest["scan_id"],
            "input_revision": {"manifest_sha256": hashlib.sha256((scan_dir / "manifest.json").read_bytes()).hexdigest(),
                               "annotations_sha256": hashlib.sha256(json.dumps(annotations, sort_keys=True).encode()).hexdigest()},
            "source": manifest.get("source"), "stage": stage, "unit": "mm", "warnings": warnings,
            "measurements": list(annotations.get("measurements", [])), "primitives": [],
            "observations": {"accepted_frames": [f["frame_id"] for f in frames], "rejected_frames": rejected},
            "metrics": {"accepted_frames": len(frames), "rejected_frames": len(rejected), "timestamp_gaps": gaps},
            "physical_validation": {"phone_sensing": "not_tested", "dimension_accuracy": "not_calibrated", "printed_fit": "not_tested"}}
    if not frames:
        base.update(status="needs_input", bounds_mm={"min": [], "max": [], "extent": []}, point_count=0)
        base["warnings"].append("No usable native depth: capture more supported views or enter manual dimensions")
        _json(output_dir / "scan_preview.json", {"vertices": [], "triangles": [], "colors": [], "normals": [], "unit": "mm"})
        _json(output_dir / "reconstruction.json", base)
        return base
    points = np.concatenate([f["points"] for f in frames])
    colors = np.concatenate([f["colors"] for f in frames])
    raw_points = np.concatenate([f["raw_points"] for f in frames])
    raw_colors = np.concatenate([f["raw_colors"] for f in frames])
    registration = _registration_evidence(frames)
    depth_consistency = _depth_consistency(frames)
    np.savez_compressed(output_dir / "points_raw.npz", points_m=raw_points, colors=raw_colors)
    if np.ptp(points, axis=0).max() > 1.5:
        base["warnings"].append("object_extent_too_large: crop the hand-sized target before surface integration")
    voxel_m = float(np.clip(np.ptp(points, axis=0).max() / 350, .0005, .004))
    fused, fused_colors = _voxel_fuse(points, colors, voxel_m if stage != "raw_depth_pose" else .00001)
    # Statistical isolated-point rejection preserves topology and narrow components;
    # it does not close holes or remove a whole detached fragment as "background".
    removed = 0
    if stage != "raw_depth_pose" and len(fused) > 100:
        from scipy.spatial import cKDTree
        distances = cKDTree(fused).query(fused, k=min(8, len(fused)), workers=1)[0][:, 1:].mean(axis=1)
        median = np.median(distances)
        mad = np.median(np.abs(distances - median))
        keep = distances <= max(median + 6 * mad, voxel_m * 4)
        removed = int(np.count_nonzero(~keep))
        fused, fused_colors = fused[keep], fused_colors[keep]
    # Keep the engineering measurement evidence immutable across the RGB stage.
    # Even valid triangulation has uncertainty and must not expand observed
    # dimensions or move an interface merely by contributing a colored anchor.
    measurement_points = fused.copy()
    measurement_colors = fused_colors.copy()
    rgb, rgb_points, rgb_colors = {"status": "not_requested"}, np.empty((0, 3)), np.empty((0, 3))
    if stage == "rgb_assisted":
        rgb, rgb_points, rgb_colors = _rgb_consistency(frames)
        if len(rgb_points) >= 12:
            # Refinement is tightly anchored to metric depth and never changes pose/scale.
            fused, fused_colors = _voxel_fuse(np.vstack((fused, rgb_points)), np.vstack((fused_colors, rgb_colors)), voxel_m)
        else:
            warnings.append("rgb_insufficient_texture_or_baseline: depth remains metric; no RGB refinement claimed")
    np.savez_compressed(output_dir / "rgb_metric_anchors.npz", points_m=rgb_points, colors=rgb_colors)
    scale = _scale_factor(annotations)
    scale_reference = annotations.get("scale_reference")
    if scale_reference:
        warnings.append("scale_reference_used: entered reference is calibration evidence, not an independent accuracy test")
    np.savez_compressed(output_dir / "points_filtered_uncorrected.npz", points_m=fused, colors=fused_colors)
    corrected = fused * scale
    np.savez_compressed(output_dir / "points_filtered.npz", points_m=corrected, colors=fused_colors)
    corrected_measurement_points = measurement_points * scale
    np.savez_compressed(output_dir / "points_measurement.npz", points_m=corrected_measurement_points, colors=measurement_colors)
    # Bounds deliberately describe observed support. There is no hidden-surface completion.
    lo, hi = np.min(corrected_measurement_points, axis=0), np.max(corrected_measurement_points, axis=0)
    bounds = {"min": (lo * 1000).tolist(), "max": (hi * 1000).tolist(), "extent": ((hi - lo) * 1000).tolist()}
    frame_ids = [f["frame_id"] for f in frames]
    measurements = [_measurement(f"extent_{axis}", f"Observed {axis.upper()} extent", value, frame_ids)
                    for axis, value in zip("xyz", bounds["extent"])]
    feature_frames = frames
    feature_annotations = annotations
    if scale != 1:
        feature_frames = [dict(f, points=f["points"] * scale) for f in frames]
    primitives, feature_measurements = _features(corrected_measurement_points, feature_frames, feature_annotations)
    measurements.extend(feature_measurements)
    manual_ids = {m["id"] for m in base["measurements"]}
    base["measurements"].extend(m for m in measurements if m["id"] not in manual_ids)
    centers = np.array([f["pose"][:3, 3] for f in frames])
    baseline = float(np.linalg.norm(np.ptp(centers, axis=0)))
    directions = centers - (lo + hi) / (2 * scale)
    azimuth = np.arctan2(directions[:, 1], directions[:, 0])
    occupied_bins = len(set(np.floor((azimuth + np.pi) / (2 * np.pi) * 12).astype(int).tolist()))
    status = "ready"
    if len(frames) < 3 or len(corrected) < 100 or baseline < .01:
        status = "needs_input"
        warnings.append("insufficient_multiview_support: capture at least three useful views with a changed viewpoint")
    if np.ptp(points, axis=0).max() > 1.5 or not manifest.get("complete"):
        status = "needs_input"
    if any(p.get("status") == "needs_measurement" for p in primitives):
        status = "needs_input"
        warnings.append("unresolved_contact_geometry: selected patches need more views or manual measurements")
    if any(f["mask_source"].endswith("needs_confirmation") for f in frames):
        status = "needs_input"
    violation_fraction = depth_consistency["free_space_violation_fraction"] or 0
    median_residual_mm = depth_consistency["median_visible_residual_mm"] or 0
    if (depth_consistency["compared_visible_samples"] >= 500
            and (violation_fraction > .15 or (violation_fraction > .01 and median_residual_mm > .65))):
        status = "needs_input"
        warnings.append("cross_view_depth_inconsistency: observations violate measured free space; check object motion, tracking drift or calibration")
    if rgb.get("inconsistent_fraction") is not None and rgb.get("matched_features", 0) >= 30 and rgb["inconsistent_fraction"] > .65:
        status = "needs_input"
        warnings.append("rgb_pose_inconsistency: image matches disagree with metric poses/depth; object movement, calibration or tracking drift suspected")
    mesh = None
    if stage != "raw_depth_pose" and np.ptp(points, axis=0).max() <= 1.5:
        mesh = _tsdf(frames, voxel_m, output_dir)
    if mesh is not None and len(mesh.triangles):
        vertices = np.asarray(mesh.vertices) * 1000 * scale
        preview = {"vertices": vertices.tolist(), "triangles": np.asarray(mesh.triangles).tolist(),
                   "colors": np.asarray(mesh.vertex_colors).tolist(), "normals": np.asarray(mesh.vertex_normals).tolist(), "unit": "mm"}
    else:
        indices = np.linspace(0, len(corrected) - 1, min(len(corrected), MAX_PREVIEW_POINTS), dtype=int)
        preview = {"vertices": (corrected[indices] * 1000).tolist(), "triangles": [],
                   "colors": fused_colors[indices].tolist(), "normals": [], "unit": "mm"}
        warnings.append("surface_mesh_unavailable: observed colored point cloud retained")
    _json(output_dir / "scan_preview.json", preview)
    base.update(status=status, bounds_mm=bounds, point_count=len(corrected), primitives=primitives,
                scale_correction={"factor": scale, "reference": scale_reference, "original_points": "points_filtered_uncorrected.npz",
                                  "raw_depth_preserved": True},
                uncertainty_budget={"capture_mm": None, "registration_mm": None,
                                    "reference_mm": scale_reference.get("uncertainty_mm") if scale_reference else None,
                                    "cad_mm": None, "printer_mm": None,
                                    "combination": "conservative additive only after each bound is independently calibrated",
                                    "status": "not_calibrated"})
    base["warnings"] = list(dict.fromkeys(warnings))
    base["metrics"].update({"raw_point_count": len(raw_points), "fused_point_count": len(corrected),
                            "isolated_points_rejected": removed, "voxel_size_mm": voxel_m * 1000,
                            "measurement_point_count": len(corrected_measurement_points),
                            "measurement_support": "confidence-filtered native depth only; RGB anchors do not alter engineering dimensions",
                            "voxel_size_is_accuracy": False, "camera_baseline_m": baseline,
                            "occupied_azimuth_bins_of_12": occupied_bins, "coverage_is_complete": False,
                            "rgb": rgb, "tsdf_vertices": len(preview["vertices"]) if preview["triangles"] else 0,
                            "depth_consistency": depth_consistency, "segment_registration": registration,
                            "tsdf_triangles": len(preview["triangles"]), "elapsed_s": time.monotonic() - start,
                            "masked_native_samples": sum(f["native_foreground_samples"] for f in frames),
                            "segmentation_sources": sorted({f["mask_source"] for f in frames})})
    _json(output_dir / "reconstruction.json", base)
    return base
