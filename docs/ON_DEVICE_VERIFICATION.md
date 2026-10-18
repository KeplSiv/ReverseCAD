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
