# Rectangular planar repair — local phone prototype

## Decision and scope

The default app flow now completes boundary damage on an explicitly assumed rectangular, planar part. It uses captured RGB edges, calibrated camera intrinsics and native depth plane distance. It does not require a consistent room mesh. The user reviews the inferred rectangle and ghost on the actual capture. Unknown sheet thickness blocks solid export; a measured thickness produces individual STL patches, a combined STL/3MF and a STEP solid.

Several disconnected missing corners are supported in this planar model. Multiple missing Rubik's cubies and removed corners of solid 3D blocks are **not validated or completed by this implementation**. Cube reconstruction remains accessible as an experimental mode.

The surface detector uses image contrast. It requires substantial surviving segments of all four original edges, the whole outline inside the image, a near-planar depth sample, and a plausible calibrated rectangle. White paper on a dark tabletop is the demonstrated case; other materials remain to be tested physically. It does not identify arbitrary design intent or recover hidden mechanisms.

## Research basis

- [Criminisi, Reid and Zisserman — Single View Metrology](https://ora.ox.ac.uk/objects/uuid%3A9b99df78-df75-49a9-a1b8-1b38e1b173a8): geometric relationships and vanishing directions constrain planar measurements. This implementation uses those principles with camera intrinsics and depth scale; it is not a reproduction of the entire paper.
- [OpenCV homography documentation](https://docs.opencv.org/4.11.0/d9/dab/tutorial_homography.html): a planar surface supports a perspective mapping. We derive the four supporting image lines, check their camera-space orthogonality, and rectify the contour.
- [CAD-Recode](https://github.com/filaPro/cad-recode), [DeepJoin](https://github.com/Terascale-All-sensing-Research-Studio/DeepJoin), and [SymmCompletion](https://github.com/HKUST-SAIL/SymmCompletion) remain research candidates for richer objects. They have not been benchmarked as repair generators on these paper scans. The known rectangle assumption lets us compute the missing area explicitly without guessing a learned shape prior.

## Actual saved input

- `0DB4857E-AC4E-4BFB-9BA0-84360B02969E`: previously failed in the cube pipeline. The planar replay finds **one missing region**, creates a photo overlay, and estimates an approximately **291 × 212 mm** original sheet. Those dimensions are uncalibrated estimates, not a measurement certificate. Two selected views gave dimensions within 5% of the chosen view.
- `0FF793E8-ED6E-4C42-B8EC-32A8A6AB0AC0`: the visible sheet is cropped by the image boundary. No reliable full rectangular outline was produced. It remains unresolved; this is not counted as success.
- The removed fragment is visible separately in the successful capture, but is curled and oblique. No quantitative physical-fit validation against it has been performed.

`reports/planar-real-replay/planar_overlay.jpg` shows the inferred boundary and missing region on the source photograph. The exported solids in that folder use **3 mm solely as a software validation parameter**. This is not the measured thickness of the paper. On the phone the field starts empty.

## Verification

- Independent polygon cases: two missing corners at three scales, intact rectangle, non-rectangular negative, cropped-image negative.
- Concave patch extrusion checks volume, topology and reloaded STL dimensions.
- Multiple patches survive 3MF export as two separate closed bodies.
- Real capture export: STL and 3MF reopen as one closed solid with matching dimensions.
- Authenticated Mac service replay: stored scan to ghost artifacts with thickness unresolved.
- Signed iOS device build and direct install.

These checks establish software behavior. They do not establish printer tolerances, dimensional accuracy or functional fit.

## On the phone

The main camera captures a short three-second sequence while held still. The result has Original / Ghost / Piece views. Saved scans can be reopened and reprocessed with this workflow. Confirm the outline, enter measured thickness, create the solid, then export. Keep the paired Mac service running on the reachable network.

No GitHub push was performed.

## Saved scan identity and obsolete chooser — 2026-10-18

The user identified the 11:34 PM scan as the preferred capture. Its actual
project is `FE5184CE`, scan `95B2CBEB`; it is the successful face-first replay
above. The 11:54 PM project `50258C29` has a different 38-frame raw capture,
`05061206-CA89-4B3C-917F-20AED9DCEADA`, but its phone-side reconstruction was an
old `rgbd-1.4.2` comparison result carrying the 11:34 scan's ID. None of its
comparison variants contained a closed replacement. That explains the stale
method chooser and absent ghost without attributing the failure to scanning.

Removed the comparison panel and comparison action from the normal cube result
screen. Normal processing now defaults to a single repair workflow. Legacy
cube results are refreshed when opened. Loading, receiving, previewing, and
exporting results now check scan identity; processing also retains its original
project identity across async work. Starting a new capture while another scan
is processing is blocked in both the view and model. Mismatched cached files
are preserved but never displayed or exported as another scan's result.

Uploaded the actual 11:54 capture to the paired local service and replayed it
with no manual dimensions or color classification. Job
`464a40ce479a46f29dcc5f01138b0359` completed in 42.1 seconds: 23 photos aligned,
nine views supported the face and donor, and a closed exterior test piece was
generated. Original/ghost/solid evidence is in `reports/face-first-1154-scan/`.
Its inferred face width is 62.0 mm versus 67.8 mm for the 11:34 capture; this
variation reinforces that physical scale and fit are still uncalibrated.
The repair remains an observed front outline with inferred side extrusion,
not reconstructed internal attachment geometry.

Twenty focused iOS tests passed, including rejection of mismatched cached
results, mismatched downloaded responses and artifact records, and blocking
project creation during processing. The updated signed build was installed.
The 11:54 result was downloaded through the app; its saved scan ID was checked
and all 13 downloaded artifact hashes matched the service output. The 11:34
result remains the preferred test capture. No new physical scan was required.

## Guide region and startup regression (planar-1.1)

The original guide was visual only. New planar captures now record its normalized raw-image rectangle on each frame, using that ARFrame's inverse display transform and the actual ARView viewport. The guide is drawn and measured in the same view. Segmentation statistics and contour search are restricted to that region; candidates touching its boundary or predicting a rectangle outside it are rejected. Output photographs are cropped to the analyzed region. Legacy captures have no saved guide coordinates and retain their previous full-photo search.

Single-frame planar reconstruction no longer requires a normal ARKit world pose. A limited-tracking frame still has to pass the same depth-confidence, planarity, calibrated rectangle and edge-support checks; world poses are not used in this path. This recovers scan `6C51653D-DB25-498D-BEBE-49288E7F69C5`, frame `000002`, as one missing region. Authenticated service replay completed with one region. The other recent capture `365D7292-A9C3-4F52-9176-3319AC84F00C` remains unresolved.

Ten planar tests pass, including outside-guide distractions, guide-clipped objects, and a calibrated synthetic single-frame limited-tracking end-to-end case. Device build, install and launch succeeded. The first new physical capture with recorded guide coordinates still needs user validation; no claim of physical fit is made.

## Shared capture boundary

The guide is now required for every live CaptureController start, including cube experiments and the legacy workflow. All modes use the same ARView guide and per-frame inverse display transform. The backend's shared `capture_region.py` maps that metadata without changing image calibration. The boundary is enforced in native-depth selection (including manual mask overrides), ORB, COLMAP feature masks and scale sampling, stereo in both cameras, cube face detection/tracking, learned comparison inputs and reasoning image inputs. On-phone foreground masks used by live ghosts are also clipped. This restriction selects an area; it does not guarantee separation of an object from background remaining inside that area.

Forty focused backend tests pass, including the ORB boundary guard; the suite includes actual COLMAP extraction and a stereo test where changing all out-of-guide pixels leaves the depth result identical. The former cube capture `93F89437-80A6-4ACD-9B62-2851E60624E4` contains 27 frames with no guide metadata, so its original on-screen box cannot be replayed exactly. No successful cube replacement is claimed from this fix. A new guided capture is required to validate the physical cube workflow.

## Latest guided cube and camera layout (2026-10-17, 23:22)

Scan `506E6750-7676-49A9-BBD1-A69F7C58DF8F` records capture regions on all 26 frames; 22 photos registered. Its original failure was not an omitted boundary: the cube frame oriented each normal toward the average camera position, which can be behind a face during an orbit. This incorrectly reduced one inferred extent to 1.93 mm. Exterior normals now point away from the observed neighboring face material; a half-space check rejects planes crossing substantial material. Replaying the saved photo poses and calibrated stereo recovers extents 53.81, 57.26, 55.37 mm, with median plane residuals 0.32–0.35 mm. These are uncalibrated estimates, not verified physical dimensions.

The same replay still does not generate a replacement. Its strongest edge has recessed depth support on 2.67% and 2.22% of the two sampled faces, below the existing 25% requirement. No threshold was relaxed. Failed gap checks now retain frame dimensions and per-edge evidence in `cube_exterior_evidence.json`, and explain the insufficient matched recess depth. Missing regions remain unknown when stereo provides no measurements.

The camera now occupies its own viewport between header and capture controls. The shared guide is centered in that viewport, cannot overlap those controls, and keeps the same inverse-display-transform contract. Taps outside the guide cannot select foreground. Simulator layout inspection and a viewport-centering XCTest passed; 16 focused boundary/cube tests passed, including an orbit whose average camera is behind an observed face. Device build, installation and launch on Saran’s iPhone succeeded. No new GitHub push was performed.

## Donor inference without dense gap depth (2026-10-17, 23:49)

Implemented a photo-supported alternative to the dense-recess gate. It requires the same edge to break a mostly solved face pattern on both adjacent faces, in at least three separated views per face. Positive surviving-surface evidence vetoes a placement. This is an explicit cube/appearance hypothesis requiring visual review, not proof that a dark region is empty or a general object-completion model.

Plane fitting now evaluates multiple triplets. When one face is weak, orthogonality from two candidate planes constrains its normal while actual samples still determine its offset and must pass extent, half-space and residual checks. A photo-only initialization can triangulate a consistent square outline with held-out-view checks when three depth planes are unavailable. Unresolved inputs still fail rather than supplying a preset cube size.

A donor no longer requires a complete TSDF triangle patch: validated stereo samples establish two-face support and independently photographed donor outlines constrain the fallback exterior. Raw sparse relief produced spikes during visual review and was rejected. The released fallback forms a clean convex solid between two fitted donor profiles with inferred backing/transition surfaces. It does not claim recovered ridges, recesses, internal connectors or physical fit. Dense supported mesh donors retain their existing path. Radial interpolation also now interpolates displacement from the nominal envelope, fixing artificial bulges on a flat donor.

Fresh normal service job `196f96bfff8347f788b0230df6107150` completed for saved scan `506E6750-7676-49A9-BBD1-A69F7C58DF8F`: a separate STL and 3MF, one watertight body, positive volume and no self intersections. Both exported formats were reopened and validated. The donor's two profiles had 6 and 14 supporting photos with 95.7% and 96.1% mask agreement. Cube width estimate: 54.30 mm; prototype bounds: 17.18 × 17.04 × 17.60 mm. These dimensions remain uncalibrated. Files are copied to `reports/donor-saved-scan/` and downloaded through the normal verified-artifact flow to the phone. The phone project records `Scan reconstructed`, `cube_exterior`, and no pending job.

The newer 18-photo scan `95B2CBEB-BED4-4646-8FCF-378ED6FC8116` remains unresolved: both the dense-plane fit and the calibrated photo-outline initialization fail. The earlier successful scan is not evidence that this newer capture works. Twenty-four focused backend regressions pass, including no-depth photo nomination, intact-object/one-face/duplicate-view/collision rejection, donor ridge coordinate transfer, flat-donor bulge regression, photo-profile closure/export, and metric photo-frame recovery. The explicit diagnostics cleanup XCTest also passes. Device build, installation and launch succeeded.

Fixed saved-library routing: opening a cube or non-planar scan no longer automatically reprocesses it as a rectangle. Removed 14 preexisting `capture_diagnostics.json` files from the phone using a one-shot debug maintenance command, updated only the corresponding checksum entries, and verified no old copies remained. New captures may create new diagnostics. Photos, depth and scan records were preserved. No GitHub push was performed.

## Latest-test evaluation — 2026-10-18

Inspected the two newest uploaded captures, E1E7F475 (5 frames) and C276FDFC
(6 frames). Both depict a torn white sheet inside the saved camera guide. The
RGB segmenter produces candidate outlines, but every depth-bearing frame fails
the existing 80% plane-support check at 3 mm. This precedes rectangle fitting;
the old generic “outline not resolved” message misidentified the failure.
Updated the error to distinguish depth rejection, without relaxing the export
checks. One frame per capture has no depth. These captures remain unresolved.

Replayed the last cube capture 95B2CBEB with its saved COLMAP poses. Eighteen
photos align, but automatic face detection produces only two high-confidence
edge detections among those aligned views. Existing planar tracking cannot
extend either into neighboring photos. Visual inspection of their projected
polygons shows that the second detection includes background and puts the gap
at the wrong end of the face. Its “high confidence” label is therefore not
reliable evidence of a correct face. The multiview rejection prevents this
hypothesis becoming a printable part. This is a detection/correspondence
failure, not evidence that another whole scan is required.

Saved an evaluation illustration in
`reports/latest-scan-evaluation/cube-photo-hypotheses.jpg`. These are diagnostic
2D hypotheses, not successful replacements. A paper-style next step should
validate each local face boundary and carry its identity across views before
using it to constrain a donor's 3D placement. Preserve the distinction between
an image-space preview and a dimensioned printable solid.

Preview fixes: comparison proposals default to piece-only; the preview has a
260-point minimum height; camera fitting uses only visible geometry, honors the
viewport aspect ratio, and refits after layout. It no longer imposes a 15 mm
minimum radius on tiny parts. An XCTest checks projection inside narrow/wide
viewports and excludes a hidden distant scan. XCTest passed; device build and
installation succeeded. Focused planar, photo-donor, and guide tests: 26 passed.
No GitHub push. No new valid cube replacement generated in this evaluation.

## Grayscale face-first replay — 2026-10-18

The next implementation replaces the cube route's dense-mesh prerequisite with
grayscale repeated-boundary detection, masked planar tracking, a calibrated
square-face fit, and an observed intact edge outline. Sticker hue and saturation
do not classify the face, donor, or gap. An independent outline pass prevents an
intact tile dropped by the initial RANSAC fit from becoming a false missing tile.
The general camera guide remains enforced before feature extraction/tracking.
Paper candidate segmentation now also uses brightness contrast without hue or
saturation; its multiple-region subtraction and export logic are unchanged.

Normal service job `4a9e5d1404424fdd823800f29e57e282` on saved scan
`95B2CBEB-BED4-4646-8FCF-378ED6FC8116` completed in 36.4 seconds. Eighteen
photos aligned; three views supported the damaged face, and two supported the
opposite intact edge outline. The inferred missing location is row 1, column 0.
The held-out corner error was about 0.8% of the face width. The separate STL and
3MF are each one watertight, positive-volume body; the mesh has no detected
self-intersections. Mirrored camera frames preserve outward preview winding.
Original, ghost, model, metric evidence, and service artifact hashes are in
`reports/face-first-saved-scan/`.

This is an exterior test prototype. The front rounded outline is observed;
straight side extrusion and depth use a regular-cubie assumption. This replay
does not recover connectors, tiny surface relief, or validate physical fit.
The inferred full face width is about 67.8 mm; absolute scale is uncalibrated
(native-depth/photo scale samples have about a 9.8% relative P10–P90 half-range).
A plausible overlay is not a dimension-accuracy measurement. The new path
supports one missing edge, not cube corners or multiple missing cubies yet.

Validation: 45 focused backend tests passed, followed by the additional mirrored
preview test and a hue-change test with identical grayscale boundaries. These
cover intact-grid rejection, all four edge positions, guide exclusion, closed
export volume/placement, photo matching, and multiple planar patches. Replaying
saved paper scan `0DB4857E` still produces a reviewable missing-region outline.
The signed iOS build passed and was installed on Saran's iPhone. The first
successful normal service result (`0f36b473`) was downloaded by the app and its
verified artifact directory was confirmed on the phone. The app presents
Original / Ghost / Piece and requires reviewing the ghost before exporting.
The final corrected result (`4a9e5d14`) was subsequently loaded on the phone;
all 13 downloaded artifacts were copied back and matched their service hashes.
No GitHub push was performed.
