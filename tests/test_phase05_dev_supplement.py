"""The practice run leaves the parent release untouched and keeps dev bugs disjoint from test."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_phase05 import args, fixture
from bugzilla_qa.benchmark import dev_supplement, phase05
from bugzilla_qa.data.normalize import file_hash, write_json
from bugzilla_qa.evaluation import phase06
from bugzilla_qa.methods import m3_sql


def test_practice_set_preserves_parent_and_runs_with_sql(tmp_path):
    pins = fixture(tmp_path)
    write_json(tmp_path / "sources.json", pins)
    parent = args(tmp_path)
    generated = phase05.generate(parent, tmp_path, pins)
    run = tmp_path / generated["run"]
    (run / "review_queue.csv").write_text("human review sentinel\n", encoding="utf-8")
    (run / "FROZEN").write_text("frozen-fixture\n", encoding="utf-8")
    frozen = run / "frozen-fixture"
    frozen.mkdir()
    (frozen / "test.questions.jsonl").write_text("test sentinel\n", encoding="utf-8")
    original = phase05.read(run / "candidates.json")
    before = {path: file_hash(path) for path in run.rglob("*") if path.is_file()}
    opts = SimpleNamespace(root=tmp_path, run=run, sources=Path("sources.json"),
                           limit=2, resume=False, dry_run=True, sample_bundle=None)
    preview = dev_supplement.generate(opts)
    assert preview["state"] == "DRY_RUN"
    assert not Path(preview["output"]).exists()
    opts.dry_run = False
    report = dev_supplement.generate(opts)
    dest = Path(report["output"])
    items = phase05.read(dest / "candidates.json")
    assert report["state"] == "PRACTICE_ONLY"
    assert len(items) == report["questions"] == 2
    assert {q["split"] for q in items} == {"dev"}
    assert {q["family"] for q in items} == {"F1"}
    assert all(phase05.partition(317, q["bug_ids"][0]) == "dev" for q in items)
    assert {q["question"] for q in items}.isdisjoint(q["question"] for q in original)
    assert {path: file_hash(path) for path in run.rglob("*") if path.is_file()} == before

    state, questions, load_gold = phase06.load_benchmark(dest, unfrozen=True)
    assert state == phase06.SMOKE
    assert all(set(q) == {"qid", "question", "scope"} for q in questions)
    base, overlay = phase05.paths(tmp_path, pins)
    store = m3_sql.SqlStore(base / "canonical.duckdb", overlay / "api_enrichment.duckdb")
    try:
        assert [m3_sql.answer_question(store, q)["value"] for q in questions] == [
            q["gold"]["value"] for q in load_gold()
        ]
    finally:
        store.close()

    with pytest.raises(AssertionError, match="use --resume"):
        dev_supplement.generate(opts)
    opts.resume = True
    assert dev_supplement.generate(opts) == report
    checkpoint = phase05.read(dest / "checkpoint.json")
    write_json(dest / "checkpoint.json", {**checkpoint, "state": "GENERATING"})
    resumed = dev_supplement.generate(opts)
    assert resumed["candidates_sha256"] == report["candidates_sha256"]
    write_json(dest / "candidates.json", [])
    with pytest.raises(AssertionError, match="Supplement candidates changed"):
        dev_supplement.generate(opts)
