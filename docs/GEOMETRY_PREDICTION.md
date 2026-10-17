# Geometry prediction and live ghost

## Implemented scope

The predictor uses geometry rather than an object label or cube dimensions. It searches translational/rotational repetition and reflection, then checks for interior planar boundaries that can be continued. Existing cube-specific photo fitting remains a separately labeled comparison baseline.

Repeated features transfer original donor triangles, including modeled ridges. When connectivity separates an intact donor component and its placement is supported, the whole component is transferred instead of only its farthest triangles. Connected partial meshes still produce partial surface proposals. Planar continuation fills only a bounded coplanar interior loop; it does not invent the outer outline, thickness, or a hidden connector. Flat surfaces bypass unconstrained rotational self-alignment, which otherwise produces false outer extensions.

Ranking combines observed overlap, normal agreement, and normalized registration residual. It is **not a probability of correctness**. Proposal reports keep image reprojection, damage-versus-occlusion, hidden geometry, and volume collision status explicit. Those checks are not established by mesh self-similarity alone. An intentional opening and a scan hole can look identical to this stage. Review remains mandatory; no physical fit certification is given.

Completed reconstructions use this predictor through `pattern_hypotheses.json`. Each general proposal also appears as a separate option in the comparison picker, with export available only when the existing closed-solid and artifact-integrity checks pass. A planar surface patch alone is not a printable solid.

## Live ghost

The iPhone periodically extracts an object-filtered ARKit scene mesh from the same AR session as capture. Foreground segmentation follows the selected object's projected world position; reliable native depth rejects unrelated scene vertices. Original triangles are retained rather than randomly dropping faces to meet a budget. Oversized or sparse snapshots are skipped.

The authenticated `POST /v1/geometry/live` endpoint accepts bounded world-coordinate geometry in meters, a session identifier, sequence, and camera positions. At least three camera samples with an eight-degree view span are required. The Mac runs a short-lived isolated geometry worker with a 22-second wall budget and 16-second CPU soft limit, with only one live worker at a time. No external AI service or model download is used for this stage. Live snapshots are temporary and do not overwrite the saved capture.

The phone renders returned geometry as a translucent orange **provisional** proposal in its original AR world coordinates, converting millimeters to meters once. Multiple candidates can be cycled with **Next**. Ghosts clear after tracking loss/interruption, object reselection, capture end, or a response expiry; wrong-session and out-of-order responses are rejected. The overlay expires after 16 seconds without a replacement result. If there is no supported candidate, the app shows guidance instead of a fabricated part.

This is an experimental live preview from coarse ARKit geometry. It does not recover minute ridges from LiDAR or verify hidden surfaces. High-resolution photo detail remains a separate reconstruction problem. On-device physical alignment still needs user testing on real stationary objects.

## Validation

A predictor receives only the observed mesh. The benchmark separately holds out the removed surface and computes prediction-to-truth and truth-to-prediction surface distances, dimensional extent error, and proximity to surviving surfaces. It records unsuccessful alternatives as well as the top proposal. Two-way scoring caught incomplete donor extraction that earlier one-way checks missed.

- **18/18 clean cases:** rail, radial repeated features with a ridge, symmetric bracket, and planar surface; two arbitrary rotations/scales; complete-object and asymmetric negatives.
- **9/9 noisy cases:** the same quick suite with bounded vertex noise of 0.05% of observed extent.
- A positive passes when symmetric 95th-percentile surface distance is below 1.5% of observed extent; a negative passes only with no proposal. This is a synthetic benchmark threshold, not a manufacturing tolerance.
- **37 Python tests passed**, including the actual isolated live endpoint, invalid/bounded input, single-view rejection, planar continuation, donor preservation, complete-object negatives, export checks, and comparison integration.
- **22 iOS tests passed**, including ghost world-unit conversion, expiry, tracking reset, invalid geometry, stale response rejection, existing capture behavior, and artifact integrity.
- A signed iPhone build succeeded. The running LAN service returned an actual planar ghost proposal through the authenticated endpoint.

These are curated simple-geometry cases, not evidence of arbitrary-object repair or reliable phone reconstruction. Principal-axis symmetries and the supported translation periods do not cover all local patterns. The benchmark's component meshes also do not model every manufacturing interface or tolerance.

```sh
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python scripts/benchmark_prediction.py --output reports/prediction-benchmark
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python scripts/benchmark_prediction.py --output reports/prediction-noisy --quick --noise-fraction .0005
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python -m pytest backend/tests/test_geometry_prediction.py backend/tests/test_live_prediction.py backend/tests/test_pattern_completion.py backend/tests/test_comparison.py backend/tests/test_printable_pattern.py -q
```

Machine-readable results and synthetic observed/truth/proposal meshes are in `reports/prediction-benchmark/` and `reports/prediction-noisy/`. The test fixture dimensions are confined to the benchmark and tests; live prediction never imports them.
