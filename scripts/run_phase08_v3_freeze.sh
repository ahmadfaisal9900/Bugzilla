#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  python -m bugzilla_qa.benchmark.v3_freeze --help
  exit 0
fi
LOG_DIR="$ROOT/outputs/benchmark/v3/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/freeze-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
printf '[%s] v3 freeze; log=%s\n' "$(date -u +%FT%TZ)" "$LOG"
python -u -m bugzilla_qa.benchmark.v3_freeze "$@" 2>&1 | tee "$LOG"
