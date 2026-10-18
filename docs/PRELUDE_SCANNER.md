# Prelude standalone scanner

The `PreludeScanner` target presents only object description, Jev identification, box confirmation, capture, observed-shape review and export. It uses the existing Prelude bundle `com.pranavmuralitharan.prelude`, so this is an update to Prelude Personal in TestFlight. No main-branch merge is required.

## Capture modes

TestFlight uses the physical rear wide camera with public ARKit `sceneDepth` and visual-inertial poses. These are Apple's processed estimates; they are not the intercepted sparse stream. The private sparse capture remains isolated in `ReverseCADSparseResearch`, whose Debug/archive guards remain intact.

The description and one portrait JPEG go through the authenticated companion to TypeSafe Jev `jev-1.14.0`. Presence, instance count, category and box are evaluated together. An absent or ambiguous target cannot be confirmed. The user sees the exact queried image and box, and must confirm without moving the camera. Vision then tracks the selected box; instance segmentation is a separate step. Lost tracking ends the capture and saves committed frames. Frames without the selected foreground mask are rejected for measurement.

Jev's image/Box support is experimental. The confidence gates are conservative application rules, not calibrated accuracy guarantees. Its answers never supply dimensions.

## Companion

Run `./scripts/start_service.sh --lan --port 8769 --data-dir work/sparse-service` from this checkout. Retain the existing private pairing token. Enter the reachable Mac address and token in Prelude's Connection screen if it is not already paired.

Set `TYPESAFE_API_KEY` (or `JEV_API_KEY`) in the companion process environment or the ignored local `.env` before startup. The key stays on the Mac; it is neither bundled in the app nor returned by the API. Missing credentials produce an explicit identification error; the user may instead draw and confirm a manual box on the camera image. Manual selection is labelled in the scan provenance and does not call Jev. No live Jev call is claimed until credentials and a successful response are verified.

## Exports

The `standalone_scan` scope skips counterpart and repair proposals. It exports measured points as PLY in millimetres, measurements with support/uncertainty metadata, and an observed STL and faceted STEP surface when supported. STEP triangles represent the observed surface only; open regions remain open. This is not a reconstructed parametric feature tree or a certified printable solid. Full observed STL and PLY/measurement exports remain available if a large surface cannot fit the bounded STEP export. STEP simplification checks sampled distance in both directions and withholds that format when the sampled deviation exceeds 0.5 mm or 30,000 faces remain. This software approximation check is not a physical accuracy bound.

An insufficient reconstruction preserves its original capture and preview but withholds measured-model export. All downloaded artifacts are hash-verified before sharing. Synthetic geometry and software checks do not establish physical accuracy or fit.

## Release

Use `scripts/testflight_release.py` and `scripts/testflight_api_upload.py` with `--prelude`. Their bundle checks select the Prelude identity and their release folders are separate from ReverseCAD. Local verification checks distribution signing, profile/team, version, arm64, privacy metadata and absence of the private sensor symbols. Apple processing and internal-group availability must be checked separately after upload.
