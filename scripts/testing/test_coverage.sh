#!/usr/bin/env bash
# Run the offline test suite with coverage, the same way CI does (.github/workflows/ci.yml, job "test").
# Reports land in results/coverage/: coverage.xml, junit.xml and html/index.html.
#
#   bash scripts/testing/test_coverage.sh                 # Linux/macOS, inside your venv
#   bash scripts/testing/test_coverage.sh tests/a_api     # extra arguments go to pytest
#   .\scripts\testing\test_coverage.ps1                   # Windows: runs this file inside Docker
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${COVERAGE_OUT:-$ROOT/results/coverage}"

if [[ "${1:-}" == "--container" ]]; then
  # Used by test_coverage.ps1. The repo is mounted read-only, so copy the working tree
  # (tracked and new files, nothing git ignores such as .env, models or data) and install
  # the same packages CI installs.
  shift
  git config --global --add safe.directory '*'
  mkdir -p /repo
  git -C "$ROOT" ls-files -co --exclude-standard -z \
    | tar -C "$ROOT" --null --ignore-failed-read -cf - -T - 2>/dev/null | tar -C /repo -xf -
  cp -a "$ROOT/.git" /repo/.git
  ROOT=/repo
  cd "$ROOT"
  echo "Installing packages (first run takes several minutes; later runs use a cache)..."
  pip install -q --root-user-action=ignore torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
  pip install -q --root-user-action=ignore '.[serving,ui,dashboard,dev]'
fi

cd "$ROOT"
mkdir -p "$OUT"
export LLM_PROVIDER=mock LANGSMITH_SOURCE=fixture LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
export DASHBOARD_LAB_ENABLED=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=src
MLFLOW_TRACKING_URI="file:$(mktemp -d)/mlruns"
export MLFLOW_TRACKING_URI

python -m pytest -q -m "not live and not integration" \
  --cov=src/bugzilla_serving --cov-fail-under=70 \
  --cov-report=term --cov-report="xml:$OUT/coverage.xml" --cov-report="html:$OUT/html" \
  --junitxml="$OUT/junit.xml" "$@"
