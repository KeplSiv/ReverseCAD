# Prelude standalone scan update

Prelude's `PreludeScanner` target now starts with an object description, calls Jev through the paired companion, displays the returned box on the queried image for confirmation, tracks/segments the selected object, saves the capture, and opens only the observed 3D preview and exports. It does not continue into repair generation.

The TestFlight target uses public ARKit processed scene depth and a physical rear wide camera. It contains no private sparse capture sources. The separate sparse Debug target and its archive/distribution guards remain intact.

## Validation

- Release simulator build passed; the actual running home screen was inspected.
- The initial signed Prelude 0.1.0 (25) archive, export and IPA checks passed with bundle `com.pranavmuralitharan.prelude` and team `5B3Y68ZB2Y`.
- The exported IPA SHA-256 is `da3cd0dfba593ed93d2f480c47ad0fe7dfa1c3cf429e1f017806e9c6cf4ef54b`.
- Offline tests cover absent/ambiguous Jev results, invalid probabilities and boxes, millimetre STEP roundtrip, preservation of an open surface, insufficient-reconstruction export gating, authenticated service delivery and exported-asset hashes.
- Both public RGB-D and sparse synthetic fixtures are exercised through the standalone service boundary. Large/noisy public meshes retain their full STL when a bounded STEP approximation fails its deviation gate; that is an explicit per-format limitation.

The final update adds manual box selection so scanning remains usable before Jev credentials are configured. Final build 26 supersedes the unuploaded build 25. The final release result is recorded below and in `release-status.json`.

Backend verification: 5 standalone tests passed, including both service/export fixtures. The 21 existing service tests also passed.

## Outstanding physical/provider checks

No successful live Jev request is claimed: its API key has not yet been supplied/configured. No new moving-camera phone capture, dimensional check or physical fit test is claimed. This release is a prototype for those checks.

The paired service is running on the Mac at port 8769 with the existing private pairing token. It must remain reachable for identification and reconstruction. The phone's original recorded sessions were not intentionally modified; the detailed inventory report is under `reports/sparse-reconstruction/phone-recording-preservation.json`.

Apple upload and internal availability are recorded separately in `release-status.json` once verified.
