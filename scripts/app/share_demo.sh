#!/usr/bin/env bash
# Share only Streamlit. API calls and SSE remain server-to-server on localhost.
set -euo pipefail
if [[ "${1:-}" == --dry-run ]]; then
  printf '%s\n' 'Checks: http://localhost:8000/v1/health and http://localhost:8501/_stcore/health' \
    'Then: cloudflared tunnel --url http://localhost:8501' 'Ctrl-C closes the temporary public link.'
  exit 0
fi
if [[ $# -gt 0 ]]; then echo 'Usage: scripts/app/share_demo.sh [--dry-run]' >&2; exit 2; fi
command -v cloudflared >/dev/null || { echo 'Install cloudflared first; see docs/DEMO_RUNBOOK.md.' >&2; exit 2; }
curl --fail --silent --show-error --max-time 10 http://localhost:8000/v1/health >/dev/null
curl --fail --silent --show-error --max-time 10 http://localhost:8501/_stcore/health >/dev/null
printf '%s\n' 'Sharing chat only (8501). The https://*.trycloudflare.com URL appears below.' \
  'Keep API_URL on localhost. Ctrl-C ends the tunnel; local fallback: http://localhost:8501'
exec cloudflared tunnel --url http://localhost:8501
