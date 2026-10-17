# Reconstruction and measurement

`backend/reversecad/reconstruction.py` is the production path called by service workers and the fixture benchmark. It reads only the submitted capture package and annotations. Evaluator oracles and complete-part ground truth are outside the package and are never passed to reconstruction.

`reconstruct(scan_dir, output_dir, annotations=None)` writes `reconstruction.json`, `scan_preview.json`, native-derived point arrays, RGB metric anchors, and an Open3D TSDF surface. A result is `ready` for review or `needs_input`; neither state establishes physical fit. A selected contact with inadequate observed support produces `needs_input`. Unsupported metadata, unregistered origins, corrupt assets, and invalid calibration fail explicitly.

## Coordinates and calibration

Capture matrices contain 16 column-major values; `T_a_b` maps frame b into frame a. Depth values and camera translations are meters. ARKit camera axes are right/up/back; computer-vision axes are right/down/forward, converted by `diag(1,-1,-1,1)`. Registration is rigid, with positive determinant and unit scale.

Depth calibration has explicit provenance:

- `depth_calibration_mode: native_arkit` follows Apple's native scene-depth point-cloud sample: multiply focal lengths and principal points directly by depth/RGB resolution ratios. Native capture emits this mode.
- `depth_calibration_mode: pixel_center`, the backward-compatible replay/import default, describes images resized using `(u + 0.5) × scale - 0.5`. The independent analytic renderer uses this convention.
- Optional `depth_intrinsics` contains nine column-major native-depth values and takes precedence over derived values. Arbitrary display rotations are never applied to raw camera intrinsics.

RGB feature-image resizing uses the actual pixel-center resize convention. Feature coordinates map to native depth through their two calibration matrices, so the native sensor distinction remains intact. Native depth row stride and byte order are honored. Tests independently check an off-center ray, rotated/translated cameras, both depth calibration modes, padded big-endian rows, column-major layout, and rejection of reflections/scaled transforms.

`scan_preview.json` vertices are millimeters; the phone converts them to meters once. Point archives use `points_m` in meters. `observed_surface.ply` remains in original, uncorrected metric coordinates; the preview applies any recorded scale correction.

**Annotations use the current corrected preview object coordinates.** Thus `point_m`, `crop_min_m`, and `crop_max_m` already include the accepted scale factor. The crop compares uncorrected native points multiplied by that factor. Contact points are never multiplied a second time. Enter a scale reference before selecting contacts, or reselect them after changing it. `points_filtered_uncorrected.npz` and the original capture bytes remain preserved. A calibration reference cannot also establish independent accuracy.

## Actual reconstruction stages

1. Validate metadata, asset paths/checksums, timestamp monotonicity, camera matrices, resolution/stride, frame count, and input size. Reject missing depth, rejected/blurred views, and non-normal tracking. Invalid/negative/zero/out-of-range depth never enters geometry.
2. Apply captured foreground masks, corrected 3D crop, or user include/exclude polygons in raw depth pixels. Without a supplied mask/crop, depth-connected center selection proposes a region while preserving narrow connected handles; this remains `needs_input` until corrected/confirmed. A touching support surface may belong to the same proposal, so this is not claimed to be semantic object recognition.
3. Use confidence labels 1–2 when available, native calibrated unprojection, and the registered ARKit pose. Missing confidence is disclosed. Bound retained point samples per view and fuse colored points in metric voxels. Reject isolated statistical outliers without dropping whole disconnected fragments.
4. Integrate masked native RGB-D observations into `Open3D ScalableTSDFVolume` using inverse object-to-CV transforms, depth scale 1, and metric intrinsics. Extract a real triangle surface, bounded to 60,000 preview triangles. TSDF voxel size is 0.5–4 mm depending on object extent; it is a resource/discretization choice, never a sensor-accuracy statement. Engineering measurements use the observed point support rather than inferring precision from that surface.
5. Fit planes with deterministic RANSAC and total least squares. Fit cylinders/mild frusta using robust circle initialization and free-axis nonlinear refinement; require broad angular support and sufficient inliers. Fit selected contact patches and report actual view support, normals, residuals, degeneracy, and unresolved patches. No silhouette is converted into an asserted through-hole diameter.
6. Detect ORB correspondences, reject aliases with independent image fundamental-matrix RANSAC, then check reprojection against fixed metric poses. With sufficient texture and baseline, triangulate, require positive depth, parallax, low reprojection error, and agreement with native metric depth; fuse accepted metric anchors into the RGB-assisted point cloud. Engineering bounds and fitted interfaces continue to use the separately preserved `points_measurement.npz` native-depth support: uncertain triangulation must not expand dimensions or move a mating surface. Camera poses and scale are not optimized to conceal errors. Otherwise report `insufficient_texture_or_baseline` and claim no RGB refinement. RGB fusion can worsen a synthetic surface metric, and the stage comparison reports this rather than assuming an improvement.
7. Check cross-view native-depth free-space violations over nearby and separated viewpoints. More than 15% violations, or more than 1% plus median visible residual above 0.65 mm, requires review. A violation is a point at least 5 mm in front of another observed surface; behind-surface occlusions are excluded. These conservative software review thresholds can flag tracking drift, object motion, bias, or noise; they do not identify the cause or guarantee detection of every failure.
8. Validate supplied multi-segment transforms through bidirectional surface overlap. Require at least 12% overlap within 4 mm and inlier RMS at most 3 mm. No unregistered origin is silently concatenated, and no similarity transform absorbs a scale error. This v1 path verifies supplied rigid registration rather than guessing an arbitrary reset transform without evidence.

