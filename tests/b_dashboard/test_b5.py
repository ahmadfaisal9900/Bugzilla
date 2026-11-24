"""Offline B5 acceptance on tiny synthetic data, including a zero-SDK warm path."""

import json
import re
import time
from pathlib import Path

import pytest
import test_dashboard as support
from streamlit.testing.v1 import AppTest

from bugzilla_serving.contracts.run_config import ROOT, RunConfig, load_spec
from bugzilla_serving.dashboard import labels as L
from bugzilla_serving.dashboard.comparison import (
    delta_to_questions,
    noise_marker,
    paired_counts,
    summary,
)
from bugzilla_serving.dashboard.data import mlflow_source as mf
from bugzilla_serving.dashboard.data.snapshot import (
    build_snapshot,
    directory,
    load_snapshot,
    safe_uri,
    stale,
)
from bugzilla_serving.experiments import bundle_verify as bv
from bugzilla_serving.tracking.backfill import read
from bugzilla_serving.tracking.client import TrackingClient, params_for

APP = support.APP

fixture_store = pytest.fixture(name="store")(support.store.__wrapped__)
fixture_offline = pytest.fixture(autouse=True)(support.offline.__wrapped__)


@pytest.fixture
def bundle(tmp_path):
    path = tmp_path / "tiny-bundle"
    path.mkdir()
    pins = read(ROOT / "configs/retrieval_v3.yaml")
    retrieval = {
        k: pins[k]
        for k in ("embedding_model", "embedding_revision", "reranker_model", "reranker_revision")
    }
    (path / "retrieval.json").write_text(json.dumps(retrieval))
    (path / "indexes/C1").mkdir(parents=True)
    for model, revision in [
        ("embedding_model", "embedding_revision"),
        ("reranker_model", "reranker_revision"),
    ]:
        snapshot = (
            path
            / "models/huggingface/hub"
            / ("models--" + pins[model].replace("/", "--"))
            / "snapshots"
            / pins[revision]
        )
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}")
    (path / "text.txt").write_text("Tiny synthetic record")
    manifest = dict(
        split="dev",
        synthetic=False,
        available_corpora=["C1"],
        missing_corpora=["C0", "C2"],
        files={},
    )
    for file in path.rglob("*"):
        if file.is_file():
            manifest["files"][str(file.relative_to(path))] = {
                "bytes": file.stat().st_size,
                "sha256": bv.sha(file),
            }
    (path / "manifest.json").write_text(json.dumps(manifest))
    return path


