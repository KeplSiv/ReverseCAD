#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
if [[ ! -x .venv/bin/python ]]; then
  print -u2 'Run ./scripts/bootstrap.sh first.'
  exit 1
fi
exec .venv/bin/python scripts/serve.py "$@"
