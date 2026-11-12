#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export LANGSMITH_TRACING=false LANGCHAIN_TRACING=false LANGCHAIN_TRACING_V2=false
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  python -m bugzilla_qa.retrieval_v3.cli --help
  exit 0
fi
LOG_DIR="$ROOT/outputs/retrieval/v3/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/${1:-plan}-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
printf '[%s] Retrieval v3; log=%s\n' "$(date -u +%FT%TZ)" "$LOG"
python -u -m bugzilla_qa.retrieval_v3.cli "$@" 2>&1 | tee "$LOG"
