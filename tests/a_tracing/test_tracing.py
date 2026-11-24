"""Check sampling, metadata, SDK child runs, feedback persistence and secret redaction offline."""

import importlib.util
import json
import logging
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from langsmith import Client

from bugzilla_serving import tracing
from bugzilla_serving.api import app as api
from bugzilla_serving.api.presets import PresetStore
from bugzilla_serving.contracts.names import TRACE_METADATA_KEYS
from bugzilla_serving.contracts.run_config import ROOT, RunConfig

SECRET = "fake-secret-tracing-NEVER-PERSIST-456789"
HEADERS = {"X-API-Key": "fake-tracing-server-key"}
BODY = {
    "session_id": "trace-test",
    "message": "What product is recorded for bug 100000?",
    "preset_slug": "fast",
}


def test_missing_key_is_quiet(monkeypatch):
    monkeypatch.setattr(tracing, "env_values", lambda path: {})
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    constructor = Mock()
    monkeypatch.setattr(tracing, "SafeClient", constructor)
    assert tracing.client() is None
    constructor.assert_not_called()


def test_metadata_has_exact_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY_2", SECRET)
    metadata = tracing.root_metadata(RunConfig(), "fast", "request-1", SECRET)
    assert set(metadata) == TRACE_METADATA_KEYS
    assert metadata["session_id"] == "[redacted]"
    assert metadata["preset_slug"] == "fast"
    assert metadata["model"] == "openai/gpt-oss-20b"
    monkeypatch.setattr(tracing, "env_values", lambda path: {"GROQ_API_KEY": "file-secret-value"})
    monkeypatch.setenv("GROQ_API_KEY", "environment-secret-value")
    assert tracing.sanitize("file-secret-value environment-secret-value") == "[redacted] [redacted]"


def test_sampling_and_durable_cap(tmp_path):
    path = tmp_path / "budget.sqlite"
    count = sum(
        tracing.should_trace(str(i), sample=0.2, daily_cap=1000, db_path=path) for i in range(1000)
    )
    assert 150 < count < 250
    assert not tracing.should_trace("never", sample=0, db_path=path)
    capped = tmp_path / "capped.sqlite"
    for name in ("one", "two"):
        assert tracing.should_trace(name, sample=1, daily_cap=2, db_path=capped, day="2026-11-22")
    assert not tracing.should_trace("one", sample=1, daily_cap=2, db_path=capped, day="2026-11-22")
    assert not tracing.should_trace(
        "three", sample=1, daily_cap=2, db_path=capped, day="2026-11-22"
    )
    assert tracing.should_trace("four", sample=1, daily_cap=2, db_path=capped, day="2026-11-23")


