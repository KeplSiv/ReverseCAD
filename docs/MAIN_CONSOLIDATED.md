# Consolidated Prelude: scanning and damage repair

Branch: `main-consolidated`. Base: `pranav-dev` including current `main` (`754c0661f97d4b4c1e74ca2cb60519113c1d6c54`). The user subsequently requested an immediate merge into `main`; the consolidated changes are published to both `main-consolidated` and `main`. `pranav-dev` is preserved. The separate experimental sensor/reference work is not merged.

## Two app flows

- **Scan an object:** adjust the rectangle → identify the selected object → scan around it → build the observed model → preview and export.
- **Repair damage:** the same selection, identification and capture → build the observed model → main's existing damage analysis → review the proposed CAD and export supported repair pieces.

Both flows reuse the public-API scanner, saved sessions, refined masks, reconstruction, preview and export code. Saved projects retain their flow, so a repair remains in the repair list even while its initial object model is being built.

Both flows use the original main-branch visual system: plum backgrounds, copper accents, rounded surfaces and the same primary/secondary controls. Home, selection, capture, saved scans, preview and repair review share this styling.

## Adjustable selection

The initial guide is the center rule-of-thirds cell. Drag any corner to resize, or drag inside to move it. Keep bounds within the preview and a minimum usable size. Map the user's edited rectangle through the inverse camera display transform. Jev receives that raw-image rectangle explicitly with the full reference image, not a destructive crop. Identification runs only when the user taps **Identify object in box**. Moving or resizing the box invalidates the previous identity. **Start scan** becomes available when one object is identified.

Store the original selection image in the capture as `rgb/selection-reference.jpg`, with its hash, raw bounds and Jev result in the project selection record. Capture still saves full images, available depth/confidence, poses, intrinsics and timestamps locally. No continuous Jev loop or Mac connection is used for capture. Original images and frame records remain unchanged.

After capture, use the earlier selection image and rectangle as the identity reference for roughly 8–10 sharp separated saved views. Verify the same physical instance and category across views. A correction can select a point in that same saved reference; it does not require recapture. One initial request, up to ten post-capture requests, and at most one additional reference request for a correction are bounded and cancellable. Network/key/rate-limit failures keep the saved session.

## Geometry and repair handoff

Local segmentation refines boxes into masks. Exclude unconfirmed views and hand overlaps; gate geometry by native depth/confidence and cross-view consistency. The framing rectangle and semantic category do not provide shape or measurements. Full-image tracking evidence is retained. Holes and unseen surfaces remain missing in the observed scan.

The scan-only flow stops at the existing measured preview and STL/PLY/measurements/conditional faceted STEP exports. The repair flow continues only when the object reconstruction is ready. Keep its original reconstruction/export index alongside the later repair revision, then invoke the existing `automatic` main-branch router on the same capture. Confirmed masks define per-view padded search regions, and background-only repair candidates are rejected. No second capture is required.

Main's existing repair component currently supports planar rectangular parts and repeated 3×3 cube faces. Unsupported or ambiguous damage asks for a supported shape or more evidence; it does not invent a general repair. Proposed geometry, inferred thickness/connectors and physical-fit uncertainty remain explicitly separate from measured scan geometry. The existing review toggle and measured-thickness controls gate repair export.

The Mac service must advertise `capture_first_masks` and `consolidated_object_repair`. The app explains that reconstruction and CAD run on the connected Mac and refuses incompatible services. The personal Jev credential stays in the existing ignored resource, outside Git, logs and capture exports. Private sensor interception stays in its separate research target.

## Verification boundaries

Verify rectangle movement/resizing and rotated/cropped coordinate mapping; request binding to the edited box; selection-image preservation and post-capture reuse; no live request loop; ambiguity/cancellation/retry; flow separation; same-session damage handoff; object-mask filtering; existing damage/CAD checks and exports. Simulator, synthetic and API checks do not establish actual phone sensing, segmentation quality, dimensional accuracy or physical fit.
