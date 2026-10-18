# Prelude standalone scan update

Prelude's `PreludeScanner` target starts with an object description, automatically calls Jev through the paired companion approximately every 200 ms, and displays fresh category/box results over the moving camera preview. Tap Scan to confirm the current target. The app tracks/segments the selected object, saves the capture, and opens only the observed 3D preview and exports. It does not continue into repair generation.

The TestFlight target uses public ARKit processed scene depth and a physical rear wide camera. It contains no private sparse capture sources. The separate sparse Debug target and its archive/distribution guards remain intact.

## Validation

- Release simulator build passed; the actual running home screen was inspected.
- The final signed Prelude 0.1.0 (26) archive, export and IPA checks passed with bundle `com.pranavmuralitharan.prelude` and team `5B3Y68ZB2Y`.
- The final IPA SHA-256 is `ecedea28575da5e45e69bc1a8f7972e36e8145f87ee067320bc6fe0a3098955a`.
- Apple accepted upload `8be2427a-f0d6-42c4-b923-2a680e9b1807`, completed processing (`VALID`), and reports the build as `IN_BETA_TESTING` for the existing Prelude Personal internal group.
- Offline tests cover absent/ambiguous Jev results, invalid probabilities and boxes, millimetre STEP roundtrip, preservation of an open surface, insufficient-reconstruction export gating, authenticated service delivery and exported-asset hashes.
- Both public RGB-D and sparse synthetic fixtures are exercised through the standalone service boundary. Large/noisy public meshes retain their full STL when a bounded STEP approximation fails its deviation gate; that is an explicit per-format limitation.

The final update adds manual box selection so scanning remains usable before Jev credentials are configured. Final build 26 supersedes the unuploaded build 25. The final release result is recorded in `release-status.json`.

Backend verification: 5 standalone tests passed, including both service/export fixtures. The 21 existing service tests also passed.

## Outstanding physical/provider checks

A live Jev request succeeded using the private key file supplied by the user. The provider returned `jev-1.14.0` through the `jev-preview` alias, classified the synthetic fixture as one container, and returned a confirmable bounding box. The fixture was enlarged from 320×240 to 640×480 to satisfy the provider minimum dimensions; this is an API integration check, not physical validation. No new moving-camera phone capture, dimensional check or physical fit test is claimed. This release is a prototype for those checks.

The paired service is running on the Mac at port 8769 with the existing private pairing token. It must remain reachable for identification and reconstruction. The phone's original recorded sessions were not intentionally modified; the detailed inventory report is under `reports/sparse-reconstruction/phone-recording-preservation.json`.

Apple upload and internal availability are recorded in `release-status.json`. Build 26 is present in the Prelude Personal internal group's build list, and the group contains the existing tester. The tester's account state is `INSTALLED`; that account-level state does not prove build 26 is installed on the phone. The update is available through TestFlight, and installation of this specific build remains unverified.

The same live Jev request also succeeded through the authenticated companion endpoint (HTTP 200), with the key loaded from the configured private file. The environment-parser regression check passed.

## Live detection correction — build 28

The user's revised requirement replaces the tap-to-identify/frozen-image flow with continuous camera checks. The loop targets 200 ms between new JPEG requests, permits four in flight, drops opportunities under backpressure and does not queue stale images. It continues during capture, pauses in the background, and stops on close, finish or manual selection. Results carry a request ID and image hash; out-of-order, expired (>1.2 seconds), ambiguous and pose-stale boxes cannot confirm a scan. The overlay uses the AR frame's display transform. Confirmation preserves the actual detection image and does not let later overlays switch the measurement target.

The authenticated companion was tested with 12 real Jev calls spaced 200 ms apart on the synthetic calibration image. All returned a category and box. Median response latency was 185.8 ms; range 137.6–839.1 ms. This is a server integration test, not proof of phone-to-provider latency or physical accuracy. Request cadence and inference completion latency are different quantities. The fresh-frame and concurrency limits prevent slow replies from accumulating.

All 23 shared Swift tests passed, including five new cadence/order/expiry/backoff cases. The existing provider absent/ambiguous/invalid-target test passed. The updated Release simulator build passed. Build 28's distribution and Apple availability are verified separately before the release is declared available.

Build 27 compiled but its archive stopped at signing with `errSecInternalComponent`. The existing signing keychain was unlocked using its preconfigured private credential file. The failed release directory is preserved; build 28 is the new release attempt. The simulator interface was inspected: live-detection status and the Scan outlined object action replace Identify and frozen-image confirmation. The simulator has no LiDAR, so this was a UI check only.
