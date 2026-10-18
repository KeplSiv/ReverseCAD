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
- The initial physical framing check exposed pixel-valued output coordinates where normalized coordinates were expected. Conversion now explicitly normalizes by the delivered image dimensions and reverses that normalization on the inverse mapping. A fresh physical check of the corrected mapping is pending.
- The phone executed native reconstruction of the bundled synthetic fixture in 2.97 seconds, producing 4,956 vertices and 11,845 triangles with no geometry network request. This proves native execution, not a completed real-object scan. That initial phone run predates the final STEP correction; independent validation above uses the corrected Swift output from the simulator.
- A host-side live Jev suitability request succeeded. Direct-phone identification of a freshly captured physical view remains pending; synthetic/mocked identity tests do not replace it.

The user declined the moving-camera check. Full physical two-orbit capture, completed front-to-rear field calibration, sustained moving tracking, live-preview quality, dimensional accuracy and printed fit remain unverified. Neither sensor delivery nor simulator tests establish those results.

## Release boundary

The app keeps its existing bundle identifier, scan storage and TestFlight app/tester group. Visible branding is ReverseCAD. The older listing is named ReverseCAD Legacy. Build 36 is prepared in source; signing and final phone installation are blocked while the Mac is locked. Apple processing and internal availability must be checked after upload before calling the build ready.
