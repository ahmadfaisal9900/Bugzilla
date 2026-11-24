#!/usr/bin/env bash
# Owner-run B11 jobs. Preview by default; --run starts the selected stage.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$TASK_ROOT"
export PYTHONPATH="$TASK_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON:-python}" scripts/testing/demo_job.py "$@"
