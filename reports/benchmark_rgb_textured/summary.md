# Synthetic reconstruction benchmark

synthetic software validation only; not real iPhone accuracy or printed fit

Clean dimension gates: **0/0 stage runs passed**. Total stage runs: 3.

No alignment or scale fitting was used. Both configured scene sizes are evaluated independently. Baseline, filtered fusion, and RGB-assisted checks receive identical input bytes.

| Clean-stage metric | Raw depth/pose | Filtered fusion | RGB-assisted |
| --- | ---: | ---: | ---: |
| Largest absolute axis error (mm) | not evaluated | not evaluated | not evaluated |
| Mean surface RMS error (mm) | not evaluated | not evaluated | not evaluated |
| Mean full-surface coverage within 2mm | not evaluated | not evaluated | not evaluated |
| Mean runtime (s) | not evaluated | not evaluated | not evaluated |
| Maximum process RSS (MiB) | not evaluated | not evaluated | not evaluated |

The raw synthetic clean observations already lie on the analytic surfaces. Filtering or RGB checks need not improve this idealized baseline; see measured values rather than assuming an improvement. Coverage includes occluded surfaces and is not a measured assurance of completeness.

| Production RGB-assisted fixture | State | Largest axis error (mm) | Surface P95 (mm) |
| --- | --- | ---: | ---: |
| calibration_block_rgb_textured | ready | 2.7960 | 0.0000 |

Per-run errors, warnings, code/input hashes, dependency versions, timing, memory, and geometric metrics are in `benchmark.json`; original worker results and logs are under `runs`. Degradation errors are diagnostics, not an assertion that an unknown real sensor bias is detectable. No run verifies phone sensing, real dimensional accuracy, or printed fit.
