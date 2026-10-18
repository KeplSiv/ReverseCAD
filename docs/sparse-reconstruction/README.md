# One-camera sparse-range prototype

Local feature branch: `codex/sparse-reconstruction`, based on remote main
`754c0661f97d4b4c1e74ca2cb60519113c1d6c54`. The original dirty checkout and
Prelude sources/recordings are not edited. Selective reuse is recorded in
[reuse.json](reuse.json). Nothing is merged, pushed, uploaded to TestFlight or published.

This implementation uses physical rear 1× images and the intercepted computed
BackSparseTimeOfFlight packet stream. It requires neither a ruler nor a board for
reconstruction. Absolute accuracy and physical fit remain unvalidated. See the
[measured report](../../reports/sparse-reconstruction/REPORT.md).

## Run on saved inputs

From this worktree, install its own pinned environment:

```sh
uv sync --frozen
PYTHONPATH=backend .venv/bin/python scripts/sparse_reconstruct.py import-prelude \
  /Users/pranav/prelude/build/LiDARResearch/quick-tests/2026-10-18T09-43-59Z_arRulerBlack_B3C530 \
  work/ruler-import
PYTHONPATH=backend .venv/bin/python scripts/sparse_reconstruct.py run \
  work/ruler-import work/ruler-result --compare
```

Outputs must be fresh paths. The importer preserves the source recording and
verifies the original packet hash, per-packet hashes, extrinsic hash, and original
processed-depth/confidence plane hashes. It copies the source movie and retains
the journals. Its PNGs are decoded from the original lossy H264 stream, with no
resize/crop. Missing original arrival times stay null. Black-input ARKit poses
are labelled diagnostics and are not used by the sparse reconstruction.

Run the analytic integration fixture separately:

```sh
PYTHONPATH=backend .venv/bin/python scripts/generate_sparse_fixture.py work/example-synthetic
PYTHONPATH=backend .venv/bin/python scripts/sparse_reconstruct.py run \
  work/example-synthetic work/example-result --compare
PYTHONPATH=backend .venv/bin/python scripts/evaluate_sparse_fixture.py \
  work/example-synthetic work/example-result work/example-evaluation.json
PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_sparse_reconstruction.py
swift test --package-path packages/ReverseCADCore
```

This fixture is explicitly synthetic. Its oracle is outside the capture package
and is not an input to reconstruction. The comparison uses identical saved
inputs: the new method ignores processed depth and ARKit poses; the existing
`raw_depth_pose` baseline consumes them. The analytic baseline has exact rendered
depth and poses, so its accuracy is not a forecast of real ARKit accuracy.

## Build and run the phone prototype

The checked-in `ReverseCADSparseResearch` scheme is Debug only. The ordinary
`ReverseCAD` target has no private source files or bridging header. Research
Release and archive/install build actions fail. No distribution build is produced.

The signing arrangement available on this Mac is the existing Prelude
development profile. It signs the research executable with Prelude's bundle ID.
**Installing it would replace/restart Prelude. Do not install while its experiment
is active.** First coordinate with the phone owner and preserve the existing app
recordings. This implementation only writes to its separate Projects directory.
An in-place update must retain the existing recording directories; verify their
file paths, sizes and modification times before and after. Do not uninstall the app. A separate matching development profile for
`com.pranav.reversecad.sparse` would avoid replacing Prelude, but is not currently
configured by this task.

```sh
xcodegen generate --spec ios/project.yml
xcodebuild -project ios/ReverseCAD.xcodeproj -scheme ReverseCADSparseResearch \
  -configuration Debug -sdk iphoneos -derivedDataPath build/sparse-signed \
  CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM=5B3Y68ZB2Y \
  'CODE_SIGN_IDENTITY=Apple Development' \
  PROVISIONING_PROFILE_SPECIFIER=474c6492-2617-48a1-bace-b4f27ed41fc3 \
  PRODUCT_BUNDLE_IDENTIFIER=com.pranavmuralitharan.prelude build
codesign --verify --deep --strict \
  build/sparse-signed/Build/Products/Debug-iphoneos/ReverseCADSparseResearch.app
```

