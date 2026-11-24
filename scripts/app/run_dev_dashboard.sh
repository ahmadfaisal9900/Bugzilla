#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$TASK_ROOT"
export PYTHONPATH="$TASK_ROOT/src:$TASK_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export LANGSMITH_SOURCE="${LANGSMITH_SOURCE:-fixture}"
TASK_ENV_FLAGS=()
if [[ -n "${DASHBOARD_ENV_FILE:-}" ]]; then
  TASK_ENV_FLAGS+=(--env-file "$DASHBOARD_ENV_FILE")
fi
exec python scripts/app/run_dashboard.py "${TASK_ENV_FLAGS[@]}" "$@"
