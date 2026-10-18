# Capture-first verification — Prelude 0.1.0 (31)

Implementation branch: `pranav-dev`. Starting remote main: `754c0661f97d4b4c1e74ca2cb60519113c1d6c54`. The unrelated primary checkout was not modified.

## Passed checks

- Shared Swift package: 32 tests executed, 30 passed and two explicit live-network tests skipped in the offline suite; no failures. Coverage includes exact center-thirds guide and inverse display transforms, sharp/diverse reference selection, stationary/rotated duplicate exclusion, same-instance consensus and out-of-box ambiguity.
- Native iOS simulator: 43 tests passed. New tests cover optional-description identification, ten-call bound, two-image request structure, saved-identity reload without network calls, ambiguity followed by one-tap retry on the same scan, 401 handling/retry, cancellation of an in-flight request, rate-limit cooldown, and native float-mask stride/value handling. Existing capture and artifact-integrity tests also passed.
- Backend: 40 tests passed across capture-first masks, legacy framing compatibility, reconstruction geometry and standalone exports. Six capture-first tests passed again after the service capability gate was added. The end-to-end fixture uploads a saved capture plus derived masks, reconstructs and exports STL/PLY/measurements, verifies download hashes, and proves original frame/image/depth files remained unchanged. Existing tests verify conditional faceted STEP and open-surface preservation.
- Direct TypeSafe request using the final two-image Swift client: passed on an explicitly resized synthetic fixture. Returned `jev-1.14.0`, category `container`; this is API/schema evidence, not a phone capture or an accuracy test. An initial small fixture was rejected by the provider's minimum image dimensions; the production image preparation now enforces those dimensions. Reference asset IDs are UUIDs to prevent accidental text substitution.
- Prelude Debug simulator build passed. Home UI visually checked: optional description, camera entry and the five stages. The simulator has no live camera/depth; actual guide-on-camera alignment remains a phone check, beyond the coordinate math tests.
- Credential resource is ignored by Git, and its key bytes were absent from every changed source/report file. Original raw-frame metadata is never rewritten by identification. Derived masks have independent hashes.

## Important behavior

The exact guide is an initial framing hint. Object silhouettes can extend outside it. Negative Jev views stop local tracking propagation. Local foreground segmentation, hand-pose rejection, depth/confidence, supported surrounding-plane removal and cross-view geometric overlap gate object geometry. A matching `capture_first_masks` backend capability is required before upload; an older service cannot silently ignore the new masks.

Capture and identification work without a Mac. Building the model uses the existing Mac service. Update that service from the same branch before processing build 31 captures. No private sensor code enters this TestFlight target. No category-shaped replacement or unseen surface completion is introduced.

## Physical validation not performed

Fresh phone camera/depth behavior, object-segmentation accuracy across real scans, round-trip physical measurements, printed fit, and installation of this build on the user's phone are not established by these checks. A real stationary-object capture with independently measured dimensions is still required.

## Release

Signed archive, export, upload and Apple processing/internal-group results will be recorded after completion. TestFlight availability is a separate gate from the passing simulator/API tests.
