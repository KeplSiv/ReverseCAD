# Dependencies and fixture provenance

Exact transitive versions/hashes are pinned in `uv.lock`; install with `uv sync --frozen`. The native app has no external Swift dependency. Xcode frameworks are supplied by Apple. This table records installed package license metadata; full license texts remain in the installed distributions and upstream projects.

| Package | Version | License metadata |
| --- | --- | --- |
| fastapi | 0.115.12 | MIT License |
| uvicorn | 0.34.2 | BSD-3-Clause |
| pydantic | 2.11.4 | MIT |
| numpy | 2.2.6 | BSD-3-Clause; bundled-library notices in its installed LICENSE.txt |
| scipy | 1.15.3 | BSD-3-Clause; bundled-library notices in its installed LICENSE.txt |
| opencv-python-headless | 4.11.0.86 | Apache 2.0 |
| open3d | 0.19.0 | MIT |
| cadquery | 2.6.1 | Apache Public License 2.0 |
| cadquery-ocp | 7.8.1.1.post1 | Apache-2.0 for the wrapper, per installed cadquery_ocp/LICENSE; OCCT has a separate license below |
| trimesh | 4.6.8 | The MIT License (MIT) |
| rtree | 1.4.1 | MIT |
| networkx | 3.4.2 | BSD License |
| httpx | 0.28.1 | BSD-3-Clause |
| Pillow | 11.2.1 | MIT-CMU |
| pytest | 8.3.5 | MIT |
| psutil | 7.0.0 | BSD-3-Clause |

Fixtures are generated here by an analytic ray renderer from independently specified geometric scenes, with fixed random seeds. They contain no phone footage or third-party training set. Evaluation oracles live separately under `fixtures/oracles` and are never uploaded, bundled in the app, or read by production reconstruction. See [FIXTURES.md](FIXTURES.md).

CadQuery exports editable trusted generator source and typed parameter JSON. The source remains dependent on the pinned CAD environment and is not a standalone STEP feature history.

The `cadquery-ocp` wrapper license does not replace the native Open CASCADE Technology license. OCCT publishes LGPL-2.1 with an additional exception in its [official license text](https://occt3d.com/dev/doc/overview/html/occt_public_license.html), checked October 16, 2026. NumPy/SciPy binary distributions include separate notices for bundled components; preserve the full installed license files when redistributing those binaries.
