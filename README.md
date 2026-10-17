# Reverse CAD

The signed TestFlight release and Apple processing/tester status are recorded in [release status](reports/testflight/STATUS.md). Reproducible release commands are in [TestFlight setup](docs/TESTFLIGHT.md).

Native iPhone RGB-D capture and a local Mac processing service for a two-mount bridge handle, curved saddle cup handle, and flat/L repair bracket. The app keeps observed geometry, design assumptions, manual measurements and physical test results distinct.

Open **`ios/ReverseCAD.xcodeproj`**, scheme **ReverseCAD**, bundle **com.pranav.ReverseCAD**, deployment target **iOS17.0**. The tested build host is Apple silicon, macOS26.6.2, Xcode26.6 with the iOS26.5 SDK/runtime. Signing and an actual LiDAR iPhone are separate from unsigned compilation.

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
4. Review the object. Select damage/contact points, correct the crop, review scale and enter critical manual dimensions in **Evidence**. Save evidence; reprocess after crop/scale changes.
5. In **Design**, select a supported family and attachment method. Request evidence-based candidates when available, inspect assumptions and choose/edit bounded parameters. Default dimensions are design proposals, not measured holes or verified interfaces.
6. Acknowledge unresolved fit for prototype generation/export. Generate and inspect **Results**, the scan/part comparison, validity, missing dimensions, collisions, assembly and printer checks.
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
