#!/bin/sh
set -eu
mkdir -p "${DASHBOARD_CACHE_DIR:-/app/outputs/dashboard_cache}"
python scripts/mlops/build_dashboard_snapshot.py > "${DASHBOARD_CACHE_DIR:-/app/outputs/dashboard_cache}/startup.log" 2>&1 &
exec "$@"