## Measurements and uncertainty

Every automatically measured extent/profile/contact dimension is unconfirmed, retains frame references, and has `uncertainty_status: not_calibrated` with `uncertainty_mm: null`. Manual values, confirmation state, measurement identifiers, and uncertainty are preserved. Numerical fit residuals are not real-device accuracy bounds. Body-radius repeatability uses 500 bootstrap resamples of per-view radius medians; systematic sensor, reference, registration, CAD, and printer errors remain separate.

Object-frame extrema describe the **observed support**, not hidden surfaces. Missing material, unseen holes, cup wall thickness, and inaccessible mating geometry are not completed or measured. Radius describes the observed fitted profile origin; for a frustum, radius varies with axial position by the reported taper. Unsupported/insufficient geometry must be resolved by additional views, manual measurements, or an explicitly selected repair design.

`input_revision` hashes the input manifest and annotations. The service persists each job/revision output separately. Reconstruction never rewrites original capture observations. New measurements do not erase previous revisions.

## Limits and tests

Limits are 240 frames, 512 MiB referenced capture assets, native depth at most 640×480, calibrated RGB metadata at most 4096×4096, 8,000 retained points per view, 24 selected RGB feature views, and 60,000 TSDF preview triangles. A target extent above 1.5 m requests cropping and skips volumetric integration. Service worker time/memory limits provide an additional process boundary. These bounds and the acceptance thresholds are configurable implementation constraints, not iPhone performance measurements.

`scripts/benchmark.py` runs the same callable in separate fresh processes for `raw_depth_pose`, `filtered_fusion`, and `rgb_assisted` on identical package bytes. Raw includes masks/crop and basic valid-depth/pose checks, while bypassing confidence/outlier/TSDF/RGB stages. Outputs preserve raw/filtered samples for evaluator-only surface and dimension comparisons. The benchmark reports its independent oracle, held-out dimensions, runtime, peak resident memory, stage differences, and source/input hashes.

Run `uv run pytest -q backend/tests/test_reconstruction_geometry.py backend/tests/test_benchmark.py`. Numeric regression tests can additionally use `-W error::RuntimeWarning`. Small camera/vector contractions use non-BLAS `einsum` because the verified macOS Accelerate/NumPy 2.2.6 combination emitted floating warning flags for finite `N×3 @ identity` products; this avoids suppressing real warnings. Fixture generation has its separate independent math implementation.

Automated replay success establishes software behavior only. Native ARKit sensing, real calibration/distortion, thin/glossy-object behavior, actual fit tolerances, printed dimensions, and attachment strength require the phone and printed-fit trials in `PHONE_TEST_PLAN.md`.

Primary references: [Apple scene-depth point cloud](https://developer.apple.com/documentation/arkit/displaying-a-point-cloud-using-scene-depth), [Open3D RGB-D integration](https://www.open3d.org/docs/latest/tutorial/pipelines/rgbd_integration.html), [OpenCV calibrated projection and triangulation](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html).
