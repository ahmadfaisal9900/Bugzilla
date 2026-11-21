"""Shared P0 acceptance. No real questions, gold, remote service or model weights."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from bugzilla_serving.contracts.names import (
    EXPERIMENTS, validate_mlflow_run, validate_trace_metadata,
)
from bugzilla_serving.contracts.records import AnswerRecord, SSEEvent
from bugzilla_serving.contracts.run_config import SYSTEM_IDS, RunConfig, config_hash, load_spec
from bugzilla_serving.engine import _mock_provider, build_runner

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def test_config_and_golden_hashes(fixture_bundle):
    golden = json.loads((fixture_bundle.parent / "config_hashes.json").read_text())
    for system, expected in golden.items():
        cfg = RunConfig(system_id=system, provider="mock").validate_against()
        assert config_hash(cfg) == expected
        reordered = dict(reversed(list(cfg.model_dump().items())))
        assert config_hash(RunConfig(**reordered)) == expected
    assert len(config_hash(RunConfig())) == 12
    with pytest.raises(ValidationError):
        RunConfig(unrecognized=True)
    with pytest.raises(ValidationError):
        RunConfig(temperature=float("nan"))


@pytest.mark.parametrize("values,field", [
    ({"model": "missing"}, "model"),
    ({"top_k": 0}, "top_k"),
    ({"context_budget_tokens": 4097}, "context_budget_tokens"),
    ({"system_id": "S1", "s4_tau": 0.0}, "s4_tau"),
    ({"system_id": "S5", "s5_dossier_budget": 4097}, "s5_dossier_budget"),
    ({"system_id": "S1", "rrf_k": 5}, "rrf_k"),
    ({"system_id": "R0", "retriever": "R7b"}, "retriever"),
    ({"system_id": "S3", "query_transform": "R7a", "retriever": "R7b"}, "query_transform"),
])
def test_bad_configuration(values, field):
    with pytest.raises(ValueError, match=field):
        RunConfig(**values).validate_against()


def test_every_knob_has_ui_metadata():
    spec = load_spec()
    assert set(spec["hyperparameters"]) == set(RunConfig.model_fields)
    required = {"type", "default", "label", "help", "applies_to", "advanced"}
    for knob in spec["hyperparameters"].values():
        assert required <= knob.keys()
        assert "choices" in knob or {"min", "max"} <= knob.keys()
    RunConfig(**spec["default_config"]).validate_against(spec)


@pytest.mark.parametrize("system", SYSTEM_IDS)
def test_all_systems_use_existing_graph(fixture_bundle, system):
    cfg = RunConfig(system_id=system, provider="mock")
    provider = _mock_provider()
    events = []
    question = json.loads((fixture_bundle / "dev_questions.jsonl").read_text().splitlines()[0])
    with build_runner(cfg, provider=provider) as runner:
        record = runner.run(question["question"], on_event=events.append)
        assert isinstance(record, AnswerRecord)
        assert not record.errors
        assert record.config_hash == config_hash(cfg)
        assert [e["data"]["stage"] for e in events] == [
            "retrieving", "retrieved", "generating", "done",
        ]
        if system == "R0":
            assert provider.calls == 0 and record.degraded
        else:
            assert record.llm_calls == provider.calls


def test_overrides_reach_backend_and_graph(fixture_bundle):
    cfg = RunConfig(system_id="S3", query_transform="R7a", provider="mock", top_k=2,
                    rrf_k=23, context_budget_tokens=256)
    with build_runner(cfg, _mock_provider()) as runner:
        assert runner.backend.rc["rrf_k"] == 23
        assert runner.config["context_tokens"] == 256
        assert runner.config["query_transform"] == "R7a"
        answer = runner.run("What product is recorded for bug 100000?")
        assert not answer.errors and len(answer.evidence) <= 2
    for corpus in ("C0", "C1", "C2"):
        with build_runner(RunConfig(system_id="S1", corpus=corpus, provider="mock")) as runner:
            assert runner.backend.corpus == corpus
            assert runner.backend.directory.name == corpus


def test_s4_low_evidence_has_no_calls(fixture_bundle):
    with build_runner(RunConfig(system_id="S4", s4_tau=30.0, provider="mock")) as runner:
        record = runner.run("unrelated synthetic observation")
        assert record.llm_calls == 0
        assert record.route == "abstain_low_evidence" and record.answer.abstain


def test_fixture_records_and_trace_names(fixture_bundle):
    fixtures = fixture_bundle.parent
    AnswerRecord.model_validate_json((fixtures / "sample_answer_record.json").read_text())
    adapter = TypeAdapter(SSEEvent)
    for row in json.loads((fixtures / "sample_sse_events.json").read_text()):
        adapter.validate_python(row)
    runs = json.loads((fixtures / "sample_langsmith_runs.json").read_text())
    assert len(runs) == 30
    for run in runs:
        validate_trace_metadata(run["metadata"])
        assert run["feedback"][0]["key"] == "user_rating"
    with pytest.raises(ValueError):
        validate_trace_metadata({})


def test_bundle_rejects_tamper_and_non_dev(fixture_bundle):
    manifest = fixture_bundle / "manifest.json"
    original = json.loads(manifest.read_text())
    manifest.write_text(json.dumps(dict(original, split="test")))
    with pytest.raises(ValueError, match="dev"):
        build_runner(RunConfig(system_id="S1", provider="mock"))
    manifest.write_text(json.dumps(original))
    (fixture_bundle / "bugs.jsonl").write_text("corrupt")
    with pytest.raises(ValueError, match="mismatch"):
        build_runner(RunConfig(system_id="S1", provider="mock"))


def test_fixture_rebuild_deterministic(tmp_path):
    from conftest import module

    builder = module(ROOT / "scripts/build_fixture_bundle.py", "builder_determinism")
    first = builder.build(tmp_path / "first")
    second = builder.build(tmp_path / "second")
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()


def test_openapi_snapshot(monkeypatch):
    from fastapi.testclient import TestClient

    from bugzilla_serving.api.stub import create_app

    app = create_app()
    path = Path(__file__).with_name("openapi.json")
    actual = app.openapi()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.write_text(json.dumps(actual, sort_keys=True, indent=2) + "\n")
    assert path.exists(), "Generate once after installing pins: UPDATE_SNAPSHOTS=1 pytest tests/contracts"
    assert json.loads(path.read_text()) == actual
    client = TestClient(app)
    assert client.get("/v1/health").json() == {"status": "ok"}
    for route in ("ready", "options", "presets", "examples", "quota"):
        assert client.get("/v1/" + route).status_code == 501
    for route in ("ask", "chat/stream"):
        assert client.post("/v1/" + route, json={"session_id": "fake", "message": "hello"}).status_code == 501
    assert client.post("/v1/feedback", json={"request_id": "fake", "score": 1}).status_code == 501


def test_mlflow_seed_idempotence_and_secret_scan(tmp_path, fixture_bundle, monkeypatch, capsys):
    from conftest import module
    from mlflow.tracking import MlflowClient

    key = "fake-secret-phase0-NEVER-PERSIST-123456"
    for variable in ("GROQ_API_KEY", "LANGSMITH_API_KEY", "MLFLOW_TRACKING_PASSWORD"):
        monkeypatch.setenv(variable, key)
    seed = module(ROOT / "scripts/seed_mlflow_fixture.py", "p0_seed")
    uri = (tmp_path / "mlruns").as_uri()
    first, second = seed.seed(uri), seed.seed(uri)
    assert first["created_runs"] == 9 and second["created_runs"] == 0
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    for name in EXPERIMENTS:
        exp = client.get_experiment_by_name(name)
        runs = client.search_runs([exp.experiment_id])
        assert len(runs) == 3
        for run in runs:
            validate_mlflow_run(run.data.params, run.data.tags, run.data.metrics)
    versions = list(client.search_model_versions("name = 'bugzilla-qa-config'"))
    assert len(versions) == 3
    assert sum(v.tags.get("published") == "true" for v in versions) == 2
    assert client.get_model_version_by_alias("bugzilla-qa-config", "champion")
    # Inject a key into public evidence; the returned AnswerRecord must redact it.
    with build_runner(RunConfig(system_id="S1", provider="mock")) as runner:
        for d in runner.backend.docs:
            d["text"] += " " + key
        record = runner.run("Synthetic bug 100000")
        (tmp_path / "answer.json").write_text(record.model_dump_json())
    output = capsys.readouterr()
    assert key not in output.out + output.err
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes(), str(path)


def test_mlflow_names_reject_invalid_values():
    from bugzilla_serving.contracts.run_config import config_hash

    cfg = RunConfig()
    params = dict(cfg.model_dump(), config_hash=config_hash(cfg))
    tags = dict(source="ci", eval_set="synthetic", datasets="synthetic", split="dev",
                scorer="synthetic", git_sha="synthetic")
    validate_mlflow_run(params, tags, {"answer.F1.score": 0.5, "answer.F1.n": 10})
    for metric in ("overall_accuracy", "answer.F9.score"):
        with pytest.raises(ValueError):
            validate_mlflow_run(params, tags, {metric: 1.0})
    with pytest.raises(ValueError):
        validate_mlflow_run(params, dict(tags, split="test"), {})
    with pytest.raises(ValueError):
        validate_mlflow_run(params, tags, {"cost.tokens_in": float("nan")})


def test_native_tool_uses_readonly_fixture_and_returns_evidence(fixture_bundle):
    from bugzilla_qa.llm.provider import MockProvider

    def reply(prompt):
        payload = json.loads(prompt)
        if not payload.get("evidence"):
            name = "get_bug_fields"
            args = {"bug_id": 100000, "fields": ["product"]}
        else:
            name = "submit_answer"
            args = dict(abstain=False, answer="Firefox", answer_type="string",
                        bug_ids=[100000], citations=["metadata-100000:0"],
                        rationale="The synthetic field is Firefox.")
        return {"calls": [{"name": name, "arguments_json": json.dumps(args)}]}

    with build_runner(RunConfig(system_id="S7", provider="mock"), MockProvider(reply)) as runner:
        record = runner.run("What product is recorded for bug 100000?")
        assert record.answer.answer == "Firefox"
        assert not record.errors and record.llm_calls == 2
        assert record.evidence[0].chunk_id == "metadata-100000:0"


def test_unknown_private_body_refused(fixture_bundle):
    from bugzilla_serving.engine import _bundle

    # Make a self-consistent but nonpublic synthetic corpus: Backend must still refuse it.
    path = fixture_bundle / "indexes/C1/corpus.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["visibility"] = "unknown"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    variant_path = fixture_bundle / "indexes/C1/manifest.json"
    variant = json.loads(variant_path.read_text())
    variant["sha256"]["corpus.jsonl"] = hashlib.sha256(path.read_bytes()).hexdigest()
    variant_path.write_text(json.dumps(variant))
    build_path = fixture_bundle / "indexes/manifest.json"
    build = json.loads(build_path.read_text())
    build["sha256"]["C1/manifest.json"] = hashlib.sha256(variant_path.read_bytes()).hexdigest()
    build_path.write_text(json.dumps(build))
    manifest_path = fixture_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for changed in (path, variant_path, build_path):
        manifest["files"][changed.relative_to(fixture_bundle).as_posix()] = {
            "bytes": changed.stat().st_size,
            "sha256": hashlib.sha256(changed.read_bytes()).hexdigest(),
        }
    manifest_path.write_text(json.dumps(manifest))
    _bundle(fixture_bundle)
    with pytest.raises(ValueError, match="visibility"):
        build_runner(RunConfig(system_id="S1", provider="mock"))
