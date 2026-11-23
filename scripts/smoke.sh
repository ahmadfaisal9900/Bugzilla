#!/usr/bin/env bash
# Smoke-test a running stack (compose.ci.yaml locally or in CI, compose.yaml on the host).
#
#   bash scripts/smoke.sh              # ready + one /v1/ask per preset (mock LLM) + chat + dashboard
#   bash scripts/smoke.sh --r0-only    # ready + one R0 query (retrieval only, 0 LLM calls) + chat
#
# Settings (environment): API_URL, CHAT_URL, DASHBOARD_URL, SERVING_API_KEY,
# SMOKE_DASHBOARD=0 to skip the dashboard, SMOKE_TIMEOUT seconds to wait for /v1/ready.
# Works in Git Bash on Windows and on Linux. Needs curl and python (or python3).
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
CHAT_URL="${CHAT_URL:-http://localhost:8501}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:8502}"
SERVING_API_KEY="${SERVING_API_KEY:-ci-smoke-key}"
SMOKE_DASHBOARD="${SMOKE_DASHBOARD:-1}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-240}"
MODE="${1:-all}"

PY="$(command -v python3 || command -v python)"
failures=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*" >&2; failures=$((failures + 1)); }

status_of() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@" || true; }

# Wait until a URL answers 200 (the UIs can start a few seconds after the API is ready).
wait_200() {
  local url="$1" code="" until=$((SECONDS + 60))
  while :; do
    code="$(status_of "$url")"
    [[ "$code" == 200 || SECONDS -ge until ]] && break
    sleep 2
  done
  printf '%s' "$code"
}

# 1. /v1/ready returns 200 (the API loads the bundle at startup, so allow time).
deadline=$((SECONDS + SMOKE_TIMEOUT))
until [[ "$(status_of -H "X-API-Key: ${SERVING_API_KEY}" "${API_URL}/v1/ready")" == 200 ]]; do
  if ((SECONDS >= deadline)); then
    fail "/v1/ready did not return 200 within ${SMOKE_TIMEOUT}s"
    exit 1
  fi
  sleep 3
done
pass "/v1/ready 200"

# POST /v1/ask and check the answer record. Prints "slug llm_calls latency_ms" on success.
ask() {
  local label="$1" body="$2" max_calls="$3" out
  out="$(mktemp)"
  local code
  code="$(curl -s -o "$out" -w '%{http_code}' --max-time 180 \
    -H "X-API-Key: ${SERVING_API_KEY}" -H 'Content-Type: application/json' \
    -d "$body" "${API_URL}/v1/ask" || true)"
  if [[ "$code" != 200 ]]; then
    fail "/v1/ask ${label}: HTTP ${code} $(head -c 300 "$out")"
  elif summary="$("$PY" - "$out" "$max_calls" <<'EOF'
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))["record"]
max_calls = int(sys.argv[2])
assert "answer" in record, "no answer in record"
assert max_calls < 0 or record["llm_calls"] <= max_calls, f"llm_calls={record['llm_calls']}"
print(f"llm_calls={record['llm_calls']} latency_ms={record['latency_ms']:.0f}")
EOF
  )"; then
    pass "/v1/ask ${label} (${summary})"
  else
    fail "/v1/ask ${label}: unexpected record $(head -c 300 "$out")"
  fi
  rm -f "$out"
}

body() {  # body <session> <preset_slug> <overrides-json>
  printf '{"session_id":"%s","message":"%s","preset_slug":"%s","overrides":%s}' \
    "$1" "What component is bug 100000 filed under?" "$2" "$3"
}

if [[ "$MODE" == "--r0-only" ]]; then
  # 2. R0 is retrieval only: it must answer with zero LLM calls (free, safe after a deploy).
  ask "R0" "$(body "smoke-r0-$RANDOM" fast '{"system_id":"R0","retriever":"R5"}')" 0
else
  # 2. One /v1/ask per preset, forced onto the mock provider.
  presets="$(curl -fsS --max-time 10 -H "X-API-Key: ${SERVING_API_KEY}" "${API_URL}/v1/presets" |
    "$PY" -c 'import json, sys; print(" ".join(p["slug"] for p in json.load(sys.stdin)))')"
  [[ -n "$presets" ]] || fail "/v1/presets returned no presets"
  for slug in $presets; do
    ask "preset=${slug}" "$(body "smoke-${slug}-$RANDOM" "$slug" '{"provider":"mock"}')" -1
  done
fi

# 3. The chat page (Streamlit's own health route, then the page itself).
for path in /_stcore/health /; do
  code="$(wait_200 "${CHAT_URL}${path}")"
  [[ "$code" == 200 ]] && pass "chat ${path} 200" || fail "chat ${path} HTTP ${code}"
done

# 4. The dashboard.
if [[ "$SMOKE_DASHBOARD" == 1 ]]; then
  code="$(wait_200 "${DASHBOARD_URL}/")"
  [[ "$code" == 200 ]] && pass "dashboard / 200" || fail "dashboard / HTTP ${code}"
else
  printf 'SKIP  dashboard (SMOKE_DASHBOARD=0)\n'
fi

if ((failures)); then
  printf '%d check(s) failed\n' "$failures" >&2
  exit 1
fi
printf 'All smoke checks passed\n'
