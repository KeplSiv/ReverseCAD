#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
mkdir -p reports
.venv/bin/python -m pytest -q --junitxml=reports/python-junit.xml "$@"
