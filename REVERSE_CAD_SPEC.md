# Reverse CAD iPhone application specification

> Current consolidated revision: [Adjustable selection and two app flows](docs/MAIN_CONSOLIDATED.md) on `main-consolidated` supersedes the ordering below. Jev uses the edited rectangle before scanning; the same reference is checked across saved views afterward. Scan and repair are separate flows; repair continues into the existing main-branch CAD component.


## Prelude capture-first revision (2026-10-18)

The standalone Prelude scanner on `pranav-dev` follows **Frame object → Scan around it → Identify object → Build 3D model → Preview and export**. Its normative workflow, direct-phone Jev contract, saved-session masks, backend requirement and verification boundaries are in [PRELUDE_SCANNER.md](docs/PRELUDE_SCANNER.md). This supersedes any earlier identify-before-capture or continuously polled Jev flow for Prelude. Descriptions are optional; the center rule-of-thirds cell is a framing hint, never a crop. Full calibrated capture happens locally before identification. Original geometry, supported scale and refined same-instance masks drive reconstruction; category-shaped completion is prohibited. Work and release stay on `pranav-dev`; private sensor experiments and `main` remain separate.


Version 1.0 · October 16, 2026 · Implementation brief for Codex

Build a native iPhone application that captures a broken rigid object, estimates its measured geometry, helps the user specify a repair, constructs an editable replacement part, and exports files for 3D printing. Deliver the complete application and processing service, with every test possible without a physical phone executed before handoff.

The first completion milestone is **software validated and ready for a phone trial**. Scan accuracy, physical fit, and attachment strength remain separate results that require the user's phone and printed samples. “Exact replacement” is the objective to evaluate, not a capability to assert before measurement.

The authoritative product idea is the user's description in this chat. The supplied [shared conversation](https://chatgpt.com/share/6ad2def1-db70-83ea-82ee-b28d0e381486) was accessible as “Open ended clarification”; its visible contents covered other HackHarvard ideas and contained no Reverse CAD discussion. Do not import unrelated project requirements from it.

## 1 Product scope and success

The complete primary workflow is:

1. Create a repair project and identify the broken object.
2. Scan the stationary object by moving the iPhone around it.
3. Review scan coverage, crop the object, identify damage and attachment surfaces, and check scale.
4. Infer candidate repairs from measured geometry, images, remaining fragments, symmetry where available, and the user's functional requirements.
5. Confirm uncertain dimensions and select a repair.
6. Generate and edit an actual CAD solid.
7. Check geometry, clearances, fit uncertainty, and print constraints.
8. Preview the replacement aligned with the scan, export it, and record the result of a real print.

A usable version must perform this workflow with live sensor input on supported hardware and with replay input in Simulator. A canned mesh viewer, prompt-only CAD generator, or UI backed by fixed output files is insufficient.

### Required repair families

Implement these as real parametric generators, each with multiple valid sizes and negative tests:

| Family | Required behavior | What establishes fit |
| --- | --- | --- |
| Bridge handle | A curved or arched grip joining two mounting pads, with configurable span, standoff, grip section, pad dimensions, and optional mounting holes | Measured attachment locations and normals; user-confirmed critical hole dimensions |
| Cup handle | A replacement grip joining two selected contact regions on a cylindrical or mildly tapered cup, with curved saddle pads and editable contact gap | Fitted cup profile, selected contact regions, confirmed attachment method and dimensions |
| Simple repair bracket | Flat or L-shaped bracket with configurable thickness, offsets, and hole pattern | Selected mating planes, measured or entered offsets, and confirmed hole pattern |

A cup handle is a supported repair hypothesis, not an automatic reproduction of unseen ceramic fracture details. If the surviving stubs cannot be measured reliably, offer a user-approved saddle-pad design or request measurements. Do not silently change the attachment method. The initial cup test concerns fit on an empty, room-temperature object; the software does not certify adhesive strength, food contact, or hot-liquid use.

