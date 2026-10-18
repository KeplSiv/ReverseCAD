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
