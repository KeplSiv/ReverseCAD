"""Metric camera geometry shared by reconstruction and independently tested fixtures.

Integer pixel coordinates name pixel centers. Stored matrices are column-major.
ARKit camera axes are right/up/back; OpenCV axes are right/down/forward.
"""
from __future__ import annotations

import numpy as np

AR_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])


def dot(a, b):
    """Small-dimensional contraction without platform BLAS floating flag leakage.

    NumPy 2.2.6/Accelerate on the verified macOS host reports overflow/invalid
    flags even for finite random N×3 @ identity products. Non-BLAS einsum has
    identical geometry and lets genuine invalid arithmetic remain detectable.
    """
    a, b = np.asarray(a), np.asarray(b)
    return np.einsum("...i,i->...", a, b, optimize=False) if b.ndim == 1 else np.einsum("...i,ij->...j", a, b, optimize=False)


def matrix(values, size: int = 4) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.size != size * size or not np.isfinite(result).all():
        raise ValueError(f"Expected {size * size} finite column-major matrix values")
    return result.reshape((size, size), order="F")


def rigid_transform(values) -> np.ndarray:
    result = matrix(values)
    rotation = result[:3, :3]
    if (not np.allclose(result[3], [0, 0, 0, 1], atol=1e-5)
            or not np.allclose(dot(rotation.T, rotation), np.eye(3), atol=2e-3)
            or not np.isclose(np.linalg.det(rotation), 1, atol=2e-3)):
        raise ValueError("Pose/registration must be a finite proper rigid transform, without scale")
    return result


def scaled_intrinsics(values, source_width: int, source_height: int,
                      target_width: int, target_height: int,
                      mode: str = "pixel_center") -> np.ndarray:
    """Map intrinsics with explicit source calibration provenance.

    Synthetic/imported resized pixels use cv2.resize's pixel-center mapping.
    Native ARKit scene depth follows Apple's sample: direct coordinate scaling.
    """
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("Camera dimensions must be positive")
    k = matrix(values, 3).copy()
    if not (1e-5 < k[0, 0] < 1e7 and 1e-5 < k[1, 1] < 1e7) or not np.allclose(k[2], [0, 0, 1], atol=1e-7):
        raise ValueError("Invalid pinhole intrinsics")
    sx, sy = target_width / source_width, target_height / source_height
    if mode not in ("pixel_center", "native_arkit"):
        raise ValueError("Unknown native-depth calibration mode")
    dx, dy = ((sx - 1) / 2, (sy - 1) / 2) if mode == "pixel_center" else (0., 0.)
    resize = np.array([[sx, 0, dx], [0, sy, dy], [0, 0, 1.]])
    return dot(resize, k)


def transform_points(points: np.ndarray, transform: np.ndarray) -> np.ndarray:
    return dot(np.asarray(points), transform[:3, :3].T) + transform[:3, 3]


