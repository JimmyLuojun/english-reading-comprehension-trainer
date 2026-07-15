#!/usr/bin/env bash
# Run the complete deterministic test suite and enforce coverage policy.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing project virtual environment: $PYTHON" >&2
  exit 1
fi

cd "$ROOT_DIR"
"$PYTHON" -m pytest tests/ --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml
"$PYTHON" -m scripts.check_coverage coverage.xml
