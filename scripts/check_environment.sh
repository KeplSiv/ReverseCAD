#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
sw_vers
uname -m
xcodebuild -version
xcodegen --version
xcrun simctl list runtimes
.venv/bin/python --version
.venv/bin/python -c 'import importlib.metadata as m; print({n:m.version(n) for n in ["cadquery","cadquery-ocp","open3d","numpy","opencv-python-headless","fastapi","httpx"]})'
