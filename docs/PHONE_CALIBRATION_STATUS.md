# pradev-4 implementation status

Based on capture-first commit ad1b2a3. The original requested branch was overridden by the user to pradev-4. No changes to main or the active pranav-dev release checkout.

Implemented in this revision:
- First-use front-reference entry point inside Prelude, with explicit Start before camera access.
- Public AVCapture synchronized front TrueDepth and RGB. Unfiltered metric depth formats only; actual filter state, timestamp offset, calibration, original colour/depth planes and distortion tables preserved.
- Four-second framing period, bounded eight-view capture and twenty-second timeout; incomplete/error captures retained locally.
- Frankly visible-surface reconstruction port, including per-frame calibration, one distortion correction, optical-axis depth, open PLY/OBJ surface exports, and unknown systematic-error labels.
- Immutable provisional profile revisions bound to reference archive SHA-256; selected profile snapshot included and hashed in rear scans. A reference does not install fitted rear-camera corrections.
- Rear preview starts only after an explicit Start camera tap; existing capture-first identification/reconstruction/export flow retained.

Still required for the complete request:
- Feature-based front-to-rear registration and integration of the existing residual calibration solver; held-out validation, compatible-format selection, safe promotion, rollback UI and normal-scan refinement.
- Wide/ultrawide/telephoto integration and calibrated-ray fusion; optional reference angle variation must not be combined as if camera pose were unchanged.
- Combined reference/archive export and profile-aware backend consumption; selectable object measurement endpoints and full CSV/readback coverage.
- Apple processing/internal availability for build 32 and actual phone capture/independent dimensional validation. Existing build 31 is a separate capture-first release, not this revision.

A stationary front burst cannot identify all rear-camera parameters. The app explicitly leaves factory per-frame rear calibration active. Do not interpret a successful replay or compile as calibrated accuracy.

Verified during this revision:
- PreludeScanner iOS simulator build succeeded.
- 34 shared tests: 32 passed, 2 skipped, 0 failed.
- Six native TrueDepth tests passed, including real saved capture replay, per-frame calibration change, mirrored-frame rejection, LUT direction, depth discontinuities, and direct measurement/exports.
- The replay reads the saved 2026-10-18 Frankly burst; it does not establish new physical measurement accuracy.

Release: Prelude 0.1.0 (32) archived, exported, IPA-verified and uploaded. Apple upload state PROCESSING; internal availability remains unverified. SHA-256: fc86a487da72e62622791e099d4d2e9b785c81627b4a890a723680bc36b45cf3.