def unproject(depth: np.ndarray, intrinsics: np.ndarray, t_object_cv: np.ndarray,
              valid: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    if valid is None:
        valid = np.isfinite(depth) & (depth > 0)
    v, u = np.nonzero(valid)
    pixels = np.column_stack((u, v, np.ones_like(u)))
    camera = dot(pixels, np.linalg.inv(intrinsics).T) * depth[v, u, None]
    return transform_points(camera, t_object_cv), np.column_stack((u, v))


def project(points_object: np.ndarray, intrinsics: np.ndarray,
            t_object_cv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    camera = transform_points(points_object, np.linalg.inv(t_object_cv))
    homogeneous = dot(camera, intrinsics.T)
    with np.errstate(divide="ignore", invalid="ignore"):
        pixels = homogeneous[:, :2] / homogeneous[:, 2, None]
    return pixels, camera[:, 2]


def fit_plane(points: np.ndarray, threshold_m: float = .0015,
              seed: int = 42, iterations: int = 180) -> dict | None:
    """Deterministic RANSAC followed by TLS; inliers refer to the supplied array."""
    points = np.asarray(points, dtype=float)
    if len(points) < 12 or not np.isfinite(points).all():
        return None
    rng = np.random.default_rng(seed)
    sample = points if len(points) <= 5000 else points[rng.choice(len(points), 5000, replace=False)]
    best = None
    best_count = 0
    for _ in range(iterations):
        a, b, c = sample[rng.choice(len(sample), 3, replace=False)]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        if length < 1e-10:
            continue
        normal /= length
        count = np.count_nonzero(np.abs(dot(sample - a, normal)) < threshold_m)
        if count > best_count:
            best_count, best = count, (a, normal)
    if best is None or best_count < 12:
        return None
    center, normal = best
    for _ in range(3):
        inlier = np.abs(dot(points - center, normal)) < threshold_m
        accepted = points[inlier]
        if len(accepted) < 12:
            return None
        center = np.mean(accepted, axis=0)
        _, singular, vectors = np.linalg.svd(accepted - center, full_matrices=False)
        if singular[1] < 1e-5:
            return None
        normal = vectors[-1]
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    residual = np.abs(dot(points - center, normal))
    return {"center_m": center, "normal": normal, "inliers": residual < threshold_m,
            "residual_mm": float(np.sqrt(np.mean(residual[inlier] ** 2)) * 1000),
            "degenerate": bool(singular[1] / max(singular[0], 1e-12) < .02)}


def fit_circle(points_2d: np.ndarray, threshold_m: float = .0015, seed: int = 42) -> dict | None:
    """Robust observed circle fit; this never establishes that a circle is a hole."""
    from scipy.optimize import least_squares

    points = np.asarray(points_2d, dtype=float)
    if len(points) < 24:
        return None
    rng = np.random.default_rng(seed)
    best, best_count = None, 0
    for _ in range(100):
        q = points[rng.choice(len(points), 3, replace=False)]
        a = 2 * (q[1:] - q[0])
        if abs(np.linalg.det(a)) < 1e-10:
            continue
        center = np.linalg.solve(a, np.sum(q[1:] ** 2, axis=1) - np.sum(q[0] ** 2))
        radius = np.linalg.norm(q[0] - center)
        if not .003 < radius < 1:
            continue
        residual = np.abs(np.linalg.norm(points - center, axis=1) - radius)
        count = np.count_nonzero(residual < threshold_m)
        if count > best_count:
            best, best_count = np.r_[center, radius], count
    if best is None:
        return None
    for _ in range(3):
        error = np.linalg.norm(points - best[:2], axis=1) - best[2]
        inliers = np.abs(error) < threshold_m * 2
        if np.count_nonzero(inliers) < 24:
            return None
        result = least_squares(lambda p: np.linalg.norm(points[inliers] - p[:2], axis=1) - p[2],
                               best, loss="soft_l1", f_scale=threshold_m, max_nfev=60)
        best = result.x
    angles = np.sort(np.arctan2(*(points[inliers] - best[:2])[:, ::-1].T))
    coverage = 2 * np.pi - np.max(np.diff(np.r_[angles, angles[0] + 2 * np.pi]))
    return {"center": best[:2], "radius": best[2], "inliers": inliers,
            "coverage_degrees": float(np.rad2deg(coverage)),
            "residual_mm": float(np.sqrt(np.mean(error[inliers] ** 2)) * 1000)}


def fit_cylinder_frustum(points: np.ndarray, threshold_m: float = .0015) -> dict | None:
    """Robust free-axis cylinder/frustum estimate, requiring broad angular support.

    The cone parameter is radius change per axial meter. A fitted side profile
    does not establish a cup wall thickness or any hidden attachment geometry.
    """
    from scipy.optimize import least_squares

    points = np.asarray(points, dtype=float)
    if len(points) < 150:
        return None
    rng = np.random.default_rng(281)
    p = points if len(points) <= 6500 else points[rng.choice(len(points), 6500, replace=False)]
    origin = np.median(p, axis=0)
    q = p - origin
    _, _, pca = np.linalg.svd(q, full_matrices=False)
    candidates = list(pca) + list(np.eye(3))
    best = None
    for axis in candidates:
        axis = axis / np.linalg.norm(axis)
        helper = np.eye(3)[np.argmin(np.abs(axis))]
        e1 = np.cross(axis, helper)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        planar = np.column_stack((dot(q, e1), dot(q, e2)))
        circle = fit_circle(planar, threshold_m * 2)
        if circle is None or circle["coverage_degrees"] < 100:
            continue
        # Axis small tilts plus center in its perpendicular plane remove gauge freedom.
        start = np.r_[circle["center"], 0., 0., circle["radius"], 0.]

        def values(params):
            a = axis + params[2] * e1 + params[3] * e2
            a /= np.linalg.norm(a)
            center = params[0] * e1 + params[1] * e2
            delta = q - center
            height = dot(delta, a)
            radial = np.linalg.norm(delta - height[:, None] * a, axis=1)
            return radial - (params[4] + params[5] * height), a, center, height

        result = least_squares(lambda pars: values(pars)[0], start,
                               bounds=([-1, -1, -.4, -.4, .003, -.3], [1, 1, .4, .4, 1, .3]),
                               loss="soft_l1", f_scale=threshold_m, max_nfev=70)
        params = result.x
        for _ in range(2):
            errors, _, _, _ = values(params)
            inlier = np.abs(errors) < threshold_m * 1.7
            if np.count_nonzero(inlier) < 100:
                break
            result = least_squares(lambda pars: values(pars)[0][inlier], params,
                                   loss="soft_l1", f_scale=threshold_m / 2, max_nfev=50)
            params = result.x
        errors, fitted_axis, center, heights = values(params)
        inlier = np.abs(errors) < threshold_m
        fraction = np.mean(inlier)
        if fraction < .52 or np.count_nonzero(inlier) < 100 or abs(params[5]) > .3:
            continue
        span = np.ptp(heights[inlier])
        if span < .012 or params[4] > .5 or params[4] < .003:
            continue
        delta = q[inlier] - center
        radial = delta - dot(delta, fitted_axis)[:, None] * fitted_axis
        angles = np.sort(np.arctan2(dot(radial, e2), dot(radial, e1)))
        coverage = 2 * np.pi - np.max(np.diff(np.r_[angles, angles[0] + 2 * np.pi]))
        if coverage < np.deg2rad(140):
            continue
        # A near-flat plane can fit a huge cylinder; reject that degeneracy.
        if params[4] > max(np.ptp(q, axis=0)) * 1.5:
            continue
        residual_mm = float(np.sqrt(np.mean(errors[inlier] ** 2)) * 1000)
        score = fraction - residual_mm * .04
        if best is None or score > best[0]:
            center_global = origin + center
            if fitted_axis[np.argmax(np.abs(fitted_axis))] < 0:
                fitted_axis = -fitted_axis
                params[5] = -params[5]
                heights = -heights
            best = (score, {"type": "cylinder" if abs(params[5]) < .005 else "frustum",
                            "axis": fitted_axis.tolist(), "center_m": center_global.tolist(),
                            "radius_mm": float(params[4] * 1000), "taper": float(params[5]),
                            "height_range_mm": (np.array([np.min(heights[inlier]), np.max(heights[inlier])]) * 1000).tolist(),
                            "fit_residual_mm": residual_mm, "inlier_fraction": float(fraction),
                            "angular_support_degrees": float(np.rad2deg(coverage)),
                            "uncertainty_status": "not_calibrated", "source": "depth_fit"})
    return best[1] if best else None
