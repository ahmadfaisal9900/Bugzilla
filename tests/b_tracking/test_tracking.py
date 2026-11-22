"""Stream B: synthetic fixtures, temporary MLflow stores, no network/model downloads."""

import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bugzilla_serving.contracts.names import validate_mlflow_run
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.tracking.backfill import (
    aggregate,
    answer_runs,
    csv_text,
    projected_config,
    read,
    retrieval_runs,
)
from bugzilla_serving.tracking.client import TrackingClient, config_artifact, params_for
from bugzilla_serving.tracking.policy import assess
from bugzilla_serving.tracking.registry import Registry

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def local_mlflow_defaults(tmp_path, monkeypatch):
    import mlflow

    uri = (tmp_path / "default-tracking").as_uri()
    previous, registry = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("MLFLOW_REGISTRY_URI", uri)
    monkeypatch.setenv("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    try:
        yield
    finally:
        mlflow.set_tracking_uri(previous)
        mlflow.set_registry_uri(registry)


def module(path):
    spec = importlib.util.spec_from_file_location("b_publish", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tags(**extra):
    return dict(
        source="backfill",
        eval_set="pilot125",
        datasets="sample",
        split="dev",
        scorer="synthetic",
        git_sha="synthetic",
        **extra,
    )


def review_fixture(tmp_path):
    source = tmp_path / "pilot125"
    source.mkdir()
    header = next(
        csv.reader(
            (ROOT / "tests/fixtures/sample_partner_eval/REVIEW.csv").open(encoding="utf-8-sig")
        )
    )
    values = []
    for i, family in enumerate(["F1", "F1", "F5"]):
        row = dict.fromkeys(header, "")
        row.update(
            review_id=f"r{i}",
            dataset="sample",
            question_type="synthetic",
            current_result=["Correct (automatic)", "Wrong (automatic)", "Needs your grading"][i],
            question=f"synthetic question {i}",
            model_answer="synthetic",
            reference_answer="synthetic",
        )
        if family == "F5":
            row.update(
                answer_verdict="CORRECT", reviewer="synthetic-reviewer", note="synthetic check"
            )
        values.append(row)
    (source / "REVIEW.csv").write_text(csv_text(values, header))
    metadata = [
        dict(row, method="S1", family=family, question_id=f"q{i}")
        for i, (row, family) in enumerate(zip(values, ["F1", "F1", "F5"]))
    ]
    (source / "START_HERE.html").write_text(
        '<script id="data" type="application/json">' + json.dumps({"rows": metadata}) + "</script>"
    )
    return source


def test_review_only_temp_store_and_idempotency(tmp_path):
    source = review_fixture(tmp_path)
    plans, info = answer_runs(source)
    assert info["mode"] == "review-only"
    plan = plans[0]
    assert plan["metrics"]["answer.F1.n"] == 2
    assert plan["metrics"]["answer.F1.score"] == 0.5
    assert plan["metrics"]["answer.F5.score"] == 1
    assert "answer.F2.n" not in plan["metrics"]
    assert not any(k.startswith(("cost.", "latency.")) for k in plan["metrics"])
    assert plan["tags"]["config_origin"] == "reconstructed"
    assert plan["tags"]["scorer.F5"] == "human-review"
    tracker = TrackingClient((tmp_path / "store").as_uri())
    rid = tracker.log_run(**plan)
    assert tracker.log_run(**plan) == rid
    assert len(tracker.runs(plan["experiment"])) == 1
    for path in (tmp_path / "store").rglob("*"):
        if path.is_file():
            assert b"synthetic question" not in path.read_bytes()
    # Later exact ledgers upgrade this identity; no downgrade allowed.
    upgrade = {
        **plan,
        "tags": {**plan["tags"], "provenance": "ledgers", "config_origin": "historical"},
        "metrics": {**plan["metrics"], "cost.llm_calls": 3},
    }
    assert tracker.log_run(**upgrade) == rid
    tracker.log_run(**plan)
    assert tracker.client.get_run(rid).data.tags["provenance"] == "ledgers"
    # A changed historical configuration is a conflict, never a duplicate pilot system.
    cfg = RunConfig(system_id="S1", top_k=4)
    with pytest.raises(ValueError, match="config conflict"):
        tracker.log_run(**{**upgrade, "params": params_for(cfg)})


@pytest.mark.parametrize("output", [r"C:\Courses\ENSF 621\Bugzilla\run-123", "missing/run-123"])
def test_missing_or_foreign_manifest_falls_back(tmp_path, output):
    source = review_fixture(tmp_path)
    (source / "latest.json").write_text(json.dumps({"evaluations": {"sample": {"output": output}}}))
    plans, info = answer_runs(source)
    assert info["mode"] == "review-only"
    assert plans[0]["tags"]["provenance"] == "review-only"
    assert not any(k.startswith(("cost.", "latency.")) for k in plans[0]["metrics"])
    with pytest.raises(ValueError, match="Exact referenced prediction ledgers unavailable"):
        answer_runs(source, "ledgers")


def test_explicit_review_only_does_not_discover_ledgers(tmp_path):
    source = review_fixture(tmp_path)
    (source / "latest.json").write_text("[invalid provenance metadata")
    plans, info = answer_runs(source, "review-only")
    assert info["mode"] == "review-only" and plans


@pytest.mark.parametrize("prefix", [r"C:\Courses\ENSF 621\Bugzilla", "/former/owner/Project"])
def test_relocated_exact_ledgers_are_hash_checked(tmp_path, prefix):
    from bugzilla_serving.tracking.backfill import discover_ledgers, sha

    root = tmp_path / "owner's Project"
    source = root / "outputs/evaluation/phase11/pilot125"
    evaluation = source / "natural/dev/run-eval"
    directory = root / "outputs/predictions/natural/dev/run-exact"
    evaluation.mkdir(parents=True)
    directory.mkdir(parents=True)
    (directory / "S0.jsonl").write_text("synthetic dev prediction\n")
    (directory / "manifest.json").write_text("{}")

    def saved(path):
        suffix = str(path.relative_to(root))
        return prefix + ("\\" + suffix.replace("/", "\\") if "\\" in prefix else "/" + suffix)

    (source / "latest.json").write_text(
        json.dumps({"evaluations": {"natural": {"output": saved(evaluation)}}})
    )
    (evaluation / "manifest.json").write_text(
        json.dumps({"input_sha256": {saved(p): sha(p) for p in directory.iterdir()}})
    )
    assert discover_ledgers(source, root) == {"natural": str(directory)}
    (directory / "S0.jsonl").write_text("modified prediction\n")
    with pytest.raises(ValueError, match="checksum"):
        discover_ledgers(source, root)
    (directory / "manifest.json").unlink()
    assert discover_ledgers(source, root) == {}


def test_missing_archived_retrieval_setting_is_unknown():
    cfg = read(ROOT / "configs/answering.yaml")
    cfg["effective_llm"] = read(ROOT / "configs/llm.yaml")
    cfg["retrieval_config"] = "outputs/not-present-archived-runtime/retrieval.json"
    historical = projected_config("S2", cfg)
    assert historical.rrf_k is None


def test_saved_test_prediction_reference_refused_before_hashing(tmp_path, monkeypatch):
    from bugzilla_serving.tracking import backfill as b

    source = tmp_path / "pilot"
    source.mkdir()
    target = tmp_path / "outputs/predictions/natural/test/run-exact"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}")
    (source / "latest.json").write_text(
        json.dumps({"evaluations": {"natural": {"output": str(source)}}})
    )
    (source / "manifest.json").write_text(
        json.dumps({"input_sha256": {str(target / "manifest.json"): "not-read"}})
    )

    def never_hash(path):
        raise AssertionError("Must reject test reference before hashing its files")

    monkeypatch.setattr(b, "sha", never_hash)
    with pytest.raises(ValueError, match="Non-dev"):
        b.discover_ledgers(source, tmp_path)


def test_review_split_and_signature_refused(tmp_path):
    source = review_fixture(tmp_path)
    with (source / "REVIEW.csv").open() as f:
        rows = list(csv.DictReader(f))
    rows[0]["split"] = "test"
    (source / "REVIEW.csv").write_text(csv_text(rows, list(rows[0])))
    with pytest.raises(ValueError, match="Test split"):
        answer_runs(source)
    for row in rows:
        row["split"] = "dev"
    rows[2]["reviewer"] = ""
    (source / "REVIEW.csv").write_text(csv_text(rows, list(rows[0])))
    with pytest.raises(ValueError, match="requires reviewer"):
        answer_runs(source)


def test_validator_refuses_before_write(tmp_path):
    tracker = TrackingClient((tmp_path / "store").as_uri())
    with pytest.raises(ValueError):
        tracker.log_run("research-answer-eval", {}, tags(), {"bad": 1}, {})
    assert not tracker.runs("research-answer-eval")


def test_retrieval_na_and_selected(tmp_path, monkeypatch):
    directory = tmp_path / "retrieval"
    directory.mkdir()
    summary = read(ROOT / "tests/fixtures/sample_retrieval_summary.json")
    summary["cells"][0].update(retriever="R7b", corpus="C1")
    (directory / "summary.json").write_text(json.dumps(summary))
    plans = retrieval_runs([directory])
    assert len(plans) == 1 and plans[0]["tags"]["selected"] == "true"
    assert "retr.v3.F1.mh_full_evidence_at_10" not in plans[0]["metrics"]
    assert "mh_full_evidence_at_10" in plans[0]["artifacts"]["na_cells.csv"]
    tracker = TrackingClient((tmp_path / "store").as_uri())
    tracker.log_run(**plans[0])
    tracker.log_run(**plans[0])
    assert len(tracker.runs("research-retrieval-eval")) == 1
    summary["split"] = "test"
    (directory / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="Test retrieval"):
        retrieval_runs([directory])


def test_policy_and_registry(tmp_path):
    registry = Registry((tmp_path / "store").as_uri())
    cfg = RunConfig(system_id="S1", provider="mock")
    metrics = {
        "answer.F1.score": 0.8,
        "answer.F1.n": 10,
        "answer.macro": 0.8,
        "abstain.false_rate": 0.0,
        "fail.rate": 0.0,
        "latency.p95_ms": 20.0,
    }
    run_id = registry.tracking.log_run(
        "research-answer-eval",
        params_for(cfg),
        tags(),
        metrics,
        {"config.yaml": config_artifact(cfg)},
    )
    run = registry.client.get_run(run_id)
    policy = read(ROOT / "configs/promotion.yaml")
    assert assess(run, [run], policy)["allowed"]
    pub = module(ROOT / "scripts/publish_preset.py")
    preview = pub.publish(registry, run_id, "fast", "Fast", "Synthetic only")
    assert preview["policy"]["status"] == "not applicable (preset only)"
    assert all(
        r["champion_score"] == "none" and r["champion_n"] == "none" for r in preview["comparison"]
    )
    assert registry.get_champion() is None
    result = pub.publish(registry, run_id, "fast", "Fast", "Synthetic only", True, True)
    version = result["version"]
    assert registry.register_config_version(cfg, {}) == version
    assert registry.get_champion().version == version
    assert registry.list_presets()[0]["slug"] == "fast"
    model_dir = registry.client.download_artifacts(registry.get_champion().run_id, "model")
    import mlflow.pyfunc

    loaded = mlflow.pyfunc.load_model(model_dir)
    assert json.loads(loaded.predict(["x"])[0])["system_id"] == "S1"
    registry.unpublish("fast")
    assert not registry.list_presets()
    worse = SimpleNamespace(
        data=SimpleNamespace(metrics={**metrics, "answer.F1.score": 0.1}, tags=run.data.tags),
        info=run.info,
    )
    assert not assess(worse, [worse], policy)["allowed"]
    bad_id = registry.tracking.log_run(
        "research-answer-eval", params_for(cfg), tags(), {**metrics, "fail.rate": 0.9}, {}
    )
    with pytest.raises(ValueError, match="policy failed"):
        pub.publish(registry, bad_id, "fast", "Fast", "Synthetic", True, True)
    pub.publish(
        registry,
        bad_id,
        "fast",
        "Fast",
        "Synthetic",
        True,
        True,
        override_policy="synthetic policy exception",
    )
    assert registry.get_champion().tags["policy_override"] == "synthetic policy exception"
    historical = RunConfig(system_id="S5", s5_dossier_budget=12000)
    hid = registry.tracking.log_run(
        "research-answer-eval",
        params_for(historical),
        tags(config_origin="historical"),
        metrics,
        {},
    )
    with pytest.raises(ValueError, match="not deployable"):
        pub.publish(
            registry,
            hid,
            "deep",
            "Deep",
            "Synthetic",
            True,
            True,
            override_policy="must not bypass caps",
        )


def test_fake_secret_never_written(tmp_path, monkeypatch):
    secret = "fake-B1-secret-never-write-123456"
    for name in ("GROQ_API_KEY", "LANGSMITH_API_KEY", "MLFLOW_TRACKING_PASSWORD"):
        monkeypatch.setenv(name, secret)
    tracker = TrackingClient((tmp_path / "store").as_uri())
    cfg = RunConfig(provider="mock")
    with pytest.raises(ValueError, match="Secret"):
        tracker.log_run("playground", params_for(cfg), tags(), {}, {"bad.txt": secret})
    tracker.log_run(
        "playground", params_for(cfg), tags(), {}, {"config.yaml": config_artifact(cfg)}
    )
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
    for run in tracker.runs("playground"):
        validate_mlflow_run(run.data.params, run.data.tags, run.data.metrics)


def test_missing_and_pending_families():
    metrics, families = aggregate([dict(family="F5", verdict="NEEDS_HUMAN", scorer="pending")])
    assert metrics == {"answer.F5.n": 0, "answer.F5.pending": 1}
    assert families[0]["pending_n"] == 1


def test_equal_family_denominators_shared_pending_and_errors():
    from bugzilla_serving.tracking.backfill import balanced_pending

    values = {}
    for system in (f"S{i}" for i in range(9)):
        values[system] = [
            dict(
                dataset="synthetic",
                qid="numeric",
                family="F2",
                verdict="INCORRECT" if system == "S7" else "CORRECT",
                failed=system == "S7",
                scorer="synthetic",
            ),
            dict(
                dataset="synthetic",
                qid="rationale",
                family="F5",
                verdict="NEEDS_HUMAN" if system == "S2" else "CORRECT",
                scorer="synthetic",
            ),
        ]
    balanced_pending(values)
    counts = []
    for rows in values.values():
        metrics, _ = aggregate(rows)
        counts.append({k: v for k, v in metrics.items() if k.endswith((".n", ".pending"))})
        assert metrics["answer.F2.n"] == 1 and metrics["answer.F5.pending"] == 1
        assert metrics["answer.F5.n"] == 0 and "answer.F5.score" not in metrics
    assert all(c == counts[0] for c in counts)


def test_unparseable_duration_is_failure_but_false_abstention_is_not():
    from bugzilla_serving.tracking.backfill import prediction_failed

    assert prediction_failed(dict(reason="ambiguous_duration_unit"), {}, {"status": "ok"})
    assert prediction_failed(dict(reason="integer", absolute_error=None), {}, {"status": "ok"})
    assert prediction_failed(dict(reason="execution_failure"), {}, {"status": "error"})
    assert not prediction_failed(dict(reason="false_abstention"), {}, {"status": "ok"})
    assert prediction_failed(
        dict(reason="structured"), {}, {"status": "ok", "answer": {"answer": "not JSON"}}
    )


def test_partner_mh_set_order_and_id_format_are_already_normalized():
    from bugzilla_qa.evaluation import systems as scorer

    item = dict(
        qid="synthetic",
        dataset="synthetic",
        family="MH",
        cluster_id="1",
        kind="structured",
        expected={"depends_on": ["1", "2"], "resolved_fixed": ["2"]},
    )
    prediction = dict(
        status="ok",
        system_id="S7",
        context_chunk_ids=[],
        answer={
            "abstain": False,
            "citations": [],
            "answer": json.dumps({"resolved_fixed": [2], "depends_on": [2, "01"]}),
        },
    )
    assert scorer.grade(item, prediction)["verdict"] == "CORRECT"


def test_projection_model_and_archival_dossier():
    cfg = projected_config("S5", read(ROOT / "configs/answering.yaml"))
    assert cfg.s5_dossier_budget == 12000
    assert cfg.model == "openai/gpt-oss-20b"
    with pytest.raises(ValueError):
        cfg.validate_against(mode="execute")


def test_ledger_mode_partner_scorer_and_upgrade(tmp_path, monkeypatch):
    """Run the actual scorer and checksum loaders on three synthetic dev records."""
    from bugzilla_qa.evaluation import systems as scorer
    from bugzilla_serving.tracking import backfill as b

    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    for name in ("answering.yaml", "llm.yaml", "retrieval_v3.yaml", "selected_retriever.yaml"):
        (root / "configs" / name).write_bytes((ROOT / "configs" / name).read_bytes())
    rc = read(root / "configs/retrieval_v3.yaml")
    rc["sample_dir"] = "sample"
    (root / "configs/retrieval_v3.yaml").write_text(yaml.safe_dump(rc))
    sample = root / "sample"
    sample.mkdir()
    questions = [
        dict(
            qid=f"q{i}",
            question=f"Synthetic dev question {i}",
            family=family,
            answer_type=kind,
            split="dev",
            cluster_id=str(i),
        )
        for i, (family, kind) in enumerate(
            [("F1", "string"), ("F6", "unanswerable"), ("F5", "supported_explanation")]
        )
    ]
    gold = [
        dict(qid="q0", gold={"type": "string", "value": "synthetic"}),
        dict(qid="q1", gold={"type": "unanswerable", "value": None}),
        dict(
            qid="q2",
            gold={"type": "supported_explanation", "claims": [{"text": "synthetic rationale"}]},
        ),
    ]
    for name, records in [("questions.jsonl", questions), ("gold.jsonl", gold)]:
        (sample / name).write_text("".join(json.dumps(r) + "\n" for r in records))
    manifest = dict(
        state="SOURCE_VERIFIED_DEV_SAMPLE",
        sample_id="synthetic",
        sha256={n: b.sha(sample / n) for n in ("questions.jsonl", "gold.jsonl")},
    )
    (sample / "manifest.json").write_text(json.dumps(manifest))
    items, _ = scorer.load_items(root, rc, "sample")
    prediction_dir = root / "predictions"
    prediction_dir.mkdir()
    snapshot = read(root / "configs/answering.yaml")
    (prediction_dir / "config_snapshot.json").write_text(json.dumps(snapshot))
    from bugzilla_qa.retrieval_v3.common import digest as prediction_digest

    identity = dict(
        config=snapshot,
        llm=read(root / "configs/llm.yaml"),
        selected=read(root / "configs/selected_retriever.yaml")["selected"],
        inputs={snapshot["retrieval_config"]: b.sha(root / snapshot["retrieval_config"])},
    )
    config_hash = prediction_digest(identity)
    assert config_hash != scorer.digest(identity)
    (prediction_dir / "identity.json").write_text(json.dumps(identity))
    predictions = []
    metadata, csv_rows = [], []
    for item in items:
        abstain = item["family"] == "F6"
        value = None if abstain else "synthetic"
        pred = dict(
            qid=item["qid"],
            dataset="sample",
            split="dev",
            family=item["family"],
            freeze_id="synthetic",
            config_hash=config_hash,
            system_id="S1",
            model="openai/gpt-oss-20b",
            provider="groq",
            prompt_version="answer-v1",
            status="ok",
            context_chunk_ids=[],
            call_count=1,
            latency_ms=12.0,
            tokens={"input_tokens": 10, "output_tokens": 3},
            answer=dict(abstain=abstain, answer=value, citations=[], bug_ids=[]),
        )
        predictions.append(pred)
        rid = scorer.digest([scorer.VERSION, item, "S1", pred["config_hash"], pred["answer"], []])[
            :24
        ]
        row = dict(
            review_id=rid,
            dataset="sample",
            question=item["question"],
            model_answer="synthetic",
            reference_answer="synthetic",
            current_result="Correct (automatic)",
            answer_verdict="",
            reviewer="",
            note="",
        )
        if item["family"] == "F5":
            row.update(answer_verdict="CORRECT", reviewer="synthetic-human", note="synthetic check")
        csv_rows.append(row)
        metadata.append(dict(row, method="S1", family=item["family"], question_id=item["qid"]))
    (prediction_dir / "S1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in predictions))
    (prediction_dir / "manifest.json").write_text(
        json.dumps(
            dict(
                config_hash=config_hash,
                sha256={
                    name: b.sha(prediction_dir / name)
                    for name in ("S1.jsonl", "config_snapshot.json", "identity.json")
                },
            )
        )
    )
    source = root / "pilot125"
    source.mkdir()
    (source / "REVIEW.csv").write_text(csv_text(csv_rows, list(csv_rows[0])))
    (source / "START_HERE.html").write_text(
        '<script id="data">' + json.dumps({"rows": metadata}) + "</script>"
    )
    monkeypatch.setattr(b, "git_sha", lambda _: "synthetic")
    plans, _ = answer_runs(source, "review-only", root=root)
    tracking = TrackingClient((tmp_path / "store").as_uri())
    rid = tracking.log_run(**plans[0])
    (source / "provenance.json").write_text(
        json.dumps({"prediction_dirs": {"sample": "predictions"}})
    )
    upgraded, info = answer_runs(source, "auto", root=root)
    assert info["mode"] == "ledgers"
    plan = upgraded[0]
    assert plan["metrics"]["answer.F1.score"] == 1
    assert plan["metrics"]["answer.F5.score"] == 1
    assert plan["metrics"]["abstain.correct_rate"] == 1
    assert plan["metrics"]["abstain.false_rate"] == 0
    assert plan["metrics"]["cost.llm_calls"] == 3
    assert plan["metrics"]["cost.tokens_in"] == 30
    assert tracking.log_run(**plan) == rid
    assert len(tracking.runs("research-answer-eval")) == 1
    assert tracking.client.get_run(rid).data.tags["config_origin"] == "historical"
    # Frozen dev pins are enforced, not regenerated.
    (prediction_dir / "S1.jsonl").write_text(json.dumps(predictions[0]) + "\n")
    with pytest.raises(ValueError, match="checksum"):
        answer_runs(source, "ledgers", root=root)
    (prediction_dir / "S1.jsonl").write_text("".join(json.dumps(p) + "\n" for p in predictions))
    with (root / snapshot["retrieval_config"]).open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="Historical retrieval configuration checksum"):
        answer_runs(source, "ledgers", root=root)


def test_natural_gold_parser_sees_dev_only(tmp_path, monkeypatch):
    from bugzilla_qa.evaluation import systems as scorer
    from bugzilla_serving.tracking.backfill import load_dev_items, sha

    original = tmp_path / "natural-mixed.jsonl"
    row = dict(
        qid="dev1",
        question="Synthetic dev",
        family="F1",
        answer_type="string",
        split="dev",
        human_review_state="HUMAN_APPROVED_WORDING",
        answer="synthetic",
    )
    original.write_text(
        json.dumps(row)
        + "\n"
        + json.dumps(dict(row, qid="locked", split="test", answer="LOCKED_SENTINEL_DO_NOT_PARSE"))
        + "\n"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": sha(original)}))
    real_rows = scorer.rows

    def spy(path):
        assert Path(path) != original
        assert "LOCKED_SENTINEL_DO_NOT_PARSE" not in Path(path).read_text()
        return real_rows(path)

    monkeypatch.setattr(scorer, "rows", spy)
    items, pins = load_dev_items(
        tmp_path, dict(natural_questions=str(original), natural_manifest=str(manifest)), "natural"
    )
    assert len(items) == 1 and items[0]["qid"] == "dev1"
    assert items[0]["freeze_id"] == sha(original)
    assert pins[str(original)] == sha(original)


def test_saved_intervals_are_aggregate_artifacts(tmp_path):
    from bugzilla_serving.tracking.backfill import answer_intervals

    source = tmp_path / "pilot"
    source.mkdir()
    folder = tmp_path / "evaluation"
    folder.mkdir()
    (source / "latest.json").write_text(
        json.dumps(dict(evaluations={"sample": {"output": "evaluation"}}))
    )
    summary = dict(
        split="dev", table=[dict(system_id="S1", family="F1", n=2, cluster_bootstrap_95=[0.5, 1.0])]
    )
    (folder / "summary.json").write_text(json.dumps(summary))
    result = answer_intervals(source, tmp_path, "S1")
    assert result == [dict(dataset="sample", family="F1", n=2, ci_low=0.5, ci_high=1.0)]
    summary["split"] = "test"
    (folder / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="Test source"):
        answer_intervals(source, tmp_path, "S1")