def test_bundle_cache_restat_and_rehash(bundle, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    first = bv.verify_bundle(bundle, cache_dir=cache)
    assert first["ok"] and not first["cache_reused"]
    original = bv.sha
    calls = []

    def spy(path):
        calls.append(path.name)
        return original(path)

    monkeypatch.setattr(bv, "sha", spy)
    assert bv.verify_bundle(bundle, cache_dir=cache)["cache_reused"]
    assert calls == ["manifest.json"]
    calls.clear()
    assert bv.verify_bundle(bundle, cache_dir=cache, rehash=True)["ok"]
    assert "text.txt" in calls
    (bundle / "text.txt").write_text("Tiny synthetic recorX")
    failed = bv.verify_bundle(bundle, cache_dir=cache)
    assert not failed["ok"] and any("SHA256 mismatch" in e for e in failed["errors"])


def test_bundle_corpus_and_hf_environment(bundle, monkeypatch):
    for key in ("HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.setenv(key, "unset")
    from bugzilla_serving.experiments.preflight import bundle_preflight

    with pytest.raises(ValueError, match="C0 isn't in this bundle; available: C1"):
        bundle_preflight(RunConfig(corpus="C0"), bundle)
    report = bundle_preflight(RunConfig(), bundle)
    import os

    assert report["ok"]
    assert os.environ["HF_HOME"] == str(bundle / "models/huggingface")
    assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_bundle_symlink_and_model_pin_checks(bundle, tmp_path):
    file = bundle / "text.txt"
    file.rename(bundle / "blob")
    file.symlink_to("blob")
    assert bv.verify_bundle(bundle, cache_dir=tmp_path / "cache")["ok"]
    retrieval = json.loads((bundle / "retrieval.json").read_text())
    retrieval["embedding_revision"] = "floating-main"
    (bundle / "retrieval.json").write_text(json.dumps(retrieval))
    report = bv.verify_bundle(bundle, cache_dir=tmp_path / "cache")
    assert not report["ok"]
    assert any("revision mismatch" in e for e in report["errors"])


def test_labels_cover_configs_and_fixture_runs(store):
    catalog = L.catalog()
    for field, kind in [
        ("system_id", "systems"),
        ("retriever", "retrievers"),
        ("corpus", "corpora"),
    ]:
        assert set(load_spec()["hyperparameters"][field]["choices"]) <= catalog[kind].keys()
    for preset in read(ROOT / "configs/presets.yaml")["presets"]:
        assert preset["slug"] in catalog["presets"]
    for key in read(ROOT / "configs/eval_sets.yaml")["sets"]:
        assert key in catalog["eval_sets"] or key.startswith("family-")
    for experiment in ("research-answer-eval", "research-retrieval-eval", "playground"):
        for run in mf.runs(store, experiment).value:
            for field, kind in [
                ("system_id", "systems"),
                ("retriever", "retrievers"),
                ("corpus", "corpora"),
            ]:
                assert run.params[field] in catalog[kind]
            assert run.tags["eval_set"] in catalog["eval_sets"]
            assert set(run.tags["datasets"].split(",")) <= catalog["dataset_tags"].keys()
            for key in run.metrics:
                if key.startswith("answer.") and key.endswith(".score") and key != "answer.macro":
                    assert key.split(".")[1] in catalog["families"]
    assert L.fmt_score(0.56) == "56%" and L.fmt_delta(0.04) == "+4 pts"
    assert L.fmt_seconds(1.23) == "1.2 s" and L.fmt_int(4096) == "4,096"


def test_comparison_math_and_exact_sign():
    assert delta_to_questions(1 / 24, 24) == 1
    assert noise_marker(0.04, 24)["noise"]
    assert noise_marker(0.5, 10)["noise"]
    assert noise_marker(0.5, 24, (12, 0))["p"] == pytest.approx(2 / 4096)
    assert not noise_marker(0.5, 24, (12, 0))["noise"]
    assert noise_marker(0, 20, (0, 0))["p"] == 1
    a = [dict(dataset="synthetic", qid="a", family="F1", score=0)]
    b = [dict(dataset="synthetic", qid="a", family="F1", score=1)]
    assert paired_counts(a, b, "F1") == (1, 0)
    assert paired_counts(a, [{**b[0], "qid": "b"}], "F1") is None
    text = summary(
        "Full bug dossier", "Smart search", [dict(family="KI", delta=1 / 24, n=24)], 0.55, 0.56
    )
    assert "Find bug by description (+4 pts, 1 more of 24 right)" in text
    assert "Overall: 56% vs 55%" in text


@pytest.fixture
def scored_store(store):
    tracker = TrackingClient(store)
    for system, score in [("S2", 0.5), ("S5", 0.6)]:
        tracker.log_run(
            "research-answer-eval",
            params_for(RunConfig(system_id=system)),
            dict(
                source="backfill",
                eval_set="pilot125",
                datasets="synthetic",
                split="dev",
                scorer="synthetic",
                git_sha="synthetic",
                simulated="true",
            ),
            {
                "answer.F1.score": score,
                "answer.F1.n": 20,
                "answer.F6.score": 0,
                "answer.F6.n": 20,
                "answer.macro": score / 2,
                "cost.llm_calls_per_question": 2,
                "cost.tokens_in": 1000,
                "cost.tokens_out": 100,
                "cost.usage_missing_n": 1,
                "latency.p50_ms": 1500,
                "latency.p95_ms": 2500,
            },
            {"per_family.csv": "family,source_n,n\nF1,20,20\nF6,20,20\n"},
        )
    mf.clear()
    return store


def assert_no_main_hashes(node):
    if getattr(node, "type", "") == "expander" and any(
        v in node.label for v in ("Technical details", "Raw config")
    ):
        return
    children = getattr(node, "children", None)
    if children is not None:
        for child in children.values():
            assert_no_main_hashes(child)
        return
    if getattr(node, "type", "") == "dataframe":
        text = str(node.value.to_dict())
    elif getattr(node, "type", "") in ("selectbox", "multiselect"):
        text = str(node.options) + str(node.label)
    elif getattr(node, "type", "") == "plotly_chart":
        spec = json.loads(node.proto.spec)
        text = str(
            [
                {
                    k: v
                    for k, v in trace.items()
                    if k in ("name", "text", "hovertext", "hovertemplate")
                }
                for trace in spec.get("data", [])
            ]
        )
    else:
        try:
            text = str(getattr(node, "value", "")) + " " + str(getattr(node, "label", ""))
        except KeyError:
            text = str(getattr(node, "label", ""))
    assert not re.search(r"\b[0-9a-f]{8,}\b", text), text


def test_warm_pages_zero_sdk_calls_no_hashes_and_timings(scored_store, monkeypatch):
    import mlflow.tracking

    from bugzilla_serving.dashboard import lab

    monkeypatch.setattr(
        lab, "preflight", lambda *a, **k: dict(fits=True, est_calls=3, reason="Synthetic plan")
    )
    cold = time.perf_counter()
    snapshot = build_snapshot(scored_store)
    cold = time.perf_counter() - cold
    load_snapshot.clear()
    assert not snapshot["errors"]
    calls = []

    def denied(*args, **kwargs):
        calls.append("SDK call")
        raise AssertionError("Warm page touched SDK")

    # Warm lazy detail artifacts before denying all SDK calls.
    for run in mf.runs(scored_store, "research-answer-eval").value:
        mf.artifact(scored_store, run.id, "predictions.jsonl")
    monkeypatch.setattr(mlflow.tracking.MlflowClient, "get_run", denied)
    monkeypatch.setattr(mlflow.tracking.MlflowClient, "search_runs", denied)
    monkeypatch.setattr(mlflow.tracking.MlflowClient, "search_model_versions", denied)
    monkeypatch.setattr(mlflow.tracking.MlflowClient, "download_artifacts", denied)
    app = AppTest.from_file(str(APP), default_timeout=10)
    app.run()  # Warm Python/UI imports; the disk snapshot was built separately.
    timings = {}
    for page in (
        "overview",
        "answer_eval",
        "retrieval_eval",
        "cost_latency",
        "error_analysis",
        "experiment_lab",
        "compare_runs",
        "presets_page",
        "production",
    ):
        start = time.perf_counter()
        if page == "overview":
            app.run()
        else:
            app.switch_page(f"pages/{page}.py").run()
        timings[page] = round(time.perf_counter() - start, 4)
        assert not app.exception, [e.message for e in app.exception]
        assert_no_main_hashes(app.main)
        assert "How to read this" in [e.label for e in app.expander]
    assert not calls
    assert max(timings.values()) < 2
    assert max(v for k, v in timings.items() if k != "overview") < 1
    print("B5_COLD", round(cold, 4), "B5_WARM", json.dumps(timings))
    # Explicit refresh is the only operation that may refetch.
    assert len(app.sidebar.button) == 1


def test_snapshot_credentials_and_staleness(store):
    assert safe_uri("https://user:secret@host/team?token=hidden#fragment") == "https://host/team"
    snapshot = build_snapshot(store)
    assert not stale(snapshot["meta"])
    assert stale({"built_at": "2000-01-01T00:00:00+00:00"})
    meta = json.loads((directory(store) / "snapshot_meta.json").read_text())
    assert meta["run_counts"]["playground"] == 4  # three CI seeds plus one visible Lab run
    assert Path(directory(store) / meta["file"]).exists()


def test_disk_reload_and_failed_refresh_preserve_last_good(store, monkeypatch):
    from bugzilla_serving.dashboard.profiling import request_budget

    snapshot = build_snapshot(store)
    pointer = (directory(store) / "snapshot_meta.json").read_text()
    try:
        request_budget(1)
        failed = build_snapshot(store)
        assert failed["errors"]
        assert (directory(store) / "snapshot_meta.json").read_text() == pointer
    finally:
        request_budget()
    load_snapshot.clear()

    def denied(*args, **kwargs):
        raise AssertionError("Disk reload must not fetch")

    monkeypatch.setattr(mf, "_fetch_runs", denied)
    assert load_snapshot(store)["meta"] == snapshot["meta"]


def test_compare_omits_mismatched_family(scored_store):
    run = next(
        r
        for r in mf.runs(scored_store, "research-answer-eval").value
        if r.params["system_id"] == "S5"
    )
    TrackingClient(scored_store).client.log_metric(run.id, "answer.F1.n", 21)
    mf.clear()
    app = AppTest.from_file(str(APP)).run().switch_page("pages/compare_runs.py").run()
    assert not app.exception
    assert any("Field lookup: question counts differ; omitted" in w.value for w in app.warning)
    delta = next(d.value for d in app.dataframe if "Difference" in d.value.columns)
    assert "Field lookup" not in delta["Family"].tolist()
