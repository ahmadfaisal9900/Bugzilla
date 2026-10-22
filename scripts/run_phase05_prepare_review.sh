#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
LOG_DIR="$REPO_ROOT/outputs/benchmark/phase05/logs"
mkdir -p "$LOG_DIR"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOG_PATH="$LOG_DIR/prepare-review-$RUN_STAMP.log"
printf '[%s] Phase 5 prepare-review; log=%s\n' "$(date -u +%FT%TZ)" "$LOG_PATH"
python -u -m bugzilla_qa.benchmark.phase05 prepare-review --root "$REPO_ROOT" "$@" 2>&1 | tee "$LOG_PATH"
printf '[%s] Phase 5 prepare-review finished\n' "$(date -u +%FT%TZ)"
