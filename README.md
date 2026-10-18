# ReverseCAD

`main` combines object scanning with the damage/CAD workflow in the original camera-first UI. **Scan object** and **Repair damage** use a phone reference setup, first 360° capture, automatic saved-view Jev identification, and a second detail pass with an observed-depth preview. The app is named **ReverseCAD**. Simultaneous three-camera fusion and fitted calibration remain unverified and disabled. See [the consolidated specification](docs/MAIN_CONSOLIDATED.md).


The signed TestFlight release and Apple processing/tester status are recorded in [release status](reports/reversecad-branding/VERIFICATION.md). Reproducible release commands are in [TestFlight setup](docs/TESTFLIGHT.md).

Native iPhone RGB-D capture and a local Mac processing service for a two-mount bridge handle, curved saddle cup handle, and flat/L repair bracket. The app keeps observed geometry, design assumptions, manual measurements and physical test results distinct.

The Debug-only one-camera plus sparse-range reconstruction prototype is described
in the [full implementation specification](docs/SPARSE_RECONSTRUCTION_SPEC.md),
[runnable workflow](docs/sparse-reconstruction/README.md), and
[measured validation report](reports/sparse-reconstruction/REPORT.md).

## Missing cubie exterior demo

The camera saves calibrated RGB, native depth/confidence and camera poses. Keep the object stationary and fully inside the capture guide while moving the phone. The guide bounds apply to reconstruction and uploaded visual evidence.

The current 3×3 exterior workflow tracks grayscale repeated outlines, verifies candidate face geometry across views, and transfers a same-type intact donor’s observed front contour. Corners and multiple missing locations on one supported face can produce separate closed STL/3MF pieces. Native camera poses are checked against intact depth samples; photo alignment remains a fallback. No depth inside a missing gap is required. **Original / Repair / Pieces** shows the source image, proposed front profiles, and separate solids. Review every ghost before exporting.

Side shape and depth remain inferred. Hidden connectors, fine relief, exact metric accuracy and physical fit are unresolved. Only supported faces are assessed; unobserved regions are not established damage. The shared camera and result UI selects between the paper/rectangle and 3×3 cube workflows, with a manual choice when the evidence is ambiguous. Saved-scan validation is in `reports/cube-mixed-real/validation.json`.

### Reference-shaped edge and corner prototypes

Explicitly associated same-cube scans can use image-guided CAD donors with rounded bodies, inner relief, retaining bands, a rounded edge tab, and a corner's triangular channel and recessed center. Revision 5 uses smooth traced profiles, drafted blind recess walls, and a flat-sided rounded corner neck. CAD solids and exported meshes are checked for closure; proposed pieces are checked for mutual intersection. These checks do not establish mechanical fit or exact cavity depth.

`fixtures/reference_pieces/cube_profile_v5.json` records the current estimated geometry without enabling it for arbitrary scans. For a local reference trial, copy it to `var/reference-pieces/cube.json` and explicitly populate `scan_ids` with captures of the matching physical design. Reference images and video remain local. Other cube designs need their own reviewed profiles; scaling this connector is not a general compatibility solution.

Neural reconstruction experiments are paused and excluded from the active comparison path. No dirt filter is applied. See `reports/reference-v5/validation.json` for the current CAD check and `reports/unified-ui/` for the unified screen validation.

### Optional Grok visual adviser

Currently paused in the local demo: calls are disabled in `.env`, and the `grokAdvice` view invocation is commented out. Saved-scan trials did not establish a reliable improvement. The adapter, tests, and feedback view remain available for later evaluation. The configuration below is for explicitly re-enabling experiments.

The Mac reads these server-only settings from the repository `.env` (excluded from Git):

```dotenv
XAI_API_KEY=your_xai_api_key
REVERSECAD_GROK_ENABLED=true
REVERSECAD_GROK_MODEL=grok-4.20-0309-non-reasoning
REVERSECAD_GROK_TIMEOUT=20
REVERSECAD_GROK_REASONING=low
REVERSECAD_GROK_APPLY_SELECTIONS=false
```

