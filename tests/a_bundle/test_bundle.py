"""Check bundle integrity, read-only access, portable copies and offline S1 retrieval."""

import hashlib
import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

from bugzilla_serving.bundle import load_bundle
from bugzilla_serving.contracts.run_config import RunConfig
from bugzilla_serving.engine import build_runner

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture
def bundle(tmp_path):
    path = module("build_fixture_bundle").build(tmp_path / "fixture")
    yield path
    try:
        load_bundle(path).close()
    except (ValueError, OSError):
        pass


def test_fixture_read_only_and_cache(bundle):
    with load_bundle(bundle) as loaded:
        assert load_bundle(bundle) is loaded
        assert len(loaded.examples()) == 10
        assert loaded.db.execute("select count(*) from bugs").fetchone()[0] == 20
        with pytest.raises(duckdb.Error):
            loaded.db.execute("create table forbidden(i integer)")


def test_test_split_rejected(bundle):
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["split"] = "test"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="dev"):
        load_bundle(bundle)


def test_changed_bytes_rejected(bundle):
    with load_bundle(bundle):
        pass
    path = bundle / "dev_questions.jsonl"
    path.write_bytes(b"!" + path.read_bytes()[1:])
    with pytest.raises(ValueError, match="mismatch"):
        load_bundle(bundle)


def test_path_traversal_rejected(bundle):
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["../outside.json"] = {"bytes": 0, "sha256": "invalid"}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inside"):
        load_bundle(bundle)


def test_runtime_escape_rejected(bundle):
    path = bundle / "runtime.json"
    runtime = json.loads(path.read_text())
    runtime["source_config"] = "../outside.json"
    path.write_text(json.dumps(runtime))
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["runtime.json"] = {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inside"):
        load_bundle(bundle)


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "inputs"
    fixture = module("build_fixture_bundle").build(root / "fixture")
    with duckdb.connect(str(fixture / "canonical.duckdb")) as db:
        db.execute((fixture / "canonical.sql").read_text())
    runtime = json.loads((fixture / "runtime.json").read_text())
    for key in ("source_config", "history_checkpoint", "retrieval_config", "selection"):
        runtime[key] = "fixture/" + runtime[key]
    (root / "answering.json").write_text(json.dumps(runtime))
    selection = json.loads((fixture / "selection.json").read_text())
    selection.update(state="RECONSTRUCTED_DEV_RUNTIME", index_build="fixture/indexes")
    (fixture / "selection.json").write_text(json.dumps(selection))
    (fixture / "source.json").write_text(json.dumps({"canonical_db": "fixture/canonical.duckdb"}))
    retrieval = json.loads((fixture / "retrieval.json").read_text())
    retrieval["seed"] = 317
    for key in ("phase05_dir", "v3_dir"):
        retrieval[key] = "examples/" + key
        folder = root / retrieval[key]
        folder.mkdir(parents=True)
        (folder / "dev.questions.jsonl").write_text(
            json.dumps(
                {
                    "question": "What product is recorded for bug 100000?",
                    "split": "dev",
                    "answer": "must not be copied",
                    "evidence": ["must not be copied"],
                }
            )
            + "\n"
        )
    (fixture / "retrieval.json").write_text(json.dumps(retrieval))
    for kind in ("embedding", "reranker"):
        name = retrieval[kind + "_model"].replace("/", "--")
        revision = retrieval[kind + "_revision"]
        folder = root / "models/huggingface/hub" / ("models--" + name) / "snapshots" / revision
        folder.mkdir(parents=True)
        (folder / "model.safetensors").write_bytes(b"fixture-only placeholder")
    return root


def test_builder_preview_and_apply(inputs, tmp_path, monkeypatch):
    builder = module("build_serving_bundle")
    output = tmp_path / "portable"
    preview = builder.build(inputs, output, runtime_name="answering.json")
    assert preview["state"] == "DRY_RUN" and not output.exists()
    report = builder.build(
        inputs, output, apply=True, require_all=True, runtime_name="answering.json"
    )
    assert report["state"] == "COMPLETE" and report["corpora"] == ["C0", "C1", "C2"]
    with load_bundle(output) as loaded:
        rows = [
            json.loads(line) for line in (output / "dev_questions.jsonl").read_text().splitlines()
        ]
        assert all(set(row) == {"text"} for row in rows)
        monkeypatch.setenv("BUNDLE_DIR", str(output))
        events = []
        with build_runner(RunConfig(system_id="S1", retriever="R1", provider="mock")) as runner:
            answer = runner.run(loaded.examples()[0], on_event=events.append)
        assert answer.evidence and not answer.errors and answer.answer.abstain
        assert [event["data"]["stage"] for event in events] == [
            "retrieving",
            "retrieved",
            "generating",
            "done",
        ]
    with pytest.raises(ValueError, match="already exists"):
        builder.build(inputs, output, apply=True, runtime_name="answering.json")


@pytest.mark.parametrize(
    "name", ["test.questions.jsonl", "dev.gold.jsonl", "../secret", "C:/secret"]
)
def test_forbidden_builder_paths(name):
    with pytest.raises(ValueError):
        module("build_serving_bundle").safe_name(name)


def test_missing_corpus_is_reported(inputs, tmp_path):
    directory = inputs / "fixture/indexes/C2"
    directory.rename(directory.with_name("unavailable_C2"))
    builder = module("build_serving_bundle")
    output = tmp_path / "portable"
    report = builder.build(inputs, output, runtime_name="answering.json")
    assert report["missing_corpora"] == ["C2"]
    with pytest.raises(ValueError, match="missing corpora: C2"):
        builder.build(inputs, output, require_all=True, runtime_name="answering.json")
    assert not output.exists()
