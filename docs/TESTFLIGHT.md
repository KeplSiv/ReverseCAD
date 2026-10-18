# Reverse CAD on TestFlight

TestFlight distributes the native iPhone app. The Python companion service still runs on your Mac: start it with `./scripts/start_service.sh --lan`, keep the Mac awake, and pair the app with `http://48.local:8767` and the private token in `var/service/pairing-token`. Phone and Mac need a mutually reachable network. TestFlight does not host that service, and it does not validate sensing accuracy or printed fit.

The release is intended for **internal TestFlight testing**. Xcode export requests `testFlightInternalTestingOnly=true`. Confirm Apple's reported build audience after processing, particularly when using the REST upload path. Internal testers must have suitable access to this app in App Store Connect. No public download link is created by a successful upload. The final download gate is the processed build being available to the intended internal tester in Apple's TestFlight app.

## Prerequisites

- Xcode with an iOS SDK, XcodeGen, and this project's bootstrapped resources. From the repository root, run `./scripts/bootstrap.sh`; it uses the frozen Python lock and regenerates `ios/ReverseCAD.xcodeproj` from `ios/project.yml`.
- An active Apple Developer Program team. The helper defaults to team `5B3Y68ZB2Y`; pass `--team` on every phase to use a different authorized team.
- The explicit App ID **`com.pranav.ReverseCAD`**, its App Store Connect app record, an installed Apple Distribution certificate **with its private key**, and an installed, unexpired **App Store distribution** provisioning profile for that exact App ID and certificate. A development, ad hoc, enterprise, or wildcard profile is rejected during verification.
- An unused build number for the selected marketing version. Every attempt uses a separate immutable directory; preserve failed attempts and increment the build number.
- For the optional command-line upload: an existing authorized App Store Connect API `.p8` key in a private location outside this repository, its key ID and issuer ID. Restrict the key file to mode `600`. The helpers pass its path to Xcode or OpenSSL for authentication; they never copy private-key contents into the app or reports.

The project includes its AppIcon asset, `PrivacyInfo.xcprivacy`, camera/motion/local-network purpose strings, iOS 17 deployment metadata, and phone/iPad orientations. The verification phase checks their presence in the **exported IPA**, not merely in source. It checks the four reviewed required-reason API categories against [PRIVACY_RELEASE.md](PRIVACY_RELEASE.md). The collection-declaration array is optional and is validated only when present; its absence does not assert that no user content is transferred. Changing app data collection or required-reason API use requires a review of the declarations.

## Reproducible release commands

Run these commands from the repository root. These are the settings for version **1.0, build 3**. Its App Store Connect app ID is **6824022304**. The identity and profile below are public identifiers for the installed signing material, not credentials. `security find-identity -v -p codesigning` lists local signing identities without exposing private keys. For a new release attempt, choose an unused build number consistently in every command; an existing archive attempt cannot be overwritten.

```sh
python3 scripts/testflight_release.py archive \
  --version 1.0 --build 3 \
  --profile-uuid f67ee9e4-9600-4be2-93d9-b6169c8d5ae3 \
  --identity 09B5EB4E14B816C228E6ED991380F5B8021D8255

python3 scripts/testflight_release.py export --version 1.0 --build 3
python3 scripts/testflight_release.py verify --version 1.0 --build 3
```

`archive` regenerates the Xcode project and performs a Release archive for generic iOS with explicit manual signing. The profile UUID is preserved exactly, including lowercase characters. Its target-scoped setting, `REVERSECAD_PROFILE_ReverseCAD`, is expanded through `PROVISIONING_PROFILE_SPECIFIER=$(REVERSECAD_PROFILE_$(TARGET_NAME))`; Swift package targets therefore do not receive the app's provisioning profile. The helper does not permit automatic provisioning changes. If Keychain requests access to the signing private key, authorize the intended `codesign` operation locally; dismissing that prompt fails the archive.

`export` uses `method=app-store-connect`, `destination=export`, `testFlightInternalTestingOnly=true`, and `manageAppVersionAndBuildNumber=false`. Neither archive nor local export uploads anything.

Artifacts are retained under `var/testflight/release-1.0-3/`; logs, Xcode results, and machine-readable receipts are under `reports/testflight/release-1.0-3/`. The helper refuses to overwrite an archive or export attempt. Hash receipts detect changes before subsequent phases. Verification can be repeated and retains a new timestamped report each time. Failed builds 1 and 2 remain separate historical attempts; their existence does not mean Apple received them.

The IPA verification checks:

- Valid strict code signature, Apple distribution identity, team, certificate membership in the embedded profile, and certificate expiration.
- Exact bundle/version/build; explicit, unexpired App Store profile; no registered-device list or enterprise entitlement; `beta-reports-active=true` and `get-task-allow=false` in both profile and app signature.
- Device arm64 executable, iOS 17+ minimum, iPhone support, appropriate iPad orientations, compiled AppIcon pixels/catalog, privacy manifest, purpose strings, and the export-compliance declaration.
- SHA-256 hashes of the IPA, profile, certificate, privacy manifest, and all application files.

