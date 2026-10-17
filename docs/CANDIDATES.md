# Evidence-linked repair candidates

`backend/reversecad/candidates.py` provides the pure function
`propose_candidates(reconstruction, annotations, family, attachment_method)`.
It produces bounded deterministic design hypotheses and never calls a model.

- Bridge span comes from the selected contact separation projected into compatible mating planes. Noncoplanar or incompatible planes request more evidence. Missing holes remain disabled and explicitly unresolved until independently measured.
- Cup candidates require a fitted cylinder/frustum and two selected contacts on the same radial side. Radius is evaluated at each selected axial height; the existing fit's origin, axis and taper remain unchanged. Contacts outside observed profile support or on unsupported stubs are rejected. The user must explicitly select saddle attachment.
- Bracket candidates select flat or L-shaped templates from selected mating-plane normals. Arbitrary angles/parallel plane offsets are unsupported. Hole pattern, offsets and physical dimensions still require user confirmation.

The alternatives differ in new design parameters: clearance, grip section, thickness or width. Confirmed manual dimensions are preserved. Derived observations include deterministic IDs, source references, derivation and uncalibrated uncertainty. They are not confirmations. Missing geometry, symmetry and fragment assumptions remain explicit in the rationale.

The response contains `candidates`, `questions`, `evidence_notes` and
`derived_measurements`. A `needs_input` response may include useful candidates;
it means further evidence is required, not that no hypothesis can be displayed.
Candidate IDs bind parameters and evidence. Any service accepting a candidate ID
must recompute it against authoritative reconstruction/annotations before using
derived measurement references. Never trust phone-submitted derived observations
as server measurements.

All points must use the same object frame as the reconstruction. Capture is in
meters; engineering parameters are millimeters. Scale normalization belongs at
the service boundary, before calling the candidate engine.

Automated tests use analytic independently specified interfaces, including rotated
and translated tapered cups, multiple held-out spans, incompatible planes,
unobserved contacts, manual constraint conflicts, missing measurements and
reproducible IDs. These tests validate proposal logic, not physical phone accuracy
or printed fit.

Run: `.venv/bin/python -m pytest backend/tests/test_candidates.py -q`.
