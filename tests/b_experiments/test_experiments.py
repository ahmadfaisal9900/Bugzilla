"""Bounded offline B2 checks using P0's synthetic engine and local MLflow."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from bugzilla_serving.contracts.names import validate_mlflow_run
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.engine import _mock_provider
from bugzilla_serving.experiments import data, runner, scoring, sweep
from bugzilla_serving.experiments.preflight import estimate
from bugzilla_serving.tracking.client import TrackingClient

pytestmark = pytest.mark.unit


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    import httpx
    import mlflow
    import requests

    def denied(*args, **kwargs):
        raise AssertionError("No live services or model downloads in B2 tests")

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(key, "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    uri = (tmp_path / "default-store").as_uri()
    old, registry = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    try:
        yield
    finally:
        mlflow.set_tracking_uri(old)
        mlflow.set_registry_uri(registry)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    support = module(ROOT / "tests/contracts/conftest.py", "b2_engine_support")
    bundle = support.fixture_bundle.__wrapped__(tmp_path, monkeypatch)
    questions = [
        json.loads(line) for line in (bundle / "dev_questions.jsonl").read_text().splitlines()
    ]
    items = [
        dict(
            q,
            dataset="synthetic",
            freeze_id="synthetic-freeze",
            cluster_id=q["qid"],
            kind="unanswerable"
            if q["family"] in ("F6", "F6H")
            else "supported_explanation"
            if q["family"] == "F5"
            else "string",
            expected=None if q["family"] in ("F6", "F6H") else "synthetic",
            acceptable_bug_ids=[],
            evidence=q["evidence_record_ids"],
            dataset_notes={},
            tolerance_hours=0,
        )
        for q in questions
    ]
    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    (root / "prompts").mkdir()
    for name in ("llm.yaml",):
        (root / "configs" / name).write_bytes((ROOT / "configs" / name).read_bytes())
    for name in ("answer_v1.txt", "answer_v2_compact.txt"):
        (root / "prompts" / name).write_text("Synthetic system prompt only.")
    monkeypatch.setattr(data, "catalog", lambda root=ROOT: (items, {"synthetic": "fixed"}))
    sets = data.make_sets(items)
    (root / "configs/eval_sets.yaml").write_text(yaml.safe_dump(sets))
    return dict(
        root=root, jobs_dir=tmp_path / "jobs", tracking_uri=(tmp_path / "mlruns").as_uri()
    ), items


def test_sets_deterministic_dev_only(fixture):
    args, items = fixture
    assert data.make_sets(items) == data.make_sets(items)
    assert len(data.make_sets(items)["sets"]["smoke-5"]) == 5
    for bad in (
        [{"qid": "locked", "dataset": "synthetic"}],
        [{"qid": items[0]["qid"], "dataset": "synthetic", "question": "leak"}],
    ):
        with pytest.raises(ValueError):
            data.validate_members(bad, items)
    with pytest.raises(ValueError, match="non-dev"):
        data.make_sets([{**items[0], "split": "test"}])
    with pytest.raises(ValueError, match="verified dev"):
        data.validate_members(
            [{"qid": items[0]["qid"], "dataset": "synthetic"}], [{**items[0], "split": "test"}]
        )


def test_loader_asserts_dev(fixture, monkeypatch):
    args, items = fixture
    row = items[0]
    monkeypatch.setattr(data, "catalog", lambda root: ([{**row, "split": "test"}], {}))
    path = args["root"] / "configs/eval_sets.yaml"
    path.write_text(
        yaml.safe_dump({"sets": {"bad": [{"dataset": row["dataset"], "qid": row["qid"]}]}})
    )
    with pytest.raises(ValueError, match="verified dev"):
        data.load_eval_set("bad", root=args["root"])


def pred(item, answer, abstain=False):
    return dict(
        qid=item["qid"],
        dataset=item["dataset"],
        family=item["family"],
        split="dev",
        freeze_id=item["freeze_id"],
        system_id="S1",
        status="ok",
        context_chunk_ids=[],
        answer=dict(answer=answer, abstain=abstain, citations=[], bug_ids=[], answer_type="string"),
    )


def test_scoring_partner_and_fallback(fixture):
    _, items = fixture
    a = {**items[0], "family": "F1", "kind": "string", "expected": "Firefox"}
    b = {**items[1], "family": "F4", "kind": "id_set", "expected": [1, 2]}
    c = {**items[2], "family": "F5", "kind": "supported_explanation"}
    rows = [a, b, c]
    predictions = {
        (a["dataset"], a["qid"]): pred(a, "Firefox"),
        (b["dataset"], b["qid"]): pred(b, [1]),
        (c["dataset"], c["qid"]): pred(c, "synthetic"),
    }
    results, families, metrics = scoring.score_predictions(rows, predictions)
    assert metrics["answer.F1.score"] == 1
    assert "answer.F5.score" not in metrics
    assert next(r for r in results if r["family"] == "F5")["verdict"] == "NOT_SCORED"
    _, _, fallback = scoring.score_predictions(rows, predictions, partner=False)
    assert fallback["answer.F4.score"] == pytest.approx(2 / 3)
    assert fallback["answer.F1.n"] == 1
    assert all("scorer" in f for f in families)


def test_preflight_daily_quota(fixture):
    args, items = fixture
    cfg = RunConfig(system_id="S1")
    now = dt.datetime(2026, 11, 21, 20, tzinfo=dt.timezone.utc)
    plan = estimate(cfg, items[:5], root=args["root"], now=now)
    assert plan["fits"] and plan["est_calls"] == 10
    path = args["root"] / "outputs/llm/groq/ledger.jsonl"
    path.parent.mkdir(parents=True)
    started = dict(ts=now.isoformat(), provider="groq", model=cfg.model, status="REQUEST_STARTED")
    path.write_text("".join(json.dumps(started) + "\n" for _ in range(900)))
    exhausted = estimate(cfg, items[:1], root=args["root"], now=now)
    assert not exhausted["fits"] and exhausted["remaining"]["requests"] == 0
    assert exhausted["remaining"]["unknown_usage_calls"] == 900
    # Cache events are not additional charged requests or token usage.
    path.write_text(json.dumps(dict(started, status="CACHE_HIT", input_tokens=999999)) + "\n")
    assert estimate(cfg, items[:1], root=args["root"], now=now)["remaining"]["reported_tokens"] == 0


def test_runner_engine_logs_and_resume(fixture):
    args, _ = fixture
    cfg = RunConfig(system_id="S1", provider="mock", top_k=2)
    provider = _mock_provider()
    stages = []
    first = runner.run_experiment(
        cfg,
        "smoke-5",
        limit=3,
        provider=provider,
        on_progress=lambda s: stages.append(s["state"]),
        **args,
    )
    assert first["state"] == "COMPLETED" and first["done"] == 3
    before = provider.calls
    second = runner.run_experiment(cfg, "smoke-5", limit=3, provider=provider, **args)
    assert second["mlflow_run_id"] == first["mlflow_run_id"] and provider.calls == before
    assert stages[0] == "PREFLIGHT" and "RUNNING" in stages and stages[-1] == "COMPLETED"
    tracking = TrackingClient(args["tracking_uri"])
    runs = tracking.runs("playground")
    assert len(runs) == 1
    run = runs[0]
    validate_mlflow_run(run.data.params, run.data.tags, run.data.metrics)
    assert run.data.tags["simulated"] == "true"
    assert not any(k.startswith("cost.") for k in run.data.metrics)
    folder = runner.job_folder(first["id"], args["jobs_dir"])
    assert len((folder / "predictions.jsonl").read_text().splitlines()) == 3
    assert runner.job_status(first["id"], args["jobs_dir"])["state"] == "COMPLETED"


def test_lock_and_cancel(fixture):
    args, _ = fixture
    with runner.job_lock(args["jobs_dir"]):
        with pytest.raises(RuntimeError, match="active"):
            runner.run_experiment(RunConfig(system_id="S1"), "smoke-5", **args)

    def stop(state):
        if state["state"] == "RUNNING":
            runner.cancel(state["id"], args["jobs_dir"])

    provider = _mock_provider()
    result = runner.run_experiment(
        RunConfig(system_id="S1"), "smoke-5", provider=provider, on_progress=stop, **args
    )
    assert result["state"] == "CANCELLED" and provider.calls == 0


def test_sweep_combined_budget(fixture, monkeypatch):
    args, items = fixture
    real = sweep.estimate

    def small(cfg, rows, **kw):
        value = real(cfg, rows, **kw)
        value["remaining"]["requests"] = value["est_calls"] + 1
        return value

    monkeypatch.setattr(sweep, "estimate", small)
    with pytest.raises(ValueError, match="combined grid"):
        sweep.run_sweep(RunConfig(system_id="S1"), {"top_k": [1, 2]}, "smoke-5", **args)
    assert not args["jobs_dir"].exists()


def test_secrets_redacted_in_all_outputs(fixture, monkeypatch):
    args, _ = fixture
    secret = "fake-B2-NEVER-PERSIST-api-key-123456"
    for name in ("GROQ_API_KEY", "LANGSMITH_API_KEY", "MLFLOW_TRACKING_PASSWORD"):
        monkeypatch.setenv(name, secret)
    provider = _mock_provider()
    provider.value = None
    state = runner.run_experiment(
        RunConfig(system_id="S1", provider="mock"), "smoke-5", limit=1, provider=provider, **args
    )
    assert state["state"] == "COMPLETED"
    for folder in (args["root"], args["jobs_dir"], Path(args["tracking_uri"][5:])):
        for file in folder.rglob("*"):
            if file.is_file():
                assert secret.encode() not in file.read_bytes()


def test_resume_preserves_interrupted_tail(fixture):
    args, _ = fixture
    cfg = RunConfig(system_id="S1", provider="mock")
    provider = _mock_provider()
    first = runner.run_experiment(cfg, "smoke-5", limit=1, provider=provider, **args)
    folder = runner.job_folder(first["id"], args["jobs_dir"])
    ledger = folder / "predictions.jsonl"
    with ledger.open("ab") as stream:
        stream.write(b'{"qid":"interrupted')
    before = provider.calls
    result = runner.run_experiment(cfg, "smoke-5", limit=1, provider=provider, **args)
    assert result["state"] == "COMPLETED" and provider.calls == before
    assert len(list(folder.glob("predictions.interrupted-*.jsonl"))) == 1
    assert len(ledger.read_text().splitlines()) == 1


def test_sweep_executes_separate_mock_runs(fixture):
    args, _ = fixture
    result = sweep.run_sweep(
        RunConfig(system_id="S1", provider="mock"), {"top_k": [1, 2]}, "smoke-5", limit=1, **args
    )
    assert len(result["jobs"]) == 2
    tracking = TrackingClient(args["tracking_uri"])
    runs = tracking.runs("playground")
    assert len(runs) == 2
    assert all(r.data.tags["sweep_id"] == result["plan"]["sweep_id"] for r in runs)


def test_redacts_echoed_secret(fixture, monkeypatch):
    args, _ = fixture
    secret = "fake-GROQ-echoed-secret-NEVER-STORE-12345"
    monkeypatch.setenv("GROQ_API_KEY", secret)
    provider = _mock_provider()
    original = provider.generate_json

    def echo(*a, **kw):
        response = original(*a, **kw)
        response["value"].update(abstain=False, answer=secret)
        return response

    provider.generate_json = echo
    state = runner.run_experiment(
        RunConfig(system_id="S1", provider="mock"), "smoke-5", limit=1, provider=provider, **args
    )
    for directory in [args["jobs_dir"], Path(args["tracking_uri"][5:])]:
        for path in directory.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    assert state["state"] == "COMPLETED"


def test_mock_refuses_remote_tracking(fixture):
    args, _ = fixture
    args["tracking_uri"] = "https://must-not-connect.invalid"
    with pytest.raises(ValueError, match="local file"):
        runner.run_experiment(RunConfig(system_id="S1"), "smoke-5", limit=1, **args)


def test_runtime_tpm_guard_zero_http():
    class Provider:
        calls = 0

        def generate_json(self, *a, **kw):
            self.calls += 1

    provider = Provider()
    paced = runner.PacedProvider(provider, 8000, 2048)
    with pytest.raises(RuntimeError, match="TPM"):
        paced.generate_json("x" * 8000, {})
    assert provider.calls == 0


def test_explicit_fixture_demo_reuses_p0(fixture):
    from bugzilla_serving.experiments.fixtures import build_fixture_runner

    args, _ = fixture
    result = runner.run_experiment(
        RunConfig(system_id="S1"), "smoke-5", limit=1, build=build_fixture_runner, **args
    )
    assert result["state"] == "COMPLETED" and result["actual_requests"] == 0


def test_live_refuses_synthetic_evidence_before_any_calls(fixture):
    args, _ = fixture
    provider = _mock_provider()
    result = runner.run_experiment(
        RunConfig(system_id="S1"),
        "smoke-5",
        limit=1,
        enable_llm=True,
        max_requests=10,
        provider=provider,
        **args,
    )
    assert result["state"] == "REFUSED" and "synthetic" in result["error"]
    assert provider.calls == 0


def test_fallback_does_not_grade_unsupported_abstentions(fixture):
    _, items = fixture
    item = {**items[0], "family": "F2", "kind": "calendar_hours", "expected": 1}
    result = scoring.fallback(item, pred(item, None, abstain=True))
    assert result["verdict"] == "NOT_SCORED"
