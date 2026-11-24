"""Check API routes, authentication, streaming, runner caching and preset fallback offline."""

import hashlib
import importlib.util
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from bugzilla_serving.api import app as api
from bugzilla_serving.api.presets import PresetStore
from bugzilla_serving.contracts.records import SSEEvent
from bugzilla_serving.contracts.run_config import ROOT, RunConfig, config_hash

KEY = "fake-serving-key-for-tests"
HEADERS = {"X-API-Key": KEY}
BODY = {
    "session_id": "test-session",
    "message": "What product is recorded for bug 100000?",
    "preset_slug": "fast",
    "overrides": {"provider": "mock"},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    script = ROOT / "scripts/testing/build_fixture_bundle.py"
    spec = importlib.util.spec_from_file_location("api_fixture_builder", script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    bundle = builder.build(tmp_path / "bundle")
    monkeypatch.setenv("BUNDLE_DIR", str(bundle))
    monkeypatch.setenv("SERVING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SERVING_API_KEY", KEY)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("TRACE_SAMPLE", "0")
    monkeypatch.setattr(PresetStore, "_registry", Mock(side_effect=RuntimeError("offline")))
    from bugzilla_qa.answering.backend import Backend
    from bugzilla_qa.retrieval_v3.registry import Engine

    def lexical_engine(backend):
        if backend.engine is None:
            backend.engine = Engine(
                backend.docs, backend.directory / "lexical.sqlite", None, None, [], backend.rc
            )
        return backend.engine

    monkeypatch.setattr(Backend, "_engine", lexical_engine)
    with TestClient(api.create_app()) as test_client:
        yield test_client


def events(response):
    parsed = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        parsed.append(
            {
                "event": lines[0].removeprefix("event: "),
                "data": json.loads(lines[1].removeprefix("data: ")),
            }
        )
    adapter = TypeAdapter(SSEEvent)
    for event in parsed:
        adapter.validate_python(event)
    return parsed


def test_openapi_unchanged():
    path = ROOT / "tests/contracts/openapi.json"
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    assert api.create_app().openapi() == json.loads(path.read_text())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


@pytest.mark.parametrize(
    ("slot", "name"),
    [
        ("1", "GROQ_API_KEY"),
        ("2", "GROQ_API_KEY_2"),
        ("3", "GROQ_API_KEY_3"),
        ("4", "GROQ_API_KEY_4"),
    ],
)
def test_serving_groq_key_slot(monkeypatch, slot, name):
    monkeypatch.delenv("SERVING_GROQ_KEY_SLOT", raising=False)
    monkeypatch.delenv(name, raising=False)
    values = {"SERVING_GROQ_KEY_SLOT": slot, name: "test-file-key"}
    assert api.selected_groq_key(values) == "test-file-key"
    monkeypatch.setenv(name, "test-process-key")
    assert api.selected_groq_key(values) == "test-process-key"


def test_missing_selected_groq_key_does_not_use_primary(monkeypatch):
    monkeypatch.setenv("SERVING_GROQ_KEY_SLOT", "4")
    monkeypatch.delenv("GROQ_API_KEY_4", raising=False)
    with pytest.raises(ValueError, match="GROQ_API_KEY_4 is missing"):
        api.selected_groq_key({"GROQ_API_KEY": "test-primary-key"})


def test_get_routes(client):
    assert client.get("/v1/health").json() == {"status": "ok"}
    assert client.get("/v1/ready", headers=HEADERS).json() == {"status": "ok"}
    options = client.get("/v1/options", headers=HEADERS)
    assert options.status_code == 200
    assert options.json()["models"] and options.json()["hyperparameters"]
    assert client.get("/v1/presets", headers=HEADERS).json() == options.json()["presets"]
    assert len(client.get("/v1/examples", headers=HEADERS).json()) == 10
    quota = client.get("/v1/quota", headers=HEADERS)
    assert quota.status_code == 200 and quota.json()["models"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/ready"),
        ("GET", "/v1/options"),
        ("GET", "/v1/presets"),
        ("GET", "/v1/examples"),
        ("GET", "/v1/quota"),
        ("POST", "/v1/ask"),
        ("POST", "/v1/chat/stream"),
        ("POST", "/v1/feedback"),
    ],
)
def test_auth_required(client, method, path):
    assert client.request(method, path, json={}).status_code == 401
    assert client.request(method, path, headers={"X-API-Key": "wrong"}, json={}).status_code == 401


def test_ask_feedback_and_threadpool(client, monkeypatch):
    build = api.build_runner
    threads = []

    def checked_build(config):
        threads.append(threading.current_thread().name)
        return build(config)

    monkeypatch.setattr(api, "build_runner", checked_build)
    result = client.post("/v1/ask", headers=HEADERS, json=BODY)
    assert result.status_code == 200
    body = result.json()
    assert body["record"]["evidence"] and body["record"]["answer"]["abstain"]
    assert body["langsmith_run_id"] is None
    assert threads and all("worker" in name.lower() for name in threads)
    feedback = {"request_id": body["request_id"], "score": 1, "comment": "Useful sources"}
    assert client.post("/v1/feedback", headers=HEADERS, json=feedback).json() == {"status": "ok"}
    with sqlite3.connect(client.app.state.feedback_db) as db:
        assert db.execute("select score,comment from feedback").fetchone() == (1, "Useful sources")
    feedback["score"] = 0
    assert client.post("/v1/feedback", headers=HEADERS, json=feedback).status_code == 200
    feedback["request_id"] = "unknown"
    assert client.post("/v1/feedback", headers=HEADERS, json=feedback).status_code == 404


@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"top_k": 0}, "top_k"),
        ({"top_k": 51}, "top_k"),
        ({"top_k": "5"}, "top_k"),
        ({"unexpected": KEY}, "unexpected"),
        ({"corpus": "not-a-corpus"}, "corpus"),
    ],
)
def test_invalid_config(client, overrides, field):
    for route in ("ask", "chat/stream"):
        response = client.post(
            "/v1/" + route, headers=HEADERS, json={**BODY, "overrides": overrides}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_config"
        assert field in response.json()["message"] and KEY not in response.text


def test_stream_order(client):
    response = client.post("/v1/chat/stream", headers=HEADERS, json=BODY)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = events(response)
    fixture = json.loads((ROOT / "tests/fixtures/sample_sse_events.json").read_text())
    assert [e["event"] for e in stream] == [e["event"] for e in fixture if e["event"] != "error"]
    assert [e["data"]["stage"] for e in stream if e["event"] == "status"] == [
        "retrieving",
        "retrieved",
        "generating",
        "done",
    ]
    request_id = stream[-1]["data"]["request_id"]
    assert (
        client.post(
            "/v1/feedback", headers=HEADERS, json={"request_id": request_id, "score": 1}
        ).status_code
        == 200
    )


def test_runner_failure_is_safe(client, monkeypatch):
    monkeypatch.setattr(api, "build_runner", Mock(side_effect=RuntimeError(KEY)))
    response = client.post("/v1/ask", headers=HEADERS, json=BODY)
    assert response.status_code == 500 and KEY not in response.text
    response = client.post("/v1/chat/stream", headers=HEADERS, json=BODY)
    assert [e["event"] for e in events(response)] == ["error", "done"]
    assert KEY not in response.text


def test_recoverable_errors_return_the_fallback_answer(client, monkeypatch):
    build = api.build_runner

    def with_errors(config):
        runner = build(config)
        run = runner.run
        runner.run = lambda *a, **k: run(*a, **k).model_copy(
            update={"errors": ["provider_failure:RuntimeError:tool call rejected"]}
        )
        return runner

    monkeypatch.setattr(api, "build_runner", with_errors)
    result = client.post("/v1/ask", headers=HEADERS, json=BODY)
    assert result.status_code == 200 and result.json()["record"]["answer"]["abstain"]
    stream = events(client.post("/v1/chat/stream", headers=HEADERS, json=BODY))
    assert "answer" in [e["event"] for e in stream] and "error" not in [e["event"] for e in stream]


def test_bug_missing_from_archive_is_answered_without_llm(client):
    body = {**BODY, "message": "What component is bug 9999999 filed under?"}
    record = client.post("/v1/ask", headers=HEADERS, json=body).json()["record"]
    assert record["route"] == "unknown_bug" and record["llm_calls"] == 0
    assert record["answer"]["abstain"] and not record["evidence"] and not record["degraded"]
    assert record["answer"]["rationale"].startswith("Bug 9999999 isn't in this archive")
    stream = events(client.post("/v1/chat/stream", headers=HEADERS, json=body))
    assert [e["data"]["stage"] for e in stream if e["event"] == "status"] == [
        "retrieving",
        "retrieved",
        "generating",
        "done",
    ]
    # A sampled bug is not short-circuited.
    record = client.post("/v1/ask", headers=HEADERS, json=BODY).json()["record"]
    assert record["route"] != "unknown_bug"


def test_runner_cache_is_bounded(client, monkeypatch):
    build = api.build_runner
    closed = []

    def tracked(config):
        runner = build(config)
        close = runner.close

        def cleanup():
            closed.append(config.top_k)
            close()

        runner.close = cleanup
        return runner

    monkeypatch.setattr(api, "build_runner", tracked)
    for top_k in (1, 1, 2, 3, 4, 5):
        response = client.post(
            "/v1/ask",
            headers=HEADERS,
            json={**BODY, "overrides": {"provider": "mock", "top_k": top_k}},
        )
        assert response.status_code == 200
    assert len(client.app.state.runners) == 4 and closed == [1]


def test_quota_hook_runs_before_inference(client, monkeypatch):
    def denied(config):
        api.fail(429, "rate_limited", "quota guard", 60)

    client.app.state.quota_check = denied
    build = Mock()
    monkeypatch.setattr(api, "build_runner", build)
    assert client.post("/v1/ask", headers=HEADERS, json=BODY).status_code == 429
    result = client.post("/v1/chat/stream", headers=HEADERS, json=BODY)
    assert events(result)[0]["data"]["code"] == "rate_limited"
    build.assert_not_called()


def test_registry_cache_and_champion(monkeypatch):
    config = RunConfig(system_id="S1", provider="mock")
    params = {k: json.dumps(v) for k, v in config.model_dump().items()}
    params["config_hash"] = config_hash(config)
    version = SimpleNamespace(
        version="2",
        run_id="run-2",
        tags={
            "published": "true",
            "preset_slug": "fast",
            "preset_label": "Fast",
            "preset_description": "Synthetic preset",
        },
    )
    client = Mock()
    client.search_model_versions.return_value = [version]
    client.get_model_version_by_alias.return_value = version
    client.get_run.return_value.data.params = params
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:./outputs/unused-test-store")
    import mlflow.tracking

    monkeypatch.setattr(mlflow.tracking, "MlflowClient", Mock(return_value=client))
    store = PresetStore()
    assert store.get()[0].is_champion
    assert store.get()[0].config == config
    client.search_model_versions.assert_called_once()
    store._expires = 0
    client.search_model_versions.side_effect = RuntimeError("unreachable")
    fallback = store.get()
    assert {p.slug for p in fallback} == {"recommended", "fast", "deep"}
    assert not any(p.is_champion for p in fallback)
