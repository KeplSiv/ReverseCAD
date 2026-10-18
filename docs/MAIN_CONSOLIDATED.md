# ReverseCAD: two-pass object scanning and repair

The current implementation is developed from `main-consolidated` and published to `main`. The user's latest requested scan ordering supersedes the earlier identify-before-capture and single-pass revisions.

## Original main UI

The baseline is `754c0661f97d4b4c1e74ca2cb60519113c1d6c54` (October 18, 2026, 04:06 EDT), which remained on remote main until the 07:58 EDT consolidation. Use its camera-first entry, plum background, copper controls, stage pill, circular capture button, saved-scan/reset controls and Original/Repair/Pieces review. A compact selector switches between Scan object and Repair damage. There is no card-based landing page. All visible branding is **ReverseCAD**. The installed bundle identity remains unchanged so updates retain scans and tester access.

## Current supported sequence

1. **Phone reference setup.** Explicitly capture synchronized front TrueDepth and RGB on a still, textured scene. Preserve original buffers, calibration, timestamps and the reference archive. This is a prerequisite reference capture, not completed rear-camera calibration: the profile remains `provisional_reference_only`, with no fitted rear corrections or front-to-rear registration.
2. **First 360° pass.** Adjust or move the rectangle, initially the central rule-of-thirds cell. Save its raw-image coordinates through the inverse display transform. Start capture without a Jev request. Save full original images, native depth/confidence, intrinsics and poses locally. Show guidance from accepted viewpoints and camera movement.
3. **Automatic identification.** After finishing the first pass, Jev uses the original selection image/box and about 8–10 sharp, separated saved views. One reference request plus at most ten view requests. Cancellation, specific key/network/rate-limit errors and retry preserve the capture. Ambiguity permits a tap on the saved reference.
4. **Second 360° detail pass.** Use the confirmed first-pass identity and original reference. Track/refine the selected object locally while preserving full camera frames. A translucent top-right preview accumulates actual masked, confidence-filtered native depth samples. It rejects depth discontinuities, leaves unobserved surfaces open, caps memory and resets on tracking-epoch changes. It is an observed surface preview, not generated category geometry or completed CAD.
5. **Reconstruction and export.** The original first capture remains unchanged and is copied into the second package under `identification-pass/`. The second pass is confirmed against the same reference after capture. Its geometry is processed through the existing mask-aware Mac backend; the two unregistered camera coordinate frames are not silently fused. Export the observed model and supported measurements/formats. Repair damage continues into main's existing supported planar/3×3 damage workflow and review-gated CAD export.

The first pass therefore supplies identity/reference evidence, and the second supplies the final reconstruction geometry. Cross-pass geometric fusion requires separately verified registration and is not claimed by this implementation.

## Hardware boundary

The TestFlight target uses public APIs: one ARKit rear camera, available native `sceneDepth`/confidence, poses and intrinsics, plus a separate front TrueDepth reference capture. A hardware manifest records discovered cameras, supported multi-camera sets, and actual active sources separately.

The requested simultaneous wide/ultrawide/telephoto plus LiDAR fusion is not implemented or physically verified. Earlier TrueDepth work contains only a provisional reference, not completed rear-camera calibration. Earlier private-sensor work did not obtain a genuine pre-processing LiDAR buffer. These modes must not be marked active or calibrated. Private interception remains in the separate Debug-only research target and is excluded from distribution.

The user has been asked whether to publish the supported public two-pass build while unverified hardware mode stays disabled, or hold TestFlight for full hardware validation.

## Data and verification

`ReverseCADJevConfig.plist` remains ignored and is included only in the internal scanner build. No key enters Git, logs or capture exports. Original first-pass files and TrueDepth reference archives are preserved; second-pass metadata and derived masks never overwrite them. The capture package records factory/provisional calibration provenance.

Verify inverse coordinate mapping, sharp separated view selection, post-capture identity calls, ambiguity/cancellation/retry, first-pass preservation, second-pass reference reuse, discontinuity/mask-safe live preview, public sensor provenance, existing reconstruction/CAD exports, and the restored UI. Simulator/API/synthetic checks are distinct from actual phone capture, completed calibration, metric accuracy and printed fit.