After coordination, a connected/unlocked device, and a preservation plan, use Xcode
Run for that device or `xcrun devicectl device install app --device DEVICE_ID APP_PATH`
followed by `xcrun devicectl device process launch --device DEVICE_ID com.pranavmuralitharan.prelude`.
The phone is connected and the owner released the stopped Prelude session. The
research app is installed and its launched executable was verified. A full backup
attempt timed out; its partial copy is not a verified backup. The in-place update
retains the approximately 49 GB of recordings in their separate directories, with
the post-install inventory check pending. No fresh device scan has yet been verified.

Start the isolated companion service:

```sh
PYTHONPATH=backend .venv/bin/python scripts/serve.py --lan --port 8769 \
  --data-dir work/sparse-service
```

Use the app's existing Connection settings to enter the displayed Mac address
and the private pairing token from `work/sparse-service/pairing-token`. Do not
publish that token. No live vision-model key is required for reconstruction or
deterministic repair proposals.

Aim at a stationary matte/textured object inside the guide, tap Start, and move
sideways slowly to show the front and another side with overlapping views. The
research capture automatically saves at 18 seconds or 48 stored views. It samples
views at least 0.35 seconds apart without using ARKit motion as a prerequisite.
Blur, tracking, source availability and observed direction changes drive guidance;
direction count is not a complete-surface guarantee. No processed-depth live
repair ghost is shown in this research mode.

The existing upload checks every asset SHA-256. The normal reconstruction job
dispatches the extension to this pipeline before automatic cube/planar routing.
Review the point cloud/mesh, confirm that it shows the intended object, and use
Continue to repair to enter the existing evidence, reference-photo, candidate,
parameter-edit and export workflow. Its critical-dimension and contact checks
remain in place. Missing mounting geometry must remain unresolved.

Export original scan preserves the immutable package. Any transferred package
can also be checked and reconstructed using the saved-input command above.
Interrupted captures remain recoverable as incomplete originals; they are not
silently promoted to completed measurement evidence.

## Reconstruction and limitations

COLMAP estimates poses from real image correspondences with fixed recorded
PINHOLE intrinsics, fixed sensor extrinsics and no ARKit pose prior. It uses one
worker thread and a fixed random seed. Images retain their dimensions; internal
feature scaling and stereo rectification are recorded. The prototype has no
bundle-adjusted range bias, lens distortion or time-offset fitting.

Each packet retains its own PTS. Pose interpolation needs bracketing registered
images at most 0.55 seconds apart, with no extrapolation or bank accumulation.
Within-packet spot exposure offsets are unknown. Local triangulated patches must
surround a projected observation and pass planarity, incidence, object-mask and
depth-edge checks. Geometric consensus selects among all echoes; competing
solutions abstain. One robust global metric scale is fitted with a held-out time
block. Its internal residual is not an absolute accuracy estimate.

The reused CPU stereo path uses left/right and third-view agreement. It preserves
the field of view during rectification and searches up to half the image width
(maximum 384 disparities). Additional object-silhouette and nearby triangulated
support reject repeated-texture/background matches. No point is snapped to a fit.
Point provenance separates image triangulation, stereo, and direct sparse ranges.
The local ball-pivot preview rejects long/unsupported triangles; it does not fill
holes or smooth geometry. CAD consumes observed point support, not preview triangles.

Primary artifacts are `observed_points_m.ply`, `observed_surface_m.ply` when supported,
`scan_preview.json` in mm, `points_measurement.npz` in m, `point_support.json`,
`direct_range_points.npz`, `camera_poses.json`, `decoded_sparse.jsonl`,
`sparse_associations.json`, `selected_sparse_support.json` and `reconstruction.json`.
The object frame is the first registered camera's right-handed CV frame:
x right, y down, z forward. Fit residuals, correlated support-subset variation,
coverage, unknown systematic uncertainty and physical fit are separate fields.

See [the extension contract](schema.md) and [capture implementation notes](../../research/sparse-capture/README.md).
