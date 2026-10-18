# Preview and front-reference update

The October 18 follow-up changes the viewing and shutter experience. Rear capture formats, original frame retention, accepted-view selection, calibration, registration and reconstruction remain unchanged.

## Native rear preview and permission

The rear view uses `AVCaptureVideoPreviewLayer` directly. The display-only optical-flow interpolation added in build 38 is removed because it can deform moving edges. There is no image warping, synthetic intermediate frame or Metal overlay in the rear preview. Sensor formats, resolution, cadence and reconstruction are unchanged. The native source cadence is not represented as 60 distinct frames per second.

App launch checks camera permission before constructing any camera screen. Undecided permission triggers the system request; denied permission shows a Settings action; restricted access shows its status. Returning from Settings rechecks permission. Already granted permission does not request it again.

The app opens the rear-camera screen automatically. The native preview attaches as soon as its session is configured, before the existing three-second sensor acceptance check completes. That check still gates scanning. A themed opening state covers only hardware startup. The front reference remains a separate user-selected setup flow.

## User-selected front reference

Opening the front-reference flow starts the selfie camera automatically. The primary action stays at the top, followed by a short instruction, a flexible full-image preview and a short status. The screen has no scroll view. Saved-reference review and retake use the same layout.

The native preview layer is attached immediately and remains attached through startup and interruptions. Front/rear handoff waits for the previous camera session to stop. Returning from the background or the end of a camera interruption restarts the front session and collects a fresh reference window. The top Save scan action remains visible while setup is open, disabled until fresh frames are ready. While the camera starts, a themed “Opening selfie camera…” cover stays visible until AVFoundation reports that the layer is ready to display its first frame. Startup does not wait for the depth-quality or exposure checks. Camera permission and hardware startup can still take time; the screen does not present that delay as an empty black preview.

The front camera stays open until the user presses **Save scan**, presses a volume button, or closes it. The former eight-frame auto-finish and 20-second timeout are removed. A bounded two-second rolling window retains eight recent synchronized RGB/TrueDepth samples in memory. Every synchronized frame is eligible; the former 0.12-second throttle starved the eight-frame window at lower delivery rates. Save freezes that window, preserving the original image/depth buffers and metadata. It archives the originals and shows the saved photo with an editable object box before numerical stability or scene-suitability checks. Blur is shown as a hint, so a low-texture or dim scene still produces a saved photo and box when the user captures it. The user checks the selected object explicitly. Low-sharpness captures remain reviewable, but the explicit calibration check retains the prior sharpness threshold of 7 and rejects them with a retake message. A failed check keeps the photo and box available for adjustment or retake.

The rolling window owns independent copies of the image/depth planes, including original row padding, timing and calibration attachments. It does not retain camera-pool buffers that could starve capture and freeze the live view.

After auto-exposure settles, the requested selfie shutter duration is half the measured baseline, clamped to the hardware minimum, when custom exposure is supported. ISO compensates where its supported range permits. Cameras without that control keep automatic exposure and remain usable. Baseline, requested ratio and actual exposure are recorded for verification. This reduces exposure-time blur; it cannot guarantee a blur-free result if the camera or object moves.

System capture-button APIs handle volume-button release. They are enabled only when the capture action is available. On the rear camera they start or finish the current pass; on the front camera they perform the same action as Save scan, using the same fresh-frame readiness condition. No private button notifications or volume-setting tricks are used.

## Verification

Simulator tests cover permission decisions, returning from Settings, app launch, preservation of source images, fresh-window requirements, shutter limits and framing gestures. Phone checks must separately confirm display cadence, persistent front preview, measured shutter ratio and a real volume-button save. Passing these checks does not establish dimensional accuracy or resolve the previously recorded full-orbit tracking limitations.

## Build identity and diagnostic cleanup

On October 18, the connected iPhone still had version 0.1.0 (38) installed and running after build 39 became available in TestFlight. Build 38 contains the rear optical-flow renderer; TestFlight availability alone does not establish that its replacement is running. Check the installed bundle version and the running executable before interpreting a preview test. Associate saved sensor evidence with a newly created capture ID, rather than reusing an old diagnostic file.

Build 40 retains build 39's native rear preview and permission handling. It removes the unused selfie preview-buffer cache and the ad hoc front-camera JSON/JPEG diagnostic writes. The native selfie layer never consumed that cache. This cleanup does not change the saved reference's original RGB/depth planes, calibration, timestamps, exposure settings, capture ID or user-selected shutter trigger. The original buffer-copy regression checks remain.

## Selfie flow regression coverage

The current regression checks cover bounded reference windows at 5, 7, 10, 15 and 30 Hz, stale and non-increasing timestamps, saving originals with invalid depth, retaining the saved image after a failed depth check, and the top calibration hint and Save scan layout. These are simulator/code checks; physical continuous preview and volume-button capture still require the connected phone.

## Preserving NV12 samples

Owned NV12 buffers can report a different aggregate row size from the camera allocation even when every plane's dimensions, stride, padding and image bytes are unchanged. Reusing the original format description then fails CoreMedia's image/format check with `kCMSampleBufferError_InvalidMediaFormat` (`-12743`). The old combined error mislabeled that failure as reference timing and stopped the selfie session before saving.

The copy now preserves every original format extension except the allocation-specific aggregate row size, which is set from the owned buffer and checked before creating the sample. Original presentation/decode/duration timestamps, output presentation time, intrinsics, pixel attachments, buffer attachments and per-sample attachments are retained. A regression constructs the failing aligned NV12 case, verifies the former `-12743` result, checks the corrected copy and writes its PNG without changing the source planes.
