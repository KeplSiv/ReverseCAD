# ReverseCAD on-device architecture

This is the normative October 18, 2026 revision for the two released app flows. It supersedes the earlier Mac-service and identify-before-capture revisions. The retained Python backend and service APIs are development/reference tools, not prerequisites or fallbacks in either released flow. There is no cloud geometry reconstruction.

## Product sequence

Both **Scan object** and **Repair damage** use the restored main-branch plum/copper camera UI and the same capture sequence:

1. First use captures synchronized selfie RGB and metric, unfiltered front TrueDepth. A stationary burst is checked numerically and Jev assesses the selected object and surrounding texture. Compatible device-bound calibration is reused later. Jev assesses suitability/identity, never distance or shape.
2. The user moves/resizes a rectangle, initially the middle third of preview width and height. Preview-layer coordinates pass through metadata coordinates into the unrotated camera output. The rectangle is a selection hint; original camera images remain whole.
3. The first orbit captures simultaneous wide, ultra-wide, telephoto and LiDAR on the phone. All four streams must actually deliver frames. Guidance and coverage depend on tracking and accepted camera viewpoints, never the elapsed timer.
4. After capture, the existing bounded direct-phone Jev client compares roughly 8–10 sharp separated views against the saved initial selection. Ambiguity is corrected by tapping the saved reference. Cancellation, key/network/rate-limit errors and retries retain the session.
5. The second detail orbit uses the confirmed identity. A translucent upper-right inset accumulates measured object surfaces. It is a live preview, with open holes, not a promised completed shape.
6. The iPhone performs reference registration, bounded calibration refinement, object masking, camera registration, three-camera correspondence checks, measured-surface fusion and final exports. A Mac, pairing token, service URL and cloud reconstruction are not involved. Jev is the explicit identification/suitability network dependency.
7. The finished model is saved locally and shown with orbit/zoom, observed extents and save/share buttons. A computer is only an optional share destination.

## Implemented geometry

`MultiCameraSession` runs one AVFoundation multi-camera session. Every accepted frame retains full original NV12 planes and JPEGs for all three lenses, original LiDAR, per-frame calibration, individual exposure timestamps, poses and derived local validity. Native confidence is unavailable on this capture path and is not fabricated. `RGBDTracking` uses full-scene bidirectional optical flow, depth/texture gates and rigid metric fits. ARKit is not run in a competing session.

`NativeReconstruction` consumes that same saved session. `SavedObjectMasks` supplies refined same-instance Vision masks with hand rejection. No bounding box is treated as a silhouette. Depth discontinuities and cross-view free-space/mask contradictions reject geometry. Tracking continues to use the full scene.

`NativeRegistration` matches rotation-aware multi-scale binary features and validates rigid fits with distinct held-out correspondences; scale is never fitted. Adjacent saved poses receive bounded rigid corrections. First-pass surfaces are fused only if a measured first-to-detail transform passes these checks. If they do not, the first pass remains identity evidence, its geometry is excluded, and the final report explicitly records this limitation.

`NativeCalibration` registers the saved front reference map against rear RGB-D correspondences, checks held-out metric error, and tests bounded focal/radial corrections. Unsupported corrections remain zero. Compatible profiles require the same device, reference, image format and intrinsic range. A legacy scan without a front reference can still be opened/reconstructed using its recorded scale; new captures cannot bypass first-use setup.

`NativeAuxiliaryStereo` uses physical camera extrinsics (translation converted from mm to m once), pose interpolation at each exposure and no time extrapolation. Correspondences must pass reprojection, baseline, ray intersection, mask and native-depth gates. They refine existing observed samples only; they never populate a hole. Unsupported auxiliary evidence is excluded and counted as such. A camera delivering images is not proof that its samples passed geometry validation.

`NativeSurfaceFusion` welds and averages compatible interior observations at a 2 mm grid. Boundary vertices are protected from welding, and distinct vertices within one observation cannot collapse together. Faces come only from fully supported native-depth cells. It removes duplicate/degenerate faces; it does not run Poisson closure, a convex hull, category completion, hole filling or watertight conversion. Memory is bounded at 240,000 vertices and 480,000 faces. The result can intentionally remain an open, usable surface mesh. Very fine features below sensor resolution are not promised.

## Exports and repair

STL and binary PLY contain the finished measured triangle surface in millimetres. Measurements report observed extents, not guaranteed complete-object dimensions. STEP, when at or below 20,000 faces, is a faceted surface representation with explicit units, planar faces and explicit edge topology; open boundaries stay open. It is labelled **faceted STEP**, not a parametric solid. Larger meshes still export STL/PLY. Files are validated and published as an immutable checksum-verified revision. Raw images, calibration archives, credentials and capture packages are not included in normal sharing.

Repair uses `NativeRepair` on the phone. The supported generator is a flat rectangular part with a measured planar surface, surviving support for all four straight edges, and limited boundary-connected missing regions. Internal holes are preserved. Missing regions are proposals requiring user review; intentional cutouts and occlusion can resemble damage. A measured thickness is required before making separate closed repair pieces. Other shapes return a clear unsupported result while retaining the finished measured model. The older Python cube/general generators are not silently invoked from the phone.

Measured and inferred geometry are separate artifacts and separate blue/orange previews. Exporting a repair never overwrites the measured model. Physical fit, attachment strength and dimensional accuracy require independent measurement/printing evidence.

## Recovery and verification

All computation is off the UI thread and cancellable between bounded work units. Cancellation preserves the input and last complete result. Failed builds cannot publish partial revisions. Retry reuses the capture, and a saved interrupted detail pass can be recovered. Normal UI no longer exposes a connection requirement or substitutes a raw package for a finished model.

Verification is separated into Swift/simulator tests, live Jev API checks, on-phone synthetic execution, actual sensor delivery/tracking/framing, and physical accuracy. The connected stationary sensor run delivered all three cameras and LiDAR; the earlier run drifted about 7.5 mm and does not establish metric accuracy. The user declined the moving-camera test. Full physical orbit, completed front-to-rear field calibration and printed fit must remain explicitly unverified until actually performed.
