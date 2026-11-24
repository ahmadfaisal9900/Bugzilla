"""B6 uses synthetic dev data, fake services and temporary registries only."""

import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_experiments as support
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bugzilla_serving.contracts.api_models import AskResponse, ChatRequest
from bugzilla_serving.contracts.names import TRACE_METADATA_KEYS
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.engine import _mock_provider, build_runner
from bugzilla_serving.experiments import f5_grade, preflight
from bugzilla_serving.experiments.parity import check
from bugzilla_serving.experiments.runner import PacedProvider
from bugzilla_serving.experiments.token_budget import input_estimate
from bugzilla_serving.tracking import backfill
from bugzilla_serving.tracking.f5_gold import VERSION, fingerprint, load_verdicts
from bugzilla_serving.tracking.langsmith_smoke import smoke
from bugzilla_serving.tracking.registry import Registry
from bugzilla_serving.tracking.rollback import rollback

fixture_offline = pytest.fixture(autouse=True)(support.offline.__wrapped__)
fixture_experiment = pytest.fixture(name="experiment_fixture")(support.fixture.__wrapped__)


@pytest.mark.parametrize("budget", [4096, 12000])
def test_dossier_amendment_and_engine_override(experiment_fixture, budget):
    cfg = RunConfig(system_id="S8", provider="mock", s5_dossier_budget=budget).validate_against()
    with build_runner(cfg, _mock_provider()) as engine:
        assert engine.config["dossier_tokens"] == budget
    with pytest.raises(ValueError, match="context_budget_tokens"):
        RunConfig(context_budget_tokens=4097).validate_against()
    with pytest.raises(ValueError, match="s5_dossier_budget"):
        RunConfig(system_id="S8", s5_dossier_budget=12001).validate_against()


def test_token_gate_trims_before_send_and_shares_pacing():
    class Provider:
        calls = 0
        prompts = []

        def generate_json(self, prompt, *args, **kwargs):
            self.calls += 1
            self.prompts.append(prompt)
            return {"state": "SUCCESS", "value": {}}

    provider = Provider()
    # A fake monotonic clock proves multiple calls share the same reservation pool.
    from unittest.mock import patch

    clock = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    paced = PacedProvider(provider, 8000, 2048, sleep=sleep)
    with patch("bugzilla_serving.experiments.runner.time.monotonic", side_effect=lambda: clock[0]):
        original = json.dumps({"question": "Synthetic question", "evidence": "évidence " * 10000})
        paced.generate_json(original, {})
        assert paced.last_gate["trimmed"]
        assert input_estimate(provider.prompts[-1], ({},), "") + 2048 <= 7200
        assert json.loads(provider.prompts[-1])["question"] == "Synthetic question"
        paced.generate_json("small", {})
    assert sleeps and provider.calls == 2
    assert len(provider.prompts[0]) < len(original)


def test_estimator_history_and_fresh_s1_cap(experiment_fixture):
    args, items = experiment_fixture
    cfg = RunConfig(system_id="S1")
    history = [
        {
            "params": {"system_id": "S1", "model": cfg.model},
            "metrics": {"cost.tokens_in": 235702, "cost.llm_calls": 127, "cost.usage_missing_n": 0},
        }
    ]
    plan = preflight.estimate(
        cfg,
        items[:5],
        root=args["root"],
        history=history,
        max_requests=8,
        now=dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc),
    )
    assert plan["input_estimate_source"] == "historical complete usage"
    assert plan["input_tokens_per_call"] == 1856
    assert plan["est_calls"] == 8 and plan["fits"]
    history[0]["metrics"]["cost.usage_missing_n"] = 1
    assert (
        preflight.estimate(cfg, items[:1], root=args["root"], history=history)[
            "input_estimate_source"
        ]
        == "UTF-8 bytes / 3"
    )


