#!/usr/bin/env bash
set -euo pipefail
if [[ $# -eq 0 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'HELP'
Usage: bash scripts/run_phase06_baselines.sh m0|m1|m3|bm25 [OPTIONS]

m0    Ask the local model without project evidence.
m1    Retrieve BM25 evidence, then ask the same local model.
m3    Run the parameterized SQL method on development questions, then score it.
bm25  Build the keyword index, retrieve for development questions, report Recall@5/10.

Development questions only: this tool has no option for the locked test. M0/M1 require an
already installed Ollama model on localhost. No model is downloaded. M1, m3 and bm25 need
the local Phase 3B database and Phase 4 overlay, so run them on the data machine.

Options:
  --unfrozen-dev-smoke  Use dev questions from the unreviewed candidates. Results are a code check,
                        never a study result. Without this flag the benchmark must be frozen.
  --run PATH            Generation run (default: outputs/benchmark/phase05/run-65c5be3381f66811)
  --limit N             Answer at most N questions in total; the run is marked PARTIAL
  --resume              Continue an existing output from its checkpoint
  --dry-run             Report missing inputs only; writes no results
  --summary PATH        Summary JSON (default: a timestamped file beside the log)
  --model NAME          Required for m0/m1; use the same installed model for both
  --max-requests N      Cap model calls per invocation (default 5, including failed calls)
  --max-output-tokens N Output cap (default 512)
  --top-k N             M1 retrieval count (default 5)
  --evidence-chars N    M1 serialized evidence character budget (default 12000)
  --timeout SECONDS     Local model response timeout (default 60)

Outputs go to outputs/phase06/<method>-dev-<smoke|frozen>-<question hash>/, with a checkpoint,
summary.json, and for m3 scores.jsonl. M3 here uses a development-wording parser, so F5 is an
abstention by design and the numbers are not the study's M3 result.

Examples:
  bash scripts/run_phase06_baselines.sh m3 --unfrozen-dev-smoke --dry-run
  bash scripts/run_phase06_baselines.sh m3 --unfrozen-dev-smoke
  bash scripts/run_phase06_baselines.sh bm25 --unfrozen-dev-smoke --limit 5
  bash scripts/run_phase06_baselines.sh m0 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5 --dry-run
  bash scripts/run_phase06_baselines.sh m1 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5
HELP
  exit 0
fi
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
LOG_DIR="$REPO_ROOT/outputs/phase06/logs"
mkdir -p "$LOG_DIR"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOG_PATH="$LOG_DIR/$1-$RUN_STAMP.log"
SUMMARY_ARGS=(--summary "$LOG_DIR/$1-$RUN_STAMP.json")
for arg in "$@"; do
  if [[ "$arg" == "--summary" ]]; then SUMMARY_ARGS=(); fi
done
printf '[%s] Phase 6 %s; log=%s\n' "$(date -u +%FT%TZ)" "$1" "$LOG_PATH"
python -u -m bugzilla_qa.evaluation.phase06 "$@" ${SUMMARY_ARGS[@]+"${SUMMARY_ARGS[@]}"} 2>&1 | tee "$LOG_PATH"
printf '[%s] Phase 6 %s finished\n' "$(date -u +%FT%TZ)" "$1"
