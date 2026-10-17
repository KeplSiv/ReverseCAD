# Research decision: incremental reconstruction of missing mechanical parts

Reviewed 17 October 2026. Scope: research papers, official implementations, current license files, local architecture, and the saved failing phone capture. This is a literature and implementation review, not a benchmark of the newly identified neural models. Recommendations below are engineering judgments; published performance is not performance measured on this phone or Mac.

**Recommendation.** Build an object-centered, incremental repair system with several competing hypotheses. Use a lightweight structural path for early proposals and compare alternative geometry backends offline before adopting one. Preserve a distinction between observed surfaces, inferred original structure, and the proposed replacement. Keep high-resolution donor detail available throughout. The current requirement for a completed, consistent depth mesh before general pattern reasoning is too restrictive for early repair.

## What the actual failure establishes

The latest inspected capture is `BF3BBC74-12D9-4C26-BCCA-1ADF6141F317`, job `d4fea4a55e014619a10e5f706f2f89e9`. COLMAP registered 21 of 25 input frames with mean reprojection error about 1.15 pixels. Stereo accepted 12,213 samples, but only 454 survived agreement across different pairs; fusion produced eight triangles. The automatic metric scale uses background depth correspondences and has about 5.7% relative p10–p90 half-range. That dispersion is not a calibrated dimensional error bound.

The capture stores RGB at 3840×2160 and depth at 256×144: a 15× difference along each image axis. Upsampling the depth image cannot create the missing geometric measurements. The RGB images contain additional visual information, but turning that into shape still requires sharp correspondence, appropriate camera baselines, and a reliable coordinate frame. Some views show clipped glare on the damaged face.

The current code also has a separate structural failure: the photo fallback independently redetects a mostly solved cube face in each image, then groups detections by color and missing cell. Most images fail that detector. General pattern completion is gated behind consistent native depth, so it never gets a useful opportunity on this capture. Improving model reasoning and image tracking can therefore help before dense reconstruction is solved.

A preliminary optical-flow experiment carried one detected face into two adjacent registered views. It obtained three face observations, but the fitted square still had about 19 pixels median corner error and the donor radius fit reached its lower bound. This is evidence that observation tracking can repair part of the pipeline, not evidence of an accurate replacement. The experiment remains unintegrated.

Local evidence: `var/service/jobs/d4fea4a55e014619a10e5f706f2f89e9/output/reconstruction.json`, `photo_alignment.json`, `photo_recovery.json`, and the immutable capture. No independent real-world dimensions or print fit were measured.

## Alternatives considered

### Geometry, tracking, and segmentation

| Approach | Useful contribution | Main limitation for this app | Decision |
| --- | --- | --- | --- |
| ARKit + image tracks + Open3D | Existing metric observations, camera motion, geometric fitting and registration | Bad local depth and repeated texture can corrupt alignment; a room model does not identify a broken part | Keep as a baseline; use local evidence rather than one global pass/fail |
| COLMAP + learned feature matching | Geometrically checked image correspondence and bundle adjustment | Better camera alignment still does not supply dense donor detail or intended geometry | Benchmark stronger matching before replacing the entire pipeline |
| MapAnything | Conditions reconstruction on images and optional calibration, poses, and depth | Estimated metric geometry is not a precision guarantee; incorrect inputs can bias it | First learned geometry candidate to benchmark |
| VGGT / VGGT-Ω | Joint camera and dense geometry initialization from multiple views | No missing-part reasoning; deployment and metric accuracy need testing | Ω is a current research challenger, not an automatic default |
| Pi3X | Alternative multiview model with optional geometric inputs | Learned scale and confidence still require independent checks | Compare if the first learned candidate fails |
| GLUEMAP | Fuses learned local geometry with global SfM optimization | Sparse output, substantial dependency stack, not a ready live repair system | Strong offline alignment challenger |
| MASt3R-SLAM | Dense sequential mapping from learned reconstruction priors | Published implementation targets CUDA; scene mapping is not repair inference | Research reference / optional GPU benchmark |
| CUT3R / STream3R | Persistent-state or causal reconstruction as images arrive | Predictive geometry can drift or invent unseen surfaces; metric consistency needs testing | Revisit for streaming after the first repair backend is measurable |
| BundleSDF / FoundationPose | Explicit object tracking, including object movement relative to the camera | Requires suitable RGB-D/reference evidence and a substantial GPU stack | Relevant for hand-held objects, later than stationary scanning |
| Apple Vision / SAM 2 | Separates the object from the table and maintains an image region | Segmentation is not damage recognition, geometry, or 6-DoF tracking | Add only where object masks fail; retain cavity visibility evidence |

