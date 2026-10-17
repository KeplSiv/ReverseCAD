"""Analytic oracles: these tests do not call the fixture renderer for expectations."""
import json
from pathlib import Path

import numpy as np
import pytest

from reversecad.geometry import (AR_TO_CV, dot, fit_circle, fit_cylinder_frustum,
                                 fit_plane, matrix, rigid_transform, scaled_intrinsics, unproject)
from reversecad.reconstruction import _mask, _read_depth, _registration_evidence, reconstruct

ROOT = Path(__file__).resolve().parents[2]


def cm(array):
    return np.asarray(array).flatten(order="F").tolist()


def test_independent_offcenter_ray_rotated_camera_millimeters():
    # Pixel (3,1), z=.4 gives CV (.2,-.2,.4). AR sign flip gives
    # (.2,.2,-.4), yaw +90 gives (-.4,.2,-.2), translate -> (-.3,.4,.1).
    depth = np.zeros((4, 5), dtype=np.float32)
    depth[1, 3] = .4
    k = np.array([[4., 0, 1], [0, 4, 3], [0, 0, 1]])
    pose = np.array([[0, 0, 1, .1], [0, 1, 0, .2], [-1, 0, 0, .3], [0, 0, 0, 1]])
    xyz, pixels = unproject(depth, k, dot(pose, AR_TO_CV))
    np.testing.assert_allclose(xyz[0] * 1000, [-300, 400, 100], atol=.0001)
    np.testing.assert_array_equal(pixels, [[3, 1]])


def test_intrinsic_pixel_center_mapping_not_naive_scaling():
    k = [[1000, 0, 641.2], [0, 900, 359.3], [0, 0, 1]]
    resized = scaled_intrinsics(cm(k), 1280, 720, 256, 144)
    np.testing.assert_allclose(resized, [[200, 0, 127.84], [0, 180, 71.46], [0, 0, 1]])


def test_native_arkit_depth_intrinsics_follow_direct_scale_independent_ray():
    k = [[1000, 0, 641.2], [0, 900, 359.3], [0, 0, 1]]
    native = scaled_intrinsics(cm(k), 1280, 720, 256, 144, mode="native_arkit")
    np.testing.assert_allclose(native, [[200, 0, 128.24], [0, 180, 71.86], [0, 0, 1]])
    depth = np.zeros((144, 256), dtype=np.float32)
    depth[30, 200] = .5
    observed, _ = unproject(depth, native, AR_TO_CV)
    # Independent direct Apple formula (pixel-principal)/focal * native z.
    np.testing.assert_allclose(observed[0] * 1000, [179.4, 116.2777777778, -500], atol=1e-7)


def test_column_major_translation_and_reflection_rejection():
    values = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, .1, -.2, .3, 1]
    np.testing.assert_allclose(matrix(values)[:3, 3], [.1, -.2, .3])
    reflected = np.diag([-1., 1, 1, 1])
    with pytest.raises(ValueError, match="proper rigid"):
        rigid_transform(cm(reflected))
    with pytest.raises(ValueError, match="proper rigid"):
        rigid_transform(cm(np.diag([1.01, 1.01, 1.01, 1])))


def test_native_padded_rows_and_big_endian(tmp_path):
    array = np.array([[.1, .2, 99], [.3, .4, 99]], dtype=">f4")
    (tmp_path / "depth.f32").write_bytes(array.tobytes())
    frame = {"depth_path": "depth.f32", "depth_width": 2, "depth_height": 2,
             "depth_row_bytes": 12, "depth_byte_order": "big"}
    np.testing.assert_allclose(_read_depth(tmp_path, frame), [[.1, .2], [.3, .4]])
    frame["depth_row_bytes"] = 8
    with pytest.raises(ValueError, match="byte count"):
        _read_depth(tmp_path, frame)


def test_robust_plane_observed_noise_and_outliers():
    rng = np.random.default_rng(4)
    xy = rng.uniform(-.05, .05, (1600, 2))
    z = .013 + .2 * xy[:, 0] + rng.normal(0, .00008, len(xy))
    points = np.vstack((np.column_stack((xy, z)), rng.uniform(-.07, .07, (200, 3))))
    plane = fit_plane(points, threshold_m=.0004)
    normal = np.array([-.2, 0, 1]) / np.sqrt(1.04)
    assert abs(np.dot(plane["normal"], normal)) > .99999
    assert plane["residual_mm"] < .12
    assert plane["inliers"].sum() >= 1590
    assert abs(np.dot(plane["center_m"], normal) - .013 / np.sqrt(1.04)) < .00002