@pytest.fixture
def f5_source(tmp_path):
    source = tmp_path / "pilot125"
    source.mkdir()
    rows = []
    for system in ("S1", "S2"):
        for family in ("F1", "F5"):
            rows.append(
                dict(
                    review_id=system + family,
                    system_id=system,
                    family=family,
                    qid=family,
                    dataset="phase05",
                    split="dev",
                    question="Synthetic question",
                    model_answer="Synthetic reason",
                    reference_answer="Synthetic reference",
                    current_result="Correct (automatic)"
                    if family == "F1"
                    else "Needs your grading",
                    answer_verdict="",
                )
            )
    with (source / "REVIEW.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return source, rows


def test_semantic_grading_checkpoints_and_import(f5_source, tmp_path):
    source, rows = f5_source
    output = tmp_path / "verdicts.jsonl"

    class Judge:
        calls = 0

        def generate_json(self, prompt, *args, **kwargs):
            self.calls += 1
            data = json.loads(prompt)
            return {
                "state": "SUCCESS",
                "value": {
                    "grades": [
                        {"id": r["id"], "correct": True, "reason": "Same substantive reason"}
                        for r in data["candidates"]
                    ]
                },
            }

    judge = Judge()
    plan = f5_grade.run(source, output)
    assert plan["state"] == "DRY_RUN" and not output.exists()
    done = f5_grade.run(source, output, enable_llm=True, provider=judge)
    assert done["state"] == "COMPLETE" and judge.calls == 1
    assert len(load_verdicts(rows, output)) == 2
    f5_grade.run(source, output, enable_llm=True, provider=judge)
    assert judge.calls == 1
    human, _ = backfill.answer_runs(source, "review-only")
    llm, _ = backfill.answer_runs(source, "review-only", f5_gold="llm", f5_verdicts=output)
    assert all("answer.F5.score" not in p["metrics"] for p in human)
    assert all(p["metrics"]["answer.F5.n"] == 1 for p in llm)
    assert all(
        p["metrics"]["answer.macro"] == p["metrics"]["answer.macro_excl_F5"] == 1 for p in llm
    )
    assert all(p["tags"]["f5_gold"] == "llm" for p in llm)
    assert len({p["metrics"]["answer.F5.n"] for p in llm}) == 1
    rows[-1]["model_answer"] = "Changed answer"
    with pytest.raises(ValueError, match="stale"):
        load_verdicts(rows, output)


def test_f5_partial_and_missing_gold_refused(f5_source, tmp_path):
    source, rows = f5_source
    row = next(r for r in rows if r["family"] == "F5")
    path = tmp_path / "partial.jsonl"
    path.write_text(
        json.dumps(
            dict(
                review_id=row["review_id"],
                fingerprint=fingerprint(row),
                version=VERSION,
                judge_model="synthetic",
                reason="Synthetic",
                verdict="INCORRECT",
            )
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="coverage incomplete"):
        load_verdicts(rows, path)
    rows[-1]["reference_answer"] = ""
    with pytest.raises(ValueError, match="no reference"):
        load_verdicts(rows, path)


@pytest.mark.parametrize("text_only", [False, True])
def test_parity_fake_api_and_stub(experiment_fixture, text_only):
    _, items = experiment_fixture
    if text_only:
        _replace_bundle_examples([{"text": item["question"]} for item in items])
    cfg = RunConfig(system_id="S1", provider="mock")
    app = FastAPI()

    @app.post("/v1/ask", response_model=AskResponse)
    def ask(request: ChatRequest):
        config = RunConfig(**request.overrides).validate_against()
        with build_runner(config, _mock_provider()) as engine:
            return AskResponse(request_id="synthetic", record=engine.run(request.message))

    with TestClient(app) as client:
        rows = check(cfg, items[:3], "http://testserver", client=client)
    assert len(rows) == 3 and all(r["match"] for r in rows)
    from bugzilla_serving.api.stub import create_app

    with TestClient(create_app()) as client:
        rows = check(cfg, items[:3], "http://testserver", client=client)
    assert all(not r["match"] and r["error"] == "API HTTP 501" for r in rows)


def _replace_bundle_examples(rows):
    bundle = Path(os.environ["BUNDLE_DIR"])
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    path = bundle / manifest["dev_questions"]
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode()
    path.write_bytes(payload)
    manifest["files"][manifest["dev_questions"]] = {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    "row",
    [
        {"question": "Synthetic?", "split": "test"},
        {"question": "Synthetic?"},
        {"text": "Synthetic?", "split": "test"},
        {"text": ""},
    ],
)
def test_bundle_example_scope_stays_strict(experiment_fixture, row):
    _replace_bundle_examples([row])
    with pytest.raises(ValueError, match="bundle:"):
        build_runner(RunConfig(system_id="S1", provider="mock"), _mock_provider())


def test_langsmith_smoke_mock_only(monkeypatch):
    from langsmith.utils import LangSmithNotFoundError

    monkeypatch.setattr("bugzilla_serving.tracking.langsmith_smoke.time.sleep", lambda _: None)

    class Client:
        events = []
        reads = 0

        def create_run(self, **kwargs):
            self.events.append(("trace", kwargs))

        def update_run(self, *args, **kwargs):
            self.events.append(("end", kwargs))

        def create_feedback(self, *args, **kwargs):
            self.events.append(("feedback", kwargs))

        def read_run(self, run_id):
            self.reads += 1
            if self.reads == 1:
                raise LangSmithNotFoundError("Synthetic index delay")
            return SimpleNamespace(id=run_id)

        def get_run_url(self, **kwargs):
            return "https://example.invalid/synthetic-trace"

    client = Client()
    result = smoke(client)
    metadata = client.events[0][1]["extra"]["metadata"]
    assert metadata["smoke"] is True and TRACE_METADATA_KEYS <= metadata.keys()
    assert [e[0] for e in client.events] == ["trace", "end", "feedback"]
    assert result["llm_calls"] == 0 and client.events[-1][1]["score"] == 1
    assert client.reads == 2


def test_rollback_local_store(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "seed_b6", ROOT / "scripts/testing/seed_mlflow_fixture.py"
    )
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    uri = (tmp_path / "store").as_uri()
    seed.seed(uri)
    registry = Registry(uri)
    versions = sorted(registry.versions(), key=lambda v: int(v.version))
    registry.set_champion(versions[-1].version)
    old = registry.get_champion().version
    unchanged = rollback(registry, to_version=old)
    assert unchanged["before"] == unchanged["after"] and not unchanged["would_change"]
    preview = rollback(registry)
    assert preview["state"] == "DRY_RUN" and registry.get_champion().version == old
    with pytest.raises(ValueError, match="reason"):
        rollback(registry, apply=True)
    applied = rollback(registry, reason="Synthetic demo", apply=True)
    target = registry.get_champion()
    assert str(target.version) == applied["after"]
    assert target.tags["rolled_back_from"] == str(old)
    assert target.tags["rollback_reason"] == "Synthetic demo"


def test_production_hides_smoke_unless_requested(tmp_path, monkeypatch):
    from bugzilla_serving.dashboard.data import langsmith_source as source

    rows = json.loads(source.FIXTURE.read_text())
    trace = {
        **rows[0],
        "id": "synthetic-b6-smoke",
        "metadata": {**rows[0]["metadata"], "smoke": True},
    }
    path = tmp_path / "traces.json"
    path.write_text(json.dumps([*rows, trace]))
    monkeypatch.setattr(source, "FIXTURE", path)
    source.roots.clear()
    args = ("fixture", "2020-01-01T00:00:00+00:00", "2020-01-02T00:00:00+00:00")
    assert len(source.roots(*args).value) == 30
    assert len(source.roots(*args, show_smoke=True).value) == 31
    source.roots.clear()


def test_no_silent_f5_downgrade(tmp_path):
    from bugzilla_serving.tracking.client import TrackingClient, params_for

    tracker = TrackingClient((tmp_path / "store").as_uri())
    tags = dict(
        source="backfill",
        eval_set="synthetic",
        datasets="phase05",
        split="dev",
        scorer="synthetic",
        git_sha="synthetic",
        f5_gold="llm",
    )
    tracker.log_run(
        "research-answer-eval",
        params_for(RunConfig()),
        tags,
        {"answer.F5.score": 1, "answer.F5.n": 1},
        {},
    )
    with pytest.raises(ValueError, match="downgrade"):
        tracker.log_run(
            "research-answer-eval",
            params_for(RunConfig()),
            {k: v for k, v in tags.items() if k != "f5_gold"},
            {"answer.F5.n": 0},
            {},
        )
