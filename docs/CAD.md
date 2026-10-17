# CAD template and validation contract

`backend/reversecad/cad.py` implements deterministic, bounded CadQuery/OpenCascade generators. `cad_validation.py` checks their exported geometry independently using STEP reimport, Trimesh and Open3D. The API is:

```python
from pathlib import Path
from reversecad.cad import generate
result = generate("bridge_handle", {"span": 80.0}, Path("output"), context={})
```

All generator parameters, vertices and reported geometry are millimeters. ARKit contacts enter as `point_m` and are converted exactly once. `T_object_part_mm` is a rigid column-major 4×4 matrix with millimeter translations. The app converts preview millimeters to meters exactly once. No measured parameter is scaled or adjusted to make a Boolean operation succeed.

## Templates

The live machine-readable catalog is `template_catalog()`, also exposed through service capabilities. It contains defaults, numerical bounds and generator version. Cross-parameter constraints are checked by `normalize_parameters`; being within an individual slider range does not guarantee a viable combination.

| Family | Geometry and parameters | Canonical frame |
| --- | --- | --- |
| `bridge_handle` | Half elliptical annular grip, rectangular pads, optional through holes. `span`, `standoff`, `grip_width`, `grip_depth`, `pad_width`, `pad_length`, `pad_thickness`, `hole_diameter`. | Mount centers at `(±span/2,0,0)`. Object-facing pad plane Z=0. Grip extends +Z. Width extends Y. `standoff` is ellipse centerline height measured from pad midplane; maximum Z is pad_thickness/2 + standoff + grip_depth/2. |
| `cup_handle` | Two actual curved annular-sector saddle pads, joined by a half elliptical grip. `cup_radius`, optional `cup_radius_top`, `contact_spacing`, `standoff`, `grip_width`, `grip_depth`, `pad_height`, `pad_thickness`, `contact_gap`. Linear taper limited to 0.2 radius change per axial mm. | Cup axis Z. Lower/upper contact centers at Z=±contact_spacing/2, on +X. Radius parameters are at these contact heights. Width extends Y. Contact pad arc width is derived from grip_width and radius. |
| `bracket` | Flat rectangular plate, or integral 90° L when leg_height>0; two configurable mounting holes. `width`, `length`, `thickness`, `leg_height`, `hole_diameter`, `hole_spacing`, `hole_offset`. | Base X width/Y length, bottom Z=0. Leg at Y=−length/2. Hole centers at `(hole_offset,±hole_spacing/2)` in the base. `leg_height=0` selects flat. |

Cup saddle generation requires `context.attachment_method == "saddle"` and `context.saddle_approved == true`. Unsupported surviving-stub attachment is rejected instead of silently becoming a saddle. Missing material and grip shape are design proposals; the generator never labels them sensor observations.

The v1 bracket has two base holes and a fixed 90° leg. Nonorthogonal mating planes, independently offset multi-hole arrays, threaded holes, and reconstructed irregular cup fracture surfaces need a different template or additional evidence. These cases are not silently approximated.

## Evidence and placement

`context.contacts` is a list of `{id,point_m:[3],normal:[3],radius_mm}`. `observed_points_mm` is the registered reconstructed point cloud. Optional context includes `measurements`, `manufacturing`, `scan_revision`, and an explicit rigid `T_object_part_mm`.

A bridge uses the two selected contact points and average outward normal. Span and normal-offset residuals are reported; an offset exceeding 2 mm requests input rather than flattening the observations. Contact normals must be compatible. A cup uses the two contact points and the selected outward radial direction; the radius difference is checked against observed contact offset. Flat brackets require coplanar selected patches. An L bracket requires two normals at 90°±5° and a second patch within the generated leg height/width. Their two mating planes determine a rigid placement; the confirmed dimensions are retained.

Missing contact patches leave geometry in its documented canonical frame with `placement.status=needs_input`. The report never implies that canonical preview alignment matches a scan.

Critical dimensions must have matching confirmed evidence in `context.measurements`, using an ID or normalized name equal to the parameter name, unit `mm`, and a value agreeing within 0.1 mm. Required critical dimensions are bridge span, cup radius/contact_spacing (and upper radius for taper), and any enabled hole diameter/hole_spacing. Editing a critical value invalidates its old confirmation. Parameter provenance, observation references and uncertainty are retained in `parameters.json`.

## Exports and reproducibility

Each accepted CAD revision writes:

- `part.step`: genuine valid one-solid BREP declaring millimeters.
- `part.stl`: watertight mesh; STL has no unit field, so the report explicitly declares mm.
- `part.3mf`: native CadQuery export with a millimeter unit declaration, independently reimported.
- `preview.json`: millimeter vertices, triangle indices, vertex normals and a replacement material group.
- `part.py`, `generator.py`, `parameters.json`: complete trusted parametric regeneration source, numerical values, evidence provenance and placement.
- `coupon.step`, `coupon.stl`, `coupon.3mf`, `coupon.json`: a single mount-hole/contact-thickness coupon or curved cup saddle radius/contact-gap coupon.
- `validation.json`, `report.txt`, `manifest.json`: detailed checks, unresolved evidence, revision identifier and SHA-256 hashes.

The revision ID hashes normalized parameters, generator version, scan revision, placement and parameter provenance. The manifest lists output sizes and hashes; it does not include its own hash. The service adds the manifest's artifact hash when publishing it. STEP is interoperability geometry; the Python generator and parameter JSON retain editability.

