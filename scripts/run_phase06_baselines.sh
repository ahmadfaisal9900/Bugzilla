#!/usr/bin/env bash
set -euo pipefail
if [[ $# -eq 0 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'HELP'
Usage: bash scripts/run_phase06_baselines.sh m0|m1|m3|m3-llm|bm25 [OPTIONS]

m0    Ask the local model without project evidence.
m1    Retrieve BM25 evidence, then ask the same local model.
m3    Smoke-test parameterized SQL with the development-wording parser.
m3-llm  Ask the local model for a typed intent, then answer with read-only SQL.
bm25  Build the keyword index, retrieve for development questions, report Recall@5/10.

Development questions only: this tool has no option for the locked test. M0/M1 and m3-llm require an
already installed Ollama model on localhost. M3 can use the shared sample bundle.
The full-source path uses the pinned Phase 3B database and Phase 4 overlay.

Options:
  --unfrozen-dev-smoke  Use dev questions from the unreviewed candidates. Results are a code check,
                        never a study result. The default full-source mode requires a freeze.
  --review-bundle PATH  Use only development rows from the signoff bundle for a smoke
  --sample-bundle PATH  Use shared DuckDBs for M3, with the tracked review bundle by default
  --run PATH            Generation run (default: outputs/benchmark/phase05/run-65c5be3381f66811)
  --limit N             Answer at most N questions in total; the run is marked PARTIAL
  --resume              Continue an existing output from its checkpoint
  --dry-run             Report missing inputs only; writes no results
  --summary PATH        Summary JSON (default: a timestamped file beside the log)
  --model NAME          Required for m0/m1/m3-llm; use the same installed model
  --max-requests N      Cap model calls per invocation (default 5, including failed calls)
  --max-output-tokens N Output cap (default 512)
  --top-k N             M1 retrieval count (default 5)
  --evidence-chars N    M1 serialized evidence character budget (default 12000)
  --cpu                 Run the local model without GPU offloading
  --timeout SECONDS     Local model response timeout (default 60)

Outputs go to outputs/phase06/<method>-dev-<smoke|shared-smoke|frozen>-<question hash>/, with a checkpoint,
summary.json, and scores.jsonl for answer methods. Both SQL commands have no comment text,
so F5 is an abstention by design. The study's M3 uses m3-llm.

Examples:
  bash scripts/run_phase06_baselines.sh m3 --unfrozen-dev-smoke --dry-run
  bash scripts/run_phase06_baselines.sh m3 --unfrozen-dev-smoke
  bash scripts/run_phase06_baselines.sh bm25 --unfrozen-dev-smoke --limit 5
  bash scripts/run_phase06_baselines.sh m0 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5 --dry-run
  bash scripts/run_phase06_baselines.sh m1 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5
  bash scripts/run_phase06_baselines.sh m3-llm --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5
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
