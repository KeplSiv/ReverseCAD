# Native reconstruction verification — October 18, 2026

This record distinguishes execution on a phone from validation of physical geometry. The native reconstruction code has no service client or geometry network request. The normal model-building entry point was tested with an unreachable service address.

## Software checks

- 22 selected iOS tests passed: native reconstruction, registration, calibration/profile reuse, repair, first/second-pass recovery, identity consensus/tap correction, cancellation/retry, front stability and RGB-D tracking.
- Six simulator UI tests passed, including the consolidated flow and five framing-box drag/resize cases. The stationary gesture-coordinate fix incorporates the work from `4f3524fe7f48cd9b98c237fdaa63287bdfc0c256`.
- The eight native tests passed again after the final STEP topology correction and explicit inferred-repair export labels.
- The iPhone Release configuration compiled without signing. This does not substitute for signing, installation or Apple processing.
- ReverseCADCore: 41 tests executed, three platform/dependency skips, no failures.
- Retained backend comparison tests: 60 passed, 25 dependency deprecation warnings.
- Native cancellation preserves inputs and the previous result. Retry reuses the saved session. Deleting compatibility caches still reloads the immutable published model correctly.
- Fusion tests preserve an interior hole and a sub-voxel gap. Repair tests require thickness and leave interior holes alone.

## Independent export validation

The Swift writer's synthetic result contains 11,845 triangles. Both binary STL and PLY parse independently. Open CASCADE reads and transfers the faceted STEP successfully, and its boundary-representation checker reports a valid shape. STEP surface area is 64,337.200571 mm² versus PLY's 64,337.200849 mm², a relative difference of about 4.3e-9. The fixture extents are approximately 120 × 60 × 31 mm. These are fixture checks, not measurements of a physical object.

STEP contains planar faces with explicit edge topology and millimetre units. It is a faceted surface, not a parametric or automatically watertight solid. Native STEP output is limited to 20,000 faces; STL/PLY remain available above that limit.

## Connected iPhone evidence

Device: iPhone 15 Pro (`iPhone16,1`), iOS 27.

- An earlier stationary production-capture check delivered 349 wide, 352 ultra-wide, 351 telephoto and 349 LiDAR frames. All 53 processed views tracked, with one accepted keyframe. Approximately 7.5 mm of stationary drift was observed; this does not certify distance accuracy.
- A subsequent stationary check delivered 398 wide, 400 ultra-wide, 402 telephoto and 398 LiDAR frames, but only one of 61 processed views tracked and no keyframe was accepted. This is a tracking rejection, not a successful scan. Texture/correspondence diagnostics were expanded for the next check.
- The initial physical framing check exposed pixel-valued output coordinates where normalized coordinates were expected. Conversion now explicitly normalizes by the delivered image dimensions and reverses that normalization on the inverse mapping. A fresh phone check of all four preview orientations passed: every box stayed in normalized image coordinates, with maximum round-trip error below 1.5e-13 preview pixels. In portrait, the default box mapped to the middle third of the full camera image.
- After the rear cameras were uncovered, a further check delivered 398 wide, 401 ultra-wide, 400 telephoto and 398 LiDAR frames. One view was accepted; most tracking updates were rejected. The initial failures had only four or five of twelve image cells supporting depth/flow matches, below the six-cell gate. A visible image and sensor delivery therefore still do not establish sustained tracking.
- The final repeat delivered 396 wide, 399 ultra-wide, 398 telephoto and 396 LiDAR frames, but accepted no views. Early updates had only eight to ten depth/flow correspondences in two image cells. Tracking in this scene remains insufficient; the acceptance gate was not weakened to report a passing capture.
- Build 36 executed native reconstruction and separate repair generation on the phone in 7.23 seconds using synthetic fixtures, with no geometry network request. The scanned fixture produced 4,956 vertices, 11,845 triangles and 1,636 open boundary edges. Independent readers verified the actual phone-generated STL, PLY and faceted STEP, including valid STEP topology and matching surface area. The separate 30 × 20 × 3 mm repair fixture produced a watertight STL with approximately 1,800 mm³ volume; its exports explicitly identify inferred repair geometry. These are device-executed fixture checks, not physical measurement validation.
- A direct-phone Jev request completed using the configured personal key and `jev-1.14.0`, with no Mac service. It returned `other` without a box for the captured scene. This verifies the phone transport and response path, not successful object identity or multi-view consistency in a real orbit.

The user declined the moving-camera check. Full physical two-orbit capture, completed front-to-rear field calibration, sustained moving tracking, live-preview quality, dimensional accuracy and printed fit remain unverified. Neither sensor delivery nor simulator tests establish those results.

## Release boundary

The app keeps its existing bundle identifier, scan storage and TestFlight app/tester group. Visible branding is ReverseCAD. The older listing is named ReverseCAD Legacy. Source commit `cf35fb20d4cdb04f3316f8865b86b4ff34a0cb34` was archived as 0.1.0 (36), installed for phone diagnostics, signed, exported and uploaded. The verified IPA SHA-256 is `1fefe40af21c7eadac3d2602725e95ba3b5882e2e59c8a0adc1422583b53bc35`.

At 09:18:39 EDT, App Store Connect reported build 36 `VALID`, non-expired, `INTERNAL_ONLY`, and `IN_BETA_TESTING`. It belongs to the existing ReverseCAD Personal internal group, which still has its existing tester. Release notes were updated. This verifies TestFlight availability; it does not establish that the tester installed build 36. The connected phone was returned to the normal app screen after diagnostics.


