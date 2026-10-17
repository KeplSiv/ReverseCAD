# Reverse CAD complete build prompt

Before sending this prompt, select **GPT-6 Astra** and **Ultra** in Codex. Those are the coding agent's settings; the application's runtime API configuration is separate. Run in `/Users/pranav/Desktop/hack-harvard/reverse-cad`. The specification and phone test plan in this directory are part of the prompt.

---

Build Reverse CAD from beginning to end as a working native iPhone application and its companion processing service. Implement it, run all tests possible without a physical phone, fix failures, and leave me ready to install it on my iPhone and conduct a real scan and 3D-print fit test. Do not stop at a plan, scaffold, mock UI, or prerecorded demo.

First read these files completely:

- `/Users/pranav/Desktop/hack-harvard/reverse-cad/REVERSE_CAD_SPEC.md`
- `/Users/pranav/Desktop/hack-harvard/reverse-cad/PHONE_TEST_PLAN.md`
- `/Users/pranav/Desktop/hack-harvard/reverse-cad/research/SOURCES.md`

Treat the specification's mandatory requirements as the implementation contract. Preserve this product goal throughout: I move an iPhone around a broken object, such as a handle or cup. The phone captures LiDAR depth, RGB video, and camera pose derived from visual and inertial sensors. The system measures the surviving object, understands the repair I want, infers a plausible replacement, constructs editable CAD, validates it, and exports files I can print. Physical accuracy is established through tests, not asserted by the model.

Work autonomously through ordinary implementation decisions. Inspect applicable repository instructions and existing files before changing anything. Keep a brief working plan and an evidence-based progress report. Resolve routine issues yourself and keep progressing on independent work when a credential, signing step, or physical device is unavailable.

## Build the complete system

Use Swift/SwiftUI with ARKit, RealityKit, Vision, CoreMotion, and AVFoundation for the phone. Use a tested Python/FastAPI service with Open3D/OpenCV/NumPy for reconstruction and CadQuery/OpenCascade for CAD. Run the service on this Mac for the first trial. Pin compatible versions and verify them on the actual host. Prefer this architecture; change a component only for a concrete compatibility or implementation reason and document that decision.

Inspect the actual Xcode installation, SDKs, simulators, and Python dependency compatibility. Use current primary documentation and installed SDK declarations to resolve uncertain APIs. The spec's environment observations are a starting point, not permission to assume dependencies work.

Implement all three required repair families: a two-mount bridge handle, a cup handle with selected curved contact pads, and a simple flat/L-shaped repair bracket. Support varying dimensions and attachment constraints, not only one hand-picked example. Unknown shapes or unresolved contact geometry must produce an honest request for more evidence.

Build the full user flow: project creation, capability detection, permissions, guided capture, saved scans, object cropping, damage/contact annotations, scale review, manual critical dimensions, repair candidates, parameter editing, scan/part comparison, geometric validation, native export, and recorded physical-test feedback.

The result must include the Xcode project and shared schemes, companion service, configuration examples without secrets, versioned schemas, replay fixtures, tests, startup scripts, and practical documentation.

## Use the sensors correctly

Use one ARKit world-tracking session for synchronized captured RGB, native scene depth/confidence, calibrated intrinsics, timestamps, tracking state, and camera transforms. Use ARKit visual-inertial odometry for phone pose. Do not estimate position by double-integrating accelerometer samples or count the same inertial information twice.

Record a compressed review video from the ARKit stream, and persist calibrated paired keyframes separately. Optional CoreMotion logs provide diagnostics with explicit units and timestamp alignment. Keep the object stationary while the phone moves.

Implement a serializable CaptureFrame contract shared by real acquisition and replay. Retain/copy image buffers safely, respect row stride and orientation, keep processing off capture/UI threads, and bound memory, recording size, and queued work. Recover incomplete captures.

Explicitly test camera/world/object transforms, column-major serialization, image/depth resolution mapping, meter-to-millimeter conversion, and preview conversion back to meters. Start a new segment after uncertain origin resets; register segments before merging them.

Runtime-check LiDAR and AR support. On unsupported devices, offer sample replay/import and clearly labeled limited camera/manual workflows. Simulator must never pretend to provide live LiDAR.

## Measure first and infer missing geometry explicitly

Implement actual confidence-filtered RGB-D fusion with ARKit poses, foreground/background separation with user correction, robust primitive/attachment fitting, and RGB multiview consistency checks. Use metric evidence to retain scale. Depth upsampling and small voxels must not be presented as increased sensor accuracy.

For each important dimension retain value, unit, source observation or manual entry, uncertainty status, and confirmation state. Keep measured features separate from symmetry assumptions and invented design dimensions. Add scale-reference input and fit coupons. Ask for caliper/ruler measurements when scan quality cannot resolve a critical feature.

