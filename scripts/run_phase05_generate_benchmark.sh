#!/usr/bin/env bash
# Compatibility for the byte-frozen research module's help text.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$TASK_ROOT/scripts/phases/run_phase05_generate_benchmark.sh" "$@"