[Open3D's documented global registration](https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html) provides an existing FPFH/RANSAC baseline rather than requiring a new learned dependency. [COLMAP now documents several learned matching options](https://colmap.github.io/features.html); available options depend on the installed build. [LightGlue](https://github.com/cvg/LightGlue) is a useful bounded correspondence baseline, but its published CPU/GPU timings are not Mac timings.

[MapAnything](https://map-anything.github.io/) is especially relevant because the input need not be RGB alone. Compare images plus intrinsics, then add only trusted metric observations and camera information. Do not provide every inconsistent native pose/depth map as unquestioned truth. The [official implementation](https://github.com/facebookresearch/map-anything) exposes these combinations and multiview consistency filtering. Its Apache checkpoint is distinct from the default research checkpoint.

[VGGT](https://github.com/facebookresearch/vggt) should not be treated as the newest option: [VGGT-Ω](https://github.com/facebookresearch/vggt-omega) has a 2026 release, including separate in-the-wild and reproduction checkpoints. Its reported 25-frame peak memory is 7.80 GB on an A100 under the documented setup. That does not establish MPS compatibility, phone viability, or latency on this Mac. [Pi3X](https://github.com/yyfz/Pi3) is another conditional geometry alternative rather than a repair model.

[GLUEMAP](https://github.com/colmap/gluemap) already implements a fusion direction worth examining: learned local reconstruction, global motion/scale averaging, and bundle adjustment. It produces a COLMAP sparse reconstruction; a dense surface and the missing piece remain separate tasks. This is stronger evidence for benchmarking hybrid alignment than for simply discarding geometric optimization.

[MASt3R-SLAM](https://github.com/rmurai0610/MASt3R-SLAM), [CUT3R](https://github.com/CUT3R/CUT3R), and [STream3R](https://github.com/NIRVANALAN/STream3R) address different sequential mapping problems. Their relevance is maintaining geometry as new images arrive. Their outputs must still be tested for object-relative consistency and must not turn predictions of unseen surfaces into measured evidence.

[BundleSDF](https://github.com/NVlabs/BundleSDF) explicitly tracks and reconstructs an unknown rigid object from RGB-D. [FoundationPose](https://github.com/NVlabs/FoundationPose) supports a supplied object model or reference images. Both are more relevant to rotating the object in a hand than static world tracking alone. Neither independently solves missing mechanical geometry.

A newer [NVIDIA object reconstruction workflow](https://github.com/NVIDIA/3DObjectReconstruction) combines segmentation, stereo, matching, tracking, and an SDF. Its documented minimum is a 24 GB CUDA GPU, 32 GB RAM, and Linux; the phone's RGB-plus-LiDAR capture is not its stereo input without adaptation. [Fast-FoundationStereo](https://github.com/NVlabs/Fast-FoundationStereo) is an optional donor-detail benchmark for rectified pairs, not a direct replacement for camera calibration or tracking. Its published speed is for NVIDIA hardware.

[Apple Vision foreground masks](https://developer.apple.com/documentation/vision/vngenerateforegroundinstancemaskrequest) offer an on-device starting point. [SAM 2](https://github.com/facebookresearch/sam2) adds video segmentation and mask propagation. A mask must not silently turn intentional openings or an exposed cavity into filled material. [ARKit scene depth](https://developer.apple.com/documentation/arkit/arconfiguration/framesemantics-swift.struct/scenedepth) supplies synchronized distance observations and confidence, not a guarantee that every small surface feature is resolved.

### Missing geometry and intended structure

| Approach | Why examine it | Why it is insufficient alone |
| --- | --- | --- |
| Structural repetition and local symmetry | Transfers this object's own repeated features and can work with incomplete observations | Intentional asymmetry, normal holes, and occlusion can look like damage |
| SymmCompletion | Learns local transformations and refines a partial shape | Completion benchmarks are not mechanical fit tests; transformations can deform detail |
| AdaPoinTr | Useful general point completion baseline | A completed point set is neither a replacement solid nor a damage explanation |
| DeepJoin | Models fractured geometry and the restoration together | Needs a suitable fractured-shape input and learned prior; not live phone reconstruction |
| Beyond Reassembly | Recent research explicitly combines missing parts with fragment placement | Fragment recovery differs from locating a damaged region in a phone video; runnable release not confirmed here |
| Retrieval of complete or donor shapes | Can propose a structurally suitable counterpart from a known family | Similar-looking objects may have different dimensions or interfaces |
| SAM 3D Objects / TRELLIS.2 / PartCrafter | Can supply diverse semantic and shape hypotheses | Plausible shape, texture, or part decomposition does not establish this object's missing dimensions |
| Surface continuation | Planes, cylinders, extrusions, and tangent constraints can bridge simple losses | A short observed patch can have several equally plausible continuations |

[Pauly et al. (2008)](https://geometry.stanford.edu/paper/pmwpg-dsr3dg-08/pmwpg-dsr3dg-08.pdf) is a direct structural foundation: regularity is discovered from transformations between repeated geometry, including incomplete patterns. Our current principal-axis ICP prototype is much narrower than that work. The next baseline should search local feature correspondences and repeated transformations, retaining alternatives when correspondence is ambiguous.

[SymmCompletion](https://arxiv.org/html/2503.18007v1) predicts point-wise affine transformations and translations before refinement. This makes it relevant, but it does not guarantee rigid copying of a measured ridge. For manufacturing, initially restrict donor transfer to rigid transforms/reflections, report deviations, and freeze trusted detail. The paper's PCN/ShapeNet-style results and stated difficult asymmetric cases should not be interpreted as proof of phone repair performance. [AdaPoinTr](https://github.com/yuxumin/PoinTr) is a useful comparison, not a reason to adopt the highest benchmark completion score blindly.

[DeepJoin](https://arxiv.org/html/2211.12400v1) addresses a crucial distinction: fracture creates new surfaces absent from the original object. Ordinary partial completion does not model that distinction. Its joint occupancy, signed-distance, and normal representation provides a better conceptual basis for the intended body and restoration than subtracting two noisy meshes. The [released quickstart](https://github.com/Terascale-All-sensing-Research-Studio/DeepJoin) is centered on a fractured mug example and an older environment. It needs evaluation on our mechanical domain.

[Beyond Reassembly (CVPR 2026)](https://openaccess.thecvf.com/content/CVPR2026/html/Xu_Beyond_Reassembly_Fractured_Object_Recovery_with_Missing_Parts_CVPR_2026_paper.html) jointly reasons about existing fragments and absent pieces. This is relevant to future multi-fragment work, but it is a paper lead rather than a verified ready-to-integrate component. [Learned proxy retrieval](https://tars-home.github.io/papers/SCF2021_Lamb.pdf) is another alternative when same-object evidence is unavailable; retrieved geometry still needs fitting and rejection tests.

[SAM 3D Objects](https://github.com/facebookresearch/sam-3d-objects) supplies full-shape hypotheses from an image. [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) generates detailed assets, while [PartCrafter](https://github.com/wgsxm/PartCrafter) generates explicit parts. Benchmark these only as low-confidence proposal sources when observed donors and continuation fail. A visually convincing invented connector must not be exported as recovered geometry. TRELLIS.2's documented Linux/CUDA and 24 GB GPU requirement also makes it a poor first local dependency.

### CAD and active capture

[CAD-Recode](https://github.com/filaPro/cad-recode) converts point clouds to CadQuery code; it is relevant after the surviving shape and repair constraints are established. Executable code can still describe the wrong part. [BrepGen](https://brepgen.github.io/) generates boundary representation geometry and topology, but is not an end-to-end damaged-phone-scan solution. For the first supported objects, constrained analytic fitting and existing CadQuery/OCCT tooling offer a more inspectable baseline than generated programs.

[VideoCAD](https://github.com/ghadinehme/VideoCAD) concerns learning CAD software interactions from CAD screen videos. It does not convert a handheld scan into the missing replacement. It is not an appropriate reconstruction dependency here.

[SCONE](https://papers.neurips.cc/paper_files/paper/2022/hash/828c6d69bdf91fca7f2b97c4dc214e94-Abstract-Conference.html) predicts coverage gain for possible views. Its objective is informative for active scanning, but repair needs a more specific utility: which view can distinguish our competing repairs or expose the interface? Initially implement and measure an explicit candidate-disagreement score instead of adding an entire learned planner.

## Proposed fusion architecture

This architecture is a recommendation inferred from the literature and observed failures. It has not been implemented or validated as a complete system.

**1. Keep evidence in object coordinates.** Maintain calibrated RGB keyframes, native depth/confidence, masks, camera poses, exposure/blur, tracking segment IDs, and the coordinate transform between the object and AR session. Track temporal correspondences so a face, edge, or donor feature does not need to be rediscovered in every frame. Maintain object and scene tracking separately. A fixed-object first milestone is easier to validate; supporting movement in the hand needs explicit object tracking.

**2. Start structural reasoning with local observations.** Extract planar patches, line intersections, curved profiles, and local neighborhoods. Build a graph of relative orientation, spacing, curvature, and repeated substructure. Keep structural alternatives such as translation repetition, rotation, reflection, extrusion continuation, and a retrieved/learned completion. A cube may produce a grid hypothesis, but the solver must also handle ribbed rails and symmetric mounting features without a cube label or fixed dimensions.

**3. Separate three representations.** Store the current observed object, the hypothesized intended complete object, and the replacement volume. Each surface carries provenance: observed donor, copied donor, fitted analytic surface, inferred closure, or learned prior. A proposal is never fused back as if it were a new sensor measurement. This prevents a hypothesis from confirming itself over time.

**4. Use visibility correctly.** Reconstructed surviving surfaces must respect camera-confirmed free space. A replacement is expected to occupy a missing region that is currently empty. Therefore do not reject a replacement merely because it fills that space. Instead penalize penetration into surviving material, incorrect interface/contact placement, inconsistent repetition, and unsupported extent. Distinguish an intentional hole from a missing feature, and distinguish a confirmed opening from an area never observed. Evaluate the current damaged object against the current image, and evaluate the proposed original structure using donors and structural constraints; do not expect nonexistent replacement surfaces to appear in today's photos.

**5. Refine jointly, with robust weights.** Optimize object pose, structural dimensions, donor placement, and boundary alignment across views. Weight native depth by reliability and region. Use learned geometry as an initializer or bounded prior. Use independent observations to reject it; never average incompatible reconstructions simply because both produce dense point clouds. Compare an RGB-only model configuration with configurations using trusted metric inputs to detect harmful conditioning.

**6. Preserve detail separately from the scaffold.** Refine selected donor patches using original-resolution crops and multiview correspondence. The low-resolution structural model locates the part; it is not the detail source. Transfer measured ridges and recesses rigidly before fitting editable surfaces. If evidence is insufficient, retain uncertainty instead of converting lighting boundaries into geometry. Evaluate geometry without texture, and verify details from another view. Hidden connectors remain unresolved until observed or justified by an appropriate counterpart.

**7. Choose views that reduce repair uncertainty.** For candidate camera motions, estimate visibility of disputed surfaces, projected separation between hypotheses, expected triangulation baseline, glare/blur risk, and overlap needed for tracking. Examples: move lower when the mating underside distinguishes candidates; move sideways when parallax distinguishes a ridge from a painted line; change angle/light when highlights clip the donor. Select a bounded movement the user can perform. Compare against current coverage-only guidance rather than assuming the richer planner helps.

**8. Separate display cadence from geometry cadence.** The phone can render a ghost at the camera rate while a slower solver updates it on keyframes. The first display is an outline with uncertainty; a solid translucent candidate requires repeated support. Maintain candidate identity and hysteresis so close alternatives do not flicker. Fade the ghost when tracking or coordinate alignment is lost. A world anchor alone will not follow an object rotated in a hand. [ARKit's anchors](https://developer.apple.com/documentation/ARKit) provide a rendering coordinate mechanism; they do not validate the repair.

**9. Make incremental transport part of the design.** Today's finish-scan/upload/process path cannot deliver a live ghost. Stream bounded keyframes and metadata to the companion with session IDs and observation revisions. Return proposals with the exact reference frame and transform. Reject stale or different-session results. When bundle adjustment changes the backend frame, align it to the current AR frame through shared observations; a saved model cannot simply reuse an old session's world transform after restart.

**10. Fit and verify manufacturing geometry last.** Once a supported hypothesis stabilizes, construct an editable scaffold and retain detail with provenance. Check boundary deviation, surviving-material penetration, minimum wall thickness for the selected process, manifoldness, self-intersection, units, and exported-file reimport. Distinguish geometric validity, inferred interface dimensions, and actual printed fit. The first deliverable should be a useful exterior test piece; functional internal interfaces require additional evidence.

## Hardware and licensing decisions

Local hardware is an Apple M3 Pro Mac with 18 GB unified memory and an iPhone 13 Pro. CUDA benchmarks do not establish feasibility on either. An isolated small-view CPU/MPS trial is reasonable for compatible PyTorch models, but compatibility, memory, and latency are unmeasured. Keep heavy model environments separate from the currently working companion service.

| Component | Terms observed in official sources | Practical consequence |
| --- | --- | --- |
| MapAnything | Apache code; separate Apache and CC-BY-NC checkpoints | Prefer the explicitly named Apache checkpoint for the first integration candidate. [Model card](https://huggingface.co/facebook/map-anything-apache) |
| VGGT | Custom VGGT terms; original and commercial checkpoints have different availability/terms | Pin the checkpoint and read its terms; do not infer rights from the architecture name. [License](https://github.com/facebookresearch/vggt/blob/main/LICENSE.txt) |
| VGGT-Ω | FAIR Noncommercial Research License; checkpoint access request | Suitable as a research comparison under its terms, not a drop-in permissively licensed component. [License](https://github.com/facebookresearch/vggt-omega/blob/main/LICENSE) |
| Pi3 / Pi3X | BSD code; CC-BY-NC weights | Treat code and weights separately. [Terms](https://github.com/yyfz/Pi3#-license) |
| GLUEMAP | BSD itself; separately licensed backbone dependencies | The default pipeline does not inherit one blanket permissive license. [Repository](https://github.com/colmap/gluemap) |
| SymmCompletion / AdaPoinTr | MIT repositories | Verify specific checkpoint and dependency terms before packaging. [SymmCompletion license](https://github.com/HKUST-SAIL/SymmCompletion/blob/main/LICENSE), [PoinTr](https://github.com/yuxumin/PoinTr) |
| DeepJoin | Apache-2.0 repository; separate data/dependencies | Useful research baseline with environment adaptation. [Repository](https://github.com/Terascale-All-sensing-Research-Studio/DeepJoin) |
| MASt3R-SLAM / CUT3R / STream3R | Noncommercial research licenses | Keep as research alternatives rather than assume general redistribution rights. [MASt3R-SLAM](https://github.com/rmurai0610/MASt3R-SLAM/blob/main/LICENSE.md), [CUT3R](https://github.com/CUT3R/CUT3R/blob/main/LICENSE), [STream3R](https://github.com/NIRVANALAN/STream3R/blob/main/LICENSE) |
| BundleSDF / FoundationPose / Fast-FoundationStereo research implementations | NVIDIA-specific terms, with separate commercial/model releases in some cases | Identify exact implementation and weights; avoid treating all NVIDIA releases alike. [BundleSDF](https://github.com/NVlabs/BundleSDF/blob/master/LICENSE.txt), [FoundationPose](https://github.com/NVlabs/FoundationPose/blob/main/LICENSE), [Fast-FoundationStereo](https://github.com/NVlabs/Fast-FoundationStereo) |
| NVIDIA 3DObjectReconstruction | Apache framework; constituent models/dependencies have separate terms | Framework license does not settle every model's terms or hardware suitability. [Framework](https://github.com/NVIDIA/3DObjectReconstruction) |
| SAM 2 / SAM 3D Objects | Apache SAM 2 models/code; custom SAM terms for SAM 3D Objects | Do not conflate segmentation and generated-object releases. [SAM 2](https://github.com/facebookresearch/sam2#license), [SAM 3D](https://github.com/facebookresearch/sam-3d-objects/blob/main/LICENSE) |
| TRELLIS.2 / PartCrafter | MIT releases with separately licensed dependencies | Useful hypothesis generators, subject to dependency and checkpoint review. [TRELLIS.2](https://github.com/microsoft/TRELLIS.2#%EF%B8%8F-license), [PartCrafter](https://github.com/wgsxm/PartCrafter) |
| CAD-Recode | CC-BY-NC-4.0 repository | Research comparison; existing CadQuery can remain the initial constructive backend. [License](https://github.com/filaPro/cad-recode/blob/main/LICENSE.md) |
| OpenMVS | AGPL-3.0 | Optional dense-reconstruction benchmark with a different license profile. [Repository](https://github.com/cdcseacave/openMVS) |

These are source observations for choosing experiments, not a legal clearance or a claim that internal testing automatically satisfies every model's terms. Record the exact code revision, checkpoint identifier, and checkpoint terms in each experiment.

Observed upstream HEADs for reproducible follow-up: MapAnything `3d10cf7a3016fc0f9bb13a071ee66c47b10be0d9`; VGGT `a288dd0f14786c93483e45524328726ab7b1b4ce`; VGGT-Ω `48b23c8ce72c9a8fcf987f0d7f43d8e4870759f6`; GLUEMAP `adc9e4bb5f41014d3f7c157a879edc278588c829`. Recheck checkpoint versions separately. Cached raw license URLs can differ from current repository pages, so use the pinned revision when implementing.

## Benchmark before choosing the implementation

**Geometry tournament.** Use identical frames and masks for: (A) the current ARKit/COLMAP baseline, (B) temporal image tracking plus geometric optimization, (C) MapAnything with RGB/intrinsics, then trusted metric inputs, (D) VGGT-Ω or Pi3X where available, and (E) a GLUEMAP hybrid. Add neural stereo only when correct poses and rectification exist. Do not run every model in production or average their outputs. Select the smallest backend that materially improves the failing case and held-out objects.

**Repair tournament.** Hold the geometry backend fixed while comparing: local rigid donor transfer; reflection/repetition plus analytic continuation; a SymmCompletion or AdaPoinTr prior; and DeepJoin where its input/domain requirements fit. Add a generic generative prior only if it improves unsupported cases without increasing confidently wrong repairs. This separates reconstruction gains from completion gains.

**Data.** Keep the latest failed scan and earlier failed scans as regressions. Add physically captured simple examples: repeated tabs/ribs with one removed, a symmetric bracket with a missing mounting feature, and a curved repeated feature. Capture the intact state before removal for evaluation. Include complete versions, intentional holes, ordinary occlusions, asymmetric objects, repeated colors, glare, object movement, and tracking resets as negative or stress cases. Independent dimensions are evaluation evidence, not dimensions secretly supplied to the model.

[Fantastic Breaks](https://terascale-all-sensing-research-studio.github.io/FantasticBreaks/) provides real broken/intact scans and documents a gap between real and synthetic fractures. It can test fracture reasoning, but it does not replace a phone RGB-D capture set or provide the same sensor failure modes. Use it alongside mechanical and phone-specific data.

**Incremental evaluation.** Replay prefixes of 4, 8, 16, and all useful keyframes. Measure time to the first *correct* missing-region hypothesis, candidate stability, and whether the requested next view actually resolves an ambiguity. Keep future frames and intact ground truth out of the fitting inputs. Use held-out views to test current-surface geometry and observable boundaries; use intact/donor evidence to test the repair that does not yet exist in damaged-view images.

**Metrics.** Measure object-region boundary and reprojection error, relative pose consistency, scale error against independent dimensions, missing-region precision/recall, donor relief preservation, interface deviation, surviving-material penetration, correct topology, false repairs on intact/occluded objects, ghost image-space error and jitter, end-to-end latency, peak memory, and exported STL/3MF/STEP reimport. Chamfer distance, attractive texture, and watertightness alone are insufficient. Define acceptable dimensional errors from the particular interface and printing process before selecting a winner; a percentage of object size may be far too loose for a connector.

**Release gates.** A basic working milestone requires: a real missing region found without preset size, the correct donor/continuation supported across views, an exterior proposal with stated uncertainty, a stable ghost during controlled camera movement, an independently checked exported piece, and a real print-fit trial. Generalization requires the same procedure on additional non-cube objects and negative cases. Software tests and mesh fixtures remain necessary but do not satisfy those gates.

## Implementation order recommended by this review

1. Introduce object-region tracking, an observation/structure graph, and separate current-object/intended-object/replacement state. Repair the coordinate and evidence contracts before adding a model.
2. Build an early local donor/continuation baseline and an incremental proposal endpoint. Benchmark it on the saved failure and new controlled objects.
3. Run the geometry tournament in isolated environments; start with MapAnything's Apache checkpoint and compare rather than preselect a winner. Use GLUEMAP for an offline hybrid challenger. Test small-view Mac feasibility before committing to deployment.
4. Add a session-aligned wireframe ghost with pose-loss handling. Let hypotheses update while rendering stays responsive. Validate ghost placement separately from geometry quality.
5. Add high-resolution donor refinement, uncertainty-directed capture instructions, and checked editable/exterior export. Complete the physical fit trial.
6. Add a learned completion prior, explicit moving-object tracking, or a heavier generative model only for a measured failure that the preceding stages cannot address.

The most promising contribution for this hackathon is an evidence-guided repair interaction: identify a structural absence, expose the proposed explanation immediately, and request the view that resolves it. Missing-part inference itself already has a research history. A useful demonstration must show an actual repair and identify the remaining unknowns rather than claim a new universal reconstruction method.
