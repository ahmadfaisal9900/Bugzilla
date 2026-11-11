#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "--help" ]]; then
  printf '%s\n' 'Usage: scripts/run_phase07_natural_review.sh [--dry-run] [--resume] [--limit N] [--seed N] [--output-root PATH]'
  exit 0
fi
args=("$@")
for arg in "${args[@]}"; do
  if [[ "$arg" == '--dry-run' ]]; then
    python -m bugzilla_qa.eval_extension.pipeline --stage natural "${args[@]}"
    exit 0
  fi
done
python -m bugzilla_qa.eval_extension.pipeline --stage natural "${args[@]}"
plan="$(python -m bugzilla_qa.eval_extension.pipeline --stage natural --dry-run "${args[@]}")"
bank_dir="$(python -c 'import json,sys; print(json.load(sys.stdin)["out"])' <<< "$plan")"
printf 'Open http://127.0.0.1:8766/ and stop with Ctrl+C\n'
python scripts/review_natural_v2.py "$bank_dir/natural_review.csv"
