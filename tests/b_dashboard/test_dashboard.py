"""Offline Streamlit pages against synthetic local tracking and trace fixtures."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import mlflow
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.dashboard import lab
from bugzilla_serving.dashboard.data import langsmith_source as ls
from bugzilla_serving.dashboard.data import mlflow_source as mf
from bugzilla_serving.dashboard.data.common import display_frame, family_cell, tracking_location
from bugzilla_serving.tracking.backfill import retrieval_runs
from bugzilla_serving.tracking.client import TrackingClient, params_for

APP = ROOT / "src/bugzilla_serving/dashboard/app.py"


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    import httpx
    import requests

    def denied(*args, **kwargs):
        raise AssertionError("Dashboard tests must not contact live services")

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("LANGSMITH_SOURCE", "fixture")
    monkeypatch.setenv("DASHBOARD_LAB_ENABLED", "true")
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.delenv("BUNDLE_DIR", raising=False)
    uri = (tmp_path / "default").as_uri()
    before, registry = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    mf.clear()
    ls.roots.clear()
    lab.publication_preview.clear()
    st.cache_resource.clear()
    try:
        yield
    finally:
        mlflow.set_tracking_uri(before)
        mlflow.set_registry_uri(registry)


@pytest.fixture
def store(tmp_path, monkeypatch):
    uri = (tmp_path / "mlruns").as_uri()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    module(ROOT / "scripts/seed_mlflow_fixture.py", "dashboard_seed").seed(uri)
    # MLflow's set_tracking_uri restores its previous value through os.environ.
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    directory = tmp_path / "retrieval"
    directory.mkdir()
    (directory / "summary.json").write_bytes(
        (ROOT / "tests/fixtures/sample_retrieval_summary.json").read_bytes()
    )
    tracker = TrackingClient(uri)
    for plan in retrieval_runs([directory]):
        tracker.log_run(**plan)
    # A sparse review-only run must not become an all-zero answer/cost row.
    cfg = RunConfig(system_id="S0")
    tags = dict(
        source="backfill",
        eval_set="pilot125",
        datasets="phase05",
        split="dev",
        scorer="review-csv",
        git_sha="synthetic",
        provenance="review-only",
        config_origin="reconstructed",
    )
    tracker.log_run(
        "research-answer-eval",
        params_for(cfg),
        tags,
        {},
        {"per_family.csv": "family,source_n,scored_n,pending_n\nF5,2,0,2\n"},
    )
    tracker.log_run(
        "playground",
        params_for(RunConfig()),
        {
            k: v
            for k, v in {
                **tags,
                "source": "lab",
                "eval_set": "smoke-5",
                "scorer": "synthetic",
            }.items()
            if k != "config_origin"
        },
        {"answer.F1.score": 0.5, "answer.F1.n": 2},
        {"per_family.csv": "family,source_n,scored_n,pending_n\nF1,2,2,0\n"},
    )
    return uri


@pytest.mark.ui
@pytest.mark.parametrize(
    "page",
    [
        "overview",
        "answer_eval",
        "retrieval_eval",
        "cost_latency",
        "error_analysis",
        "experiment_lab",
        "compare_runs",
        "presets_page",
        "production",
    ],
)
def test_every_page(store, page, caplog):
    at = AppTest.from_file(str(APP), default_timeout=15).run()
    if page != "overview":
        at.switch_page(f"pages/{page}.py").run()
    assert not at.exception, [(e.message) for e in at.exception]
    assert any("Dev dashboard" in t.value for t in at.title)
    assert any("MLflow:" in c.value for c in at.sidebar.caption)
    assert any("LangSmith source: fixture" in c.value for c in at.sidebar.caption)
    if page in ("overview", "answer_eval", "retrieval_eval", "cost_latency", "presets_page"):
        assert at.dataframe
    assert "Serialization of dataframe to Arrow table was unsuccessful" not in caplog.text


def test_mixed_metric_display_is_arrow_safe_and_preserves_source():
    import pandas as pd
    import pyarrow as pa

    rows = [
        {
            "macro": "not available yet: review-only",
            "latency": "not available",
            "n": None,
            "answer": {"answer": [1, 2]},
            "numeric": 0.0,
        },
        {
            "macro": 0.625,
            "latency": 25.5,
            "n": 21,
            "answer": {"answer": "synthetic"},
            "numeric": 0.75,
        },
    ]
    frame = display_frame(rows)
    pa.Table.from_pandas(frame)
    assert frame.loc[1, "macro"] == "0.625"
    assert frame.loc[0, "macro"] == "not available yet: review-only"
    assert pd.isna(frame.loc[0, "n"])
    assert frame.loc[0, "numeric"] == 0.0
    assert rows[1]["macro"] == 0.625 and isinstance(rows[0]["answer"], dict)


def test_tracking_footer_never_displays_credentials():
    value = tracking_location(
        "https://user:fake-secret@host.example/team/repo.mlflow?token=hidden#secret"
    )
    assert value == "host.example/team/repo.mlflow"
    assert "user" not in value and "secret" not in value and "hidden" not in value


@pytest.mark.ui
def test_read_only_and_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", (tmp_path / "empty").as_uri())
    monkeypatch.setenv("DASHBOARD_LAB_ENABLED", "false")
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception
    assert any("No champion" in e.value for e in at.info)
    at.switch_page("pages/experiment_lab.py").run()
    assert not at.exception and any("disabled" in e.value for e in at.info)
    assert not at.button and not at.toggle


def test_family_cells_and_test_artifact_gate(tmp_path):
    assert family_cell({"answer.F1.score": 0.0, "answer.F1.n": 5}, "F1").label == "0 · n=5"
    na = [dict(dataset="v3", family="F6", metric="recall_at_10", state="N/A", n=11)]
    assert family_cell({}, "F6", dataset="v3", metric="recall_at_10", na_rows=na).state == "N/A"
    assert family_cell({}, "F2").state == "not in dataset"
    assert family_cell({}, "F5", tags={"provenance": "review-only"}).state.startswith(
        "not available yet"
    )
    uri = (tmp_path / "mlruns").as_uri()
    tracker = TrackingClient(uri)
    cfg = RunConfig()
    rid = tracker.log_run(
        "research-answer-eval",
        params_for(cfg),
        dict(
            source="ci",
            eval_set="agg",
            datasets="synthetic",
            split="test-aggregate",
            scorer="fixture",
            git_sha="synthetic",
        ),
        {"answer.F1.score": 0.5, "answer.F1.n": 5},
        {},
    )
    assert "dev split only" in mf.artifact(uri, rid, "predictions.jsonl").error


def test_production_groups_and_empty(tmp_path, monkeypatch):
    data = ls.roots("fixture", "2020-01-01T00:00:00+00:00", "2020-01-02T00:00:00+00:00")
    assert len(data.value) == 30
    assert sum(r["n"] for r in ls.grouped(data.value)) == 30
    path = tmp_path / "no_traces.json"
    path.write_text("[]")
    monkeypatch.setattr(ls, "FIXTURE", path)
    ls.roots.clear()
    at = AppTest.from_file(str(APP)).run().switch_page("pages/production.py").run()
    assert not at.exception and any("No production data yet" in e.value for e in at.info)


@pytest.mark.ui
def test_password_blocks_reads(tmp_path, monkeypatch):
    secret = "fake-dashboard-password-not-for-output-1234"
    monkeypatch.setenv("DASHBOARD_PASSWORD", secret)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", (tmp_path / "empty").as_uri())
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception and not at.dataframe
    at.text_input[0].set_value(secret)
    at.button[0].click().run()
    at.run()
    assert not at.exception
    assert at.session_state["auth_digest"]
    assert secret not in str(at)


@pytest.mark.ui
def test_lab_mock_completion_and_secret_scan(tmp_path, monkeypatch):
    fixture_module = module(
        ROOT / "tests/b_experiments/test_experiments.py", "dashboard_b2_fixture"
    )
    args, _ = fixture_module.fixture.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(lab, "LAB_ROOT", args["root"])
    monkeypatch.setattr(lab, "SETS_PATH", args["root"] / "configs/eval_sets.yaml")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", args["tracking_uri"])
    secret = "fake-B3-no-secret-output-1234567890"
    for key in ("GROQ_API_KEY", "LANGSMITH_API_KEY", "MLFLOW_TRACKING_PASSWORD"):
        monkeypatch.setenv(key, secret)
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.switch_page("pages/experiment_lab.py").run()
    assert not at.exception
    button = next(b for b in at.button if b.label == "Run experiment")
    assert not button.disabled
    button.click().run()
    assert not at.exception
    token = at.session_state["launch"]
    lab.jobs().futures[token].result(timeout=15)
    at.run()
    state = lab.jobs().status(token)
    assert state["state"] == "COMPLETED", state
    assert state["actual_requests"] == 0
    assert not at.exception
    assert any("Job completed" in item.value for item in at.success)
    assert secret not in str(at)
    for directory in [args["root"], Path(args["tracking_uri"][5:])]:
        for file in directory.rglob("*"):
            if file.is_file():
                assert secret.encode() not in file.read_bytes()


def test_cache_and_no_api_imports(store, monkeypatch):
    first = mf.runs(store, "research-answer-eval")

    def denied(*args, **kw):
        raise AssertionError("Cached loader must not refetch")

    monkeypatch.setattr(TrackingClient, "runs", denied)
    second = mf.runs(store, "research-answer-eval")
    assert first.updated_at == second.updated_at and len(first.value) == len(second.value)
    import ast

    for path in (ROOT / "src/bugzilla_serving/dashboard").rglob("*.py"):
        tree = ast.parse(path.read_text())
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not any(
            n.startswith(("bugzilla_serving.api", "bugzilla_serving.chat_ui")) for n in names
        )


@pytest.mark.ui
def test_compare_and_registry_confirmation(store):
    at = AppTest.from_file(str(APP), default_timeout=15).run()
    at.switch_page("pages/compare_runs.py").run()
    assert len(at.multiselect[0].options) >= 2, ([w.value for w in at.warning], mf.uri())
    at.multiselect[0].set_value(at.multiselect[0].options[:2]).run()
    assert not at.exception and at.dataframe
    at.switch_page("pages/presets_page.py").run()
    # No publication writes occur while rendering or reviewing a confirmation.
    count = len(mf.presets(store).value)
    next(b for b in at.button if b.label == "Review unpublish").click().run()
    apply = next(b for b in at.button if b.label == "Apply change")
    assert apply.disabled and not at.exception
    assert len(mf.presets(store).value) == count


def test_unpublish_and_policy_preview(store):
    from bugzilla_serving.tracking.registry import Registry

    registry = Registry(store)
    values = mf.runs(store, "research-answer-eval").value
    sparse = next(r for r in values if r.tags.get("provenance") == "review-only")
    preview = lab.publication_preview(store, sparse.id, "candidate", "Candidate", "Fixture", True)
    assert not preview["policy"]["allowed"]
    registry.unpublish("fast")
    mf.clear()
    assert "fast" not in {p["slug"] for p in mf.presets(store).value}


def test_evaluation_runs_hide_carriers_and_non_evaluation_sources(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    def record(source, eval_set):
        return SimpleNamespace(
            info=SimpleNamespace(run_id=source + eval_set, start_time=1, experiment_id="1"),
            data=SimpleNamespace(
                params={}, metrics={}, tags=dict(source=source, eval_set=eval_set, split="dev")
            ),
        )

    candidates = [
        record("lab", "config-registry"),
        record("ci", "smoke"),
        record("registry", "config-registry"),
        record("backfill", "pilot125"),
        record("lab", "smoke-5"),
    ]
    with patch.object(TrackingClient, "runs", return_value=candidates):
        result = mf.runs((tmp_path / "filtered").as_uri(), "playground").value
    assert {r.tags["eval_set"] for r in result} == {"pilot125", "smoke-5"}


@pytest.mark.ui
def test_cost_page_reuse_label_and_usage_columns(store):
    tracker = TrackingClient(store)
    tracker.log_run(
        "research-answer-eval",
        params_for(RunConfig()),
        dict(
            source="backfill",
            eval_set="reuse-fixture",
            datasets="v3",
            split="dev",
            scorer="synthetic",
            git_sha="synthetic",
            reused_from="S2",
        ),
        {
            "cost.tokens_in": 0,
            "cost.tokens_out": 0,
            "cost.llm_calls": 0,
            "cost.llm_calls_per_question": 0,
            "cost.usage_missing_n": 0,
        },
        {"per_family.csv": "family,source_n,scored_n,pending_n\nF1,2,2,0\n"},
    )
    mf.clear()
    at = AppTest.from_file(str(APP), default_timeout=15).run()
    at.switch_page("pages/cost_latency.py").run()
    assert not at.exception
    frame = at.dataframe[0].value
    assert "reused from S2 (no own latency)" in frame["latency.p95_ms"].tolist()
    assert "cost.llm_calls_per_question" in frame.columns
    assert any("not interactive chat latency" in c.value for c in at.caption)