def test_degenerate_line_does_not_become_plane():
    p = np.column_stack((np.linspace(0, .1, 100), np.zeros(100), np.zeros(100)))
    assert fit_plane(p) is None


def test_robust_circle_is_not_labeled_observed_hole():
    angles = np.linspace(0, np.pi * 2, 500, endpoint=False)
    circle = fit_circle(np.column_stack((.021 * np.cos(angles) + .01, .021 * np.sin(angles) - .004)))
    assert circle is not None
    assert abs(circle["radius"] - .021) < 1e-7
    assert circle["coverage_degrees"] > 350
    assert "hole_diameter" not in circle


@pytest.mark.parametrize("taper", [0., .08, -.06])
def test_free_axis_cylinder_frustum_with_outliers(taper):
    rng = np.random.default_rng(73)
    theta = rng.uniform(0, 2 * np.pi, 3200)
    height = rng.uniform(-.045, .045, 3200)
    radius = .036 + taper * height
    local = np.column_stack((radius * np.cos(theta), height, radius * np.sin(theta)))
    # Independent right-handed, non-axis-aligned rotation and translation.
    rotation = np.array([[.36, -.48, .8], [.8, .6, 0], [-.48, .64, .6]])
    translation = np.array([.01, -.02, .03])
    observed = np.einsum("ni,ji->nj", local, rotation) + translation
    observed += rng.normal(0, .00008, observed.shape)
    observed = np.vstack((observed, rng.uniform(-.05, .05, (150, 3))))
    result = fit_cylinder_frustum(observed, threshold_m=.0005)
    assert result is not None
    axis = rotation[:, 1]
    assert abs(np.dot(result["axis"], axis)) > .999
    # Reference radius is at the reported fitted origin, which may move axially.
    expected_radius = 36 + taper * np.dot(np.asarray(result["center_m"]) - translation, axis) * 1000
    assert abs(result["radius_mm"] - expected_radius) < .15
    assert abs(result["taper"] - taper) < .002
    assert result["fit_residual_mm"] < .2


def test_small_finite_matrix_math_does_not_leak_blas_float_flags():
    rng = np.random.default_rng(4)
    points = rng.random((10000, 3))
    with np.errstate(all="raise"):
        np.testing.assert_array_equal(dot(points, np.eye(3)), points)


def test_mask_correction_preserves_narrow_handle_and_excludes_selected_background(tmp_path):
    depth = np.ones((40, 50), dtype=np.float32) * .7
    depth[10:30, 15:30] = .3
    depth[19:21, 30:44] = .3  # two-pixel handle must survive connected selection
    frame = {"frame_id": "x", "rgb_width": 100, "rgb_height": 80}
    mask, source = _mask(tmp_path, frame, depth, {})
    assert mask[20, 40] and not mask[0, 0]
    assert "needs_confirmation" in source
    corrected, source = _mask(tmp_path, frame, depth,
                             {"mask_corrections": {"x": {"exclude_polygons": [[[38, 18], [49, 18], [49, 25], [38, 25]]]}}})
    assert not corrected[20, 40] and corrected[20, 25]
    assert source == "user_mask_correction"


def test_registration_requires_geometric_overlap():
    rng = np.random.default_rng(13)
    p = rng.uniform(-.05, .05, (1000, 3))
    with pytest.raises(ValueError, match="overlap"):
        _registration_evidence([{"segment_id": "a", "points": p}, {"segment_id": "b", "points": p + 1}])


def test_scale_correction_preserves_uncorrected_and_manual_provenance(tmp_path):
    annotation = {"scale_reference": {"measured_mm": 120, "observed_mm": 100, "uncertainty_mm": .1},
                  "measurements": [{"id": "hole_diameter", "name": "Caliper hole diameter", "value": 4.2,
                                    "unit": "mm", "source": "manual", "confirmed": True, "critical": True,
                                    "uncertainty_mm": .05, "observation_ids": []}]}
    result = reconstruct(ROOT / "fixtures/sample_scan", tmp_path, annotation, stage="raw_depth_pose")
    assert result["scale_correction"]["factor"] == 1.2
    raw = np.load(tmp_path / "points_filtered_uncorrected.npz")["points_m"]
    corrected = np.load(tmp_path / "points_filtered.npz")["points_m"]
    np.testing.assert_allclose(corrected, raw * 1.2)
    manual = next(m for m in result["measurements"] if m["id"] == "hole_diameter")
    assert manual == annotation["measurements"][0]
    for measurement in result["measurements"]:
        if measurement["source"] == "depth_fit":
            assert measurement["confirmed"] is False
            assert measurement["uncertainty_mm"] is None
    assert result["physical_validation"]["printed_fit"] == "not_tested"


