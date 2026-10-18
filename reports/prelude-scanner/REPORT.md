# Prelude standalone scan update

Prelude's `PreludeScanner` target now starts with an object description, calls Jev through the paired companion, displays the returned box on the queried image for confirmation, tracks/segments the selected object, saves the capture, and opens only the observed 3D preview and exports. It does not continue into repair generation.

The TestFlight target uses public ARKit processed scene depth and a physical rear wide camera. It contains no private sparse capture sources. The separate sparse Debug target and its archive/distribution guards remain intact.

## Validation

- Release simulator build passed; the actual running home screen was inspected.
- The final signed Prelude 0.1.0 (26) archive, export and IPA checks passed with bundle `com.pranavmuralitharan.prelude` and team `5B3Y68ZB2Y`.
- The final IPA SHA-256 is `ecedea28575da5e45e69bc1a8f7972e36e8145f87ee067320bc6fe0a3098955a`.
- Apple accepted upload `8be2427a-f0d6-42c4-b923-2a680e9b1807`; TestFlight processing is checked separately below.
- Offline tests cover absent/ambiguous Jev results, invalid probabilities and boxes, millimetre STEP roundtrip, preservation of an open surface, insufficient-reconstruction export gating, authenticated service delivery and exported-asset hashes.
- Both public RGB-D and sparse synthetic fixtures are exercised through the standalone service boundary. Large/noisy public meshes retain their full STL when a bounded STEP approximation fails its deviation gate; that is an explicit per-format limitation.

The final update adds manual box selection so scanning remains usable before Jev credentials are configured. Final build 26 supersedes the unuploaded build 25. The final release result is recorded in `release-status.json`.

Backend verification: 5 standalone tests passed, including both service/export fixtures. The 21 existing service tests also passed.

## Outstanding physical/provider checks

A live Jev request succeeded using the private key file supplied by the user. The provider returned `jev-1.14.0` through the `jev-preview` alias, classified the synthetic fixture as one container, and returned a confirmable bounding box. The fixture was enlarged from 320×240 to 640×480 to satisfy the provider minimum dimensions; this is an API integration check, not physical validation. No new moving-camera phone capture, dimensional check or physical fit test is claimed. This release is a prototype for those checks.

The paired service is running on the Mac at port 8769 with the existing private pairing token. It must remain reachable for identification and reconstruction. The phone's original recorded sessions were not intentionally modified; the detailed inventory report is under `reports/sparse-reconstruction/phone-recording-preservation.json`.

Apple upload and internal availability are recorded separately in `release-status.json` once verified.

The same live Jev request also succeeded through the authenticated companion endpoint (HTTP 200), with the key loaded from the configured private file. The environment-parser regression check passed.
