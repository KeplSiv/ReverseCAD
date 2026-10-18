# Prelude standalone scan update

Prelude's `PreludeScanner` target starts with an object description, automatically calls Jev through the paired companion approximately every 200 ms, and displays fresh category/box results over the moving camera preview. Tap **Scan outlined object** to confirm the current target. The app tracks/segments the selected object, saves the capture, and opens the observed 3D preview, measurements and exports. It does not continue into repair generation.

TestFlight uses public ARKit processed scene depth and the physical rear wide camera. It contains no private sparse capture sources. The separate sparse Debug target and its archive/distribution guards remain intact. The code and specification are published only to `pranav-dev`; no merge into `main` is part of this release.

## Continuous Jev detection

The live loop replaces the earlier tap-to-identify/frozen-image Jev flow. It targets 200 ms between new JPEG requests, permits four in flight, drops opportunities under backpressure and never queues stale frames. It continues during capture, pauses in the background, and stops on close, finish or manual selection. Resuming waits for a new camera frame. Manual box selection remains available and uses a frozen local image.

Results are bound to the request UUID and JPEG hash. Out-of-order, expired (>1.2 seconds), absent, ambiguous and pose-stale detections cannot confirm a scan. Boxes disappear if camera translation exceeds 2.5 cm or any camera-axis cosine drops below 0.995 relative to the source frame. The overlay uses the AR frame's display transform. Confirmation saves the source JPEG, frame timestamp, response and box. Later Jev overlays do not switch the measurement tracker to a different object.

Failures back off for 2, 4, then 8 seconds. Client requests time out after 3 seconds, and the companion's upstream socket timeout is 2.5 seconds. Actual displayed update rate depends on network latency, model latency, camera motion and available frames; 200 ms is a dispatch target, not a guaranteed inference latency.

## Verification

- All 23 shared Swift tests passed, including five new tests covering cadence, bounded concurrency, no catch-up bursts, reply ordering, expiry, stop/restart, timeout handling and failure recovery.
- The existing provider absent/ambiguous/invalid-target test passed.
- The authenticated companion was exercised with 12 real Jev calls dispatched at 200 ms intervals on a synthetic calibration image. All returned a category and box from `jev-1.14.0`. Median response latency was 185.8 ms, with a range of 137.6–839.1 ms. See `jev-cadence-check.json`.
- After the companion restart, an authenticated live Jev check returned HTTP 200 and a confirmable box in 253.6 ms. See `jev-service-restart-check.json`.
- The Release simulator build passed. The running live-camera interface was inspected: the Scan outlined object action and continuous detection status replace Identify and frozen-image confirmation. Closing returned to the home screen. The simulator has no camera/LiDAR, so this is a UI check, not a live sensor check.
- Prelude 0.1.0 (28) passed signed archive, export and IPA verification for bundle `com.pranavmuralitharan.prelude`, team `5B3Y68ZB2Y`, distribution signing and exclusion of the private sensor symbols.
- Verified IPA SHA-256: `8c4dede932c6d37177202d52cfd3aa63432e4e194b6f155a6ca5efc69f053cd3`.
- Apple accepted all 1,773,101 verified IPA bytes, upload ID `b64253bd-12a0-4b0b-bd3f-7696d68195c1`. Apple processing completed with `VALID`; the build is `IN_BETA_TESTING` and is present in the Prelude Personal internal group, which includes the existing tester. See `release-status.json`. The account-level tester state is `INSTALLED`, which does not prove this particular build is installed on the phone.

The earlier export verification remains applicable to the unchanged reconstruction/export code: five standalone backend tests and 21 existing service tests passed. Public RGB-D and sparse synthetic fixtures exercise standalone exports and asset hashes. Large/noisy public meshes retain their full STL if a bounded STEP approximation fails its deviation gate. STEP is a faceted observed surface, not a reconstructed parametric feature tree.

## Release history

Build 26 was the earlier one-shot identification release, verified in internal TestFlight. Build 27 compiled but its archive stopped at signing with `errSecInternalComponent`; it was never uploaded. The existing signing keychain was unlocked using its preconfigured private credential file, and the failed directory was preserved. Build 28 is the continuous Jev update.

## Physical checks and companion dependency

The API fixtures are synthetic, not a new moving-camera phone capture. Phone-to-provider cadence, live overlay alignment under real motion, dimensional accuracy and physical fit remain unverified. This prototype is ready for those checks.

The paired Mac service must remain reachable on port 8769 for Jev identification and reconstruction. The Jev key is loaded from the user's private key file and is not embedded in the app, returned to the phone or committed to Git. The original phone recordings were not intentionally modified; preservation evidence remains under `reports/sparse-reconstruction/phone-recording-preservation.json`.