## Preview and front-reference follow-up — build 38

Source commit `139f54887ecff27edd3f2788aac9bf50951f1324` was signed, exported and uploaded as ReverseCAD 0.1.0 (38). The exported IPA SHA-256 is `858992a314450074b06e7e93055a39cb2f63bb5b90c474d2659c5b9ae954fda9`. The existing bundle identifier, scan storage and tester group are retained. Build 37 was archived during development but was not uploaded.

The front-reference screen starts capture on entry, keeps Save scan at the top, uses concise instructions without a scroll view, and retains the native unwarped preview. A themed loading cover remains until the native preview reports that it is rendering. Manual save, public volume-button capture and the shorter selfie exposure remain in place. Rear capture formats and reconstruction were not changed by this follow-up; the rear smoothing path is display-only. See [Preview and front reference](PREVIEW_AND_REFERENCE.md).

The final source passed three camera-preview/buffer tests and two consolidated simulator UI tests. The tests cover source-buffer independence (including independent image decoding), display interpolation, the bounded fresh reference window, shutter limits, top-action layout, both flows and framing interactions. Simulator camera unavailability is not physical preview validation.

A freshly installed development build 38 launched directly into front capture on the connected iPhone. Within its first recorded three seconds it delivered 83 RGB frames and 78 depth frames at 4032 × 3024 RGB resolution. A retrieved camera frame showed a lit scene rather than black output. Measured exposure changed from 0.018684 s to 0.009334 s (ratio 0.49957). These observations confirm automatic camera acquisition and the requested shutter change, not a successful saved object reference, screen-to-first-frame latency, volume-button save, sustained full-orbit tracking or dimensional accuracy. Later diagnostic launches were interrupted; no additional persistence claim is made from their stale diagnostic files.

At 09:39:17 EDT on October 18, App Store Connect reported build 38 `VALID`, non-expired, `INTERNAL_ONLY`, and `IN_BETA_TESTING`, with membership in the existing ReverseCAD Personal group and its one existing tester. The upload reported no errors or warnings. This confirms internal TestFlight availability, not installation of this exact TestFlight build or external-beta availability.


## Native rear-preview correction — build 39

Commit `b204ace2f87f80a9bcc993fce27b9ab6041d19ff` removes the rear display-only optical-flow renderer, uses the native camera preview directly, and checks permission before constructing camera screens. The app still opens the rear-camera flow; front-reference setup remains a separate user action. The native layer attaches before the existing three-second sensor acceptance gate completes. Rear capture formats, saved geometry and reconstruction remain unchanged. This release does not claim to resolve the separately reported front-camera deformation.

Six selected unit tests and four simulator UI tests passed, covering permission decisions, a single pending system request, Settings-state refresh, launch routing, both flows, saved scans, front-reference layout and buffer preservation. The final rear-launch UI check passed again after the loading-cover adjustment. The earlier denied-permission accessibility failure was corrected and its test passed. Five framing gesture tests also passed in the preceding run.

The development build installed on the connected iPhone, but later inspection showed TestFlight build 38 had replaced it before the rear-motion check. No build-39 physical movement or measurement validation is claimed. Build identity must be checked again before diagnosing any remaining front or rear issue.

ReverseCAD 0.1.0 (39) was signed, exported and uploaded with IPA SHA-256 `3c69e52a4f8113a4d83ed0b8c31d06cf15af5826bd612eb6c5fbc068e7a20db7`. At 09:47:50 EDT on October 18, App Store Connect reported `VALID`, non-expired, `INTERNAL_ONLY`, and `IN_BETA_TESTING`, with the build assigned to the existing ReverseCAD Personal group and its one tester. The upload reported no errors or warnings. Existing app identity and scan storage are retained.

## Rear 1× follow-up — build 40

The user clarified that the deforming preview was the rear 1× camera; the selfie camera had been working. Do not treat the earlier front-camera diagnosis as an established defect. Build 40 removes the unused selfie preview-buffer cache and ad hoc per-frame diagnostic JSON/JPEG work, while keeping its native preview, manual/volume capture, original RGB/depth storage, metadata, short exposure and layout.

The initial device inspection found the running app was still 0.1.0 (38), including the rear display-only optical-flow renderer. Build 39's removal of that renderer therefore had not reached the running process. A later screen capture showed TestFlight's explicit 0.1.0 (39) overlay and then a coherent native rear view of a keyboard. The user confirmed that the rear view was now fine. This supports the removed synthetic display interpolation as the source of the reported deformation; it does not establish a sensor or reconstruction defect.

Two Debug 40 installs were replaced by TestFlight 39. The second Debug 40 launch was verified as PID 22714 in its matching app container; it created validation directory `A66491E1-56BB-45ED-BBC1-1FD3B875239C` and scan ID `47997251-4C07-44E9-B836-E64692C6F9E2`, then ended with `CancellationError` as the process/container changed to build 39. Its initial saved image was black. This interrupted run is not evidence of sustained build-40 preview, sensor failure or buffer corruption. The stable rear-view report applies to native build 39.

Six selected unit tests and four simulator UI tests passed for build 40's source, including pixel-copy independence/decoded equality, reference-window and shutter policy, permission states, rear launch, selfie layout and saved-scan navigation. An independent final review found no actionable issues in the scoped changes. A fresh saved-project inventory after the TestFlight replacement matched all 537 original entries by path, size and modification time. Physical geometry accuracy and printed fit remain separate, unvalidated gates.