Allow scans of other objects, but return “unsupported repair type” or “more measurements needed” when the required part cannot be expressed by a supported generator. Do not disguise a generic stock handle as a reconstruction. Keep the generator interface extensible for knobs, clips, caps, and more general CAD operations.

### Engineering boundaries

- The object remains rigid and stationary within each scan segment. Moving the phone is supported; rotating the object on a turntable during the primary ARKit scan is not.
- Initially target hand-sized, opaque objects with visible attachment geometry. Thin, reflective, transparent, and featureless surfaces need explicit quality handling.
- Missing material has no direct sensor observations. Infer it from constraints and label its provenance.
- A scan mesh represents observed surfaces. A repair CAD model represents a proposed functional replacement. Preserve both.
- Do not require training a new CNN or solving arbitrary inverse CAD before the supported workflows work.
- Keep optional research features out of the completion gate: general shape completion, arbitrary freeform CAD, calibrated finite-element analysis, and automatic printer operation.

## 2 Recommended architecture

Use this architecture unless a verified compatibility problem requires a documented replacement.

| Component | Default |
| --- | --- |
| iPhone application | Swift, SwiftUI, ARKit, RealityKit, Vision, CoreMotion, AVFoundation |
| Deployment target | iOS 17 or later, adjusted only for a documented required API; use runtime capability checks |
| Shared iOS logic | Swift package containing capture DTOs, geometry transforms, validation, state machines, persistence, and API client |
| Reconstruction service | Python 3.11 or another verified compatible version, FastAPI, Pydantic, NumPy, OpenCV, Open3D |
| CAD service | CadQuery with OpenCascade, isolated worker process, deterministic generators |
| Persistence | Project directories and SQLite job metadata; no external database required |
| Reasoning provider | Server-side OpenAI Responses API, vision input and structured output; model configurable |
| Default deployment | Service running on the user's Mac; phone connects over the same network |
| Test mode | Synthetic/replay capture plus the same real service and CAD workers; only external AI responses may be replaced with labeled fixtures |

The workspace was empty when this brief was prepared. Local inspection found Apple silicon, macOS 26.6.2, Xcode 26.6, and installed iOS 26.5 simulators. Recheck these before implementation; no application build or application test has been run by this specification task.

This is a phone application with a companion processing service. Heavy CAD/reconstruction does not have to run on the phone. Cloud hosting is optional, not a prerequisite for the first physical trial.

### Sensing model

Use ARKit's visual-inertial world tracking as the authoritative camera-pose source. It combines camera analysis with motion sensing; the app should consume `ARCamera.transform`, not double-integrate accelerometer readings to construct a competing position estimate. [Apple world tracking](https://developer.apple.com/documentation/arkit/understanding-world-tracking)

