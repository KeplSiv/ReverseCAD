# Prelude capture-first scanner

> Current consolidated revision: [Adjustable selection and two app flows](MAIN_CONSOLIDATED.md) on `main-consolidated` supersedes the ordering below. Jev uses the edited rectangle before scanning; the same reference is checked across saved views afterward. Scan and repair are separate flows; repair continues into the existing main-branch CAD component.


Scope: KeplSiv/ReverseCAD, `pranav-dev`, public-API `PreludeScanner` target (`com.pranavmuralitharan.prelude`). `main` is unchanged. Private sparse sensor interception stays in its separate Debug-only target and cannot be archived.

## Workflow

**Frame object → Scan around it → Identify object → Build 3D model → Preview and export.**

1. Open the camera. Show **“Place one object inside the box.”** Description is optional. The rectangular guide is exactly the center third of the rendered preview's width and height. Inverse `ARFrame.displayTransform` maps it to normalized raw-image coordinates for each viewport/orientation. Images, calibration and depth remain in raw orientation. No Jev request is made before or during capture.
2. **Start scan** starts one local session. Show **“Keep the object still. Walk slowly around it, keeping it inside the box.”** Save full-resolution camera JPEGs, available native scene depth and confidence, intrinsics, camera poses and aligned timestamps. No Mac or internet connection is needed. The guide is a framing/initial-selection hint, not a crop or permanent segmentation constraint.
3. Guidance uses tracking, sharpness, accepted views and measured camera positions about a stationary center. **Finish** is always available. A short higher/lower pass is suggested conditionally, without requiring another complete circle. Observed directions are not a guarantee of surface completeness.
4. After Finish, show **“Finding your object…”** Select up to ten sharp separated views, preserving the first usable centered view as identity reference. Reject near duplicates, poor tracking and blur. Sparse sessions can supply fewer views; fewer than three separated usable views require additional capture evidence.
5. Direct phone HTTPS requests to TypeSafe compare each selected image with the same reference. Ask which object is selected at the reference point, its category, whether the same physical instance appears in the current view, its box, and whether hands obscure/touch it. Category alone is not instance identity. Require reference containment, at least three accepted matches and 60% agreement. Ambiguity displays the saved reference image for one tap and retries identification on the existing session.
6. Show **“Building your 3D model…”** Local Vision instance segmentation refines the Jev boxes. Short-range local tracking is periodically reset by confirmed Jev views and stopped by negative selected views. Local hand-pose detection also excludes views with hands over the selected region. Weak, ambiguous, absent or unanchored masks are excluded. Store derived masks separately and bind them to the original image hashes. Do not alter the original images, depth, poses or frame records. Silhouettes can extend beyond the guide and initial Jev box.
7. **Before Build**, explicitly state that reconstruction runs on the Mac and needs its reachable companion service. Upload/resume the saved session with derived masks. Backend geometry uses masks, native depth/confidence, support-plane rejection and cross-view measured overlap. Full images are retained for tracking. Jev supplies selection only; captured geometry and supported scale supply shape and dimensions. No category mesh, guessed hidden geometry or automatic hole filling is allowed.
8. Present the existing rotatable, zoomable geometry preview and observed dimensions. Separate **STL**, **PLY**, **STEP** and **Measurements** export buttons use the existing hash-verified artifacts. STEP is conditional and explicitly a faceted observed surface, not a parametric solid. Unsupported STEP is explained; other formats remain available. Insufficient reconstruction preserves the capture, explains missing evidence and withholds measured exports.

## Network, cancellation and persistence

Identification is sequential, one request per selected view, at most ten requests per attempt. Each carries two resized full-frame images (maximum long edge 1280; no crop), with boxes normalized back to the original coordinates. Request timeout is 15 seconds and resource timeout 20 seconds. There are no hidden automatic retry loops. Cancellation cancels in-flight requests and invalidates late completions. Retry acts on saved files, never restarts capture. Rate-limit cooldown honors `Retry-After`, bounded to 1–300 seconds. Missing key, 401, 402, 403, 429, offline, timeout, malformed response and service errors are distinct.

Confirmed identity is saved in the project with the source frame-record hash and reloads without another Jev call. Original capture files remain unchanged; derived masks have unique generation paths under `masks/objects/`. Upload hashes include the masks. Reconstruction masks with mismatched image/mask hashes fail closed. Unconfirmed views never fall back to table/center depth in this flow. Existing legacy capture modes retain their prior behavior.

The personal key comes from the existing Git-ignored `ios/PrivateResources/PreludeJevConfig.plist`. It is absent from capture exports, identity records and logs. The release script verifies the resource in the internal-only IPA and rejects private sensor symbols. The previous live-detection helper remains unused by the standalone flow.

## Reconstruction and limits

Run the existing service with `scripts/start_service.sh --lan --port 8769` and configure its URL and pairing token under Connection. This revision does not claim on-device reconstruction. The app checks the `capture_first_masks` capability before upload and refuses older services. Capture-first mask support requires the matching backend revision; update the Mac service before processing these scans.

Apple scene-depth and visual-inertial poses provide the current public-path geometry/scale. Camera-only captures are retained when depth is unavailable, but this backend may require depth to produce measured geometry. No physical accuracy, fit, fresh sensor performance or complete surface coverage is established by builds, simulator runs, API fixtures or synthetic exports.

## Verification

Shared tests exercise thirds/display mapping, representative selection, near-duplicate rejection and multi-view consensus. Native tests exercise zero-description requests, bounded direct calls, saved-session reload, ambiguity/tap retry, authentication retry, in-flight cancellation, rate-limit cooldown and native Vision mask formats. Backend tests cover masks extending outside the guide, missing identity fail-closed behavior, source binding, disjoint-object rejection, support removal and observed STL/PLY/STEP export. The verification report records actual results and remaining physical-phone/measurement checks.
