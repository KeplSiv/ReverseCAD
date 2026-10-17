# Synthetic reconstruction benchmark

synthetic software validation only; not real iPhone accuracy or printed fit

Clean dimension gates: **33/33 stage runs passed**. Total stage runs: 90.

No alignment or scale fitting was used. Both configured scene sizes are evaluated independently. Baseline, filtered fusion, and RGB-assisted checks receive identical input bytes.

| Clean-stage metric | Raw depth/pose | Filtered fusion | RGB-assisted |
| --- | ---: | ---: | ---: |
| Largest absolute axis error (mm) | 0.005814 | 0.005814 | 0.005814 |
| Largest fitted primitive error (mm) | 0.021706 | 0.029302 | 0.029302 |
| Mean surface RMS error (mm) | 0.000006 | 0.004301 | 0.011315 |
| Mean full-surface coverage within 2mm | 0.905076 | 0.901943 | 0.901943 |
| Mean runtime (s) | 0.698449 | 2.486860 | 2.593259 |
| Maximum process RSS (MiB) | 198.953125 | 912.218750 | 918.078125 |

The raw synthetic clean observations already lie on the analytic surfaces. Filtering or RGB checks need not improve this idealized baseline; see measured values rather than assuming an improvement. Coverage includes occluded surfaces and is not a measured assurance of completeness.

| Production RGB-assisted fixture | State | Largest axis error (mm) | Surface P95 (mm) |
| --- | --- | ---: | ---: |
| asymmetric_clean | ready | 0.0000 | 0.0000 |
| asymmetric_heldout | ready | 0.0000 | 0.0000 |
| bracket_clean | ready | 0.0000 | 0.0000 |
| bracket_heldout | ready | 0.0000 | 0.0000 |
| broken_bridge_clean | ready | 0.0000 | 0.0000 |
| broken_bridge_heldout | ready | 0.0000 | 0.0000 |
| calibration_block_blur | needs_input | — | — |
| calibration_block_clean | ready | 0.0000 | 0.0000 |
| calibration_block_depth_bias | needs_input | 22.0246 | 9.9948 |
| calibration_block_depth_holes | ready | 0.0000 | 0.0000 |
| calibration_block_heldout | ready | 0.0000 | 0.0000 |
| calibration_block_incomplete | needs_input | 0.0000 | 0.0000 |
| calibration_block_invalid_depth | ready | 0.0000 | 0.0000 |
| calibration_block_low_texture | ready | 0.0000 | 0.0000 |
| calibration_block_mismatched_image_sizes | rejected | — | — |
| calibration_block_missing_confidence | ready | 0.0000 | 0.0000 |
| calibration_block_missing_depth | needs_input | — | — |
| calibration_block_noise | needs_input | 6.2785 | 1.8792 |
| calibration_block_occlusion | ready | 0.0000 | 0.0000 |
| calibration_block_origin_reset | rejected | — | — |
| calibration_block_padded_stride | ready | 0.0000 | 0.0000 |
| calibration_block_partial_coverage | needs_input | 37.7655 | 0.0000 |
| calibration_block_portrait_raw | ready | 0.0000 | 0.0000 |
| calibration_block_pose_drift | needs_input | 12.9314 | 8.4000 |
| calibration_block_registered_reset | ready | 0.0000 | 0.0000 |
| calibration_block_rgb_textured | ready | 0.0058 | 0.0000 |
| calibration_block_timestamp_gap | ready | 0.0000 | 0.0000 |
| calibration_block_unmasked | needs_input | 0.0000 | 0.0000 |
| cup_clean | ready | 0.0000 | 0.0002 |
| cup_heldout | ready | 0.0000 | 0.0002 |

Per-run errors, warnings, code/input hashes, dependency versions, timing, memory, and geometric metrics are in `benchmark.json`; original worker results and logs are under `runs`. Degradation errors are diagnostics, not an assertion that an unknown real sensor bias is detectable. No run verifies phone sensing, real dimensional accuracy, or printed fit.
