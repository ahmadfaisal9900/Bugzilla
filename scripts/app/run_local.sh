#!/usr/bin/env bash
# API + chat; --dashboard adds the read-only dashboard. Ctrl-C stops all children.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$TASK_ROOT"
case "${1:-}" in
  --help|-h) echo 'Usage: scripts/app/run_local.sh [--dashboard]'; exit 0 ;;
  ''|--dashboard) ;;
  *) echo 'Unknown argument; use --help' >&2; exit 2 ;;
esac
PYTHON="${PYTHON:-python}"
export PYTHONPATH="$TASK_ROOT/src:$TASK_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# Parse .env as data with the existing parser; never execute its values as shell code.
while IFS= read -r -d '' entry; do export "$entry"; done < <("$PYTHON" - <<'PY'
from bugzilla_qa.llm.provider import env_values
import sys
for key, value in env_values('.env').items():
    sys.stdout.buffer.write((key + '=' + value + '\0').encode())
PY
)
export BUNDLE_DIR="${BUNDLE_DIR:-$TASK_ROOT/serving_bundle}"
export API_URL="http://127.0.0.1:8000" DASHBOARD_LAB_ENABLED=false
"$PYTHON" - "${1:-}" <<'PY'
import os, socket, sys
from pathlib import Path
from bugzilla_serving.bundle import load_bundle
if not os.environ.get('SERVING_API_KEY'):
    raise SystemExit('Set SERVING_API_KEY in .env first.')
if not (Path(os.environ['BUNDLE_DIR']) / 'manifest.json').is_file():
    raise SystemExit('BUNDLE_DIR must contain manifest.json.')
with load_bundle(os.environ['BUNDLE_DIR']):
    pass
for port in ((8000, 8501, 8502) if sys.argv[1] == "--dashboard" else (8000, 8501)):
    with socket.socket() as s:
        try: s.bind(('127.0.0.1', port))
        except OSError: raise SystemExit(f'Port {port} is already in use.')
PY
TASK_PIDS=()
cleanup() {
  trap - EXIT INT TERM
  if ((${#TASK_PIDS[@]})); then
    kill "${TASK_PIDS[@]}" 2>/dev/null || true
    wait "${TASK_PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$PYTHON" -m uvicorn bugzilla_serving.api.app:app --host 127.0.0.1 --port 8000 &
TASK_PIDS+=("$!")
"$PYTHON" -m streamlit run src/bugzilla_serving/chat_ui/app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true &
TASK_PIDS+=("$!")
if [[ "${1:-}" == --dashboard ]]; then
  "$PYTHON" -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502 --server.address 127.0.0.1 --server.headless true --server.fileWatcherType none &
  TASK_PIDS+=("$!")
fi
printf 'Chat: http://localhost:8501\nAPI: http://localhost:8000\n'
wait -n "${TASK_PIDS[@]}"
