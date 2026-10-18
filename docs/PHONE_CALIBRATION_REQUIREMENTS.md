# Requested complete workflow

Branch override from the user: `pradev-4`; do not alter `main` or `pranav-dev`.

Build the complete first-use calibration → object scan → measured 3D/CAD export workflow now. Implement, test, integrate, and publish it; do not stop after writing a specification.

## 1. Continue the existing implementation

Read these chats and their latest implementation before editing:

- Capture-first Prelude scanner: codex://threads/01a14ed3-28ab-7e33-aea2-39f6bcb15456
- Frankly front TrueDepth capture and validation: codex://threads/01a14ec2-396e-7f11-961c-fe854b2171b3
- Earlier scanner implementation: codex://threads/01a14ea5-3320-75e1-9d7e-26283b94295e
- Standalone measurement specification: codex://threads/01a14ecd-aabc-74f3-bcb1-cf162b630e93

Main repository: `/Users/pranav/Desktop/hack-harvard/reverse-cad`

Existing `pranav-dev` checkout:
`/Users/pranav/.codex/worktrees/reversecad-testflight/reverse-cad`

Frankly reference implementation:
`/Users/pranav/frankly`

Reuse the latest completed capture-first changes. Check for an active writer before editing shared files; do not overwrite another chat’s work or restart from an older commit.

Keep this work on `pranav-dev`. Preserve unrelated changes and keep `main` unchanged. The deliverable is the scanned object and its measurements/CAD exports. Do not integrate missing-part generation or the main repair workflow in this revision.

Use Frankly as a source of reusable capture, geometry, validation, and replay code. Put the finished user workflow in Prelude so users do not need to switch between apps.

## 2. Finished user experience

First use:

**Set up this phone → Capture front reference → Scan the same object with rear cameras → Build model → Preview/export**

Later uses:

**Frame object → Scan → Identify object → Build model → Preview/export**

The calibration screen must explain simply that the first scan helps adjust the camera model for this particular phone. Start cameras and captures only after the user explicitly taps Start.

For normal scanning:

- Show the existing guide covering the middle third of the preview’s width and height.
- Say “Place one object inside the box.”
- Make the written description optional.
- On Start, say “Keep the object still. Walk slowly around it, keeping it inside the box.”
- Capture full images locally. The guide is a selection hint, never a destructive crop.
- Show coverage based on accepted viewpoints and tracking quality.
- Allow Finish without requiring another full orbit. Request a short extra view only when useful geometry is missing.
- Preserve the session through cancellation, identification failure, network errors, and reconstruction retries.

Capture must work without a Mac connection. Retain the existing reconstruction backend where useful and clearly disclose its connection requirement before processing. Do not claim backend computation runs on the phone.

## 3. First-use selfie/TrueDepth reference

Port the working Frankly front capture and per-frame reconstruction logic into Prelude.

Relevant references:

- `/Users/pranav/frankly/Frankly/CameraController/TrueDepthReconstruction.swift`
- `/Users/pranav/frankly/Frankly/CameraController/TrueDepthValidationAnalysis.swift`
- `/Users/pranav/frankly/docs/true-depth-validation.md`
- `/Users/pranav/frankly/build/validation-cv-review/ruler-verification.html`
- `/Users/pranav/Desktop/hack-harvard/reverse-cad/experiments/truedepth-selfcal/calibrate.py`

Use the front TrueDepth device with synchronized selfie RGB and supported unfiltered depth. Do not substitute a face mesh, facial landmarks, or monocular depth.

Guide the user through a short front reference capture of the same stationary object and surrounding features that the rear scan will observe. Collect enough variation in angle, image position, and depth to constrain useful parameters, without turning setup into a complicated calibration exercise.

Then guide the user to turn the phone and scan that unchanged scene with the rear cameras.

Preserve:

- Original colour and numerical depth/disparity buffers.
- Each frame’s own intrinsics, distortion tables, reference dimensions, timestamps, orientation, and mirroring conventions.
- Actual filtering state, formats, focus, crop, zoom, and available stabilization metadata.
- Invalid regions, dropped samples, and errors.
- Hashes and manifests for offline replay.

Build 23 fixed a false rejection caused by small per-frame calibration changes. Keep that fix: use each frame’s calibration rather than requiring all calibration values to be identical.

TrueDepth supplies optical-axis depth; sparse LiDAR uses a different radial-range convention. Implement distinct conversions and explicit coordinate frames. Apply distortion correction exactly once.

The latest real Frankly capture measured approximately:

- 101.6 mm → 100.096 mm
- 152.4 mm → 149.719 mm

Treat these as evidence that the reference is useful but imperfect. Do not automatically rescale every capture from these two results or label TrueDepth perfect ground truth.

## 4. Camera calibration and reusable phone profile

Reuse and extend the existing reference-to-rear calibration solver.

Match front-reference features and supported 3D points to the rear views. Explicitly estimate the rigid transform between the front reference capture and rear capture. The phone moves between them; a calibration matrix attached to a depth frame is not automatically that transform.

Model:

- Each physical camera’s intrinsics and distortion.
- Full relative rotations and translations.
- Field of view, overlap, crop, resolution, and pixel-coordinate conventions.
- Focus and zoom state.
- Source timestamps, measured inter-stream offsets, and available exposure timing.
- Visibility, occlusion, depth discontinuities, and ambiguous correspondences.

Use gyroscope, accelerometer, gravity, and reliable compass information as appropriate orientation/motion observations. Record their reference frames and timestamps. Do not treat compass heading or integrated acceleration as exact metric position. Use visual-inertial tracking and image geometry for translation, with depth constraints where supported.

