# Reconstruction options — evaluated 2026-10-17

## Working implementation

The cube prototype uses OpenCV color segmentation, convex face boundaries, perspective rectification, and repeated 3×3 cell validation. A photo now supplies its own face corners. The photo-library prototype analyzes one image. The main camera flow now captures calibrated RGB-D/poses and fuses accepted views through the existing Open3D TSDF pipeline; it no longer selects one frame. The detector supports a mostly solved face with one dark missing edge; scrambled faces, multiple gaps, missing outer corners, occlusion, and poor light can require correction or fail.

The measured full cube width sets scale. CadQuery creates an exterior cubie envelope, STEP solid, STL mesh, and editable Python parameters. The normal UI asks only for full face width. Visible outline spacing is estimated from intact center-connected face regions when consistent; unresolved spacing and 3D rounding use labeled priors. Detection and detail provenance are exported; they do not certify mechanical clearance. The preview reads the exported binary STL. Neither connector fit nor arbitrary missing geometry is solved by this path.

## Hybrid surface and intact-edge proposal

The current camera flow uses existing OpenCV stereo rectification/SGBM and subpixel photometric alignment on bounded overlapping RGB pairs. ARKit baselines set scale; bidirectional correspondence, texture, photometric and depth checks reject unsupported detail. Supported high-resolution samples replace only covered coarse integration pixels, leaving native dimensions and capture files unchanged. Open3D fuses the derived surface. This is an experimental detail pass with a LiDAR fallback, not validated submillimeter metrology. See [OpenCV calibration and stereo documentation](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html).

A visible solved-face grid plus native plane fit establishes a cube frame. The proposal copies an observed intact edge with two exterior faces into the missing grid location by a proper rotation. It preserves the donor’s surface instead of generating a generic envelope. The app overlays the proposal in orange and exports its source/target cells and transform. It is explicitly an open surface proposal; it does not invent hidden geometry or claim a closed editable CAD replacement.

## Reusable projects

| Project | Useful output / role | License and practical fit | Decision |
|---|---|---|---|
| [OpenCV](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) | Detection, homographies, calibration | Already pinned in this repo | Used for automatic cube face detection |
| [Open3D](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html) | Registered RGB-D integration into a mesh | [MIT](https://github.com/isl-org/Open3D/blob/main/LICENSE); already installed | Retain for metric scan fusion; inspect foreground isolation and registration quality before trusting small features |
| [CadQuery](https://github.com/CadQuery/cadquery) | Parametric solids and STEP/STL export | Apache 2.0; already installed and generating valid solids | Retain for editable repair geometry |
| [COLMAP](https://github.com/colmap/colmap) | Camera calibration, structure from motion and multiview stereo | BSD core; dependency licenses separate. [macOS/Homebrew supported](https://colmap.github.io/install.html), but available dense-reconstruction acceleration depends on build/hardware | Candidate for initial geometry from overlapping RGB frames; it does not infer missing material or produce a feature history |
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
