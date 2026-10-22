#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="$ROOT/outputs/data_exploration"
LIMIT=""
SEED=317
DRY_RUN=0
RESUME=0

usage() {
  cat <<'EOF'
Usage: bash scripts/phases/run_phase03a_explore.sh [options]

Stream and profile the configured BugsRepo CSV files. With no --limit, this
reads all configured sources and may take hours on the largest comment export.

Options:
  --dry-run          List source paths and sizes without reading CSV content
  --limit N          Read at most N CSV records per source (bounded prefix)
  --sample-seed N    Deterministic schema reservoir seed (default: 317)
  --resume            Reuse completed source checkpoints in the latest run
  -h, --help          Show this help

Run from the Project/ root. Full mode is intended for the user's terminal.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --limit)
      (($# >= 2)) || { echo "--limit requires a positive integer" >&2; exit 2; }
      LIMIT="$2"; shift 2 ;;
    --sample-seed)
      (($# >= 2)) || { echo "--sample-seed requires an integer" >&2; exit 2; }
      SEED="$2"; shift 2 ;;
    --resume) RESUME=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$LIMIT" && ! "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "--limit must be a positive integer" >&2
  exit 2
fi
if [[ -n "$LIMIT" && "$LIMIT" == "0" ]]; then
  echo "--limit must be a positive integer" >&2
  exit 2
fi

mkdir -p "$BASE"
if ((DRY_RUN && !RESUME)); then
  RUN_ID="dry-run"
  RUN_DIR="$BASE/$RUN_ID"
  mkdir -p "$RUN_DIR"
elif ((RESUME)); then
  [[ -f "$BASE/LATEST_RUN" ]] || { echo "No previous Phase 3A run to resume; omit --resume." >&2; exit 2; }
  RUN_ID="$(<"$BASE/LATEST_RUN")"
  [[ "$RUN_ID" =~ ^run-[A-Za-z0-9T._-]+$ ]] || { echo "Invalid LATEST_RUN entry" >&2; exit 2; }
  RUN_DIR="$BASE/$RUN_ID"
  [[ -d "$RUN_DIR" ]] || { echo "Checkpoint directory is missing: $RUN_ID" >&2; exit 2; }
else
  RUN_ID="run-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  RUN_DIR="$BASE/$RUN_ID"
  mkdir -p "$RUN_DIR"
  printf '%s\n' "$RUN_ID" > "$BASE/LATEST_RUN.tmp"
  mv "$BASE/LATEST_RUN.tmp" "$BASE/LATEST_RUN"
fi

LOG="$RUN_DIR/terminal.log"
exec > >(tee -a "$LOG") 2>&1
echo "[$(date -Is)] Phase 3A profile; output=$RUN_DIR"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(--root "$ROOT" --config configs/data_paths.local.yaml --output "$RUN_DIR" --sample-seed "$SEED")
if [[ -n "$LIMIT" ]]; then ARGS+=(--limit "$LIMIT"); fi
if ((RESUME)); then ARGS+=(--resume); fi
if ((DRY_RUN)); then ARGS+=(--dry-run); fi

python -m bugzilla_qa.data.profile "${ARGS[@]}"
if ((DRY_RUN)); then
  echo "[$(date -Is)] Dry-run plan complete; no CSV records were read. Log: $LOG"
else
  echo "[$(date -Is)] Phase 3A command finished. Profile: $RUN_DIR/profile.json; summary: $RUN_DIR/summary.json; progress: $RUN_DIR/progress.log"
fi
