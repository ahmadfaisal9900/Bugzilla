#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
LOG_DIR="$REPO_ROOT/outputs/phase04/logs"
mkdir -p "$LOG_DIR"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_PATH="$LOG_DIR/enrich-$RUN_STAMP.log"
export PHASE04_LOG_PATH="$LOG_PATH"
printf 'Phase 4 enrichment log: %s\n' "$LOG_PATH"
python -m bugzilla_qa.data.phase04 enrich --root "$REPO_ROOT" "$@" 2>&1 | tee "$LOG_PATH"
