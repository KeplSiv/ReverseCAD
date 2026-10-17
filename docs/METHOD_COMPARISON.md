# One capture, five methods

The iPhone result screen compares the current RGB-D pipeline, COLMAP-aligned photo stereo, a tracked repeated-feature repair, MapAnything RGB, and MapAnything RGB + depth. Use **Compare methods on saved scan** to reprocess one capture. Select a method to inspect its surface and proposed part. Failed methods retain their explanation. Standard reconstruction remains available in the menu.

The tracked method currently assumes a square face with a regular 3x3 grid. It is a cube baseline, not general missing-part completion. The learned methods reconstruct observed surfaces; they do not inherently identify a missing component. General pattern completion remains evidence-gated. Neither a dense surface nor a watertight mesh proves dimensional accuracy or functional fit. The comparison does not implement a live AR ghost.

## Optional learned model environment

The CAD service keeps its Python 3.11 dependencies. Install the official MapAnything project into a separate Python 3.12 environment. The tested upstream revision was `3d10cf7` and package version 1.1.4. See the [official repository](https://github.com/facebookresearch/map-anything) for its installation and checkpoint terms. This integration uses `facebook/map-anything-apache`; no upstream implementation or model weights are vendored here.

Set these variables for the Mac service (absolute paths):

```sh
REVERSECAD_GEOMETRY_PYTHON=/path/to/model-env/bin/python
REVERSECAD_MODEL_CACHE=/path/to/model-cache
```

The cache must already contain the Apache checkpoint and its DINO backbone. Use the official project's pretrained loading process with `HF_HOME` set to the cache directory and `TORCH_HOME` set to its `torch` subdirectory to populate them. The service adapter runs offline, with telemetry disabled. It consumes at most six views per learned pass, uses MPS when available, and produces numeric arrays in a private temporary directory. Missing dependencies/checkpoints leave these two variants unavailable without discarding other results. Weights and local environments are intentionally excluded from Git.

The API accepts `compare_methods: true` on the reconstruction request. The comparison worker has a 600 second / 10 GiB process-tree budget; the model subprocess has a 240 second budget. These are configurable via `create_app`. Normal jobs retain their existing budgets. The phone downloads bounded previews and verified export artifacts, not raw model predictions.

## Actual failed-scan trial, 2026-10-17

All five methods used capture `BF3BBC74-12D9-4C26-BCCA-1ADF6141F317`. The comparison stage took approximately 157 seconds after the shared baseline reconstruction.

| Method | Result |
| --- | --- |
| Current | Views inconsistent; no replacement |
| Photo stereo | 447 cross-pair supported samples; 3 surface triangles; no replacement |
| Tracked repeated feature | Closed STL/3MF exterior proposal from three tracked views; donor outline transferred, fine relief and hidden geometry unresolved |
| Learned RGB | 221,215 surface triangles; no supported replacement hypothesis |
| Learned RGB + depth | 343,564 surface triangles; no supported replacement hypothesis |

The tracked proposal's median held-out corner error was about 2.95% of face width, with approximately 19 pixel median corner reprojection error. Its scale is inferred from recorded metric evidence, not a preset cube width. Those errors do not establish manufacturing tolerance. The learned depth-conditioned pass agreed more closely with native depth (~5.0 mm versus ~9.2 mm median discrepancy), but native depth is itself inconsistent and is not independent ground truth. No verified winner or physically tested fit is claimed.

Export requires explicit review and file-integrity checks. The closed tracked prototype is the useful first candidate to inspect; it is not established as a working replacement part.

## Validation

The iOS pattern/comparison and verified-artifact suites passed 12 tests, covering saved report restoration, switching variants, clearing review state, export gating, and rejecting modified artifacts. A signed device build succeeded. Python comparison tests cover known perspective tracking, unrelated-view rejection, isolated model failure, incomplete print sets, and request idempotency. Actual RGB and RGB + depth inference completed on Apple M3 Pro MPS; no fixture output stands in for those passes.
