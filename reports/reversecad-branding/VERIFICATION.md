# ReverseCAD: restored main UI and branding

## Historical UI recovered

The source is `754c0661f97d4b4c1e74ca2cb60519113c1d6c54`, “Unify repair UI and refine reference edge and corner CAD,” committed October 18, 2026 at 04:06:08 EDT. The remote-main reflog confirms this was main before the 07:58:47 EDT consolidation (`44c07e8`). The subsequent 08:00:52 EDT update (`3155e48`) added the card-based design; this revision removes those cards.

The restored app opens directly to the camera. It uses the exact original `RepairStyle` palette, circular capture control, stage pill, saved-scan/reset controls, preview tabs and repair review. A compact selector separates Scan object and Repair damage. The editable box, optional description and full-image capture are retained. The latest sequence is a first 360-degree pass, automatic saved-view identification, then a second detail pass with a translucent observed-depth preview. Camera lifetime is preserved when Start creates the project; it is removed only after saved capture completion.

Visible app branding, icon label, scanner product, configuration-error text, settings, backend service name and new CAD report titles use **ReverseCAD**. Current scanner target: `ReverseCADScanner`. The installed bundle identifier and historical release receipts remain unchanged for update/data compatibility. The new ignored credential resource is `ReverseCADJevConfig.plist`; no key is committed or exported.

Source implementation: `a7ce47c` on `main` and `main-consolidated`.

## Verification

- Shared Swift: 38 executed, 36 passed, 2 opt-in live checks skipped. Includes masked/depth-edge-safe preview triangulation, unobserved-hole preservation and bounded accumulation.
- Service/capture integration: 31 passed. Same-session object reconstruction, damage routing and exports remain covered.
- Restored UI checks passed: direct camera entry, both flow selectors, editable boundaries, saved scans, help and required reference setup.
- Final two-pass native/UI run: 56 native tests and one UI test passed. Ten focused tests also passed after final state/provenance adjustments. Screenshots for camera, setup, saved scans and Connection were exported and visually checked.
- Build 35 is signed and verified. Its display/product names are ReverseCAD, and no packaged file is named Prelude. IPA SHA-256: `41cd2136a8d5efcef480e032af1e62174c369cefda66c922c7770d8b83b20a4f`. **It has not been uploaded.** Release awaits the hardware-scope choice.
- App Store Connect metadata rename: blocked by the current API key's 403 response; the opened App Store Connect browser is still at sign-in. The app binary and UI branding are ReverseCAD; the remote listing name has not changed yet.

The newly ported public TrueDepth reference passed eight native checks and two profile tests, including existing physical-data replay. The rear-camera fitting/registration and simultaneous three-camera/private-LiDAR paths remain unimplemented; current phone connection is unavailable. These checks do not establish fresh live-phone sensing, physical measurement accuracy or printed repair fit. Reconstruction still runs on the paired Mac.

## Current release gate

`main` and `main-consolidated` contain implementation commit `a7ce47c`. Build 35 is signed and locally verified, not uploaded. The internal group was renamed to ReverseCAD Personal. App Store Connect still needs an authorized browser sign-in to change its listing name because the upload key cannot edit app-info names (HTTP 403). The user was asked whether to publish the supported public two-pass mode or hold for fully validated three-camera hardware. No answer has been received yet.
