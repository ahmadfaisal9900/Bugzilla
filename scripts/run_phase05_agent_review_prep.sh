#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python -m bugzilla_qa.benchmark.assisted_review "$@"
    exit 0
  fi
done

LOG_DIR="$ROOT/outputs/benchmark/phase05/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_PATH="$LOG_DIR/agent-review-prep-${STAMP}-$$.log"
printf '[%s] Phase 5 assisted review prep; log=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LOG_PATH"
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python -m bugzilla_qa.benchmark.assisted_review "$@" 2>&1 | tee -a "$LOG_PATH"
