#!/usr/bin/env bash
# Owner-run measurement: running compose services, one deterministic database question.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$TASK_ROOT"
export PYTHONPATH="$TASK_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON:-python}" scripts/testing/demo_resources.py "${1:?Supply output directory}"
