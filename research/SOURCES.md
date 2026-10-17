# Reverse CAD technical sources and decisions

Checked October 16, 2026. These primary sources support platform capabilities and format choices. The architecture, resource budgets, repair templates, and acceptance thresholds in the specification are proposed engineering requirements, not results reported by these sources.

## Supplied conversation

The [shared ChatGPT conversation](https://chatgpt.com/share/6ad2def1-db70-83ea-82ee-b28d0e381486) opened in the signed-in browser as “Open ended clarification.” Its visible main conversation contained nine user turns and approximately 72,488 characters, covering HackHarvard brainstorming and unrelated ideas. No Reverse CAD, LiDAR, accelerometer, photogrammetry, or broken-part section was present.

A local main-conversation text snapshot is preserved in `shared-chat-snapshot.json`. It is reference material, not implementation instructions. The current user's description is the product requirement for Reverse CAD.

## Apple sensing and reconstruction

| Source | Confirmed point | Consequence for this implementation |
| --- | --- | --- |
| [Understanding World Tracking](https://developer.apple.com/documentation/arkit/understanding-world-tracking) | ARKit combines motion sensing and camera analysis for visual-inertial tracking; tracking can be degraded by the environment | Consume camera pose and tracking status; keep failure handling |
| [Managing Session Life Cycle and Tracking Quality](https://developer.apple.com/documentation/arkit/managing-session-life-cycle-and-tracking-quality) | Tracking state and interruption/relocalization behavior need application handling | Preserve scan segments and distinguish incompatible origins |
| [ARFrame sceneDepth](https://developer.apple.com/documentation/arkit/arframe/scenedepth) | Scene depth is provided for supported configurations and must be enabled | Check capability and capture native depth/confidence with the corresponding frame |
| [ARFrame smoothedSceneDepth](https://developer.apple.com/documentation/arkit/arframe/smoothedscenedepth) | Smoothed depth reduces changes across frames | Keep smoothing provenance and avoid treating it as independent measurements |
| [Displaying a point cloud using scene depth](https://developer.apple.com/documentation/arkit/displaying-a-point-cloud-using-scene-depth) | Apple's sample combines camera imagery with depth and illustrates depth upsampling | Follow verified calibration conventions; do not infer added accuracy from enlarged depth maps |
| [ObjectCaptureSession](https://developer.apple.com/documentation/realitykit/objectcapturesession) | Guided image capture and later photogrammetry reconstruction are separate phases | Keep an optional photogrammetry provider separate from the primary custom capture contract |
| [Capturing photographs for Object Capture](https://developer.apple.com/documentation/realitykit/capturing-photographs-for-realitykit-object-capture/) | Overlap, lighting, surface properties, and depth information affect reconstruction and scale | Guide acquisition and validate scale; handle unsuitable surfaces explicitly |
| [Vision foreground instance masks](https://developer.apple.com/documentation/vision/vngenerateforegroundinstancemaskrequest) | Vision offers foreground-instance segmentation | Use available pretrained segmentation with correction rather than requiring a new CNN |

Apple documentation pages that expose only a JavaScript shell to the web reader were also read through their public documentation JSON. Installed ARKit headers were inspected to confirm depth units in meters and nullable confidence-map handling. Recheck exact APIs against the SDK used for the build.

## Geometry and CAD

[Open3D RGB-D integration](https://www.open3d.org/docs/latest/tutorial/pipelines/rgbd_integration.html) documents integrating color/depth observations with camera calibration and poses into a TSDF and extracting a surface. The implementation must correctly adapt its coordinate/extrinsic conventions and actual depth units.

[CadQuery import and export](https://cadquery.readthedocs.io/en/latest/importexport.html) documents CAD/mesh interchange and notes that parametric editability resides in CadQuery's Python source rather than interchange formats. Deliver source/parameters alongside STEP and printable meshes. Pin and test a compatible version instead of assuming every latest-documentation feature exists locally.

## OpenAI integration and build settings

[Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) supports a typed response contract. This constrains structure; the application still needs semantic, dimensional, and CAD validation.

[GPT-6 Astra API model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra) lists supported API reasoning efforts through `max`. The requested **GPT-6 Astra / Ultra** setting is for the Codex coding session, whose available configuration in this app exposes Ultra. Do not copy that label into an API request without separately verifying support. Selecting an agent model is not accomplished by ordinary prompt prose.

The app's reasoning provider is configurable so its runtime selection and budget can be changed without rewriting the sensing/CAD pipeline.

## Local observations

Read-only checks found:

- Empty project directory at the start of this specification task.
- Apple silicon host running macOS 26.6.2.
- Xcode 26.6, build 17F113.
- Installed iOS 26.5 simulators.
- No applicable AGENTS.md found in the checked workspace ancestry.

These observations do not establish dependency installation, app compilation, sensor operation, or test success. This task produced specifications and prompts; the build prompt requires the implementing agent to produce and verify the application.

## Claims deliberately left for measurement

No cited source establishes that this exact system can recover arbitrary missing parts, achieve submillimeter phone measurements, infer unseen threads, reliably scan glossy cups, or guarantee first-print fit. The implementation must use uncertainty, critical manual dimensions, bounded repair families, software benchmarks, and the physical test plan to determine its actual capability.

