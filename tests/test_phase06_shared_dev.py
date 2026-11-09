"""Check development prompts and saved review decisions with the shared sample."""
import csv
import json
import shutil
from unittest.mock import patch

import duckdb
import pytest

from test_phase05 import fixture
from bugzilla_qa.benchmark import dev_supplement
from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data.normalize import file_hash, write_json
from bugzilla_qa.evaluation import phase06, shared_dev
from bugzilla_qa.methods.contract import MODEL_KEYS
from bugzilla_qa.methods.m3_sql import POPULATION_SQL, SqlStore


def test_shared_sample_smoke(tmp_path, capsys):
    pins = fixture(tmp_path)
    write_json(tmp_path / "pins.json", pins)
    base, overlay = p5.paths(tmp_path, pins)
    sample = tmp_path / "sample"
    sample.mkdir()
    shutil.copyfile(base / "canonical.duckdb", sample / "sample.duckdb")
    shutil.copyfile(overlay / "api_enrichment.duckdb", sample / "api_enrichment.duckdb")
    items, _ = p5.complete_candidates(tmp_path, pins, per_family=5, f5_target=5)
    original = next(q for q in items if q["family"] == "F1" and q["split"] == "dev")
    with duckdb.connect(str(sample / "sample.duckdb")) as db:
        population_ids = [bug for bug, in db.execute(POPULATION_SQL).fetchall()]
        test_bug = next(bug for bug in population_ids if p5.partition(317, bug) == "test")
        unused = [bug for bug in population_ids if p5.partition(317, bug) == "dev" and bug not in original["bug_ids"]]
        linked_bug = min(unused, key=lambda bug: p5.order(317, bug))
        db.execute("INSERT INTO bug_links (link_key, bug_id, target_bug_id, relation) VALUES (?, ?, ?, ?)",
                   ["cross-partition-link", test_bug, linked_bug, "depends_on"])
    files = {name: {"bytes": (sample / name).stat().st_size, "sha256": file_hash(sample / name)}
             for name in shared_dev.SAMPLE_FILES[1:]}
    write_json(sample / "manifest.json", {
        "state": "COMPLETE", "prefix_only": False, "sample_seed": 317,
        "source_base_identity": pins["base_identity"], "counts": {"sample_membership": 20},
        "identity": {"history_summary_sha256": pins["phase04_summary_sha256"], "base_manifest_sha256": "base-manifest"},
        "files": files,
    })
    store = SqlStore(sample / "sample.duckdb", sample / "api_enrichment.duckdb")
    population = store.population_sha256
    store.close()
    review = tmp_path / "review"
    review.mkdir()
    rationale = next(q for q in items if q["family"] == "F5" and q["split"] == "dev")
    test = next(q for q in items if q["split"] == "test")
    rows = [{"qid": q["qid"], "split": q["split"], "family": q["family"], "question": q["question"],
             "record_kind": "BENCHMARK_CANDIDATE", "required": "NO",
             "decision": "PENDING", "typed_candidate_gold_json": json.dumps(q["gold"]),
             "source_evidence_compact_json": json.dumps([{"evidence_id": ev["id"]} for ev in q["evidence"]]),
             "reviewer": "", "source_checked": "", "reviewed_at_utc": "",
             "rationale_present": "", "corrected_gold_json": ""}
            for q in (original, rationale, test)]
    rows[1]["required"] = "YES"
    immutable = list(rows[0])[:6] + ["typed_candidate_gold_json", "source_evidence_compact_json"]
    backup = review / "signoff_queue.before_review.csv"
    current = review / "signoff_queue.csv"

    def write_rows(path):
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write_rows(backup)
    corrected = {"type": "unanswerable", "value": p5.UNKNOWN,
                 "missing_evidence": p5.F5_MISSING_RATIONALE,
                 "evidence_ids": [ev["id"] for ev in rationale["evidence"]]}
    rows[1].update(decision="CORRECT", reviewer="fixture", source_checked="YES",
                   reviewed_at_utc="2026-11-01T00:00:00Z", rationale_present="NO",
                   corrected_gold_json=json.dumps(corrected))
    rows[2]["typed_candidate_gold_json"] = "deliberately invalid held-out gold"
    write_rows(current)
    write_json(review / "REVIEW_BUNDLE.json", {
        "seed": 317, "immutable_columns": immutable, "packaged_file_sha256": {backup.name: file_hash(backup)},
        "source_hashes": {"phase04_summary_sha256": pins["phase04_summary_sha256"],
                          "phase03b_manifest_sha256": "base-manifest",
                          "population_manifest_declared_sha256": population},
    })
    options = ["--root", str(tmp_path), "--sources", "pins.json", "--sample-bundle", "sample",
               "--review-bundle", "review", "--limit", "1"]
    assert phase06.main(["m3", *options, "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert (preview["state"], preview["questions"], preview["model_calls"]) == ("DRY_RUN", 2, 0)
    assert phase06.main(["m3", *options]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["benchmark_state"], report["state"], report["table"][0]["correct"]) == (
        shared_dev.STATE, "PARTIAL", 1,
    )
    questions, gold, _ = shared_dev.load_review(review, pins, 317)
    assert all(set(q) == {"qid", "question", "scope"} for q in questions)
    assert gold[1]["gold"] == corrected
    response = {"done": True, "model": "fixture", "message": {"content": json.dumps({
        "answer": "Fixture answer", "abstained": False, "value": original["gold"]["value"], "evidence": [],
    })}}
    with patch("bugzilla_qa.methods.local_model._post", return_value=response) as post:
        assert phase06.main(["m0", "--root", str(tmp_path), "--sources", "pins.json",
                             "--review-bundle", "review", "--model", "fixture", "--cpu", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["model_calls"], report["table"][0]["correct"]) == (1, 1)
    assert report["model_settings"]["cpu"] is True
    request = post.call_args.args[1]
    assert request["options"]["num_gpu"] == 0
    assert set(request["format"]["required"]) == MODEL_KEYS
    payload = json.loads(request["messages"][1]["content"])
    assert set(payload) == {"question", "scope"}
    assert payload["question"] == original["question"]

    before = {file.name: file_hash(file) for file in review.iterdir()}
    assert dev_supplement.main(["--root", str(tmp_path), "--sources", "pins.json",
                                "--review-bundle", "review", "--sample-bundle", "sample", "--limit", "1"]) == 0
    practice = json.loads(capsys.readouterr().out)
    assert (practice["state"], practice["questions"]) == ("PRACTICE_ONLY", 1)
    practice_dir = tmp_path / "outputs/benchmark/phase05/dev-supplement-shared-1"
    item, = p5.read(practice_dir / "candidates.json")
    assert item["bug_ids"][0] not in [*original["bug_ids"], linked_bug]
    assert p5.partition(317, item["bug_ids"][0]) == "dev"
    assert {file.name: file_hash(file) for file in review.iterdir()} == before
    practice_opts = [*options, "--run", str(practice_dir), "--unfrozen-dev-smoke"]
    assert phase06.main(["m3", *practice_opts]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["benchmark_state"], report["table"][0]["correct"]) == (shared_dev.PRACTICE_STATE, 1)
    write_json(practice_dir / "candidates.json", [])
    with pytest.raises(AssertionError, match="Practice candidates changed"):
        phase06.main(["m3", *practice_opts, "--dry-run"])
    rows[0]["question"] += " altered"
    write_rows(current)
    with pytest.raises(AssertionError, match="Development question changed"):
        phase06.main(["m3", *options, "--dry-run"])