Obtain the key from [xAI Console](https://console.x.ai). The model is configurable; the default is [Grok 4.20 Non-Reasoning](https://docs.x.ai/developers/models/grok-4.20-0309-non-reasoning), which supports images and structured output. Grok 4.7 exceeded the 20-second budget in local trials, including with low reasoning effort. `.env.example` contains blank credentials and a disabled default. Real keys stay on the Mac and are never packaged in the iPhone app.

For completed cube scans, the adviser sees up to three supported face candidates, two guide-cropped grayscale views each (one rectified to the front plane), and numbered features. It can suggest a supported candidate and compatible donor IDs. Automatic model selections are disabled by default: a real two-piece scan showed Grok selecting an incomplete one-piece face, and the visual reviewer also produced false alarms. Set `REVERSECAD_GROK_APPLY_SELECTIONS=true` only for comparison experiments; coverage, concerns, solid and review guards still apply. The geometry engine computes placement/dimensions and validates solids. A second request reviews the original/ghost pair and may suggest a next viewpoint. This is post-scan advice; continuous live LLM guidance and general-object completion are not implemented.

Requests use structured JSON through `https://api.x.ai/v1/responses`, with `store=false`, at most two calls, bounded images/output and 2–30 second request timeouts. Invalid IDs, incompatible donors, unresolved model concerns, reduced repair coverage, a model selection rejected by its overlay review, failed solid checks, authentication errors and unavailable APIs preserve the geometry baseline. No model-generated code or dimensions are executed. Grok’s review is advisory, not a physical-fit certification; it does not remove the user’s ghost-review requirement.

To compare the exact same saved input locally (the `--live` option makes paid API calls):

```sh
PYTHONPATH=backend .venv/bin/python scripts/benchmark_grok.py \
  --scan-dir var/service/scans/SCAN_ID/capture \
  --output work/grok-comparison-01 --live
```

The output includes both sets of ghosts, closed exports when available, model status/feedback and a comparison JSON. Judge correctness against the actual missing pieces; a model response is not evidence of improved reliability.

Open **`ios/ReverseCAD.xcodeproj`**, scheme **ReverseCAD**, development team **Sivasaran Babu**, bundle **com.sivasaran.reversecad.trial**, deployment target **iOS17.0**. Signing and actual phone capture are separate from unsigned compilation.

Automated evidence is in [reports/TEST_REPORT.md](reports/TEST_REPORT.md). Synthetic/replay performance does **not** establish phone sensing accuracy, real dimensions, printed fit or strength. The [phone and print test plan](PHONE_TEST_PLAN.md) is the physical acceptance procedure.

## Set up on this Mac

Prerequisites: full Xcode selected with `xcode-select`, an iOS Simulator runtime, [uv](https://docs.astral.sh/uv/) and [XcodeGen](https://github.com/yonaskolb/XcodeGen). The Xcode project and shared scheme are included; XcodeGen regenerates them after source/resource changes.

```sh
cd /Users/pranav/Desktop/hack-harvard/reverse-cad
./scripts/bootstrap.sh
./scripts/check_environment.sh
./scripts/start_service.sh
```

The service defaults to loopback `http://127.0.0.1:8767`. It generates a private pairing token in `var/service/pairing-token` (mode0600). View that file locally and enter its contents in the app's Service settings. This is a local service token, not an OpenAI API key. Keep it private. State and scans persist in `var/service`; restarting the service does not delete them.

`uv.lock` pins Python3.11-compatible dependencies, including Open3D0.19.0, OpenCV4.11.0.86 and CadQuery2.6.1/OpenCascade7.8.1.1.post1. `bootstrap.sh` installs the lock, regenerates the raw synthetic sample, copies it into the app and generates the project. Never replace the input fixtures with expected output meshes.

Optional server configuration is documented in `.env.example`. Copy to `.env` and protect it with `chmod 600 .env` before adding secrets. The startup script parses permitted values as data; it does not execute `.env` as shell code. Live AI is optional for manual repair workflows. See [provider configuration](docs/PROVIDER.md).

## Run the Simulator workflow

Keep the service running in one terminal. In another:

```sh
./scripts/run_simulator.sh
```

This uses a dedicated **ReverseCAD Trial** simulator and does not reset unrelated simulators. In the app:

1. Open **Service**, enter the loopback URL and private pairing token, and check the connection.
2. Create a **Synthetic sample** project and load the replay. The source is labeled synthetic; Simulator never claims live LiDAR.
3. Process the scan. The app uploads original calibrated RGB/depth/poses, then downloads the real reconstruction.
4. In the single guided project screen, mark damage and surviving attachment surfaces. Add critical manual dimensions when available. Crop, scale and raw evidence controls are under disclosures.
5. Choose a supported repair type and attachment method. Request evidence-based candidates, inspect assumptions and edit bounded parameters as needed. Default dimensions are design proposals, not measured holes or verified interfaces.
6. Acknowledge unresolved fit for prototype generation/export. Generate and compare the blue scan with the orange proposed part, then review validation and unresolved measurements.
7. Export verified STEP, STL,3MF, editable source/parameters, fit coupon and reports through the native share sheet. Each new generation is a new revision. Save/reopen the project and record physical results only for the revision actually printed.

A valid BREP is allowed to remain **Needs measurements** for fit. Acknowledged prototype export does not turn it into a fit-validated part. Unresolved or unsupported attachment geometry must receive more evidence.

## Install and trial on your iPhone

1. Run `./scripts/start_service.sh --lan` on the Mac. This explicitly binds local network interfaces. Use the `.local` address printed by the script, not `localhost`. At build time this Mac advertised `48.local`; verify the current name with `scutil --get LocalHostName`. The current LAN IP can be checked with `ipconfig getifaddr en0` and may change.
2. Put the Mac and iPhone on the same reachable network. Campus/guest Wi-Fi may isolate devices even when both have internet access. Use a trusted network that permits peer access. Keep this development HTTP service off public networks; use an HTTPS reverse proxy if remote access is needed. The app enables local networking, not a global ATS security bypass.
3. Install Apple's **TestFlight** on your iPhone, accept the Reverse CAD invitation for your tester account, and install the version/build confirmed in [release status](reports/reversecad-branding/VERIFICATION.md). TestFlight does not require a cable or Developer Mode. For a separate development installation, open `ios/ReverseCAD.xcodeproj`, select your iPhone and development team, enable Developer Mode when requested, and press **Run**. An available TestFlight build does not itself verify installation on your phone.
4. Open Service settings, enter the Mac's reachable `.local` URL and pairing token, then check connection. Allow local-network access. Grant camera access when starting capture. Optional motion diagnostics have their own permission; no microphone is recorded.
5. Create a live project. The capability screen must say live LiDAR on supported hardware. Keep a matte calibration object stationary while moving the phone around it at overlapping angles/heights. Use the selection region to isolate the object; watch tracking, blur, depth, accepted frames and storage feedback.
6. Stop, reopen and process the saved scan. Confirm live RGB, native depth/confidence, timestamps and changing poses in its exported package. Do not count a preview or submitted job as a completed scan.
7. Follow [PHONE_TEST_PLAN.md](PHONE_TEST_PLAN.md): independently measure held-out dimensions, repeat scans, test negative surfaces, print coupons, then perform an actual replacement fit test. Cup trials use an empty room-temperature object.
8. Export the scan package from the app/Files for regression replay. Editable annotations are stored separately from immutable original capture observations. Keep the failing scans too.

Unsupported devices offer replay/import and limited camera/manual capture with explicit missing-depth status. They do not synthesize LiDAR. An origin reset starts a new unregistered segment; incompatible origins are never silently fused. End that capture and rescan if no verified registration is available.

## Reproduce automated validation

```sh
./scripts/test_python.sh
./scripts/test_swift.sh
./scripts/test_ios.sh
.venv/bin/python scripts/generate_fixtures.py
.venv/bin/python scripts/benchmark.py --help
.venv/bin/python scripts/trial_cli.py
```

The native UI tests and HTTP integration command need the running service on port8767. The HTTP command uploads raw fixtures, runs actual isolated reconstruction/CAD jobs for all three families, downloads and hashes outputs, and independently reimports STEP/STL. Its default is manual mode; it is not a live AI test. Test output directories contain explicitly labeled synthetic input.

Native test/build commands and result bundles are listed in [TEST_REPORT.md](reports/TEST_REPORT.md) and the iOS test script. UI tests connect to the real local service and use the private local token at runtime. A skipped test is not a pass.

## Artifacts and architecture

- `ios/ReverseCAD`: SwiftUI app, ARKit/RealityKit live view, Vision foreground masks, AVAssetWriter review video, optional CoreMotion diagnostics, native Files/share export and Keychain pairing.
- `packages/ReverseCADCore`: shared capture DTOs, geometry, package persistence/recovery, replay and API transport.
- `backend/reversecad`: FastAPI, SQLite durable jobs, bounded worker processes, Open3D/OpenCV reconstruction, declarative reasoning and deterministic CadQuery generators.
- `schemas`: versioned machine-readable capture/intent contracts.
- `fixtures`: independently rendered RGB-D/poses and separate evaluator oracles. Only raw samples are bundled.
- `docs`: [requirements/status audit](docs/REQUIREMENTS_STATUS.md), [integration contracts](docs/INTEGRATION_CONTRACT.md), [reconstruction](docs/RECONSTRUCTION.md), [CAD](docs/CAD.md), [fixtures](docs/FIXTURES.md), [provider](docs/PROVIDER.md), [dependency provenance](docs/DEPENDENCIES.md).

Coordinates use column-major `T_a_b` mapping b→a, ARKit meters and engineering millimeters. Native ARKit depth uses Apple's direct calibration scale; resized synthetic images explicitly use a pixel-center mapping. Preview conversion is mm→m exactly once. Native measurements are kept separate from RGB triangulation/TSDF display refinement. An explicit scale reference preserves original observations and correction provenance. Contact/crop annotations refer to the current corrected object frame; changing scale needs review.

Every accepted CAD revision includes genuine STEP, watertight STL, tested millimeter3MF, `part.py`, `generator.py`, `parameters.json`, preview mesh, validation/report files, coupons, hashes and input/revision provenance. STEP alone does not preserve parametric editability; run the provided source in the pinned environment. No generated model code is executed. No arbitrary freeform repair, structural FEA, load rating, automatic printer operation or food/hot-liquid certification is claimed.

## Troubleshooting

- **Unauthorized:** copy the service pairing token into the app; never enter an OpenAI key there.
- **Cannot connect on phone:** check the printed Mac address, same-network reachability, local-network permission and Mac firewall. Simulator loopback success is not phone network evidence.
- **Needs measurements:** inspect missing critical dimensions/contact geometry. Enter caliper/ruler values with uncertainty or capture more suitable views. Do not infer hole diameter from a silhouette.
- **Interrupted capture:** reopen the project; committed frames are recovered and incomplete video is labeled. Preserve the scan before retrying. Unregistered reset segments need new evidence.
- **Failed/cancelled job:** saved raw data remains. Resume missing uploads or start/retry processing; explicit cancel reaches the subprocess. A terminal result must still have intact artifacts.
- **Provider missing/unavailable:** use manual mode. Configure a server key and explicitly consent before live image reasoning; provider failures do not become simulated success.
- **Invalid geometry:** fix the reported bounded parameter/attachment conflict. No automatic resizing of a confirmed measurement is allowed.

See [reconstruction options and VideoCAD assessment](docs/RECONSTRUCTION_OPTIONS.md) for the next pipeline stage.