## Upload through Apple's API

Upload is a **separate explicit phase**. The [official Build Upload API](https://developer.apple.com/documentation/appstoreconnectapi/build-uploads) supports the retained, verified IPA directly. Use this path on this Mac because its clock has differed from Apple's by about 11 hours. The helper derives a JWT-only time offset from Apple's HTTPS `Date` response and issues five-minute tokens; it does not change the host clock. The offset is freshly measured on each invocation rather than hardcoded.

First check signing, exact release hashes, API authentication, and the app record without uploading:

```sh
python3 scripts/testflight_api_upload.py check --version 1.0 --build 3 \
  --app-id 6824022304 \
  --key-path /absolute/private/path/AuthKey_KEYID.p8 \
  --key-id YOUR_KEY_ID --issuer-id YOUR_ISSUER_ID
```

Then explicitly upload:

```sh
python3 scripts/testflight_api_upload.py upload --version 1.0 --build 3 \
  --app-id 6824022304 \
  --key-path /absolute/private/path/AuthKey_KEYID.p8 \
  --key-id YOUR_KEY_ID --issuer-id YOUR_ISSUER_ID
```

The helper repeats archive/IPA verification, confirms `com.pranav.ReverseCAD`, creates a build and file reservation, sends the exact byte ranges Apple returns, and commits with `uploaded=true`, as shown in [Apple's WWDC25 Build Upload walkthrough](https://developer.apple.com/videos/play/wwdc2025/324/). It retains independent local SHA-256 and MD5 hashes and compares a full-file checksum if Apple returns one. It omits the optional `sourceFileChecksums` request field: Apple rejected a SHA-256 hex value during the first commit attempt, and its schema does not specify the expected hash encoding. A missing server checksum remains explicitly unconfirmed.

JWTs go only to the fixed App Store Connect API origin. File upload requests use a separate connection to the signed HTTPS URLs returned by Apple, with no API JWT and no redirects. Tokens, private-key contents, signed URLs, and upload headers are omitted from reports.

`api-upload-progress.json` and append-only `api-upload-events.jsonl` under the release's report directory retain upload IDs, completed byte-range hashes, and state. After an interrupted attempt, inspect Apple and these records first. `upload --resume` resumes the recorded upload without creating a second build; an uncertain creation with no recorded ID stops for reconciliation. Do not switch upload methods after an uncertain attempt without confirming whether Apple already received it.

Check processing separately:

```sh
python3 scripts/testflight_api_upload.py status --version 1.0 --build 3 \
  --app-id 6824022304 \
  --key-path /absolute/private/path/AuthKey_KEYID.p8 \
  --key-id YOUR_KEY_ID --issuer-id YOUR_ISSUER_ID
```

The REST API's build creation schema has no audience field. Keep the internal-only Xcode export and verify Apple's final `buildAudienceType` before distribution. `PROCESSING` is pending; `COMPLETE` confirms processing, not assignment to an internal testing group or installation on the iPhone.

An alternative Xcode upload path remains available when its own authentication works with the host clock:

```sh
python3 scripts/testflight_release.py upload --version 1.0 --build 3 \
  --key-path /absolute/private/path/AuthKey_KEYID.p8 \
  --key-id YOUR_KEY_ID \
  --issuer-id YOUR_ISSUER_ID
```

This alternative asks `xcodebuild -exportArchive` to upload an internal-only re-export of the unchanged archive. Xcode's uploaded bytes can differ from the retained locally exported IPA, so the local IPA hash is not claimed to identify Xcode's re-exported package. API key paths and public identifiers may appear in its command log; key contents never belong in commands, logs, Git, or app resources.

## Finish in App Store Connect and on iPhone

1. In [Reverse CAD's TestFlight page](https://appstoreconnect.apple.com/apps/6824022304/testflight), confirm version **1.0, build 3** appears and finishes processing. Verify its audience and resolve any export-compliance or metadata questions accurately. An upload receipt alone is not install availability.
2. Assign the processed build to the intended internal testing group, ID `63d8963d-fbc1-4b94-998e-3681370d83f4`, and confirm the owner's Apple account has access to that build. Group membership alone is not build availability. Handle any invitation through the authorized App Store Connect workflow.
3. On the iPhone, install Apple's TestFlight app, sign in with that tester account, accept the invitation if needed, and install **Reverse CAD**. The app's version and build must match the release receipt. TestFlight distribution does not require connecting the phone to Xcode or enabling Developer Mode.
4. Start the companion service, enter its URL and pairing token in Reverse CAD's Service settings, and grant the requested camera/local-network permissions. First verify connectivity and the bundled replay, then follow [PHONE_TEST_PLAN.md](../PHONE_TEST_PLAN.md) for real sensing, independent measurements, and printed coupons.

The existing [automated validation report](../reports/TEST_REPORT.md) covers software and synthetic replay. Apple processing, a successful installation, real-device sensing, dimensional accuracy, and printed fit are distinct gates and should be recorded separately. Live AI also requires the companion service's provider key; manual repair workflows remain available without one.
