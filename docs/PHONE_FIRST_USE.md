> Current implementation: [On-device architecture](ON_DEVICE_RECONSTRUCTION.md). This document describes the retained first-use reference contract.

# Required first-object setup

Both camera-first buttons share `PhoneSetupStore`. First use is: capture selfie RGB plus infrared TrueDepth on the chosen still object; assess numerical reference support; have Jev judge visual adequacy; turn the phone and take the first rear orbit; identify the object and verify the same physical instance; take the second detail orbit; register and reconstruct on the iPhone. Later objects reuse setup and compatible corrections. Full captured views remain available for tracking.

## Front reference

The front preview stays open until **Save scan** or a volume-button capture. A rolling window provides eight recent sharp samples; there is no automatic completion after eight frames or twenty seconds. A failed stability check leaves the preview open. Selfie shutter duration is requested at half the settled auto-exposure baseline, subject to hardware limits. See [preview and reference behavior](PREVIEW_AND_REFERENCE.md).

The existing Frankly-derived writer retains original buffers, numerical optical-axis depth in metres, per-frame intrinsics/distortion tables, timestamps, mirroring, crop and filtering metadata. The existing per-frame TrueDepth reconstruction applies the inverse distortion mapping once and creates a supported correspondence map. It rejects unstable or mixed-edge samples. Camera movement is screened during the stationary burst. Adequacy is evaluated within the user's box rather than requiring that an object fill the whole sensor. The full scene remains available to constrain registration.

`JevReferenceReview` uses the existing personal-key HTTPS transport. A bounded request returns visual adequacy, a reason and a starting box. It cannot certify metric accuracy. Rejection, cancellation, key failure, rate limiting and retry preserve the saved samples. No companion URL is required for the front check or rear identification.

## Front-to-rear mathematics

The native solver reuses the earlier `experiments/truedepth-selfcal/calibrate.py` reference-registration design, replacing desktop dependencies with multi-scale Harris features, rotation-aware binary descriptors and rigid 3D-to-3D RANSAC. It uses saved front depth and rear RGB-D correspondences, a rigid reference-to-rear transform, bounded focal/radial residuals and distinct held-out reference features. It does not use the experiment's hard-coded camera baseline, ruler annotations or manually supplied camera model. Recorded factory camera extrinsics supply the auxiliary-camera baselines.

Front points are in optical coordinates (x right, y down, z forward), metres. The current rear capture supplies RGB-D poses in the existing column-major camera convention; conversion to optical coordinates flips the y and z axes. TrueDepth and sceneDepth provide optical-axis z, never silently radial range. No scale is fitted from the Jev category or box.

A rigid fit requires at least sixteen training inliers and five distinct held-out inliers, with training and held-out RMSE below 10 mm and 12 mm respectively. Registration samples up to eight saved rear views. Focal/radial refinement requires at least forty registered correspondences; a separate held-out subset must improve by at least 10 percent and end below two pixels. Log-focal adjustment is bounded to ±0.025, and radial coefficients to ±0.08 and ±0.05. Unsupported or worsening corrections remain zero. These are numerical acceptance gates, not a dimensional-accuracy certification. A device/format/intrinsic-range mismatch prevents profile reuse and requires fresh reference registration.

Factory distortion mapping is applied once to the derived working grids. Accepted residuals adjust reconstructed rays once; they do not rewrite the original images. Depth and masks use nearest-neighbour sampling; missing observations stay missing. Reconstruction still rejects mask, depth-edge and multiview inconsistency. Original files and their hashes remain intact.

`calibration/front/`, `calibration/setup.json` and `calibration/object-link.json` preserve the required reference and identity evidence in the capture. `phone-calibration.json` records registration, all acceptance results, correction scope and uncertainty. The phone accepts it only after normal artifact hash verification, for the matching reference/device, and saves an immutable revision. A failed first registration preserves the scan and describes the missing overlap.

## Simultaneous rear capture

`MultiCameraSession` starts the physical wide/LiDAR, ultra-wide and telephoto streams in one session and requires fresh delivery from all of them. It keeps each exposure timestamp and original full image. It does not run ARKit concurrently because the connected-device test showed camera interruption. `RGBDTracking` computes only rigid motion from measured full-scene depth and bidirectionally consistent textured image correspondence. Tracking rejection preserves prior observations. It does not integrate a guessed camera trajectory.

The primary working RGB/depth grids receive the recorded factory lens correction once. The native phone processor interpolates valid bracketing poses at auxiliary exposure times, uses the recorded physical camera baselines, checks auxiliary correspondences against reference-calibrated metric rays, and uses bounded on-phone stereo. Unsupported corrections and stereo samples are excluded. Primary reference registration and auxiliary support are reported separately.

The top-right inset accumulates selected LiDAR observations locally. Final residual lens correction and auxiliary photo detail are computed on the iPhone after capture. No stage requires a Mac reconstruction service. Private sensor experiments are excluded from TestFlight.

A connected iPhone 15 Pro stationary run verified changing frames from all three cameras and LiDAR and tested the actual saved package. The user skipped the moving-camera check. This is not a completed physical calibration, full-orbit tracking, dimension or fit validation.
