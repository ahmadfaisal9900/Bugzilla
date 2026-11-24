#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$TASK_ROOT/scripts/app/run_dev_dashboard.sh" "$@"
