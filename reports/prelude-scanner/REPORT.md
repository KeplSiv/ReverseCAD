# Prelude standalone scan update

Prelude's `PreludeScanner` target starts with an object description, automatically calls TypeSafe directly from the iPhone approximately every 200 ms, and displays fresh category/box results over the moving camera preview. Tap **Scan outlined object** to confirm the current target. The app tracks/segments the selected object, saves the capture, and opens the observed 3D preview, measurements and exports. It does not continue into repair generation.

TestFlight uses public ARKit processed scene depth and the physical rear wide camera. It contains no private sparse capture sources. The separate sparse Debug target and its archive/distribution guards remain intact. The code and specification are published only to `pranav-dev`; no merge into `main` is part of this release.

## Continuous Jev detection

The live loop replaces the earlier tap-to-identify/frozen-image Jev flow. It targets 200 ms between new JPEG requests, permits four in flight, drops opportunities under backpressure and never queues stale frames. It continues during capture, pauses in the background, and stops on close, finish or manual selection. Resuming waits for a new camera frame. Manual box selection remains available and uses a frozen local image.

Results are bound to the request UUID and JPEG hash. Out-of-order, expired (>1.2 seconds), absent, ambiguous and pose-stale detections cannot confirm a scan. Boxes disappear if camera translation exceeds 2.5 cm or any camera-axis cosine drops below 0.995 relative to the source frame. The overlay uses the AR frame's display transform. Confirmation saves the source JPEG, frame timestamp, response and box. Later Jev overlays do not switch the measurement tracker to a different object.

Network/service failures back off for 2, 4, then 8 seconds; rate limits honor the supplied delay up to 300 seconds. Invalid credentials, access denial and exhausted credits stop retries and show specific messages. Direct client requests time out after 3 seconds. No Mac URL or pairing token is used by Jev detection. Actual displayed update rate depends on network latency, model latency, camera motion and available frames; 200 ms is a dispatch target, not a guaranteed inference latency.

## Direct connection correction — build 29

The user reported that build 28 stayed on "Jev is reconnecting" and explicitly requested using their API key directly on the phone. Build 29 removes the companion call from `LiveObjectIdentifier`: `JevClient` uses an ephemeral HTTPS session to `api.typesafe.ai/v1/systemone`, denies redirects, and performs presence/category/instance/box validation locally. It has no AppModel, LAN service URL or pairing-token dependency.

At the user's request, the personal internal build includes a generated `PreludeJevConfig.plist` containing their key. It is ignored by Git and included only in the PreludeScanner target. The original private key file remains the build input. Key contents are not printed or written to source, reports or capture exports. The IPA contains the key and is a private personal artifact; this is not a public shared-secret distribution design.

Validation: 27 offline shared Swift tests passed; the opt-in live provider test also passed. The live check ran the exact Swift direct client, returned a category and box from `jev-1.14.0`, and completed in 238 ms on the synthetic calibration image. See `jev-direct-check.json`. Tests cover direct destination/authentication/schema, absence/ambiguity/invalid boxes, actionable 400/401/402/403 errors, redaction of provider response bodies, and 429 backoff. The Release simulator build passed, its bundled key resource matched the configured key, and the application launched to its home screen. Live phone detection remains to be checked on the user's device.

Build 29 passed signed archive, export and IPA verification, including the personal credential resource hash and exclusion of private sensor symbols. Verified IPA SHA-256: `092ce17ab663addb4d671256ef30a0740a982f08850c7ee6472f034e628c8a17`. Apple accepted all 1,815,798 bytes under upload ID `b5d92273-0eba-43e6-aa2a-18bb17022e2c`. Apple reports `VALID`, `INTERNAL_ONLY` and `IN_BETA_TESTING`. Build 29 is in the Prelude Personal internal group with the existing tester; `release-status.json` records the verification. The account-level tester state does not prove build 29 is installed on the phone. The previous verified build 28 evidence is retained here for provenance.

## Previous build 28 verification

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

The phone needs ordinary internet access for Jev detection. The existing 3D reconstruction/export pipeline still needs the paired Mac service on port 8769; this correction does not move reconstruction onto the phone. The user-authorized Jev key is embedded only in the personal internal build and excluded from Git and capture exports. The original phone recordings were not intentionally modified; preservation evidence remains under `reports/sparse-reconstruction/phone-recording-preservation.json`.
