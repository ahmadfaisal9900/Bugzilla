#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd -- "$repo_dir"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
log_dir="$repo_dir/outputs/mlops/f5_gold/jobs/$stamp"
mkdir -p -- "$log_dir"
printf 'Started %s UTC; logs %s; repeat command to resume verdict checkpoints\n' "$stamp" "$log_dir"
python scripts/grade_f5.py "$@" > "$log_dir/summary.json" 2> "$log_dir/run.log"
cat -- "$log_dir/summary.json"
