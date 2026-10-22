#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_OUTPUT="${PROJECT_ROOT}/outputs/audit/phase02"
CONFIG="${PROJECT_ROOT}/configs/data_paths.local.yaml"
DRY_RUN=0
RESUME=0
PASSTHROUGH=()

usage() {
  cat <<'EOF'
Usage: bash scripts/run_phase02_audit.sh [options]

Options:
  --dry-run              Print the command and paths without scanning.
  --limit N              Scan at most N rows per CSV (bounded sample mode).
  --resume               Reuse completed, unchanged files in the latest run.
  --skip LABEL           Skip one dataset label (repeatable or comma-separated).
  --skip-checksum        Skip SHA-256 comparison of comments Parts 1 and 2.
  --config PATH          Use another flat YAML data-path config.
  --help                 Show this help.

Dataset labels: metadata, reports, comments_part_1, comments_part_2, upstream_sample
Full audit (launched manually by the user): bash scripts/run_phase02_audit.sh
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --resume) RESUME=1; PASSTHROUGH+=(--resume); shift ;;
    --limit)
      [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] || { echo "--limit requires a positive integer" >&2; exit 2; }
      PASSTHROUGH+=(--limit "$2"); shift 2 ;;
    --skip)
      [[ $# -ge 2 ]] || { echo "--skip requires a dataset label" >&2; exit 2; }
      PASSTHROUGH+=(--skip "$2"); shift 2 ;;
    --skip-checksum) PASSTHROUGH+=(--skip-checksum); shift ;;
    --config)
      [[ $# -ge 2 ]] || { echo "--config requires a path" >&2; exit 2; }
      CONFIG="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$CONFIG" != /* ]]; then
  CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
fi

[[ -f "$CONFIG" ]] || { echo "Missing data path config: $CONFIG" >&2; echo "Copy configs/data_paths.example.yaml to configs/data_paths.local.yaml and adjust paths." >&2; exit 2; }

if ((RESUME)); then
  LATEST_FILE="${BASE_OUTPUT}/LATEST_RUN"
  [[ -f "$LATEST_FILE" ]] || { echo "No prior run found to resume under $BASE_OUTPUT" >&2; exit 2; }
  RUN_ID="$(cat "$LATEST_FILE")"
  [[ "$RUN_ID" =~ ^run-[A-Za-z0-9_.-]+$ ]] || { echo "Invalid latest-run marker" >&2; exit 2; }
else
  RUN_ID="run-$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi

OUTPUT_DIR="${BASE_OUTPUT}/${RUN_ID}"
LOG_PATH="${PROJECT_ROOT}/logs/phase02_audit_${RUN_ID#run-}.log"
COMMAND=(python3 "${PROJECT_ROOT}/src/data/audit.py" --root "$PROJECT_ROOT" --config "$CONFIG" --output-dir "$OUTPUT_DIR" "${PASSTHROUGH[@]}")

if ((DRY_RUN)); then
  printf 'PROJECT_ROOT=%s\nCONFIG=%s\nOUTPUT_DIR=%s\nLOG_PATH=%s\nCOMMAND=' "$PROJECT_ROOT" "$CONFIG" "$OUTPUT_DIR" "$LOG_PATH"
  printf '%q ' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi

mkdir -p "$OUTPUT_DIR" "${PROJECT_ROOT}/logs"
if ((!RESUME)); then
  printf '%s\n' "$RUN_ID" > "${BASE_OUTPUT}/LATEST_RUN"
fi
printf '[%s] Phase 2 audit starting; output=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$OUTPUT_DIR" | tee -a "$LOG_PATH"
cd "$PROJECT_ROOT"
"${COMMAND[@]}" 2>&1 | tee -a "$LOG_PATH"
printf '[%s] Phase 2 audit finished; machine summary=%s/audit_summary.json\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$OUTPUT_DIR" | tee -a "$LOG_PATH"
