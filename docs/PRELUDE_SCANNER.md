# Prelude standalone scanner

The `PreludeScanner` target presents only object description, Jev identification, box confirmation, capture, observed-shape review and export. It uses the existing Prelude bundle `com.pranavmuralitharan.prelude`, so this is an update to Prelude Personal in TestFlight. No main-branch merge is required.

## Capture modes

TestFlight uses the physical rear wide camera with public ARKit `sceneDepth` and visual-inertial poses. These are Apple's processed estimates; they are not the intercepted sparse stream. The private sparse capture remains isolated in `ReverseCADSparseResearch`, whose Debug/archive guards remain intact.

While the camera screen is active, Jev automatically checks a fresh portrait JPEG approximately every 200 ms, including during scanning. No Identify button or frozen Jev confirmation image is used. Each request carries the description and a 640-pixel-long-edge JPEG through the authenticated companion to `jev-preview` (verified as `jev-1.14.0`). Presence, instance count, category and box are evaluated together. The moving camera preview displays the latest eligible category and bounding box, mapped through ARKit's actual display transform. Tap **Scan outlined object** to confirm the current target and begin capture.

The loop permits at most four requests in flight, drops capture opportunities while full, and never queues old frames or sends a catch-up burst. Responses are bound to the request UUID and JPEG hash. Older, expired (>1.2 seconds), absent or ambiguous detections cannot select an object. A box also disappears if the camera moves more than 2.5 cm or any camera-axis cosine drops below 0.995 relative to the queried image. Failures back off for 2, 4, then 8 seconds; the client request timeout is 3 seconds. Actual displayed update rate depends on network/model latency and camera motion; 200 ms is a dispatch target, not a guaranteed inference latency.

The chosen JPEG, frame timestamp, response, box and selection method are saved as provenance when Scan is tapped. Vision tracks this confirmed target for measurement; subsequent Jev overlays do not silently select a different measurement target. Instance segmentation remains separate. Lost measurement tracking ends the capture and saves committed frames. Frames without the selected foreground mask are rejected. Jev requests stop on close, finish, backgrounding, or choosing manual selection; returning to the active live screen resumes them. Manual selection still uses a frozen image and stays on the phone.

Jev's image/Box support is experimental. The confidence gates are conservative application rules, not calibrated accuracy guarantees. Its answers never supply dimensions.

## Companion

Run `./scripts/start_service.sh --lan --port 8769 --data-dir work/sparse-service` from this checkout. Retain the existing private pairing token. Enter the reachable Mac address and token in Prelude's Connection screen if it is not already paired.

Set `TYPESAFE_API_KEY_FILE` to the private key file, or set `TYPESAFE_API_KEY` (or `JEV_API_KEY`) in the companion process environment or the ignored local `.env` before startup. The key stays on the Mac; it is neither bundled in the app nor returned by the API. Missing credentials produce a reconnect message with backoff; the user may instead draw and confirm a manual box on the camera image. Manual selection is labelled in the scan provenance and does not call Jev. A 12-request companion check at 200 ms intervals succeeded on a resized synthetic fixture, returning `jev-1.14.0`, a category and a box for every request. Median response time was 185.8 ms; the slowest was 839.1 ms. This verifies provider integration, not phone capture accuracy. See `reports/prelude-scanner/jev-cadence-check.json`.

## Exports

The `standalone_scan` scope skips counterpart and repair proposals. It exports measured points as PLY in millimetres, measurements with support/uncertainty metadata, and an observed STL and faceted STEP surface when supported. STEP triangles represent the observed surface only; open regions remain open. This is not a reconstructed parametric feature tree or a certified printable solid. Full observed STL and PLY/measurement exports remain available if a large surface cannot fit the bounded STEP export. STEP simplification checks sampled distance in both directions and withholds that format when the sampled deviation exceeds 0.5 mm or 30,000 faces remain. This software approximation check is not a physical accuracy bound.

An insufficient reconstruction preserves its original capture and preview but withholds measured-model export. All downloaded artifacts are hash-verified before sharing. Synthetic geometry and software checks do not establish physical accuracy or fit.

## Release

Use `scripts/testflight_release.py` and `scripts/testflight_api_upload.py` with `--prelude`. Their bundle checks select the Prelude identity and their release folders are separate from ReverseCAD. Local verification checks distribution signing, profile/team, version, arm64, privacy metadata and absence of the private sensor symbols. Apple processing and internal-group availability must be checked separately after upload.
