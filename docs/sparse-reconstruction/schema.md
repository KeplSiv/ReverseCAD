# Capture extension v1

The outer capture schema stays at version 1. Old packages without `sparse_capture`
retain their existing behavior. The extension is a typed optional field in the
Python/JSON schema and a validated optional JSON object in the Swift contract.

```json
{
  "sparse_capture": {
    "schema_version": 1,
    "mode": "sparse_range_rgb",
    "status": "available",
    "packet_path": "sparse/origin-packets.bin",
    "event_path": "sparse/origin-events.jsonl",
    "calibration_path": "sparse/calibration.json",
    "clock": "host_monotonic_seconds",
    "RGB_control": "unaltered"
  }
}
```

Status is `capturing`, `available` or `unavailable`. Available means packets were
observed, not that they are all valid, registration succeeded, or accuracy was
verified. Only a completed package with usable packets/calibration can reconstruct.
There is no automatic substitution of processed scene depth for missing sparse data.

Each frame's `sensor_observation` records absolute source and callback-arrival
monotonic seconds, physical camera identity, original pixel format, active-plane
hashes, original-plane paths, input-hook evidence, image transforms, and labelled
pose provenance. `timestamp_s` remains the existing capture-relative clock.
Absolute monotonic timestamps are included for this research mode to permit
packet/IMU alignment. Null means unavailable, never zero or an invented timestamp.

New device captures retain tightly packed original NV12 active rows in two files
under `sparse/rgb/`; padding is excluded consistently from file and identity hashes.
The full-size RGB JPEG is a declared CoreImage color conversion at quality 0.97.
No image crop/rotation/rescaling is performed before saving. Recorded source
metadata includes exposure, focus, stabilization, zoom/crop when available, and
labels callback-time device readback separately from per-sample attachments.

The packet stream is untouched bytes. Each `pointCloudSampleBuffer` journal record
indexes one contiguous byte interval, with sequence, source PTS, callback host
time, byte count, SHA-256 and `PortTypeBackSparseTimeOfFlight` metadata. The decoder
round-trips every packet exactly, including unknown header words and flags.
The service rejects overlaps, trailing unindexed bytes, hash mismatches, repeated
sequences, non-increasing timestamps and unsupported versions. Gaps stay gaps.
All 84 slots and all three echoes remain in derived records; validity is explicit.

Calibration records `T_sparse_camera`, column-major 4×4, direction
`camera_cv_to_sparse`, translation in **mm**. The observed native 4×3 affine data
uses padded SIMD lanes; raw NSData/base64 and SHA remain alongside the normalized
homogeneous last row. Reconstruction applies
`P_camera_m = R.T * (P_sparse_mm - t_mm) / 1000`.
This origin is the decoded coordinate origin, not a proven physical emitter.
The decoded Euclidean range is radial; camera-axis Z is computed separately.

Motion is diagnostic: `sparse/raw-motion.jsonl` contains labelled accelerometer
and gyroscope data with source/arrival times; `motion.jsonl` retains fused CoreMotion
estimates on the capture-relative clock. ARKit poses retain their source label.
Neither is independent ground truth or a pose prior in this reconstruction.

`checksums.json` covers every original and derived capture asset except itself,
including all sparse files and optional processed-depth planes. Swift commit,
recovery/import/export and server upload validation preserve these paths. Raw
image-plane sizes/hashes are additionally checked server-side. JSON metadata
sanitizes unavailable/nonfinite values to null; binary originals are unchanged.

The derived `decoded_sparse.jsonl` contains every slot's original fields, packet
identity/hash, timestamps, validity flag and reasons. `point_support.json` binds
output point row order to observation IDs, source classes and source frame IDs.
Measurement bounds/primitive fits reference that support and the selected metric
constraints. Unknown accuracy is null; reprojection/fit residuals are not uncertainty.
