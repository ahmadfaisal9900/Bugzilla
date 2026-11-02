#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  exec python scripts/export_sample_bundle.py --help
fi
mkdir -p outputs/share/logs
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOG_PATH="$REPO_ROOT/outputs/share/logs/export-$RUN_STAMP.log"
printf '[%s] Sample handoff; log=%s\n' "$(date -u +%FT%TZ)" "$LOG_PATH"
python -u scripts/export_sample_bundle.py "$@" 2>&1 | tee "$LOG_PATH"
