# iOS release privacy review

The app bundles `ios/ReverseCAD/PrivacyInfo.xcprivacy`. It does not track users.
The required-reason declarations match these code paths:

| Category | Reason | Actual use |
| --- | --- | --- |
| User defaults | `CA92.1` | Save and restore this app's companion URL. The pairing token stays in Keychain. |
| File metadata | `C617.1`, `3B52.1` | Validate files in the app's container or a scan folder explicitly selected through the document picker. |
| Disk space | `E174.1` | Stop capture visibly before storage is exhausted. Device free-space values are never persisted or uploaded. |
| System boot time | `35F9.1` | Measure elapsed capture-event intervals, preserving sensor synchronization. Only relative intervals leave the device. |

Live capture now stores seconds since its first ARFrame across frame records, review-video mappings, motion diagnostics and interruption events. The common origin stays in memory; diagnostics schema 2 documents the relative clock. Pre-origin motion samples are omitted. Replay preserves original source evidence.

Apple permits exporting app-event elapsed intervals under `35F9.1`, but not raw device uptime. See [approved reasons](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitypereasons?language=objc), [required reason policy](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api), and [manifest structure](https://developer.apple.com/documentation/technotes/tn3183-adding-required-reason-api-entries-to-your-privacy-manifest).

This manifest does not assert that no user content is transferred. Users explicitly upload their scans to their configured companion, and optional live reasoning sends selected images and repair evidence through the companion to its configured AI provider. App Store Connect privacy and beta-review disclosures must describe the deployment being distributed. No live-provider request or physical-sensor validation is established by this release review.
