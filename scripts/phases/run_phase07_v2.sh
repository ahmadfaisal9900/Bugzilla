#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$project_root"
export PYTHONPATH="$project_root/src:$project_root${PYTHONPATH:+:$PYTHONPATH}"
exec python -m bugzilla_serving.experiments.v2_jobs "$@"
