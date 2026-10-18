# Preview and front-reference update

The October 18 follow-up changes the viewing and shutter experience. Rear capture formats, original frame retention, accepted-view selection, calibration, registration and reconstruction remain unchanged.

## Display only

`SmoothCameraRenderer` draws a 1920 × 1080 landscape or 1080 × 1920 portrait surface at a requested 60 Hz. A small optical-flow proxy interpolates between incoming camera images. The normal preview layer remains the authority for framing-coordinate transforms. The smoothing stage only reads camera buffers; its images and flow never enter saved captures, tracking, segmentation, dimensions or exported geometry.

The front reference uses its native, undistorted-by-the-app preview layer instead of image-warp interpolation. This avoids moving-subject distortion and displays the actual full reference framing. Its source cadence follows the highest-resolution TrueDepth-compatible camera format; it is not labelled as 60 unique source frames per second.

This is a smoother rendered preview, not a claim that a lower-rate sensor suddenly supplies 60 unique frames per second or additional native image detail. Native capture resolution and cadence remain separate. Display interpolation adds approximately one source-frame interval plus processing latency. A device diagnostic records actual rendering rate rather than assuming the requested rate was achieved.

## User-selected front reference

Opening the front-reference flow starts the selfie camera automatically. The primary action stays at the top, followed by a short instruction, a flexible full-image preview and a short status. The screen has no scroll view. Saved-reference review and retake use the same layout.

The native preview layer is attached immediately. While the camera starts, a themed “Opening selfie camera…” cover stays visible until AVFoundation reports that the layer is ready to display its first frame. Startup does not wait for the depth-quality or exposure checks. Camera permission and hardware startup can still take time; the screen does not present that delay as an empty black preview.

The front camera stays open until the user presses **Save scan**, presses a volume button, or closes it. The former eight-frame auto-finish and 20-second timeout are removed. A bounded rolling window retains eight recent sharp, synchronized RGB/TrueDepth samples in memory. Save freezes that window, preserving the original image/depth buffers and metadata. Existing numerical stability and scene-suitability checks still apply. A failed stability check retains its evidence and leaves the camera open for another Save attempt.

The rolling window owns independent copies of the image/depth planes, including original row padding, timing and calibration attachments. It does not retain camera-pool buffers that could starve capture and freeze the live view. Display processing also renders to owned proxy buffers.

After auto-exposure settles, the requested selfie shutter duration is half the measured baseline, clamped to the hardware minimum. ISO compensates where its supported range permits. Baseline and actual exposure are recorded for verification. This reduces exposure-time blur; it cannot guarantee a blur-free result if the camera or object moves.

System capture-button APIs handle volume-button release. They are enabled only when the capture action is available. On the rear camera they start or finish the current pass; on the front camera they perform the same action as Save scan. No private button notifications or volume-setting tricks are used.

## Verification

Simulator tests cover interpolation between known translated images, preservation of source images, fresh-window requirements and shutter limits. Phone checks must separately confirm display cadence, persistent front preview, measured shutter ratio and a real volume-button save. Passing these checks does not establish dimensional accuracy or resolve the previously recorded full-orbit tracking limitations.
