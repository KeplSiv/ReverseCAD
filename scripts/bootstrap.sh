#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
command -v uv >/dev/null || { print -u2 'Install uv from https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
uv sync --frozen --python 3.11.16 --cache-dir .uv-cache
mkdir -p reports
.venv/bin/python scripts/generate_fixtures.py --sample-only --output fixtures/sample_scan
mkdir -p ios/ReverseCAD/SampleScan
cp -R fixtures/sample_scan/. ios/ReverseCAD/SampleScan/
command -v xcodegen >/dev/null || { print -u2 'Install XcodeGen to regenerate the checked-in Xcode project.'; exit 1; }
xcodegen generate --spec ios/project.yml
.venv/bin/python scripts/generate_schemas.py