def test_contact_patch_far_from_observed_surface_requests_measurement(tmp_path):
    result = reconstruct(ROOT / "fixtures/sample_scan", tmp_path,
                         {"contacts": [{"id": "unseen", "point_m": [2, 2, 2], "normal": [0, 0, 1], "radius_mm": 5}]},
                         stage="raw_depth_pose")
    contact = next(p for p in result["primitives"] if p["id"] == "unseen")
    assert contact["status"] == "needs_measurement"
    assert result["status"] == "needs_input"
    assert not any("hole" in m["id"] for m in result["measurements"])


def test_scale_crop_and_contact_annotations_use_corrected_preview_coordinates(tmp_path):
    # A raw right mount x=40,z=12 mm becomes x=60,z=18 mm after x1.5.
    # Cropping x=45..80 mm in corrected coordinates must keep that mount.
    annotations = {"scale_reference": {"measured_mm": 150, "observed_mm": 100, "uncertainty_mm": .1},
                   "crop_min_m": [.044, -.02, .0001], "crop_max_m": [.08, .02, .025],
                   "contacts": [{"id": "right", "point_m": [.06, 0, .018], "normal": [0, 0, 1], "radius_mm": 6}]}
    result = reconstruct(ROOT / "fixtures/sample_scan", tmp_path, annotations, stage="raw_depth_pose")
    assert result["point_count"] > 100
    assert result["bounds_mm"]["min"][0] >= 44
    assert result["bounds_mm"]["max"][0] <= 80
    patch = next(p for p in result["primitives"] if p["id"] == "right")
    assert patch["status"] == "observed_unconfirmed"
    np.testing.assert_allclose(patch["point_m"][2], .018, atol=.00005)
    assert abs(patch["point_m"][0] - .06) < .003


def test_multiview_tsdf_preserves_observed_step_and_combines_disjoint_views(tmp_path):
    from reversecad.reconstruction import _tsdf, _surface_outputs
    import open3d as o3d
    # Two independently positioned depth patches, one with a measured 8 mm step.
    # The second view covers a region invisible in the first; best-frame selection
    # cannot satisfy the combined extent oracle.
    k = np.array([[160., 0, 39.5], [0, 160., 39.5], [0, 0, 1.]])
    depth = np.full((80, 80), .2, dtype=np.float32)
    depth[24:56, 24:56] = .192
    pose = np.eye(4)
    second = np.eye(4); second[0, 3] = .14
    frames = [{"depth": d, "k": k, "pose": t, "color": np.full((80, 80, 3), 150, dtype=np.uint8)}
              for d, t in [(depth, pose), (np.full_like(depth, .2), second)]]
    mesh = _tsdf(frames, .0005, tmp_path)
    xyz = np.asarray(mesh.vertices)
    assert np.ptp(xyz[:, 0]) > .23
    top = xyz[(abs(xyz[:, 0]) < .01) & (abs(xyz[:, 1]) < .01)]
    assert abs(np.median(top[:, 2]) - .192) < .001
    outer = xyz[(xyz[:, 0] > .12) & (xyz[:, 0] < .16)]
    assert abs(np.median(outer[:, 2]) - .2) < .001
    preview = _surface_outputs(mesh, tmp_path, 1.2)
    exported = o3d.io.read_triangle_mesh(str(tmp_path / "observed_surface.stl"))
    np.testing.assert_allclose(exported.get_axis_aligned_bounding_box().get_extent(),
                               np.ptp(xyz, axis=0) * 1200, atol=1e-4)
    assert preview["unit"] == "mm"
    assert len(exported.triangles) == len(mesh.triangles)


def test_export_keeps_full_surface_while_viewer_is_bounded(tmp_path):
    import open3d as o3d
    from reversecad.reconstruction import _surface_outputs
    mesh = o3d.geometry.TriangleMesh.create_sphere(radius=.03, resolution=140)
    preview = _surface_outputs(mesh, tmp_path, 1)
    full = o3d.io.read_triangle_mesh(str(tmp_path / "observed_surface_mm.ply"))
    assert len(full.triangles) == len(mesh.triangles) > 60000
    assert len(preview["triangles"]) <= 60000
