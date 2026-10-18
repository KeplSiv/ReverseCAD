# ReverseCAD: two-pass object scanning and repair

The current implementation is developed from `main-consolidated` and published to `main`. The user's latest requested scan ordering supersedes the earlier identify-before-capture and single-pass revisions.

## Original main UI

The baseline is `754c0661f97d4b4c1e74ca2cb60519113c1d6c54` (October 18, 2026, 04:06 EDT), which remained on remote main until the 07:58 EDT consolidation. Use its camera-first entry, plum background, copper controls, stage pill, circular capture button, saved-scan/reset controls and Original/Repair/Pieces review. A compact selector switches between Scan object and Repair damage. There is no card-based landing page. All visible branding is **ReverseCAD**. The installed bundle identity remains unchanged so updates retain scans and tester access.

## Current supported sequence and architecture

The normative architecture is [on-device reconstruction](ON_DEVICE_RECONSTRUCTION.md). Both flows now finish geometry and supported flat-part repairs on the iPhone, without a reconstruction service. First-use front reference → adjustable box → first orbit → direct Jev identity → second detail orbit/live preview → local calibration, registration, fusion → finished preview/export.

The existing raw acquisition and object-identity code is reused. Native Swift components replace the Python/Open3D/OCP dependency in the released phone workflow. The Python backend remains available for comparison and development. It is never an automatic fallback.

Actual three-camera/LiDAR acquisition and full-scene RGB-D motion are preserved. First-pass geometry is combined only after independently checked cross-pass registration. Native geometry exports are STL, PLY, observed measurements and budgeted faceted STEP. The supported local repair generator handles flat rectangular boundary damage with user-measured thickness and review; unsupported objects retain their measured model.

## Data and verification

`ReverseCADJevConfig.plist` remains ignored and is included only in the internal scanner build. No key enters Git, logs or capture exports. Original first-pass files and TrueDepth reference archives are preserved; second-pass metadata and derived masks never overwrite them. The capture package records factory/provisional calibration provenance.

Verify inverse coordinate mapping, sharp separated view selection, post-capture identity calls, ambiguity/cancellation/retry, first-pass preservation, second-pass reference reuse, discontinuity/mask-safe live preview, public sensor provenance, existing reconstruction/CAD exports, and the restored UI. Simulator/API/synthetic checks are distinct from actual phone capture, completed calibration, metric accuracy and printed fit.

## Physical verification boundary

The connected-phone stationary run delivered 349 wide, 352 ultra-wide, 351 telephoto and 349 LiDAR frames. All 53 processed RGB-D views tracked; one view was saved because the phone did not move enough for another keyframe. The final pose moved about 7.5 mm over this stationary run, so drift remains a measurement limitation. The actual saved package passed backend schema, original-plane size and checksum validation. The user elected to continue without a moving-camera test. A full orbit, completed front-to-three-camera calibration, absolute measurement accuracy and printed fit remain unverified. Synthetic math, simulator UI and API checks are reported separately from these phone facts.
