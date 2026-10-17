# Reverse CAD physical phone and printed fit validation

Run this after the software build, Simulator workflow, service integration, and export checks are complete. The goal is to establish what works on the actual phone and what fits after printing. Software test results do not fill in any of these observations.

Record every trial, including failed scans and failed prints. Keep calibration, measurement validation, fit, and strength as distinct outcomes.

## 1 Prepare the first trial

Collect:

- A supported LiDAR iPhone and its model/OS version.
- The app installed through Xcode with an appropriate development signing team.
- The Mac companion service running and reachable from the phone on the same network.
- A ruler and preferably calipers, with their resolution/accuracy noted.
- An opaque matte rectangular object with independently measurable dimensions.
- A broken handle or simple two-mount test assembly.
- An empty room-temperature cup with visible contact regions, if testing the cup workflow.
- A 3D printer/slicer or access to printing, with a known printer/material profile.

Use disposable test fixtures where a first fit attempt could damage the original object. Do not apply adhesive before checking contact geometry.

The implementer must provide the actual scheme, bundle ID, startup command, server address configuration, and signing instructions in README. If the installed device OS needs a different SDK, resolve that build compatibility before recording sensing results.

## 2 Verify the actual live capture path

1. Open the installed app and record its build/revision.
2. Confirm that it detects the phone's real ARKit/LiDAR capabilities.
3. Grant camera access and local-network access when requested. Motion logging may have a separate optional permission.
4. Connect to the service using the Mac's reachable address; verify health in the app.
5. Confirm that the view is labeled live capture rather than synthetic/replay.
6. Move around the matte calibration object with the object stationary.
7. Inspect actual accepted RGB/depth pairs, depth confidence, timestamps, pose changes, and tracking state in the exported diagnostic summary.
8. End the scan, reopen it after app restart, and verify that the same data and reconstruction remain available.

Pass this stage only if live sensor data was saved, delivered to the service, reconstructed, and read back. A camera preview, empty depth stream, successful upload submission, or loading spinner is not a completed scan.

Record capture duration, accepted/rejected frames, missing-depth count, file size, app/service elapsed time, thermal state if exposed, and any tracking interruption. Set phone-specific performance goals after measuring the baseline; do not reuse Simulator timings as hardware timings.

## 3 Check dimensional accuracy and repeatability

Measure a calibration object in at least three independently accessible dimensions. Prefer spans covering roughly 30–150 mm for the initial small-object test. Record the physical dimensions before looking at app estimates.

If one length is supplied to correct scale, reserve at least two other lengths and preferably a second object for evaluation. Do not score the same entered length as an independently recovered measurement.

Perform three independent scans, starting a new scan/session each time:

- Scan A: diffuse light, textured background, complete views.
- Scan B: another starting position and camera path.
- Scan C: another height/orientation while retaining similar capture quality.

For each dimension compute:

    signed error = app estimate - reference measurement
    absolute error = abs(signed error)
    relative error percent = 100 * absolute error / reference measurement
    repeatability range = maximum estimate - minimum estimate

Record uncertainty/status from the app before revealing reference values. A dimension marked as requiring manual measurement is not an automatic scan success, but can be a correct uncertainty decision.

### Provisional trial gates

These are initial targets to evaluate, not sensor specifications or promised performance:

| Outcome | Initial target |
| --- | --- |
| Gross dimensions on suitable objects | Absolute error no greater than max(2 mm, 2% of reference length) |
| Repeatability | All three measurements and their spread reported; investigate spreads exceeding the gross-dimension target |
| Critical mating dimension | Error/uncertainty must fit the tolerance chosen for that actual interface; otherwise use manual measurement or a fit coupon |
| Manually constrained CAD output | Exported geometry agrees with the entered dimension within the software export tolerance |
| Unobservable dimension | Clearly missing or inferred, never marked measured/verified |
| Failed or poor scan | Clear actionable failure/needs-input state; no confident fabricated geometry |

Do not average away one failing critical feature. Examine bias separately from repeatability. If a scale adjustment improves one axis but not others, investigate calibration, depth distortion, alignment, or segmentation rather than applying repeated arbitrary scale corrections.