Acquire synchronized RGB and LiDAR depth through one `ARSession`. Check `ARWorldTrackingConfiguration.isSupported` and `supportsFrameSemantics(.sceneDepth)`; separately check mesh-reconstruction support before enabling it. Optional scene mesh anchors assist visualization and cropping; they are not the sole source of small-part geometry. [Apple scene depth](https://developer.apple.com/documentation/arkit/arframe/scenedepth)

Keep native depth values for measurement. Smoothed or upsampled depth may improve display but must remain distinguished from the original observations. Upsampling does not establish additional measured detail. [Apple depth sample](https://developer.apple.com/documentation/arkit/displaying-a-point-cloud-using-scene-depth)

### How the proposed technologies contribute

| Technology | Role in the shipped workflow |
| --- | --- |
| LiDAR | Metric depth observations, initial scale, surface fusion |
| RGB video | Visual tracking through ARKit; object masks, image evidence, texture and feature checks |
| Accelerometer and gyroscope | Used by ARKit for pose; optional independently recorded diagnostics and motion-quality indicators |
| Computer vision | Foreground segmentation, feature matching, geometric fitting, observation-quality checks |
| Reasoning model | Select a repair family, interpret purpose, propose bounded parameters, explain assumptions, request missing dimensions |
| CAD kernel | Construct and validate solids with reproducible dimensions |
| Geometry and physics checks | Collision, clearance, wall thickness, assembly checks; optional clearly qualified structural analysis |

A separate dense photogrammetry route may improve surface detail, but it must not delay the working RGB-D route. If implemented, use Apple's supported Object Capture/PhotogrammetrySession flow or a verified reconstruction library. Treat an independently reconstructed model as a different coordinate frame; register it to metric evidence and report residuals. Do not assume exported photogrammetry vertices already share the ARKit origin or scale. Do not run competing camera sessions simultaneously. [Apple Object Capture](https://developer.apple.com/documentation/realitykit/objectcapturesession), [capture guidance](https://developer.apple.com/documentation/realitykit/capturing-photographs-for-realitykit-object-capture/)

## 3 User experience

Use a clear, native interface with a large 3D preview and short contextual instructions. Support Dynamic Type, VoiceOver labels, light/dark appearance, and controls that do not depend only on color.

### Project and setup

- Project gallery with thumbnail, date, repair family, progress, and last exported revision.
- Capability screen that distinguishes live LiDAR capture, camera-only capture, and sample replay.
- Explain the companion service, show connection health, and support a configured server address or local pairing.
- Request camera and local-network access when needed. Request motion access only for additional CoreMotion logging. No microphone recording is needed.
- Allow local capture and saving while the service is unavailable; queue processing for later.
- Provide a sample project clearly labeled “Synthetic sample.” Never label it as a real phone scan.

### Guided capture

1. Place the object on a stable, textured surface with diffuse light.
2. Select it by tapping or drawing an initial region.
3. Include a measured reference when possible, or enter a known dimension afterward.
4. Move around it in overlapping views at multiple heights. Keep the object stationary.
5. Show coverage, tracking quality, blur, depth availability, accepted frames, and recording size.
6. Pause or reject poor observations with a useful instruction.
7. End with a review of missing views and whether the attachment regions have enough evidence.

Guidance must respond to observed state. A timer alone must not mark a scan complete. Coverage is relative to the current surface/region estimate; do not present it as a guarantee that all hidden surfaces were seen.

### Review and repair intent

- Orbit, pan, and zoom the reconstructed object; toggle images, point cloud, surface mesh, and proposed part.
- Crop the support surface/background and correct foreground selection.
- Select damage regions and contact points or patches in the 3D view or in calibrated source images.
- Ask what should be repaired and how it should attach.
- Support “fragment available,” “matching intact part available,” and “missing part” as distinct evidence states.
- Allow selection of an intact symmetric counterpart and a confirmed symmetry plane where applicable.
- Show each important dimension with its value, units, origin, and uncertainty status.
- Offer manual caliper/ruler entry for dimensions that scans cannot resolve.
- Present a small set of repair candidates with differences in attachment, dimensions, and unresolved assumptions.
- Let the user change parameters and regenerate without rescanning.

### Validation and export

Show measured geometry and the proposal in different styles with a legend. Use explicit states: “Needs measurements,” “CAD checks passed,” “Ready for test print,” and “Physical fit recorded.” Do not turn these into an undifferentiated “100% accurate” badge.

Export through the native share sheet and Files. Permit prototype export after explicit acknowledgment of unresolved fit; accompany it with the unresolved dimensions. Reject invalid solids or corrupt meshes. Never automatically upload to a print service or operate a printer.

## 4 Capture implementation and contracts

Implement `CaptureProvider` with separate `ARKitCaptureProvider` and `ReplayCaptureProvider` implementations. Both emit the same serializable `CaptureFrame` contract. The processing layer must not depend on constructing fake `ARFrame` objects.

### Required per-frame data

| Field | Contract |
| --- | --- |
| Identifiers | Scan ID, segment ID, frame ID, schema version |
| Time | Monotonic capture timestamp and optional wall-clock session start; documented units |
| RGB | Original-resolution keyframe, dimensions, pixel orientation, encoding, and checksum |
| Depth | Native-resolution Float32 depth in meters, with explicit width, height, row layout, byte order, validity mask |
| Confidence | Native confidence labels and their mapping; handle absent confidence maps explicitly |
| Intrinsics | Camera intrinsics plus their source image dimensions; depth-resolution intrinsics or documented resampling transform |
| Pose | `T_world_camera`, explicit matrix layout and transform convention |
| Tracking | State/reason, world-origin/segment identity, interruption/reset events |
| Quality | Exposure information available from the SDK, blur estimate, accepted/rejected status and reasons |
| Registration | Object frame transform and any later registration revision |
| Optional motion | Timestamped acceleration, gravity, rotation rate, attitude, reference frame, and exact units |

Record a compressed RGB video for review from the ARKit image stream with AVAssetWriter, plus calibrated paired keyframes for processing. Preserve video presentation timestamps and their mapping to capture time; compressed video alone is not a sufficient scan package. If recording is interrupted, retain the committed keyframes and mark the video incomplete.

Read depth rows respecting CVPixelBuffer stride. Copy/retain frame buffers safely before asynchronous work; avoid retaining an unbounded queue of ARFrames. Keep encoding, segmentation, file I/O, and network work off the capture callback and main UI thread.

Start with configurable targets of 60–90 seconds, at most 240 accepted keyframes, and at most 512 MiB per scan. These are resource budgets to test, not accuracy claims. Select frames using pose change, view coverage, blur, and overlap, with backpressure and drop counters. Permit changing limits deliberately rather than silently truncating data.

CoreMotion logs are optional diagnostics. Store acceleration units explicitly, distinguish gravity from user acceleration, and establish the timestamp relationship before matching streams. Do not use the same inertial observations a second time as if independent of ARKit's pose estimate.

### Coordinate and scale discipline

Define `T_a_b` to map coordinates from frame b into frame a. Use one documented storage layout, such as 16 column-major numbers, consistently across Swift and Python.

- ARKit world/camera data uses meters.
- CV camera coordinates use x right, y down, z forward.
- ARKit camera coordinates use x right, y up, z backward.
- The object frame is a right-handed frame chosen for repair modeling.
- CAD and user-facing engineering dimensions use millimeters.
- CAD previews convert millimeters back to meters exactly once.

For aligned native image/depth coordinates, the conceptual unprojection is:

    p_cv = depth_m * inverse(K_depth) * [u, v, 1]
    S = diag(1, -1, -1, 1)
    p_object_m = T_object_world * T_world_camera * S * [p_cv, 1]
    p_object_mm = 1000 * xyz(p_object_m)

Verify depth semantics, pixel-center conventions, intrinsics resizing, image orientation, and viewport-to-image mapping against the installed SDK/sample. Do not apply a portrait display transform directly to raw calibration values without adjusting the corresponding coordinates.

Test known off-center pixels, known translated/rotated cameras, asymmetric geometry, and cross-language fixtures. A projection/unprojection round trip alone can conceal a consistently wrong convention.

Keep one object reference frame per registered segment. On tracking reset or uncertain relocalization, start a new segment; do not concatenate incompatible origins. Joining segments requires an explicit estimated transform, overlap evidence, and residual checks. Never assume tracking state “normal” proves old and new origins match.

### Scan package

Use a versioned folder/archive containing:

    manifest.json
    frames.jsonl
    rgb/
    depth/
    confidence/
    masks/
    motion.jsonl
    video/
    annotations.json
    derived/
    checksums.json

Record original observations separately from derived meshes and repaired geometry. Include device/OS, capture settings, algorithm versions, transformations, sources, and rejected frames. Validate filenames, hashes, dimensions, file sizes, and schema before processing. Reject path traversal, duplicate conflicting files, malformed numeric values, and archive expansion beyond a configured limit.

Save atomically and recover incomplete captures after app restart. Provide export/import of scan packages so the user's first phone run can become a regression fixture.

## 5 Reconstruction and measurement

The primary reconstruction must genuinely combine depth, RGB evidence, and camera pose.

1. Validate and normalize the capture package.
2. Reject invalid depth, poor tracking, blur, and unsuitable views.
3. Segment the selected object using Vision foreground-instance masks where available, depth-connected components, and user correction. Preserve narrow handles and contact regions when removing background. [Apple Vision foreground masks](https://developer.apple.com/documentation/vision/vngenerateforegroundinstancemaskrequest)
4. Unproject accepted depth with calibrated intrinsics and registered poses.
5. Fuse a colored point cloud and a bounded volumetric/TSDF surface using Open3D or an equivalent tested implementation. Choose resolution from object size and resource budget, not an unsupported accuracy claim. [Open3D RGB-D integration](https://www.open3d.org/docs/latest/tutorial/pipelines/rgbd_integration.html)
6. Fit planes, cylinders/frusta, axes, circles, and attachment patches with robust estimators. Report residuals, inliers, view support, and degeneracy.
7. Use RGB feature correspondences across keyframes for reprojection checks and, when supported by adequate baseline/texture, triangulated feature refinement anchored to metric poses. Reject inconsistent matches; allow explicit “insufficient texture” instead of invented refinement.
8. Preserve scale during registration and refinement. Do not permit unconstrained similarity alignment to erase a scale error in evaluation.
9. Produce measurements, observations, missing regions, and a coverage/quality report.

The initial implementation may use plane/cylinder fitting and user-selected features instead of arbitrary surface inference. It must never count a silhouette outline as a measured through-hole diameter without the required geometric support.

Keep measurements immutable and versioned. Each dimension needs:

- Value and unit.
- Source: depth fit, multiview estimate, manual measurement, symmetry, or design inference.
- Observation/frame references.
- Fit residual and repeatability information where available.
- Uncertainty estimate and its method, or an explicit “not calibrated.”
- Whether the user confirmed it and whether it is critical to fit.

Do not equate many correlated depth pixels with many independent measurements. Bootstrap views or scan segments when estimating repeatability, and account separately for scale bias and registration error. A low surface-fit residual is not proof of accurate real-world dimensions.

### Scale and fit budget

Support a user-entered known length and an optional measured marker/reference object. Record its provenance and uncertainty. If scale is corrected, preserve the original geometry and correction factor. A reference dimension used for calibration cannot also serve as the sole accuracy test.

Budget capture, registration, reference measurement, CAD discretization, and printer error separately. Use conservative additive bounds unless independence is justified. If the uncertainty exceeds a mating feature's clearance/tolerance, request a better measurement, adjust the repair strategy, or generate a fit coupon. Never display a finer reliable precision simply because a numeric field supports more decimals.

## 6 Repair reasoning and deterministic CAD

### Model boundary

The model receives selected RGB views, rendered scan views, the user's repair intent, measured features, contact patches, supported template definitions, and manufacturing constraints. Provide a compact evidence table rather than an entire point cloud as text.

The model returns a typed `RepairIntent` or an explicit need for more information. It proposes a repair; it does not become the source of measured dimensions.

A proposal includes:

- Schema version and repair-family identifier.
- Concise functional explanation and candidate differences.
- References to existing measurement/feature IDs.
- Bounded design parameters and their provenance.
- Contact frames and attachment method.
- Fit-critical dimensions that need confirmation.
- Manufacturing assumptions and unresolved questions.
- Requested supported validation operations.

Use server-side OpenAI Responses API with structured output and semantic validation. Schema conformance alone does not validate geometry. Handle refusal, truncated responses, invalid references, rate limits, timeouts, and unavailable models. [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Use `gpt-6-astra` as the initial configurable runtime model if available, with a documented supported API reasoning setting such as `high`. **Codex's Ultra build setting is separate from the application's API setting**; the current public Astra API page lists efforts through `max`. Do not send an assumed `ultra` API value. [Astra API model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra)

Keep API credentials on the server. The phone stores only its service pairing token in Keychain. A local template/manual mode and recorded AI fixtures must be clearly labeled; never present those as a successful live model call.

### Bounded proposal loop

Validate proposal → resolve measurement references → compile CAD → evaluate fit/geometry → return structured errors for at most two repair attempts. Enforce request time, token, worker memory, and operation-count limits. Preserve attempted revisions and validation results.

Treat descriptions, images, OCR text, and model output as untrusted input. The model must not execute Python, shell commands, imports, or arbitrary file paths. Use an allowlisted declarative template/operation schema and trusted generator code. The generated editable Python artifact is rendered from those trusted generators and typed parameters.

### CAD deliverables

For each accepted revision, produce:

- `part.step`: a genuine BREP solid for CAD interoperability.
- `part.stl`: a watertight printable mesh, documented as millimeters.
- `part.3mf` when the pinned exporter supports it and round-trip tests pass; include explicit units.
- `part.py` and `parameters.json`: reproducible parametric source and values.
- A lightweight triangle mesh with normals/material groups that the iPhone can render.
- `validation.json` and a readable dimension/assumption report.
- File hashes and a manifest tying outputs to the scan and intent revision.

STEP does not preserve the application's full parametric feature history; the source generator and parameters preserve editability. Validate the actual export capabilities of the pinned CadQuery version. [CadQuery interchange formats](https://cadquery.readthedocs.io/en/latest/importexport.html)

Allow edits to span, standoff, grip section, contact gaps, hole dimensions, thickness, and permitted fillets within template-specific bounds. Never silently resize a measured feature to make a CAD Boolean succeed.

### Checks before test printing

- Valid closed BREP; expected solid/component count and positive volume.
- No unintended disconnected material, nonmanifold edges, degenerate faces, or self-intersections in exported meshes.
- Reimported STEP/STL dimensions match the intended model within declared export tolerances.
- Mating features satisfy the specified dimensions and tolerances.
- Detect collisions against observed non-contact geometry, while distinguishing intended contact and unobserved space.
- Evaluate assembly direction/path for the simple supported repairs; do not equate final-pose nonintersection with assemblability.
- Check minimum wall thickness and local weak sections using template geometry plus a documented independent mesh/geometry check where applicable.
- Flag orientation/support needs against a configurable printer profile; allow user-selected nozzle, layer height, material, and build volume.
- Generate small fit coupons for hole/pin, saddle radius, and contact-gap calibration.
- Keep sensor uncertainty separate from printer/material compensation.

A game physics engine cannot establish printed-part strength. Required v1 “physics” is the geometric fit/assembly and manufacturability work above. If structural analysis is added, require material properties, print orientation, load, restraints, and a tested numerical method; label its assumptions and validate it against analytical cases. Do not ship fabricated stress colors or an unvalidated load rating.

## 7 Service and reliability

Use asynchronous jobs with durable state:

    queued → validating_input → reconstructing → needs_input
           → planning → generating_cad → validating_cad → complete
    any active state → cancelled or failed

The phone must resume by project/job ID after network loss or relaunch. Upload files with checksums and idempotent identifiers; retry only missing data. Cancellation must reach the worker. A completed status requires verified artifacts to exist, not just a successful task submission.

Provide versioned, documented APIs covering:

| Operation | Example route |
| --- | --- |
| Health and capabilities | GET /v1/health and GET /v1/capabilities |
| Create and resume scan | POST /v1/scans and GET /v1/scans/{id} |
| Idempotent asset upload | PUT /v1/scans/{id}/assets/{asset_id} |
| Commit validated upload | POST /v1/scans/{id}/commit |
| Start reconstruction | POST /v1/scans/{id}/reconstruction |
| Save annotated evidence | PUT /v1/scans/{id}/annotations |
| Create repair candidates | POST /v1/repairs |
| Regenerate a revision | POST /v1/repairs/{id}/revisions |
| Inspect/cancel jobs | GET /v1/jobs/{id} and POST /v1/jobs/{id}/cancel |
| Download verified artifacts | GET /v1/artifacts/{id} |
| Delete project data | DELETE /v1/projects/{id} |

Return structured, actionable error codes and request IDs. Validate authorization for each scan, job, and artifact; do not rely on IDs being unguessable. Bound uploads, decompression, reconstruction memory, and CAD worker execution. Keep logs free of API keys and raw captured images.

For local development, default the service to loopback. Provide an explicit LAN-serving mode with a pairing token and clear startup instructions. The phone must use the Mac's LAN address, not localhost. Prefer HTTPS; any local HTTP exception must be limited to development/local networking rather than a global release ATS bypass. Include local-network permission descriptions, user-friendly connectivity diagnostics, and simulator-versus-device URL handling.

Raw scans stay local until the user chooses the configured processing service. Explain when selected views will be sent to the reasoning provider. Support canceling upload, deleting local/server project data, and export for debugging. Do not add unrelated analytics.

## 8 Repository and deliverables

Suggested structure:

    ios/ReverseCAD.xcodeproj
    ios/ReverseCAD/
    packages/ReverseCADCore/
    backend/
    schemas/
    fixtures/
    scripts/
    tests/
    docs/
    reports/
    .env.example
    README.md

Commit or generate a deterministic Xcode project with shared schemes; include generation instructions if using XcodeGen. Check in dependency manifests/locks and never include credentials, signing secrets, captured personal footage, or large derived build folders.

Provide commands/scripts for environment checks, backend startup, fixture generation, Swift tests, backend tests, simulator UI tests, full integration tests, and a reproducible sample demonstration. A command advertised in README must actually have been run or be clearly marked device-only.

Required documentation:

- Installation and local service startup.
- Architecture, coordinate conventions, capture package schema, API, and template contracts.
- Troubleshooting for permissions, unsupported hardware, tracking, backend access, and signing.
- Test report with environment, commands, counts, durations, logs, and pass/fail/skip/block status.
- Physical-phone checklist, measurement worksheet, and fit-test workflow.
- Known limitations and clear validation status for every major capability.
- Dependencies, licenses, fixture provenance, and model configuration.

## 9 Automated validation without a physical phone

Use the same production transformations, reconstruction, jobs, and CAD generators in tests. Keep raw fixtures distinct from expected outputs, and do not allow test ground truth into the reconstruction or model inputs.

### Geometry and capture contracts

Test analytic known rays and camera poses; native versus display orientation; differing RGB/depth resolutions; row stride; meters/millimeters; transform direction; matrix serialization; mirrored shapes; missing confidence; NaN/zero/negative depth; timestamp gaps; sensor absence; resets; and independently registered scan segments.

Use independently derived expected geometry, not just a second call to the function being tested. Test cross-language fixture round trips between Swift and Python.

### Synthetic benchmark

Generate rendered RGB-D sequences and poses for:

- A metric calibration block.
- A broken two-mount handle assembly.
- A cup with missing handle/contact regions.
- A simple bracket/mating assembly.
- Asymmetric objects that reveal mirroring or axis mistakes.

Render the damaged object seen by the phone. Keep complete replacement ground truth in the evaluator only. Include multiple camera trajectories, image orientations, objects/dimensions withheld from tuning, and seeds for noise, depth bias, blur, low texture, holes, occlusion, pose drift, and partial coverage. Include fixture masks for geometric isolation and separate segmentation tests on image fixtures.

Starting software gates, adjustable only with written rationale:

| Test | Required gate |
| --- | --- |
| Analytic coordinate conversion | Known-point error no greater than 0.01 mm with suitable numeric tolerances |
| Clean synthetic reconstruction | For supported exposed features, dimension error no greater than max(0.5 mm, 1% of true length) |
| CAD dimensions after generation | Within 0.1 mm of the specified parameters |
| STEP round trip | Dimension change no greater than 0.1 mm; valid expected solids |
| STL round trip | Dimensions within the configured tessellation tolerance plus 0.1 mm; watertight expected components |
| Unsupported or insufficient input | Explicit need-for-input/failure state; no false verified-fit result |
| Offline integration | All supported families generate real, reimportable artifacts through the service |
| Job recovery | No lost committed project, duplicate revision, or success without artifacts after tested interruptions |

These thresholds are proposed software acceptance criteria, not observed sensor performance. Report dimension error, point-to-surface error on observed regions, coverage, completion/failure rate, runtime, and peak memory. Evaluate using rigid alignment only when needed; report scale error separately.

Compare raw depth/pose baseline, filtered fusion, and RGB-assisted checks on identical fixtures. Improvements may be claimed only where measured. Do not let a benchmark on generated shapes imply general real-world repair accuracy.

### Backend and AI

Test actual reconstruction and CAD workers, real filesystem artifacts, database/job recovery, upload resume, checksum failures, malformed archives, authorization, cancellation, resource limits, invalid templates, invalid measurement IDs, invalid dimensions, provider errors, and bounded retries.

Use deterministic AI responses for offline CI. Separately run a live model smoke test when a legitimate configured key is available; record provider/model and the actual artifact validation outcome. Absence of a key blocks the live-provider check only. It must not block the deterministic app/service implementation or be reported as a live pass.

### iPhone builds and Simulator

- Build the shared package and run its tests.
- Build the Simulator app and run XCTest/XCUITest through onboarding, replay capture, annotation, manual measurement, generation, parameter edit, error recovery, persistence, and export.
- Run an end-to-end Simulator test against the actual local service with recorded/synthetic input and real CAD execution.
- Inspect rendered screenshots for layout, readable dimensions, useful errors, and preview visibility.
- Build the generic iOS-device target without signing where supported to catch code excluded by simulator conditionals.
- Keep live ARKit capture code compiled in the device target. A simulator-only conditional must not hide an unfinished implementation.
- Record skipped native sensor checks explicitly. Simulator replay tests do not validate LiDAR, real camera calibration, VIO, hardware throughput, or physical fit.

Use a dedicated test simulator or otherwise preserve unrelated simulator/app data. Save test logs and result bundles. Do not claim CI ran merely because a workflow file exists.

## 10 Implementation sequence

Complete all mandatory stages; they are dependency order, not alternative stopping points.

1. Audit tools, APIs, platform capabilities, dependency compatibility, and existing files; document decisions and establish contracts.
2. Build a real vertical slice: replay package → service → measured features → supported repair intent → CAD → export → iPhone preview.
3. Implement native ARKit acquisition, video/keyframe persistence, quality guidance, permissions, and interrupted-scan recovery.
4. Complete reconstruction, segmentation correction, annotations, scale checks, uncertainty handling, and manual measurement.
5. Integrate bounded live reasoning, all three repair families, parameter editing, clearance checks, and fit coupons.
6. Complete service reliability, local pairing, exports, project persistence, and error handling.
7. Run and repair unit, benchmark, service integration, UI, Simulator, and generic device-build failures.
8. Deliver runnable code, actual test evidence, a sample project, installation steps, and the physical trial plan.

If an optional enhancement fails, keep the primary route working and document the limitation. If a mandatory capability is blocked, state the specific block and continue all independent work. Do not quietly redefine completion to mean the first successful demo.

## 11 Definition of software completion

The handoff is ready only when:

- All three supported repair workflows are implemented with actual geometry and artifacts.
- Native capture, replay, persistence, service communication, annotation, editing, and export are connected end to end.
- All feasible mandatory tests run successfully, or a concrete environmental blocker is documented without claiming a pass.
- Critical failures have been fixed, with regression coverage where appropriate.
- A fresh user can follow the verified setup instructions, open the Xcode project, start the service, and run the sample.
- Physical signing/installation steps are clearly separated from unsigned build success.
- Every delivered artifact has known units and traceable input/parameter versions.
- Final status distinguishes implemented, automatically tested, live-provider tested, phone tested, and physically fit tested.
- The user's remaining steps are installing on their phone and performing the measurement/print trial, plus any specifically identified credential or signing requirement.

The separate `PHONE_TEST_PLAN.md` defines the physical evidence needed after this software milestone.