def test_sdk_serialization_redacts_errors_and_credentials(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY_4", SECRET)
    calls = []
    monkeypatch.setattr(Client, "create_run", lambda self, *a, **k: calls.append((a, k)))
    monkeypatch.setattr(Client, "update_run", lambda self, *a, **k: calls.append((a, k)))
    client = tracing.SafeClient(
        api_key="fake-test-key", api_url="https://example.invalid", auto_batch_tracing=False
    )
    client.create_run("test", {"question": SECRET}, "chain", extra={"metadata": {"value": SECRET}})
    client.update_run("id", error=SECRET, outputs={"answer": SECRET})
    assert SECRET not in repr(calls)


def test_log_filter_removes_secret_and_exception(monkeypatch):
    monkeypatch.setenv("SERVING_API_KEY", SECRET)
    record = logging.LogRecord(
        "langsmith.client", logging.WARNING, "", 1, "failed: %s", (SECRET,), None
    )
    tracing.SecretFilter().filter(record)
    assert SECRET not in record.getMessage()


@pytest.fixture
def client(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "trace_builder", ROOT / "scripts/testing/build_fixture_bundle.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    bundle = builder.build(tmp_path / "bundle")
    monkeypatch.setenv("BUNDLE_DIR", str(bundle))
    monkeypatch.setenv("SERVING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SERVING_API_KEY", HEADERS["X-API-Key"])
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("TRACE_SAMPLE", "1")
    monkeypatch.setenv("TRACE_DAILY_CAP", "150")
    monkeypatch.setenv("GROQ_API_KEY_2", SECRET)
    monkeypatch.setattr(PresetStore, "_registry", Mock(side_effect=RuntimeError("offline")))
    sdk = Mock(spec=Client)
    sdk.create_run.return_value = None
    sdk.update_run.return_value = None
    monkeypatch.setattr(Client, "create_run", lambda self, *a, **k: sdk.create_run(*a, **k))
    monkeypatch.setattr(Client, "update_run", lambda self, *a, **k: sdk.update_run(*a, **k))
    monkeypatch.setattr(
        Client, "create_feedback", lambda self, *a, **k: sdk.create_feedback(*a, **k)
    )
    safe_client = tracing.SafeClient(
        api_key="fake-test-key", api_url="https://example.invalid", auto_batch_tracing=False
    )
    monkeypatch.setattr(tracing, "client", lambda: safe_client)
    from bugzilla_qa.answering.backend import Backend
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
    with TestClient(api.create_app()) as result:
        result.sdk = sdk
        yield result


def test_trace_and_feedback_have_sdk_children(client, caplog):
    response = client.post(
        "/v1/ask", headers=HEADERS, json={**BODY, "message": BODY["message"] + SECRET}
    )
    assert response.status_code == 200
    value = response.json()
    assert value["langsmith_run_id"]
    creates = [call.kwargs for call in client.sdk.create_run.call_args_list]
    roots = [call for call in creates if call["name"] == "Bugzilla chat"]
    assert len(roots) == 1
    assert set(roots[0]["extra"]["metadata"]) >= TRACE_METADATA_KEYS
    assert any(call.get("parent_run_id") for call in creates)
    client.app.state.tracer.sample = 0
    client.app.state.tracer.client = None
    feedback = {"request_id": value["request_id"], "score": 1, "comment": "Useful " + SECRET}
    result = client.post("/v1/feedback", headers=HEADERS, json=feedback)
    assert result.json() == {"status": "ok"}
    client.sdk.create_feedback.assert_called_once_with(
        value["langsmith_run_id"], key="user_rating", score=1, comment="Useful [redacted]"
    )
    with sqlite3.connect(client.app.state.feedback_db) as db:
        row = db.execute("SELECT score,comment,updated_at,remote_status FROM feedback").fetchone()
        dump = "\n".join(db.iterdump())
    assert row[0] == 1 and row[1] == "Useful [redacted]" and row[2] and row[3] == "sent"
    assert (
        SECRET not in repr(client.sdk.mock_calls) + dump + response.text + result.text + caplog.text
    )


def test_stream_returns_trace_id(client):
    response = client.post("/v1/chat/stream", headers=HEADERS, json=BODY)
    assert response.status_code == 200
    frames = response.text.strip().split("\n\n")
    done = json.loads(frames[-1].splitlines()[1][6:])
    assert done["langsmith_run_id"] and done["request_id"]


def test_untraced_feedback_is_local(client):
    client.app.state.tracer.sample = 0
    response = client.post("/v1/ask", headers=HEADERS, json=BODY).json()
    assert response["langsmith_run_id"] is None
    result = client.post(
        "/v1/feedback",
        headers=HEADERS,
        json={"request_id": response["request_id"], "score": 0, "comment": "No trace"},
    )
    assert result.status_code == 200
    with sqlite3.connect(client.app.state.feedback_db) as db:
        assert db.execute("SELECT score,remote_status FROM feedback").fetchone() == (0, "local")
    client.sdk.create_feedback.assert_not_called()
    client.sdk.create_run.assert_not_called()


def test_remote_feedback_failure_keeps_local_copy(client, caplog):
    response = client.post("/v1/ask", headers=HEADERS, json=BODY).json()
    client.sdk.create_feedback.side_effect = RuntimeError(SECRET)
    feedback = client.post(
        "/v1/feedback", headers=HEADERS, json={"request_id": response["request_id"], "score": 1}
    )
    assert feedback.status_code == 200
    with sqlite3.connect(client.app.state.feedback_db) as db:
        assert db.execute("SELECT score,remote_status FROM feedback").fetchone() == (1, "pending")
    assert SECRET not in feedback.text + caplog.text


def test_trace_outage_does_not_repeat_inference(client, monkeypatch):
    monkeypatch.setattr(tracing, "trace", Mock(side_effect=RuntimeError(SECRET)))
    response = client.post("/v1/ask", headers=HEADERS, json=BODY)
    assert response.status_code == 200 and response.json()["langsmith_run_id"] is None
    runner = next(iter(client.app.state.runners.values()))
    assert runner.provider.calls == 1


def test_live_check_defaults_to_preview(monkeypatch, capsys):
    path = ROOT / "scripts/app/check_serving_tracing.py"
    spec = importlib.util.spec_from_file_location("tracing_check", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    check = Mock(side_effect=AssertionError("Live checks require explicit opt-in"))
    monkeypatch.setattr(script, "check", check)
    monkeypatch.setattr("sys.argv", [str(path)])
    script.main()
    assert json.loads(capsys.readouterr().out)["state"] == "DRY_RUN"
    check.assert_not_called()


def test_private_bundle_comment_never_reaches_mocked_trace(client):
    """Even checksum-valid private evidence must be refused before serialization."""
    import hashlib
    import os
    from pathlib import Path

    bundle = Path(os.environ["BUNDLE_DIR"])
    corpus = bundle / "indexes/C1/corpus.jsonl"
    rows = [json.loads(line) for line in corpus.read_text().splitlines()]
    sentinel = "PRIVATE_COMMENT_MUST_NOT_REACH_TRACE"
    rows[0].update(visibility="private", text=sentinel)
    corpus.write_text("".join(json.dumps(row) + "\n" for row in rows))
    variant_path = corpus.parent / "manifest.json"
    variant = json.loads(variant_path.read_text())
    variant["sha256"]["corpus.jsonl"] = hashlib.sha256(corpus.read_bytes()).hexdigest()
    variant_path.write_text(json.dumps(variant))
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for path in (corpus, variant_path):
        manifest["files"][path.relative_to(bundle).as_posix()].update(
            bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )
    manifest_path.write_text(json.dumps(manifest))
    response = client.post("/v1/ask", headers=HEADERS, json=BODY)
    assert response.status_code == 500
    assert sentinel not in response.text + repr(client.sdk.mock_calls)
