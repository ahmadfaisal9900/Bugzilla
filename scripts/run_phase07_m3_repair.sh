#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  python -m bugzilla_qa.eval_extension.m3_repair --help
  exit 0
fi
LOG_DIR="$ROOT/outputs/eval_extension/logs"
mkdir -p "$LOG_DIR"
LOG_PATH="$LOG_DIR/m3-repair-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
printf '[%s] M3 repair; log=%s\n' "$(date -u +%FT%TZ)" "$LOG_PATH"
python -u -m bugzilla_qa.eval_extension.m3_repair "$@" 2>&1 | tee "$LOG_PATH"
