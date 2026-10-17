# Reverse CAD software validation

Execution date: October 16, 2026. All commands below ran from `/Users/pranav/Desktop/hack-harvard/reverse-cad`. Final automated software checks passed. This report separates that evidence from device sensing, measurement accuracy and printed fit.

## Host and setup

Apple silicon arm64, macOS26.6.2 (25G83), Xcode26.6 (17F113), iOS26.5 SDK/runtime, XcodeGen2.46.0 and uv-managed CPython3.11.16. `uv.lock` pins all Python dependencies; `.python-version` and bootstrap pin the interpreter. The dedicated Simulator is **ReverseCAD Trial**, UDID `0576C00C-3357-433C-843C-622AD6AB2169`, iPhone17Pro. Unrelated simulators were not reset.

- `./scripts/bootstrap.sh`: **PASS**. Frozen dependencies, independently generated raw replay sample, Xcode project and seven production schemas. [Log](bootstrap.log).
- `./scripts/check_environment.sh`: **PASS**. Actual host/tool/dependency versions. [Log](environment.log).
- `./scripts/start_service.sh`: **PASS**. Real authenticated service, persistent SQLite state and private mode0600 pairing token. The token is deliberately absent from this report.
- `./scripts/start_service.sh --lan --port 8776 --data-dir var/lan-smoke` plus `curl --fail http://48.local:8776/v1/health`: **PASS on this Mac**. The temporary LAN smoke service was stopped. This does not demonstrate an iPhone connection.
- Final default port is **8767**: unrelated services already occupied 8765/8766. `REVERSECAD_DATA_DIR=var/unused-config ./scripts/start_service.sh --lan --data-dir var/service` and `curl --fail http://48.local:8767/v1/health` **passed**, verifying LAN binding, `.local` resolution and explicit data-directory precedence. The final service preserves the existing `var/service` data/token. [Startup log](service-lan-final.log). Other services were left running.

## Completed automated tests

| Command / suite | Observed result | Retained evidence |
| --- | --- | --- |
| `./scripts/test_python.sh` | **167 passed**, zero failures/skips; 16 dependency deprecation warnings; 126.95s | [Final log](python-final-tests.log), [JUnit](python-junit.xml) |
| `./scripts/test_swift.sh` | **15 passed**, zero failures; 0.055s test execution in the final rerun | [Log](swift-tests.log) |
| `./scripts/test_ios.sh`: native XCTest | **17 passed**, zero failures/skips; 0.661s test execution | [Final native log](ios-tests-20261016-164003.log), [result bundle](ios-tests-20261016-164003.xcresult) |
| Same command: actual-service XCUITest | **2 passed**, zero failures/skips; 139.445s test execution | Same result bundle; complete test operation took 148.415s |
| `.venv/bin/python scripts/benchmark.py` | **33/33 clean stage gates**, 90 total runs over 30 raw packages; zero process/evaluation failures | [Summary](benchmark/summary.md), [Data](benchmark/benchmark.json), per-run logs |
| `.venv/bin/python scripts/trial_cli.py` | Actual authenticated upload → reconstruction → manual intent → CAD → artifact download → STEP/STL reimport for all three families | [HTTP summary](http-integration/summary.json) |
| Matching cup and bracket raw-fixture HTTP trials | Each downloaded and hashed 16 artifacts; STEP valid, one solid; STL watertight | [Cup](http-cup/summary.json), [Bracket](http-bracket/summary.json) |
| Final bridge HTTP trial through port8767 | **PASS**, 16 verified artifacts and independent STEP/STL reimport | [Final bridge](http-final-bridge/summary.json) |

The Python suite includes independent rays/transforms/units, capture validation, reconstruction/segmentation, primitive fitting, candidates, all CAD families, parameter limits, provenance, round trips, contacts/collision/assembly/thickness, API authorization/path/corruption handling, resumable uploads, idempotency, real worker subprocesses, cancellation, restart and memory/time failures. Only external provider responses are mocked in adapter tests. The final aggregate includes the fastener-interface, multiview-provenance and rotated-contact STL regressions.

Shared Swift tests cover asymmetric transforms, intrinsics/depth scaling, meters/millimeters, serialization, package hashes, symlinks, recovery, replay and processing checkpoints. Native tests include six capture tests (padded CVPixelBuffers, actual AVAssetWriter review movie/timestamps and portable ZIP), four observed-patch normal tests and seven immutable-artifact tests (tampering, missing files and failed downloads preserving a prior revision).

The benchmark uses separate analytic oracles, held-out scene dimensions and trajectories, identical raw input bytes across stages, and no post hoc scale/alignment fit. The clean bound is `abs(error) <= max(0.5 mm, 1% of reference length)` per axis and the fitted cup radius. Maximum clean axis error was **0.005814mm**, fitted primitive error **0.029302mm**, and peak process RSS **918.08MiB**. These tiny synthetic errors reflect ideal analytic input, not phone accuracy. Filtered/RGB clean surface RMS was worse than the raw ideal baseline; the report preserves this counterevidence. Degraded inputs retain measured errors and explicit needs-input/rejection outcomes. The final `.venv/bin/python scripts/benchmark.py --resume` verification matched the source/input hashes for all 90 retained production runs and reevaluated their outputs; it did not pretend to execute 90 new worker runs. [Verification log](benchmark-final-verification.log).