Keep calibrated viewing rays in a common 3D frame. Reconstruct directly from those rays. Use rectification or depth-dependent reprojection only where needed for matching, fusion, or display; do not require a universal warp making every camera identical to 1×.

Start with the existing working wide/ultrawide path. Discover and integrate telephoto where the actual device, focus distance, overlap, and capture configuration support it. Check simultaneous camera/depth capabilities at runtime and measure timing. Unsupported combinations must have an explicit fallback, not fabricated synchronization.

Create a persistent, versioned calibration profile containing:

- Local device identity and physical camera identifiers.
- Factory calibration plus fitted residual corrections.
- Applicable formats, resolution/crop, focus/zoom ranges, and processing settings.
- Camera transforms, coordinate conventions, and timing calibration.
- Parameter uncertainty/observability, supporting captures, validation results, and profile revision.
- Status distinguishing provisional calibration from validated calibration.

Do not copy front-camera distortion coefficients onto rear lenses. Do not fit an unrestricted deformation map that absorbs scene errors.

A single object may constrain only part of the profile. Fit only identifiable parameters; retain factory values for unsupported ones. Save useful partial calibration and continue with an honest status. Request the smallest additional capture needed instead of blocking the entire app or pretending the calibration is complete.

## 5. Improve the profile safely over later scans

Apply the saved profile automatically when its camera configuration matches.

Collect suitable evidence during normal user-started scans. Reject calibration updates from poor tracking, insufficient overlap, moving objects, reflections, weak texture, or degenerate geometry.

Keep the active profile frozen while evaluating a candidate revision. Reserve observations or captures from fitting. Promote corrections only when they improve held-out geometry without hiding dimensional disagreement or degrading supported measurements.

Preserve earlier revisions and support rollback/reset. Do not claim every additional scan necessarily improves calibration. Do not learn systematic depth bias as apparent lens deformation.

Keep originals so older scans can be reprocessed with a selected profile.

## 6. Identification, geometry, and measurement

Retain the latest capture-first Jev design:

- No continuous Jev requests while scanning.
- After Finish, choose approximately 8–10 sharp, well-separated saved views.
- Use the initial centered view as the object-identity reference.
- Call the existing TypeSafe/Jev service directly from the phone using the established private credential configuration.
- Combine same-instance evidence across views.
- If ambiguous, let the user tap the intended object in a saved image once.
- Keep requests bounded, cancellable, and retryable.

Refine boxes into object masks using existing local segmentation and geometric consistency. Exclude hands, table, floor, and background. Preserve full images for camera tracking; store derived masks separately against immutable frame hashes.

Extend the existing reconstruction pipeline to consume the calibration profile, calibrated rays, camera poses, masks, and supported depth observations. Reuse suitable multi-view/stereo/surface code rather than rebuilding everything.

Keep source provenance explicit:

- Front TrueDepth reference.
- Public Apple processed depth.
- Camera triangulation.
- Private sparse ToF candidates, only in the separate research path.
- Fitted surfaces and derived measurements.

Keep public TestFlight capture separate from private sensor interception. Do not make unrecovered raw histograms or unfinished producer-access research a dependency of the usable app.

Use geometry, timing, visibility, and multiple-view agreement to reject bad measurements. Confidence alone does not identify the correct echo or surface. Do not double-count correlated depth/image evidence as independent validation.

## 7. Preview and CAD exports

Deliver an interactive, rotatable, zoomable model of the actual scanned object, with useful dimensions and selectable measurement endpoints or supported surfaces.

Include:

- Coloured point cloud.
- Supported surface mesh.
- Measurements with units, definitions, supporting observations, and uncertainty status.
- Clear incomplete/unknown regions.
- Optional overlays for capture coverage and measurement support.

Export:

- PLY point cloud.
- STL or OBJ observed surface.
- STEP using supported fitted surfaces or the existing faceted-surface exporter.
- Measurements JSON/CSV.
- Calibration/profile identifier, coordinate conventions, provenance, and file hashes.
- Original capture archive for reprocessing.

A partial scan may export an open surface. Do not fill unseen geometry merely to produce a watertight file. Do not present a faceted STEP shell as a fully parametric model.

Validate export units and geometry through independent readback. Report unsupported STEP conversion clearly while preserving the full mesh and point cloud.

## 8. Implementation, verification, and delivery

Complete the app flow, capture integration, calibration solver integration, profile storage, reconstruction contracts, preview, exports, and recovery paths.

Use existing saved Frankly and Prelude captures for replay before requesting another physical capture. Automatically identify reference features where possible; provide a simple correction option rather than requiring manual annotation as the default.

Test the consequential failure cases:

- Per-frame calibration changes.
- Mirrored front preview versus exported coordinates.
- Optical-axis depth versus radial range.
- Front-to-rear registration.
- Multiple camera formats and profile incompatibility.
- Timing offsets, missing data, and tracking loss.
- Degenerate calibration scenes and rejected profile updates.
- Preservation of the last good profile.
- Saved-scan identification/reconstruction retries.
- Export units, topology, and readback.

Compare factory calibration with the fitted profile using held-out image geometry and available independent dimensions. Report actual errors; better image alignment alone is not proof of better measurements.

Build and upload the next Prelude update through its existing TestFlight identity, incrementing from the latest actual build. Verify Apple processing and availability to the existing internal group. Keep credentials out of Git, logs, and exports.

Update the specifications and push the completed implementation to `pranav-dev`. Do not merge into `main`.

Do all software work and TestFlight delivery now. Do not install, launch, restart, or operate my iPhone automatically. When a physical capture is necessary, finish everything independent first, then give me one short instruction and wait for my response.

Finish with the exact build, implemented workflow, checks passed, remaining physical-validation status, and the first action I should take. Do not report a working precision calibration or completed physical scan based only on compilation, synthetic tests, or a successful upload.