With the pinned environment, an exported source is runnable independently of the service:

```sh
/path/to/reverse-cad/.venv/bin/python /path/to/export/part.py
```

Edit `parameters.json` and rerun to write `edited.step`, `edited.stl`, and `edited.3mf`. Run the changed parameters through the service to obtain a new independently validated revision. Source regeneration does not overwrite the original part exports or claim new validation.

## Actual checks and limits

1. **BREP:** valid closed positive-volume single solid. Independent analytic bounds verify bridge/bracket dimensions; cup probes verify inner saddle radius and gap at both heights; circular BREP edges verify hole diameter and location.
2. **Export round trips:** STEP is reimported and checked for validity, one solid, explicit mm and maximum bound change≤0.1 mm. STL/3MF are independently loaded with Trimesh and checked against precise OpenCascade bounds within 0.05 mm tessellation allowance +0.1 mm. Cached tessellation bounds are not used as the solid oracle, because transformed B-spline bounds can be inflated.
3. **Meshes:** watertight edge incidence, consistent winding, positive volume, one connected component, no zero-area faces, and an independent Open3D triangle self-intersection test. These run on actual exported meshes.
4. **Thickness:** template constraints preserve wall/edge allowances. An independent STL check casts up to 256 area-stratified inward surface-normal rays; the smallest exit chord is compared to the greater of the profile minimum wall and two nozzle diameters. This sampled chord test is not a proof of global minimum wall thickness or strength.
5. **Observed collision:** at most 4,000 evenly sampled observed points are tested against the placed mesh. Noncontact penetration>0.2 mm fails fit. Intentional contact patches are separate, and excessive penetration within a contact is also rejected. No points are moved or geometry resized to hide interference.
6. **Contact evidence:** each selected patch requires at least three of five geometrical probes at the intended contact gap (default tolerance 0.75 mm). It also requires at least three nearby observed points matching that gap and a noncollinear second-axis spread of at least min(0.5 mm, 10% of patch radius). A fabricated annotation with remote scan points cannot pass. Hole centers may be empty if the surrounding patch is supported. These checks do not establish actual bond area or scan calibration.
7. **Assembly:** observed geometry is checked along an outward straight translation over part extent+20 mm, capped at 240 mm, with steps≤2 mm. The report distinguishes final-pose interference from an obstruction along the path. Unobserved surfaces, obstacles between samples, tool access, flexible assembly and rotations remain unverified.
8. **Printing:** configurable nozzle, layer height, minimum wall, material label and build volume. Axis-permuted bounds check available volume; downward surfaces above the current Z print bed flag supports. Slicer review and printer calibration remain required. No load rating, stress field or adhesive strength is invented.

`validation.cad_valid` and `validation.passed` refer only to valid geometry/exports. `status=needs_input` and `ready_for_test_print=false` remain when contact alignment, observed fit, manufacturing or critical dimension confirmation is unresolved. A service request can explicitly acknowledge unresolved fit to export a prototype; that does not clear unresolved fields or change `physical_fit=not_tested`.

## Automated evidence

Run from the repository root:

```sh
.venv/bin/pytest backend/tests/test_cad.py -q --junitxml=reports/cad-tests.xml
```

Tests include three independently specified bridge sizes, three bracket configurations, cylindrical and positive/negative mild taper cups, invalid/unknown/nonfinite parameters, explicit attachment approval, standalone source editing, transform placement, hole/unit checks, mesh corruption and overlapping triangles, thin walls, collision/contact versus assembly obstruction, remote contact patches, missing contact observations, wrong mating-plane angles/offsets, and missing/stale critical confirmations. These are automated software geometry tests; none measures an iPhone or a printed object.

Pinned runtime verified here: CadQuery 2.6.1, Trimesh 4.6.8, Open3D 0.19.0; native 3MF reimport additionally uses NetworkX 3.4.2 and lxml 5.4.0. The complete dependency lock is `uv.lock`. CadQuery's [interchange documentation](https://cadquery.readthedocs.io/en/latest/importexport.html) explains why source is delivered separately from STEP. Export capabilities were verified on the installed versions rather than assumed from the documentation.

Critical confirmation is limited to actual manual/depth-fit/multiview measurement sources; `design_inference` remains unmeasured even if a model marks it confirmed. Confirmed critical uncertainty must be known and, conservatively adding 0.05 mm CAD tessellation allowance, stay within `fit_tolerance_mm` (default 0.75 mm). Unknown/excessive uncertainty leaves a prototype in needs-input. This numerical budget does not include an unmeasured printer error; the physical coupon establishes that separately. Service-generated manifests also retain exact capture manifest/checksum and intent SHA-256 digests, scan/repair IDs and numeric revision.

Generator 1.0.1 writes standard ASCII STL with 17-significant-digit coordinates from the original CadQuery tessellation. The native binary STL writer stores float32: a slightly rotated handle selected through the native UI exposed one false surface crossing after that coordinate quantization, despite a valid BREP and double-precision 3MF. Retaining tessellation precision removed the crossing without moving vertices, altering measured parameters, changing the placement, repairing topology, or relaxing validation. The exact synthetic UI contact selection is retained in `fixtures/cad/rotated-contact-precision.json`; its regression also checks standalone `part.py` regeneration and coupon encoding. Slicers that reduce imported precision still need their own geometry review.