Use at least one new shape or dimension that was not used to tune the processing settings before claiming the adjustment generalizes.

## 4 Test the supported repair workflows

### Bridge handle

Use a two-mount handle fixture or a broken handle with measurable surviving mounting locations.

1. Record center-to-center mounting distance, mating surface orientations, required standoff, and any hole diameter.
2. Scan the assembly without providing hidden ground-truth dimensions to the estimator.
3. Mark the mounting contacts and inspect the app's proposed dimensions.
4. Enter/confirm critical dimensions where the scan is inadequate; retain which values were manual.
5. Generate a handle, edit one noncritical parameter, regenerate, and verify that confirmed mounting dimensions remain unchanged.
6. Inspect the part aligned to the scan and verify hand clearance and assembly direction.
7. Export the CAD and a small mounting/clearance coupon.

### Cup handle

Use an empty room-temperature cup for fit evaluation.

1. Measure body diameter at the proposed contact heights, spacing between contact regions, and any surviving stubs.
2. Scan from multiple heights; glossy glaze may produce unreliable evidence.
3. Confirm the attachment method and whether the design uses surviving stubs or curved saddle pads.
4. Verify that the proposal distinguishes measured curvature from inferred grip shape.
5. Print contact-pad/cup-curvature coupons before the full handle.
6. Test contact and alignment without permanent adhesive.

Success here means the specified geometry fits the tested empty cup. It does not establish bond strength, loaded use, food suitability, or hot-liquid performance.

### Bracket

1. Measure mating-plane angle, hole spacing, offsets, and available installation path.
2. Annotate the mating surfaces and generate the bracket.
3. Verify that hole dimensions too small for the scan are requested rather than invented.
4. Check contact, interference, fastener access, and assembly.
5. Export, print the relevant coupon, and then print the complete bracket if the coupon fits.

## 5 Verify the actual printed part

In the slicer:

- Confirm millimeter units and compare bounding dimensions with the app's report.
- Record slicer/version, printer, material, nozzle diameter, layer height, orientation, supports, and compensation settings.
- Check that the mesh has the expected components and no slicer repair warnings that change geometry.

For each print:

1. Measure the printed coupon or part independently.
2. Separate CAD-to-print error from scan-to-CAD error.
3. Attempt the intended assembly without forcing or damaging the original.
4. Record mounting alignment, clearance, contact gaps, interference, and needed finishing.
5. Save photos of fit and a short description.
6. If adjustments are needed, create a new parameter revision rather than overwriting the previous evidence.
7. Record how many print iterations were required and why.

A useful first repair result is: the part installs by the intended method, aligns with confirmed mating features, and has the intended clearance on the tested object. The report must state whether sanding, drilling, glue-gap changes, or manual CAD edits were needed.

Use any functional/load test only after establishing material, attachment, and suitable test conditions. Do not infer strength from watertightness, appearance, or successful assembly.

## 6 Check failure and recovery behavior

| Trial | Expected behavior |
| --- | --- |
| Dim light or excessive motion | Quality feedback and rejected/flagged views |
| Shiny or transparent object | Low-quality/insufficient-evidence handling; no promise of exact dimensions |
| Thin contact feature | Request additional evidence/manual measurement when unresolved |
| Object moved during scan | Detect inconsistency where possible and flag/restart affected segment |
| App backgrounded or camera interrupted | Preserve committed frames; resume or start a registered new segment |
| Tracking reset | No silent union of incompatible world origins |
| Wi-Fi/service loss | Save locally, show clear state, resume without duplicate processing |
| Server restarted mid-job | Recover or fail explicitly; retain scan and diagnosis |
| Provider key absent/provider timeout | Labeled manual/template path or actionable error; no simulated AI success |
| Insufficient scan coverage | Needs another view or measurement |
| Unsupported repair | Explain the unsupported geometry instead of substituting a stock part |
| Invalid generated geometry | Reject export until repaired; preserve the input and error |
| Low storage or resource limit | Graceful stop/backpressure with committed data preserved |

Repeat a normal scan afterward to ensure recovery did not permanently break the workflow.

## 7 Trial worksheet

Copy this for each scan/repair revision:

| Field | Recorded result |
| --- | --- |
| Date and operator | |
| Phone model and OS | |
| App build and server revision | |
| Object and repair family | |
| Scan ID and input package hash | |
| Lighting, surface, distance/path notes | |
| Capture duration and accepted/rejected frames | |
| Tracking resets and registration result | |
| Reconstruction/planning/CAD duration | |
| Scale reference and measurement uncertainty | |
| Evaluation dimensions withheld from calibration | |
| App dimensions before manual correction | |
| Reference dimensions and absolute errors | |
| Inferred/manual/observed parameters | |
| Quality warnings and missing evidence | |
| Model/provider status and repair revision | |
| CAD/STL/3MF filenames and hashes | |
| Printer/material/slicer settings | |
| Printed dimensions | |
| Physical fit and required finishing | |
| Print iteration count | |
| Failure reason or pass scope | |
| Photos and replay-package location | |

Export the scan package and report back to the project so a bug can be reproduced without another phone session.

## 8 State the result precisely

After testing, report five separate statuses:

1. Application and service behavior.
2. Live RGB/depth/pose capture.
3. Dimensional measurement accuracy on the tested objects.
4. CAD/export correctness.
5. Printed fit and any separately performed functional test.

“Three measured handle fixtures passed fit after one coupon adjustment” is meaningful evidence. “The app passed Simulator tests, therefore it can produce exact replacements” is not.


## 9 Implementation-specific trial setup (October 16, 2026)

The delivered project is `ios/ReverseCAD.xcodeproj`; use scheme `ReverseCAD`, bundle ID `com.pranav.ReverseCAD`, deployment target iOS17.0. Choose your development signing team and device in Xcode. The automated unsigned device build is not a signed installation or a sensor test.

From this workspace run `./scripts/bootstrap.sh`, then `./scripts/start_service.sh --lan`. The script prints the current Mac `.local` address on port 8767 (currently `http://48.local:8767`); enter that address in the app's **Service** settings, with the private token from `var/service/pairing-token`. The current name can be checked using `scutil --get LocalHostName`. Phone networking remains unverified until the app connects from the actual phone; same-Wi-Fi internet access alone does not establish peer access.

Create a live project and inspect capability detection. Use **Capture**, **Evidence**, **Design**, and **Results** in sequence. Keep default design parameters labeled as proposals. The critical manual measurement names are `span`, `hole_diameter`, `cup_radius`, `cup_radius_top` for tapered cups, `contact_spacing`, and bracket `hole_spacing` as applicable. Enter only dimensions actually measured, with units and ruler/caliper uncertainty. Confirming a value is a user action; a low fit residual does not confirm it.

Use fitted candidates as hypotheses. Review their measurement references, attachment method and unresolved questions. Curved cup saddles need explicit approval; surviving ceramic stub geometry is not silently substituted. For bracket trials inspect both mating normals and the installation direction. Native capture preserves raw calibration, including the native-ARKit depth mapping distinction from resized synthetic images.

After changing a scale reference, reprocess and review contact/crop selections in the corrected object frame. A reference length used for calibration is excluded from independent scoring. Reserve at least two dimensions and a new object/shape for evaluation. Retain original depth and the correction factor in the exported evidence.

Export the original scan package for replay and the generated revision files for printing. Preserve `manifest.json`, `frames.jsonl`, native depth/confidence, calibrated RGB, diagnostics, checksums and any incomplete-video status. Editable annotations must not overwrite the immutable raw capture package. Include the project evidence and revision report with a bug reproduction.

The supplied coupons are actual STEP/STL/3MF geometry: bridge/bracket mounting-hole or pad coupon, and cup saddle-curvature/contact-gap coupon. Verify slicer dimensions against `parameters.json` and `validation.json`, record printer compensation separately from sensor uncertainty, and print the coupon before the complete replacement. Record physical feedback for the exact revision tested; regenerating creates a new untested revision.

The software tests cover synthetic reconstruction, native buffer layouts/video writing, geometry, export and service/UI behavior. They leave live LiDAR/VIO/calibration, Vision segmentation on your actual surfaces, phone thermal/storage throughput, network reachability, independent dimensional accuracy, slicer/printer behavior, contact fit and attachment strength as physical trial observations. Do not fill those worksheet fields from automated results.