A missing part is inferred from surviving interfaces, fragments or symmetry where available, functional intent, and manufacturing limits. An LLM must not invent an observed hole diameter or silently replace the attachment method.

Keep dense photogrammetry, general freeform reconstruction, custom neural-model training, and structural FEA optional until the complete required route works. If a photogrammetry route is included, verify supported APIs and explicitly register its output to the metric scan.

## Make AI and CAD real and bounded

Implement a server-side OpenAI Responses adapter with images and structured RepairIntent output. Keep the runtime model and supported reasoning effort configurable; use gpt-6-astra if available. Do not assume Codex's Ultra setting is a valid API reasoning value.

Use a legitimately configured API key through the available credential workflow, and never put it in the phone app, source, logs, or examples. If no key is available, finish the entire deterministic workflow and adapter tests using clearly labeled fixtures; identify the live-provider smoke test as blocked rather than claiming it passed.

The model selects supported repair types, references measured features, proposes bounded parameters, and requests missing information. Validate the schema and the semantics, then compile the intent through trusted deterministic CAD generators. Do not execute arbitrary model-generated Python or shell commands. Bound retries, time, memory, and operation counts.

Produce genuine STEP solids, watertight STL, tested 3MF where supported, editable CadQuery source, parameter JSON, a phone-renderable mesh, and a validation report. Export the replacement part with traceable units and revision identifiers. STEP alone is not the complete parametric source.

Check solids, mesh topology, dimensions, expected component count, collisions, intentional contacts, simple assembly paths, thickness, print constraints, and round-trip exports. Preserve the measured geometry rather than silently adjusting it to make a Boolean operation succeed. Do not substitute a game-physics animation for structural validation or fabricate a strength score.

## Test the production path without a phone

Design testability into the implementation immediately, but keep real device code complete and compiled.

1. Create independently specified synthetic RGB-D/pose sequences with known metric geometry. Include broken handle, cup, bracket, calibration block, and asymmetric scenes. Keep evaluation ground truth out of reconstruction/model inputs.
2. Test clean and degraded inputs: noise, depth bias, occlusion, blur, low texture, missing depth, timestamp gaps, pose drift, origin resets, mismatched image sizes, and incomplete scans.
3. Run Swift geometry/state/persistence tests and Python reconstruction/CAD/API tests.
4. Run a real integration test from scan-package upload through reconstruction, intent, CAD workers, validation, artifact download, and reimport. Only the external model response may be replaced by a fixture in the offline suite.
5. Build and run the app in Simulator. Use replay through the same CaptureFrame path and connect it to the real local service. Exercise annotation, manual measurements, generation, editing, save/reopen, network failures, retry/cancel, and native export.
6. Inspect actual Simulator screenshots and fix broken or confusing layouts.
7. Build the generic iOS device target without signing where possible, so live ARKit code is compiled even though hardware is absent.
8. Run a live reasoning smoke test if credentials are available, with a real model response driving a validated CAD result.
9. Reimport generated STEP/STL files and verify units, dimensions, validity, and expected solids/components.
10. Save commands, logs, result bundles, benchmark metrics, and exact pass/fail/skip/block status. Fix relevant failures and rerun the affected checks.

Follow the specification's quantitative software gates. Include held-out shapes/dimensions and an independently derived geometry oracle, not only tests that repeat the implementation. Compare reconstruction stages on the same fixtures. Never label synthetic performance as real iPhone accuracy.

Test uploads, corruption, authorization, path validation, persistent jobs, cancellation, service restart, and bounded worker failures. A job succeeds only when its verified outputs exist. Keep the UI responsive and preserve completed scan data during failures.

## Finish with a phone-ready handoff

Provide verified startup instructions for the Mac service and Simulator. Include local pairing/network settings; a physical phone must use the Mac's reachable address, not localhost. Handle local-network permissions and development transport correctly without a global release security bypass.

Provide the exact Xcode scheme, bundle ID, supported deployment target, and installation/signing steps. Do not claim a signed device installation merely because an unsigned build passed. Do not reset unrelated simulators or change unrelated projects.

Update PHONE_TEST_PLAN.md to match the implementation. Include a calibration object, independently measured reference dimensions, repeat scans, uncertainty checks, negative scans, print coupons, and a real replacement fit test. Make scan export easy so my first phone trial can become a replay regression case.

Your final response must state:

- What was implemented and where to open it.
- Which real commands/tests ran and their results.
- What evidence demonstrates the end-to-end workflow.
- Any mandatory feature still incomplete or blocked.
- Whether the live AI provider was actually tested.
- Exact steps I must take to run the app on my phone.
- What remains unverified until I scan and print a real object.

Continue until the complete mandatory workflow and all feasible validation are done. Do not stop after the first vertical slice. Do not call the result fully validated if phone sensing, real dimensions, or printed fit have not been tested. The intended handoff is working software with honest automated evidence, ready for my physical trial.

