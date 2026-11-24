#!/usr/bin/env bash
# Run the S evaluation and generate its review page from the repository root.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_root"
export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
python_runner=python
if [[ -x "$project_root/.venv/bin/python" ]]; then
  python_runner="$project_root/.venv/bin/python"
elif [[ -f "$project_root/.venv/Scripts/python.exe" ]]; then
  python_runner="$project_root/.venv/Scripts/python.exe"
fi
exec "$python_runner" -m bugzilla_qa.evaluation.experiment "$@"
