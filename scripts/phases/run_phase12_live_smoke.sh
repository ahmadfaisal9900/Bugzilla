#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$TASK_ROOT/src:$TASK_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON:-python}" "$TASK_ROOT/scripts/app/live_smoke.py" "$@"
