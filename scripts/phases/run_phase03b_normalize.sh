#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="$ROOT/outputs/normalization/phase03b"
DRY_RUN=0
RESUME=0
ARGS=()
usage() {
  cat <<'EOF'
Usage: bash scripts/phases/run_phase03b_normalize.sh [options]
  --dry-run                 Validate saved QC, file signatures, and show selection; no CSV scan
  --limit N                 Bounded logical CSV rows per source (a separate smoke version)
  --resume                  Resume latest run with the same options/seed/limit/code
  --sample-target N         Planning target, default 3000; fewer bugs allowed
  --sample-seed N           Isolated deterministic seed, default 317
  --product NAME            Sample product, default Firefox; ALL includes all products
  --include-quality         Optional quality records, kept separate from base tables
  --qc-dir PATH             Verified Phase 3A run; default its LATEST_RUN
  --memory-limit SIZE       DuckDB budget, default 512MB
  --chunk-size N            Streaming checkpoint batch, default 2000
  --cutoff ISO_TIMESTAMP    Optional explicit as-of QC only; no default T0/T1
  -h, --help                Show help

Dependency (free): python -m pip install duckdb==1.4.4
Full input is about 2.0 GB. Reserve 5-10 GB disk for database, Parquet, and spill.
Wall time is unmeasured; allow tens of minutes or longer, depending on disk/CPU.
DuckDB memory budget excludes Python's current CSV row and bounded row batch.
No API calls, model jobs, or changes to Dataset/ occur.
EOF
}
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --resume) RESUME=1; shift ;;
    --include-quality) ARGS+=("$1"); shift ;;
    --limit|--sample-target|--sample-seed|--product|--qc-dir|--memory-limit|--chunk-size|--cutoff)
      (($# >= 2)) || { echo "$1 requires a value" >&2; exit 2; }
      ARGS+=("$1" "$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if ((DRY_RUN)); then
  python -m bugzilla_qa.data.normalize --root "$ROOT" --dry-run "${ARGS[@]}"
  exit 0
fi
if ! python -c 'import duckdb' >/dev/null 2>&1; then
  echo "Install dependency in this interpreter: python -m pip install duckdb==1.4.4" >&2
  exit 2
fi
mkdir -p "$BASE"
if ((RESUME)); then
  [[ -f "$BASE/LATEST_RUN" ]] || { echo "No Phase 3B run to resume" >&2; exit 2; }
  RUN_ID="$(<"$BASE/LATEST_RUN")"
  [[ "$RUN_ID" =~ ^run-[A-Za-z0-9T_-]+$ ]] || { echo "Invalid LATEST_RUN" >&2; exit 2; }
  RUN_DIR="$BASE/$RUN_ID"
  [[ -f "$RUN_DIR/manifest.json" ]] || { echo "Run manifest missing" >&2; exit 2; }
  ARGS+=(--resume)
else
  RUN_ID="run-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  RUN_DIR="$BASE/$RUN_ID"
  mkdir -p "$RUN_DIR"
  printf '%s\n' "$RUN_ID" > "$BASE/LATEST_RUN.tmp"
  mv "$BASE/LATEST_RUN.tmp" "$BASE/LATEST_RUN"
fi
exec > >(tee -a "$RUN_DIR/terminal.log") 2>&1
echo "[$(date -Is)] Phase 3B output=$RUN_DIR"
echo "DuckDB budget 512MB by default; reserve 5-10 GB disk. Wall time is unmeasured."
python -m bugzilla_qa.data.normalize --root "$ROOT" --output "$RUN_DIR" "${ARGS[@]}"
echo "[$(date -Is)] Finished. Review $RUN_DIR/qc_report.json and manifest.json"
