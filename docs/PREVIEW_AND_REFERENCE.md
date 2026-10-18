# Preview and front-reference update

The October 18 follow-up changes the viewing and shutter experience. Rear capture formats, original frame retention, accepted-view selection, calibration, registration and reconstruction remain unchanged.

## Native rear preview and permission

The rear view uses `AVCaptureVideoPreviewLayer` directly. The display-only optical-flow interpolation added in build 38 is removed because it can deform moving edges. There is no image warping, synthetic intermediate frame or Metal overlay in the rear preview. Sensor formats, resolution, cadence and reconstruction are unchanged. The native source cadence is not represented as 60 distinct frames per second.

App launch checks camera permission before constructing any camera screen. Undecided permission triggers the system request; denied permission shows a Settings action; restricted access shows its status. Returning from Settings rechecks permission. Already granted permission does not request it again.

The app opens the rear-camera screen automatically. The native preview attaches as soon as its session is configured, before the existing three-second sensor acceptance check completes. That check still gates scanning. A themed opening state covers only hardware startup. The front reference remains a separate user-selected setup flow.

## User-selected front reference

Opening the front-reference flow starts the selfie camera automatically. The primary action stays at the top, followed by a short instruction, a flexible full-image preview and a short status. The screen has no scroll view. Saved-reference review and retake use the same layout.

The native preview layer is attached immediately. While the camera starts, a themed “Opening selfie camera…” cover stays visible until AVFoundation reports that the layer is ready to display its first frame. Startup does not wait for the depth-quality or exposure checks. Camera permission and hardware startup can still take time; the screen does not present that delay as an empty black preview.

The front camera stays open until the user presses **Save scan**, presses a volume button, or closes it. The former eight-frame auto-finish and 20-second timeout are removed. A bounded rolling window retains eight recent sharp, synchronized RGB/TrueDepth samples in memory. Save freezes that window, preserving the original image/depth buffers and metadata. Existing numerical stability and scene-suitability checks still apply. A failed stability check retains its evidence and leaves the camera open for another Save attempt.

The rolling window owns independent copies of the image/depth planes, including original row padding, timing and calibration attachments. It does not retain camera-pool buffers that could starve capture and freeze the live view.

After auto-exposure settles, the requested selfie shutter duration is half the measured baseline, clamped to the hardware minimum. ISO compensates where its supported range permits. Baseline and actual exposure are recorded for verification. This reduces exposure-time blur; it cannot guarantee a blur-free result if the camera or object moves.

System capture-button APIs handle volume-button release. They are enabled only when the capture action is available. On the rear camera they start or finish the current pass; on the front camera they perform the same action as Save scan. No private button notifications or volume-setting tricks are used.

## Verification

Simulator tests cover permission decisions, returning from Settings, app launch, preservation of source images, fresh-window requirements, shutter limits and framing gestures. Phone checks must separately confirm display cadence, persistent front preview, measured shutter ratio and a real volume-button save. Passing these checks does not establish dimensional accuracy or resolve the previously recorded full-orbit tracking limitations.

## Build identity and diagnostic cleanup

On October 18, the connected iPhone still had version 0.1.0 (38) installed and running after build 39 became available in TestFlight. Build 38 contains the rear optical-flow renderer; TestFlight availability alone does not establish that its replacement is running. Check the installed bundle version and the running executable before interpreting a preview test. Associate saved sensor evidence with a newly created capture ID, rather than reusing an old diagnostic file.

Build 40 retains build 39's native rear preview and permission handling. It removes the unused selfie preview-buffer cache and the ad hoc front-camera JSON/JPEG diagnostic writes. The native selfie layer never consumed that cache. This cleanup does not change the saved reference's original RGB/depth planes, calibration, timestamps, exposure settings, capture ID or user-selected shutter trigger. The original buffer-copy regression checks remain.
