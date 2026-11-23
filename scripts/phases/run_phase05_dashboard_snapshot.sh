#!/usr/bin/env bash
# B5 dashboard operation; unrelated to research benchmark Phase 5.
set -euo pipefail
repo_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cd -- "$repo_dir"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
log_dir="${DASHBOARD_CACHE_DIR:-$repo_dir/outputs/dashboard_cache}/jobs/$stamp"
mkdir -p -- "$log_dir"
# --dry-run and --max-requests are forwarded. Artifact checkpoints allow resume
# simply by repeating this command; the last good snapshot remains readable.
python scripts/mlops/build_dashboard_snapshot.py "$@" > "$log_dir/summary.json" 2> "$log_dir/run.log" &
job_pid=$!
printf 'Started %s UTC; PID %s; summary %s; log %s\n' "$stamp" "$job_pid" "$log_dir/summary.json" "$log_dir/run.log"
wait "$job_pid"
cat -- "$log_dir/summary.json"
