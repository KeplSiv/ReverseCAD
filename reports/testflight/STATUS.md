# TestFlight preparation status

Requested release: Reverse CAD 1.0 (1), `com.pranav.ReverseCAD`, developer team `5B3Y68ZB2Y`.

## Prepared and checked

- Release app includes opaque iPhone/iPad/App Store icons, privacy manifest, standard-OS encryption declaration and complete iPad orientation metadata.
- Capture timing now exports one synchronized elapsed timeline instead of device uptime. Seven focused Release capture tests pass, including actual AVAssetWriter output and offset-invariance checks. See `../testflight-capture-tests-final.log`.
- Final `./scripts/test_ios.sh` regression passed: **18 native unit tests and 2 actual-service UI workflows**, zero failures. See `../ios-tests-20261016-222036.log` and its `.xcresult` bundle.
- Reproducible phase-separated release tooling is in `../../scripts/testflight_release.py`; instructions are in `../../docs/TESTFLIGHT.md`. CLI and fail-closed checks passed; distribution signing/upload remain unexecuted.
- Unsigned generic iPhone Release archive passed. See `archive-unsigned.log` and `unsigned-archive-verification.json`. The archive is `../../var/testflight/ReverseCAD-1.0-1-unsigned.xcarchive`.
- The current Apple distribution certificate is available locally and Apple's API reports its expiration as September 6, 2027.
- Existing App Store Connect API authentication works when JWT time is aligned with the authenticated HTTPS Apple Date response. The Mac clock was not changed. Key/JWT contents were never printed.
- Testing notes are prepared in `what-to-test.txt`. The Mac companion remains healthy at `http://48.local:8767/v1/health`.

## Blocked before signing/upload

- Apple's live API lookup found no app record or bundle registration for `com.pranav.ReverseCAD`.
- Registering this identifier with the existing API key returned HTTP 403 `FORBIDDEN_ERROR`. No bundle or profile was created by that failed request.
- Xcode automatic signing failed: no usable signed-in Xcode account and no provisioning profile for this app. See `archive-automatic.log`.
- App Store Connect in the owner's regular Chrome session requires sign-in. The account identifier is entered and passkey sign-in started; user authentication is pending. Native Chrome passkey-prompt access was rejected by the computer-use approval layer.

The unsigned archive cannot be installed through TestFlight. No IPA has been signed or uploaded, no TestFlight build exists for this app, and no invitation has been sent. The next action is to complete owner sign-in, register the app identifier/create its App Store Connect app record and App Store distribution profile, then archive/export/verify/upload. Final success requires Apple processing VALID plus owner tester/group availability, not just an upload exit code.
