# Reconstruction options — evaluated 2026-10-17

## Real failed-scan benchmark and automatic exterior fallback (2026-10-17)

The phone capture with 25 RGB frames (23 accepted native-depth frames) failed native fusion: median visible depth disagreement 10.94 mm, free-space violations 67.2%. All-pairs Open3D colored ICP on its largest 21-frame connected component reduced depth disagreement to 5.56 mm but made image reprojection worse (about 36 px at 640 px feature resolution). It was rejected. COLMAP's initial diagnostic camera alignment improved RGB reprojection to 3.64 px but did not rescue native-depth fusion (8.17 mm residual). These residuals use different matched/visible samples, so they are diagnostics, not a ground-truth accuracy leaderboard.

Production now tries pinned CPU PyCOLMAP 4.2.1 after an inconsistent ARKit scan. The final run registered 17 photos, including two tracking-limited RGB images usable by independent SfM, retaining 15 accepted-depth frames for evidence. The sparse model had approximately 1.09 px reprojection error. Automatic scale comes from robust matched native-depth/photo-depth ratios, preferentially on background surfaces. No cube width, gap or radius is supplied by the user or preset for this scan. The retained scale ratios had about 5.7% p10–p90 relative half-range; this is scatter, not calibrated dimensional accuracy.

For a mostly solved cube, narrower hue ranges separate nearby yellow/orange faces. Six aligned views constrained the square face, with roughly 3.7% median held-out corner error relative to face size. Multiple views of an intact edge constrain a rounded rectangular outline. The output is a **closed, idealized rounded exterior estimate**, using the repeated outline on perpendicular faces. This is not a recovered dense donor surface. Three-dimensional rounding, unseen sides and closure are inferred. Fine bumps, recesses, internal locking geometry, clearance, printed fit and editable parametric CAD remain unresolved. The app labels this path “Estimated replacement” and shows the piece first. Its context cube is explicitly inferred, not a clean scan claim.

The actual failed capture now produces a single watertight, consistently oriented STL/3MF exterior with automatic dimensions. We check self-intersections and reimport the STL. No raw photos or personal scan package are committed. Reproduce registration diagnostics with:

```sh
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python scripts/compare_alignment.py /path/to/capture /path/to/output --method open3d
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python scripts/compare_alignment.py /path/to/capture /path/to/output --method colmap
```

