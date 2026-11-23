"""Check quota thresholds, session windows and source-only API responses without Groq calls."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from bugzilla_serving.api import app as api
from bugzilla_serving.api.presets import PresetStore
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.quota import QuotaGuard, SessionLimiter, SessionRateLimit, degraded_config

MODEL = "openai/gpt-oss-20b"
HEADERS = {"X-API-Key": "fake-quota-test-key"}
BODY = {
    "session_id": "quota-test",
    "message": "What product is recorded for bug 100000?",
    "preset_slug": "fast",
    "overrides": {"provider": "groq"},
}


@pytest.fixture
def guard(tmp_path):
    config = {
        "provider": "groq",
        "env_file": "missing.env",
        "ledger": "ledger.jsonl",
        "daily_fraction": 0.9,
        "models": {"generator": {"id": MODEL, "rpm": 30, "rpd": 1000}},
    }
    (tmp_path / "llm.json").write_text(json.dumps(config))
    return QuotaGuard(root=tmp_path, llm_config="llm.json")


def ledger(guard, requests=0, tokens=0, *, recent=False):
    when = datetime.now(timezone.utc) - timedelta(seconds=10 if recent else 120)
    rows = []
    for index in range(requests):
        rows.append(
            dict(
                provider="groq",
                model=MODEL,
                ts=when.isoformat(),
                status="REQUEST_STARTED",
                prompt_hash=str(index),
            )
        )
    if tokens:
        rows.append(
            dict(
                provider="groq",
                model=MODEL,
                ts=when.isoformat(),
                status="SUCCESS",
                input_tokens=tokens,
                output_tokens=0,
            )
        )
    (guard.root / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.mark.parametrize("requests,expected", [(890, "ok"), (900, "degrade"), (910, "degrade")])
def test_daily_requests(guard, requests, expected):
    ledger(guard, requests=requests)
    assert guard.check(RunConfig(), 3800).action == expected


@pytest.mark.parametrize(
    "tokens,expected", [(178000, "ok"), (180000, "degrade"), (182000, "degrade")]
)
def test_daily_tokens(guard, tokens, expected):
    ledger(guard, tokens=tokens)
    assert guard.check(RunConfig(), 3800).action == expected


def test_tpm_estimate_and_expiration(guard):
    ledger(guard, tokens=7500, recent=True)
    assert guard.check(RunConfig(), 500).action == "ok"
    assert guard.check(RunConfig(), 501).action == "degrade"
    assert guard.status().models[0].degraded_now
    guard.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=61)
    assert guard.check(RunConfig(), 3800).action == "ok"


def test_cache_hits_do_not_consume_tokens(guard):
    ledger(guard)
    row = dict(
        provider="groq",
        model=MODEL,
        ts=datetime.now(timezone.utc).isoformat(),
        status="CACHE_HIT",
        input_tokens=500000,
        output_tokens=100,
    )
    (guard.root / "ledger.jsonl").write_text(json.dumps(row) + "\n")
    assert guard.check(RunConfig(), 3800).action == "ok"
    assert guard.status().models[0].used_tokens == 0


def test_recent_unknown_usage_falls_back(guard):
    ledger(guard, requests=1, recent=True)
    assert guard.check(RunConfig(), 3800).action == "degrade"
    assert "not yet known" in guard.check(RunConfig(), 3800).reason


def test_corrupt_ledger_falls_back(guard):
    (guard.root / "ledger.jsonl").write_text("invalid JSON")
    assert guard.check(RunConfig(), 3800).action == "degrade"


def test_session_window():
    clock = [0.0]
    limiter = SessionLimiter(clock=lambda: clock[0])
    for _ in range(6):
        limiter.admit("one")
    with pytest.raises(SessionRateLimit) as result:
        limiter.admit("one")
    assert result.value.retry_after == 60
    limiter.admit("two")
    clock[0] = 59.5
    with pytest.raises(SessionRateLimit) as result:
        limiter.admit("one")
    assert result.value.retry_after == 1
    clock[0] = 60
    limiter.admit("one")
    assert "two" not in limiter.sessions


def test_r0_removes_inapplicable_options():
    config = RunConfig(system_id="S5", retriever="R7b", s5_dossier_budget=4096, rrf_k=60)
    fallback = degraded_config(config)
    assert fallback.system_id == "R0" and fallback.retriever == "R1"
    assert fallback.s5_dossier_budget is None and fallback.rrf_k is None
    for retriever in ("R1", "R2", "R3", "R4", "R5", "R6"):
        assert (
            degraded_config(RunConfig(system_id="S2", retriever=retriever)).retriever == retriever
        )


@pytest.fixture
def client(tmp_path, monkeypatch, guard):
    spec = importlib.util.spec_from_file_location(
        "quota_builder", ROOT / "scripts/testing/build_fixture_bundle.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    bundle = builder.build(tmp_path / "bundle")
    monkeypatch.setenv("BUNDLE_DIR", str(bundle))
    monkeypatch.setenv("SERVING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SERVING_API_KEY", HEADERS["X-API-Key"])
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("TRACE_SAMPLE", "0")
    monkeypatch.setattr(PresetStore, "_registry", Mock(side_effect=RuntimeError("offline")))
    from bugzilla_qa.answering.backend import Backend
    from bugzilla_qa.llm.provider import GroqProvider
    from bugzilla_qa.retrieval_v3.registry import Engine

    monkeypatch.setattr(
        Backend,
        "_engine",
        lambda backend: Engine(
            backend.docs,
            backend.directory / "lexical.sqlite",
            None,
            None,
            [],
            backend.rc,
        ),
    )
    monkeypatch.setattr(
        GroqProvider, "_request", Mock(side_effect=AssertionError("No Groq calls allowed"))
    )
    with TestClient(api.create_app()) as test_client:
        test_client.app.state.quota_guard = guard
        yield test_client


def test_api_degrades_and_reports_usage(client, guard):
    ledger(guard, requests=910, tokens=182000)
    result = client.post("/v1/ask", headers=HEADERS, json=BODY)
    assert result.status_code == 200
    record = result.json()["record"]
    assert record["degraded"] and record["route"] == "R0" and record["route_rule"] == "quota_guard"
    assert record["evidence"] and record["llm_calls"] == 0 and record["answer"]["abstain"]
    quota = client.get("/v1/quota", headers=HEADERS).json()["models"][0]
    assert (
        quota["used_requests"] == 910 and quota["used_tokens"] == 182000 and quota["degraded_now"]
    )


def test_degraded_stream_has_reason_and_no_llm_calls(client, guard):
    ledger(guard, requests=910)
    response = client.post("/v1/chat/stream", headers=HEADERS, json=BODY)
    assert response.status_code == 200
    frames = [frame.splitlines() for frame in response.text.strip().split("\n\n")]
    events = [{"event": lines[0][7:], "data": json.loads(lines[1][6:])} for lines in frames]
    assert [e["event"] for e in events] == ["status"] * 5 + ["evidence", "answer", "done"]
    assert "showing sources" in events[0]["data"]["detail"]
    answer = next(e["data"] for e in events if e["event"] == "answer")
    assert answer["degraded"] and answer["llm_calls"] == 0


def test_seventh_question_returns_429_before_queueing(client):
    body = {**BODY, "overrides": {"provider": "mock"}}
    for _ in range(6):
        assert client.post("/v1/ask", headers=HEADERS, json=body).status_code == 200
    for route in ("ask", "chat/stream"):
        response = client.post("/v1/" + route, headers=HEADERS, json=body)
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"
        assert 1 <= response.json()["retry_after"] <= 60
        assert response.headers["retry-after"] == str(response.json()["retry_after"])


def test_request_minute_limit(guard):
    ledger(guard)
    usage = guard.usage(MODEL)
    usage["minute_requests"] = 30
    assert guard.decision(MODEL, usage, 1).action == "degrade"
