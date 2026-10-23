#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'HELP'
Usage: bash scripts/run_phase05_validate_freeze.sh [OPTIONS]

Validate human signoffs and freeze the pinned Phase 5 benchmark. Run from the
existing Project root with the project Python environment active.

Options forwarded to bugzilla_qa.benchmark.phase05 validate-freeze:
  --run PATH             Candidate run (recommended: outputs/benchmark/phase05/run-65c5be3381f66811)
  --seed INT             Sampling seed (default: 317)
  --dry-run              Print preconditions only; does not inspect signoffs or hash source data
  --resume               Validate an existing identical frozen release by its output checksums
  --root PATH            Project root (defaults to current directory)
  --source-pins PATH     Pinned Phase 5 source config
  --output PATH          Phase 5 output directory
  --limit N              Not valid for freezing; full candidate set is required

The full command requires completed required row reviews and review_signoff.json.
It rehashes the 1.89-GB canonical database and rebuilds candidate gold before
writing the immutable frozen release. It never modifies review decisions.

Example:
  bash scripts/run_phase05_validate_freeze.sh --dry-run --run outputs/benchmark/phase05/run-65c5be3381f66811 --seed 317
  bash scripts/run_phase05_validate_freeze.sh --run outputs/benchmark/phase05/run-65c5be3381f66811 --seed 317 --resume
HELP
  exit 0
fi
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
LOG_DIR="$REPO_ROOT/outputs/benchmark/phase05/logs"
mkdir -p "$LOG_DIR"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOG_PATH="$LOG_DIR/validate-freeze-$RUN_STAMP.log"
printf '[%s] Phase 5 validate-freeze; log=%s\n' "$(date -u +%FT%TZ)" "$LOG_PATH"
python -u -m bugzilla_qa.benchmark.phase05 validate-freeze --root "$REPO_ROOT" "$@" 2>&1 | tee "$LOG_PATH"
printf '[%s] Phase 5 validate-freeze finished\n' "$(date -u +%FT%TZ)"
