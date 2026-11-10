#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
stage=all
args=()
while (($#)); do
  case "$1" in
    --help|-h)
      cat <<'EOF'
Usage: bash scripts/run_eval_extension.sh [--stage all|preflight|corpus|lexical|search]
       [--dry-run] [--limit N] [--seed 317] [--resume] [--output-root PATH]
       [--config PATH] [--query TEXT]

The current implementation provides source corpus export and SQLite lexical indexing.
The all stage runs those two stages and then reports the unimplemented stages.
No model downloads, network calls, benchmark generation or evaluation are performed.
EOF
      exit 0 ;;
    --stage) stage="${2:?missing stage}"; shift 2 ;;
    --limit|--seed|--output-root|--config|--query) args+=("$1" "${2:?missing value}"); shift 2 ;;
    --dry-run|--resume) args+=("$1"); shift ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
cd "$ROOT"
if [[ "$stage" == all ]]; then
  python -u -m bugzilla_qa.eval_extension.cli --stage corpus "${args[@]}"
  python -u -m bugzilla_qa.eval_extension.cli --stage lexical "${args[@]}"
  printf '%s\n' 'BLOCKED: benchmark expansion, dense/hybrid/reranking, evaluation and generation are not implemented.' >&2
  exit 3
fi
python -u -m bugzilla_qa.eval_extension.cli --stage "$stage" "${args[@]}"