## Native workflow and builds

The first native test build caught a Core/app upload signature mismatch. Shared persistence tests caught macOS temporary-path symlink normalization. Both were fixed. Earlier UI runs also identified an error alert dismissing Service settings, UI test queries/scrolling that missed native elements, and jagged preview-triangle normals making planar contact selections disagree. Those fixes now preserve the Settings context, fit normals over bounded observed patches and expose normal review. Sparse/corner contact patches are rejected; damage/fragment marks can still identify edges.

The full native path exposed a further export defect under the selected contact rotation: binary STL float32 rounding created a tiny intersection between two originally coplanar triangles, while STEP and 3MF remained valid. Generator1.0.1 writes standard ASCII STL with 17 significant digits from the unchanged original tessellation, including coupons and editable regeneration. The exact failing input is retained in `fixtures/cad/rotated-contact-precision.json`; its targeted regression passed with all formats valid and zero intersections. No measurement, placement or independent check was weakened. Both the final Python aggregate and full native workflow passed after this fix. Earlier failed logs are retained and are not counted as passes.

The complete native workflow passed against the actual paired service: raw replay import and scan ZIP share; upload/cancel/retry; reconstruction; two observed contact picks; manual critical dimension; two evidence-linked candidates and selection; real CAD generation; 16-document native share; terminate/relaunch; standoff edit from 30 to34mm and revision2; a saved/reopened synthetic trial note while fit stays **Not tested** and print iterations stay zero. The separate connection test deliberately used an unreachable port, handled the error, corrected the URL and reconnected. These flows used no mocked reconstruction/CAD server.

The final result bundle is `reports/ios-tests-20261016-164003.xcresult`. Nine actual screenshots were exported with `xcrun xcresulttool export attachments --path reports/ios-tests-20261016-164003.xcresult --output-path reports/screenshots`. The observed contacts, candidate cards, blue scan/orange part comparison at revisions1/2, native share and persisted notes were visually inspected and found readable. [Screenshot index](screenshots/README.md). Only the latest picked marker is drawn; all saved contacts can be reviewed and corrected in the contact list. CAD validity is visibly distinct from the unresolved fit status.

The actual Simulator's saved revision1/2 STEP and STL downloads were independently reimported after the UI run; both had valid one-solid STEP and watertight STL. Every one of the current revision's 16 files matched its recorded hash and byte count. [Native download verification](ui-integration-summary.json).

`./scripts/run_simulator.sh` **passed** after the final tests: build, installation, launch and opening the dedicated Simulator. [Launch log](simulator-launch.log), [build log](simulator-launch-build.log). The app is left installed and open.

The latest generic device command also **passed**:

```sh
xcodebuild -project ios/ReverseCAD.xcodeproj -scheme ReverseCAD \
  -configuration Debug -destination generic/platform=iOS \
  -derivedDataPath var/DeviceDerivedData CODE_SIGNING_ALLOWED=NO build
```

[Unsigned device build log](ios-device-final-build.log). This compiles the live ARKit code; it does not sign/install or exercise phone sensors. Remaining build warnings concern a SwiftUI localization interpolation and unused App Intents metadata extraction, not build failures. Final source hashes and dependency versions are recorded in [build-manifest.json](build-manifest.json), reproducible with `.venv/bin/python scripts/record_build_manifest.py`.

## Separate validation gates

| Gate | Status |
| --- | --- |
| Deterministic reconstruction, candidate planning, CAD and authenticated service | **PASS automated** within the documented bounded families |
| OpenAI Responses adapter schema/semantics/retry/failure handling | **PASS mocked provider boundary** |
| Live OpenAI model response driving validated CAD | **BLOCKED**: no legitimately configured server API key was available; no live call was made |
| Signed app installation on an actual iPhone | **NOT RUN**: development team/device signing is user-specific |
| Real synchronized iPhone RGB/depth/pose, permissions, thermals and phone-to-Mac network | **NOT RUN** |
| Held-out real dimensions, repeatability and uncertainty calibration | **NOT RUN** |
| Printed coupon, installed replacement fit, adhesive/fastener function or strength | **NOT RUN** |

Fixture mode is deterministic test intent, not a recorded successful live-provider response. All automated CAD results retain `physical_fit=not_tested`. Acknowledged prototype export leaves unresolved measurements unresolved. Unsupported stubs, arbitrary freeform repairs and geometry outside the documented templates request more evidence rather than being silently substituted.

Follow [README](../README.md) for setup/signing, [requirements mapping](../docs/REQUIREMENTS_STATUS.md) for scope and [PHONE_TEST_PLAN](../PHONE_TEST_PLAN.md) for the physical acceptance procedure. After configuring a server key, the explicit optional live smoke command is `.venv/bin/python scripts/trial_cli.py --live --family bridge_handle --output reports/live-provider`; it sends selected synthetic evidence to OpenAI.
