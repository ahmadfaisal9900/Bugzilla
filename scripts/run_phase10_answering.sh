#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
if [[ $# -eq 0 ]]; then set -- plan; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  exec python -m bugzilla_qa.answering.cli --help
fi
log_root="$project_root/outputs/predictions/logs"
mkdir -p "$log_root"
log_path="$log_root/${1}-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
printf '[%s] Phase 10 %s; log=%s\n' "$(date -u +%FT%TZ)" "$1" "$log_path"
python -m bugzilla_qa.answering.cli "$@" 2>&1 | tee "$log_path"
