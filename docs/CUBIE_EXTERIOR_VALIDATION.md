# Cubie exterior: local implementation and validation

## Scope

A regular 3×3 cube with one missing edge, visible from three outer faces. The app estimates dimensions from independently aligned photos scaled by robust native-depth correspondences. There is no fixed cube width and no sticker-color classification in the new repair detector. This is a bounded exterior experiment, not a general mechanical reconstruction system. Hidden connectors are excluded; inner faces are explicitly flat caps.

## Research decision

- [CAD-Recode](https://github.com/filaPro/cad-recode) converts sampled point clouds into CAD code. It could be useful for editable construction history, but it neither identifies the missing donor nor guarantees preservation of small measured relief. Its code/notebook were inspected; model inference was **not benchmarked** here.
- [DeepJoin](https://github.com/Terascale-All-sensing-Research-Studio/DeepJoin) directly addresses restoration of fractured shapes. The public quick start uses a trained shape distribution; deployment and adaptation to these assembled-cube scans remain untested.
- [SymmCompletion](https://github.com/HKUST-SAIL/SymmCompletion) is relevant to symmetry-guided completion. Predicted points still require placement, dimensional validation, and solid generation. It was reviewed, not integrated or benchmarked.
- [Fantastic Breaks](https://openaccess.thecvf.com/content/CVPR2023/papers/Lamb_Fantastic_Breaks_A_Dataset_of_Paired_3D_Scans_of_Real-World_CVPR_2023_paper.pdf) motivates using real fractured scans for evaluation rather than equating synthetic completion performance with successful repairs.
- COLMAP supplies camera registration, Open3D supplies plane fitting/fusion, and Trimesh supplies mesh validation/export. The current closure constructs a radial exterior mesh. This cube path remains experimental and has not produced a validated replacement from the latest saved cube capture.

## Actual failure and fix

The saved capture `99864C06-2F74-40F8-A116-AD1731894980` had inconsistent native surface depth. Photo recovery independently corrected poses, but stereo still required points to agree with the failed native depth. The recovery path now disables that surface-agreement gate while retaining the foreground mask, photo consistency, and independent pair checks. Normal native/photo fusion retains its strict depth gate.

Three fitted orthogonal planes establish the cube frame. A missing edge must have photographed recessed material behind both expected exterior faces, supported by distinct reference views. Unknown depth is not evidence of a hole. Other visible edges are checked for ambiguity. An intact edge is selected and rotated into the missing location.

Textureless flat regions inside observed plane hulls may be interpolated, excluding observed recesses. Captured donor geometry takes precedence near observed details. This can preserve resolved relief; it cannot recover ridges absent from the image evidence. The 0.25 mm meshing interval is **not** a claim of 0.25 mm sensing accuracy. Scale remains uncalibrated and no physical fit has been tested.

## Reproduce

Use Python 3.11 and `uv sync --python .venv/bin/python`. Run:

```sh
OMP_NUM_THREADS=2 .venv/bin/pytest backend/tests/test_cube_exterior.py backend/tests/test_hybrid_detail.py -q
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python scripts/validate_cubie_exterior.py CAPTURE_DIRECTORY OUTPUT_DIRECTORY
```

The replay invokes the production reconstruction pipeline with `repair_scope=cube_exterior`, checks exported STL/3MF units and topology, and saves a compact validation report. It reads the capture without modifying it. A closed mesh is a test-print candidate, not evidence of dimensional or mechanical fit.

## Capture guidance

Keep the cube stationary and move the phone. Include three outside faces across the scan, both sides of the missing edge, and both exposed faces of an intact edge. Use sharp overlapping views in diffuse lighting. The phone should stay far enough away to focus; a closer blurry image adds no geometric detail. See [Apple's capture guidance](https://developer.apple.com/documentation/realitykit/capturing-photographs-for-realitykit-object-capture/).

## Deployment

Changes remain local, per the user's instruction. The phone app now defaults to rectangular planar repair. Cube experiments remain available from its menu, including “Rebuild cubie exterior” for saved scans and “Show on cube” for placement review. Processing still runs on the paired Mac.
