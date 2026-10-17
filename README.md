# Reverse CAD

The signed TestFlight release and Apple processing/tester status are recorded in [release status](reports/testflight/STATUS.md). Reproducible release commands are in [TestFlight setup](docs/TESTFLIGHT.md).

Native iPhone RGB-D capture and a local Mac processing service for a two-mount bridge handle, curved saddle cup handle, and flat/L repair bracket. The app keeps observed geometry, design assumptions, manual measurements and physical test results distinct.

## Missing cubie exterior demo

The app opens as a camera. On a LiDAR device, tap **Start 3D scan**, keep the object stationary and centered, and move the phone around it at overlapping angles and heights. Tap to finish. The phone saves calibrated original-resolution RGB, native depth/confidence and camera poses; the paired Mac fuses accepted views with Open3D TSDF. The result is a rotatable observed surface, with full integrated mesh exports in millimeters (`observed_surface.stl`, `observed_surface_mm.ply`) and a quality/provenance report. Only the display mesh is simplified. This produces an observed mesh, not completed missing geometry or editable parametric CAD. Hold the object still: turning it in your hand is not supported by world-pose fusion.

Fine detail uses an experimental calibrated OpenCV stereo pass on original camera photos (up to 1280 px): rectification, bidirectional matching, local subpixel photometric alignment, texture/appearance checks and native-depth agreement. Where supported photo detail exists, it replaces coarse pixels only in the derived surface integration; the native measurement evidence stays unchanged. Weak matches fall back to LiDAR. `photo_detail.json` records accepted pairs and support. Minute-feature accuracy remains uncalibrated; a textured synthetic 2 mm step is a regression check, not a phone accuracy claim. No new dependency is required.

For a mostly solved Rubik’s cube with one missing edge, reconstruction also tries to find a clear face grid, fit its metric plane, select an intact edge with both exterior faces observed, and rotate that actual scanned surface into the gap. **Preview missing edge** shows the inferred patch in orange; export includes `counterpart_surface.stl` and `counterpart.json` when supported. This preserves observed donor details rather than substituting a box. It assumes matching edge exteriors and needs user review. The patch is open: hidden connectors, watertight printable replacements and parametric CAD fitting remain unfinished. The camera framing box is a positioning guide; foreground selection and depth masks determine geometry inclusion.

The photo-library button retains the separate **photo prototype** path: automatic detection of a mostly same-colored 3×3 face with one missing edge. Multiple missing pieces and scrambled faces are not supported yet.

Enter only the independently measured width of the full cube face. The app estimates visible outline spacing from consistent intact pieces; when that cannot be resolved it uses a labeled cube prior. Three-dimensional rounding remains a labeled prior. These estimates are not mechanical fit tolerances. The Mac makes an exterior-envelope STEP solid, STL mesh, editable CadQuery source and dimension record. **The photo does not establish millimeter scale or hidden locking geometry. This first model is an exterior prototype, not a fitted working cubie.** The cube analysis is deterministic computer vision; it does not call a model provider. The app renders the exported STL and shares five files, including a replayable `repair_plan.json` with detection provenance and per-operation CAD checks.

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
3. Install Apple's **TestFlight** on your iPhone, accept the Reverse CAD invitation for your tester account, and install the version/build confirmed in [release status](reports/testflight/STATUS.md). TestFlight does not require a cable or Developer Mode. For a separate development installation, open `ios/ReverseCAD.xcodeproj`, select your iPhone and development team, enable Developer Mode when requested, and press **Run**. An available TestFlight build does not itself verify installation on your phone.
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
