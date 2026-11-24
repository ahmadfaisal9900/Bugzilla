#!/usr/bin/env bash
# Owner-run clean environment validation. Downloads only the dashboard requirements.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$TASK_ROOT"
TASK_OUT="${1:?Supply output directory}"
mkdir -p -- "$TASK_OUT"
TASK_OUT="$(cd -- "$TASK_OUT" && pwd)"
TASK_VENV="$TASK_OUT/venv"
"${PYTHON:-python}" -m venv "$TASK_VENV"
"$TASK_VENV/bin/python" -m pip install -r dashboard/requirements.txt
"$TASK_VENV/bin/python" -m pip check
"$TASK_VENV/bin/python" - <<'PY'
import importlib.util
assert importlib.util.find_spec('torch') is None, 'Fresh dashboard venv must not have torch'
PY
/usr/bin/time -v -o "$TASK_OUT/peak_rss.txt" "$TASK_VENV/bin/python" scripts/testing/cloud_dashboard_check.py --output "$TASK_OUT/render.json"
TASK_PORT="${DASHBOARD_CLOUD_CHECK_PORT:-8599}"
"$TASK_VENV/bin/python" - "$TASK_PORT" <<'PY'
import socket,sys
with socket.socket() as s:
    s.bind(('127.0.0.1', int(sys.argv[1])))
PY
# Bind only loopback; never stop a pre-existing service on this port.
"$TASK_VENV/bin/python" -m streamlit run dashboard/streamlit_app.py --server.port "$TASK_PORT" --server.address 127.0.0.1 --server.headless true --server.fileWatcherType none >"$TASK_OUT/server.log" 2>&1 &
TASK_PID=$!
cleanup() { kill "$TASK_PID" 2>/dev/null || true; wait "$TASK_PID" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
TASK_READY=0
for ((TASK_TRY=0; TASK_TRY<30; TASK_TRY++)); do
  kill -0 "$TASK_PID" 2>/dev/null || { echo 'Dashboard server stopped; inspect server.log' >&2; exit 1; }
  if curl -fsS --max-time 2 "http://127.0.0.1:$TASK_PORT/_stcore/health" >/dev/null; then
    TASK_READY=1
    break
  fi
  sleep 1
done
[[ "$TASK_READY" == 1 ]] || { echo 'Dashboard health check timed out' >&2; exit 1; }
"$TASK_VENV/bin/python" - "$TASK_OUT/render.json" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); r=json.loads(p.read_text()); r.update(clean_venv=True, server_health='PASS')
p.write_text(json.dumps(r,indent=2)+'\n'); print(json.dumps(r))
PY