PyCOLMAP/COLMAP core is [BSD licensed](https://github.com/colmap/colmap/blob/main/LICENSE); third-party dependencies retain their own licenses. No code was copied from VideoCAD or a learned completion repository. This implementation uses COLMAP as a dependency and original bounded fitting/validation logic.

## Earlier photo-library prototype

The cube prototype uses OpenCV color segmentation, convex face boundaries, perspective rectification, and repeated 3×3 cell validation. A photo now supplies its own face corners. The photo-library prototype analyzes one image. The main camera flow now captures calibrated RGB-D/poses and fuses accepted views through the existing Open3D TSDF pipeline; it no longer selects one frame. The detector supports a mostly solved face with one dark missing edge; scrambled faces, multiple gaps, missing outer corners, occlusion, and poor light can require correction or fail.

The measured full cube width sets scale. CadQuery creates an exterior cubie envelope, STEP solid, STL mesh, and editable Python parameters. The normal UI asks only for full face width. Visible outline spacing is estimated from intact center-connected face regions when consistent; unresolved spacing and 3D rounding use labeled priors. Detection and detail provenance are exported; they do not certify mechanical clearance. The preview reads the exported binary STL. Neither connector fit nor arbitrary missing geometry is solved by this path.

## Hybrid surface and intact-edge proposal

The current camera flow uses existing OpenCV stereo rectification/SGBM and subpixel photometric alignment on bounded overlapping RGB pairs. ARKit baselines set scale; bidirectional correspondence, texture, photometric and depth checks reject unsupported detail. Supported high-resolution samples replace only covered coarse integration pixels, leaving native dimensions and capture files unchanged. Open3D fuses the derived surface. This is an experimental detail pass with a LiDAR fallback, not validated submillimeter metrology. See [OpenCV calibration and stereo documentation](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html).

A visible solved-face grid plus native plane fit establishes a cube frame. The proposal copies an observed intact edge with two exterior faces into the missing grid location by a proper rotation. It preserves the donor’s surface instead of generating a generic envelope. The app overlays the proposal in orange and exports its source/target cells and transform. When donor coverage is sufficient, an observed two-face height-field exterior is closed with inferred flat caps. Pinned scikit-image 0.25.2 supplies topology-aware marching cubes; trimesh and Open3D validate the solid and reimported STL. STL and 3MF exports are in millimeters with the inferred bottom on the build plate. This is a closed exterior prototype, not a mechanically fitted cubie or editable CAD replacement. The original open surface remains an evidence artifact.

## Reusable projects

| Project | Useful output / role | License and practical fit | Decision |
|---|---|---|---|
| [OpenCV](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) | Detection, homographies, calibration | Already pinned in this repo | Used for automatic cube face detection |
| [Open3D](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html) | Registered RGB-D integration into a mesh | [MIT](https://github.com/isl-org/Open3D/blob/main/LICENSE); already installed | Retain for metric scan fusion; inspect foreground isolation and registration quality before trusting small features |
| [CadQuery](https://github.com/CadQuery/cadquery) | Parametric solids and STEP/STL export | Apache 2.0; already installed and generating valid solids | Retain for editable repair geometry |
| [COLMAP](https://github.com/colmap/colmap) | Camera calibration, structure from motion and multiview stereo | BSD core; dependency licenses separate. [macOS/Homebrew supported](https://colmap.github.io/install.html), but available dense-reconstruction acceleration depends on build/hardware | Used for bounded CPU photo alignment in the inconsistent-scan fallback; missing geometry still requires the explicit cube model |
| [MoGe](https://github.com/microsoft/MoGe) | Predicted depth/point maps from a photo | MIT code with Apache DINOv2 component; current MoGe-3 installation explicitly excludes macOS due to Triton/FlexGEMM | Possible GPU service experiment, not installed on this Mac; inferred depth needs measurement checks |
| [VGGT](https://github.com/facebookresearch/vggt) | Camera parameters, depth and points from multiple views | Repository distinguishes commercial checkpoint from original noncommercial weights; commercial checkpoint access requires application | Promising reconstruction experiment once appropriate weights and compute are selected; not equivalent to editable CAD |
| [TRELLIS](https://github.com/microsoft/TRELLIS) | Image-conditioned mesh / Gaussian / radiance-field generation | Mostly MIT code/models with separately licensed components; documented Linux and NVIDIA GPU ≥16 GB | Could propose visual geometry on a GPU server; generated shape is not evidence of dimensional accuracy or functional fit |
| [BrepGen](https://github.com/samxuxiang/BrepGen) | Generative CAD B-reps | Research implementation and pretrained-model workflow | Interesting CAD generation research, not a drop-in broken-photo-to-repaired-CAD pipeline |

No new GPU models, gated weights, or cloud endpoints were installed. The flows use the existing OpenCV, CadQuery and Open3D dependencies.

## Recommended next stage

1. Keep the current one-edge cube demo as a measurable end-to-end baseline.
2. For general objects, capture overlapping views plus available depth; isolate the object and register the views into an initial observed mesh. Compare Open3D depth fusion against COLMAP RGB reconstruction on the same captures.
3. Fit planes, cylinders, repeated spacing, and symmetry to the observed surface. Preserve measured dimensions independently of inferred geometry.
4. Build a missing-region hypothesis with explicit dimensions in CadQuery, then render observed and inferred geometry together and export it.
5. Evaluate against a known intact reference and a printed exterior fit test before claiming a functional replacement.

For world-tracked depth fusion, keep the object still and move the phone. Rotating the object in a hand requires object-relative alignment and foreground/hand masking. The current 3D scan requires a stationary object; hand rotation would invalidate its world poses.

## VideoCAD and CADFit: applied ideas, original implementation

[VideoCAD](https://github.com/ghadinehme/VideoCAD) studies CAD UI action prediction from CAD screen recordings and a target CAD image. Its video domain is not handheld footage of a physical broken part. Its useful architectural idea here is an explicit state/action history for editable construction. We did not copy its implementation, download its dataset or load its checkpoint.

The authors' [CADFit](https://ghadinehme.com/cadfit.github.io/) is more directly relevant to the eventual mesh-to-CAD stage: it constructs executable operations with geometry-based validation against a watertight target mesh. Repair inference must still decide what missing material should be added; matching a damaged mesh alone reproduces the damage.

Our original `backend/reversecad/cad_program.py` turns the current exterior hypothesis into a bounded rectangle → centered extrusion → optional fillet program. Each solid operation must produce one valid positive-volume solid with the requested exterior dimensions. `repair_plan.json` records parameters, assumptions, client-forwarded detection provenance, and measured kernel validation results. It can be replayed through the executor; the exported CadQuery source remains directly editable. This is a working deterministic foundation for later candidate fitting, not a trained VideoCAD model or a general mesh-to-CAD solver.

## General repair research and experiments — 2026-10-17

The objective is a separate replacement inferred from intact geometry, geometric repetition, damage boundaries and mating surfaces. Detailed capture is evidence for repair; a scan alone is not the repair. A recognizable rounded cube is not adequate evidence of recovered ridges or connectors. Visible surfaces inside an opening are observable geometry; fully occluded surfaces remain unknown.

### Primary research and implementation choices

- [DeepJoin, SIGGRAPH Asia 2022](https://arxiv.org/html/2211.12400v1), [Apache-2.0 implementation](https://github.com/Terascale-All-sensing-Research-Studio/DeepJoin): learns complete and break fields jointly (occupancy, signed distance and normals), then extracts a restoration. This is directly about repair interfaces. Simply subtracting an imperfect completed shape can leave artifacts. The inspected quick-start experiment is mugs; inference contains CUDA calls and the installation targets Ubuntu/Python 3.8. It has not been run or integrated here. Its evaluated shape repair results do not establish arbitrary mechanical fit.
- [SymmCompletion, AAAI 2025](https://arxiv.org/html/2503.18007v1), [MIT implementation](https://github.com/HKUST-SAIL/SymmCompletion): estimates local transformations from existing geometry into missing regions, then refines using symmetry-guided features. Relevant to preserving donor detail. The released installation uses CUDA PyTorch and custom extensions. Point-cloud completion does not itself supply a closed replacement, a mating interface, or CAD history. No weights were installed.
- [Discovering Structural Regularity in 3D Geometry, SIGGRAPH 2008](https://www.cs.princeton.edu/courses/archive/spr11/cos598A/pdfs/Pauly08.pdf): transformation-space analysis discovers repeated elements without an object-category template. This motivates the original bounded rotational baseline below; we do not claim to implement the full paper.
- [Fantastic Breaks, CVPR 2023](https://openaccess.thecvf.com/content/CVPR2023/papers/Lamb_Fantastic_Breaks_A_Dataset_of_Paired_3D_Scans_of_Real-World_CVPR_2023_paper.pdf): paired real broken/complete scans and repair proxies provide an appropriate evaluation direction. Its results show that synthetic fracture performance does not automatically transfer to real damage.
- [Open3D registration](https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html): already available locally, used for geometric alignment rather than learned object priors.

### Implemented offline prototype (not enabled in the phone repair pipeline)

`pattern_completion.py` searches principal-axis rotational repetitions of orders 2–8 and refines with Open3D robust point-to-plane ICP. It checks overlap, normal agreement, nontrivial displacement and novel surface fraction, then extracts rigidly transformed donor triangles outside the observed surface. There is no cube grid, primitive refit, smoothing, preset physical size, fabricated connector, or automatic closure. Export is a surface hypothesis PLY, not a printable part.

A synthetic non-cube radial assembly with one missing shouldered stud produced candidates at the correct missing location. The test compares candidates against withheld geometry. Separate tests preserve a small ridge and recess exactly under rigid transfer and reject scaling. These are software checks, not phone precision measurements. This baseline still lacks arbitrary local/translation/reflection symmetry, surface segmentation, camera free-space checks, damage confirmation and mechanical interface validation; do not enable it as automatic repair yet.

```sh
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python scripts/propose_pattern_repair.py observed_mesh.ply output_directory
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python -m pytest backend/tests/test_pattern_completion.py -q
```

### Actual failed capture retest

An independent native macOS RealityKit PhotogrammetrySession experiment used all 25 existing RGB photos, high feature sensitivity, unordered samples, object masking, and full-detail output. It completed and skipped five samples. Visual inspection of the untextured geometry showed smoothed ridges and distorted/incomplete opening geometry. The rotational repetition prototype found no supported candidate in that model. No result from this experiment replaced the user's saved phone scan or was labeled printable. The experimental USDZ has no verified metric calibration; texture appearance must not be mistaken for recovered relief.

`scripts/reconstruct_photos.swift` is an optional macOS experiment, not an OSS dependency or production service. Apple owns the underlying engine; our wrapper is original. Output is USDZ. See [Apple's configuration documentation](https://developer.apple.com/documentation/realitykit/photogrammetrysession/configuration-swift.struct).

### Capture coaching now implemented

The phone gives one instruction at a time based on tracking, local image sharpness, reliable depth, target framing, distance and object-centered viewpoint bins. Guidance can request aiming left/right/up/down, moving closer/back, slowing down, orbiting left/right, raising/lowering the camera, or viewing openings. Coverage is based on camera position around a fixed depth-selected target, so rotating the phone in place does not create new coverage. New tracking origins and new selections reset guidance. Capture requests ARKit’s recommended 4K format when supported, retaining the default otherwise. Photos retain that native resolution and per-frame intrinsics with JPEG quality raised from 0.88 to 0.97. New 4K capture still needs an actual phone scan to verify delivered resolution/depth and sustained performance. No claim is made that these heuristics detect every ridge or guarantee focus, millimeter accuracy, or object stationarity.

In-app “How to capture detail” explains overlapping rings, close views of intact/damaged features, visible cavities and separate underside captures. An underside scan still needs cross-scan registration; it is not automatically combined.

### Live repair overlay: required behavior, not yet implemented

Preserve the observed full object. Once a stable candidate passes geometric and camera-consistency checks, render its mesh translucently in the current AR world coordinate frame, using its recorded donor-to-gap transform. Differentiate supported copied surfaces from inferred closures. Pause/hide the overlay when tracking or registration is lost; never reuse an old scan's world coordinates in a new session without registration. Additional views should confirm or reject a candidate. Guidance should eventually target candidate uncertainty (e.g. inspect a mating edge), rather than merely completing an orbit. The current phone build has capture coaching, not live missing-part detection or this overlay.

## Local stereo recovery regression — 2026-10-17

Three saved failed captures were replayed without modifying their source files. Two concrete defects were corrected: vertically rectified stereo was discarded, and reversed duplicate image pairs consumed the bounded attempt budget. Matching now transposes vertical pairs only for disparity search, restores calibrated pixel axes before 3D reprojection, and schedules distinct pairs across available views. Native scale/texture/left-right correspondence checks remain enforced.

After COLMAP alignment, the inconsistent-native-scan branch now attempts photo recovery rather than only an outline estimate. A second stereo pair spanning at least three source photos must agree within a 1 mm gate before a sample enters a diagnostic partial surface. This gate is not a measured accuracy bound. Recovered patches are stored separately in `photo_recovered_surface_m.ply` and `photo_recovery.json`; native geometry, engineering measurements, and the printable-repair decision are unchanged. Unsupported gaps are not closed.

Fresh full replays produced 49,282 / 60,371 / 3,790 stereo samples, with 11,583 / 15,503 / 698 surviving cross-pair agreement, and 665 / 3,709 / 79 partial-surface triangles. Before the fixes, the same captures with their saved COLMAP poses produced zero stereo samples. Fresh alignment can change exact counts. All three full runs still returned `needs_input` with no replacement generated. Reprojection of recovered patches onto a source image confirmed object-surface support, but coverage does not establish a complete intact donor or mating interface.

Thirty local hybrid-detail/reconstruction tests passed, including analytic recovery of a 2 mm raised patch with vertical camera motion, rejection of textureless images and incorrect native scale, and rejection of duplicate-pair or contradictory cross-pair evidence. These are algorithm regression tests, not proof of phone dimensional accuracy. Changes remain local pending review; this test run did not install a new phone build.


## General simple-object regression pass (2026-10-17)

Expanded the bounded Open3D self-similarity search to mirror symmetry and repeated translation periods inferred from normal-variation autocorrelation. No object category or physical size is supplied. A coarse overlap check skips implausible ICP seeds. Proposal extraction now measures distance to observed triangles, not just vertices: vertex distance incorrectly classified the interiors of large flat faces as missing geometry.

Synthetic mesh cases cover a radial part with a missing collared stud, a rail with a missing rib, and a bracket with a missing mounting feature, plus complete versions of each. All three broken cases yield a candidate near the withheld feature; complete cases yield none. The automated cases rotate, translate, and rescale the objects and also pass. These are mesh-level, noise-free tests, not physical accuracy or phone scanning benchmarks. The tolerance test checks the best of up to three hypotheses; it does not establish automatic selection accuracy or complete recovery of every withheld triangle.

Local verification: 41 tests passed across pattern completion, hybrid photo detail, and reconstruction geometry; one additional export-contract test passed. The latter verifies millimeter conversion, source-triangle provenance, and non-printable status. A full `rgb_assisted` replay of `fixtures/sample_scan` completed in 10.0 seconds and exported two reviewable general symmetry hypotheses. Consistent scan meshes now write `pattern_hypotheses.json` plus candidate previews; inconsistent scans do not run this general search. Existing cube-specific replacement UI is unchanged. General hypotheses are diagnostic alternatives, not automatically selected replacement pieces.

Remaining gates: object/background isolation, camera visibility checks to distinguish unobserved surfaces from damage, robust local symmetry outside principal axes, noisy and incomplete real-object captures, a general candidate review UI, and a justified solid/connector reconstruction. Do not claim arbitrary-object repair, tiny-detail measurement accuracy, or printable general replacements from these tests.

Reproduce the regression suite:

```sh
PYTHONPATH=backend OMP_NUM_THREADS=2 .venv/bin/python -m pytest backend/tests/test_pattern_completion.py backend/tests/test_hybrid_detail.py backend/tests/test_reconstruction_geometry.py -q
```


## Reviewed general candidate to test-print flow (2026-10-17)

General pattern results now appear in the phone's scan result screen. The user selects a proposal, compares its orange surface against the scan, and confirms that it matches the missing region. Candidate changes clear that confirmation. Saved reconstruction results reload the candidate list. The general path no longer requires the cube-specific preview or `printable_edge.stl` filename.

`printable_pattern.py` preserves donor triangles and closes only simple planar boundary loops. It rejects disconnected surfaces, curved boundaries, zero-volume patches, non-manifold vertices/edges, and self-intersections. It exports millimeter STL and 3MF, reopens both files, and rechecks solid validity and dimensions. Reports explicitly label inferred caps and untested fit. Closure is not evidence that a scan gap is broken material, and the extracted patch need not cover the full original feature. No automatic thickness, connector, clearance, or strength claim is made.

The phone verifies the complete downloaded artifact revision before preview selection and again before sharing. Export requires a closed candidate, a consistent scan, a reviewed selection, and every declared print/report file. Fragmented candidates remain viewable with a specific capture message; they cannot be exported as a test piece.

Validation: 48 focused Python tests passed, followed by seven closure tests including a newly added vertex-pinch rejection (49 distinct focused tests). The isolated-process bracket upload/reconstruction/CAD export/reimport integration passed. Ten iOS tests passed covering candidate review/export and verified artifacts. The signed device build succeeded. The sample RGB-D scan replay finished in 10.5 seconds but its two general candidates were fragmented, so neither became a print file. The mesh benchmark exported two rail surface closures; the fragmented radial fixture and top-only bracket patch were rejected. These results demonstrate the bounded software path, not general phone reconstruction accuracy or a physical fit test.

The current saved failed phone scans still lack sufficient consistent donor geometry for a reliable replacement. General repair remains limited to supported observed patterns and closures; live damage confirmation, robust recovery of arbitrary curved missing surfaces, inner mechanisms, and print-fit validation remain unfinished.
