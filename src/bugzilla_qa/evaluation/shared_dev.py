"""Check the shared sample and review files before a development smoke test."""
import csv
import json
from collections import defaultdict
from itertools import zip_longest

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data.normalize import file_hash

STATE = "SHARED_DEV_SMOKE; not reportable"
PRACTICE_STATE = "SHARED_PRACTICE_SMOKE; not reportable"
PRACTICE_FILES = ("checkpoint.json", "candidates.json")
DEFAULT_REVIEW = "outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811"
REVIEW_FILES = ("REVIEW_BUNDLE.json", "signoff_queue.csv", "signoff_queue.before_review.csv")
SAMPLE_FILES = ("manifest.json", "sample.duckdb", "api_enrichment.duckdb")


def _development_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle)
                if r["split"] == "dev" and r["record_kind"] == "BENCHMARK_CANDIDATE"]
    assert len({r["qid"] for r in rows}) == len(rows), "Duplicate development QID"
    return {r["qid"]: r for r in rows}


def development_rows(folder, pins, seed):
    bundle, current, backup = (folder / name for name in REVIEW_FILES)
    metadata = p5.read(bundle)
    sources = metadata["source_hashes"]
    assert metadata["seed"] == seed, "Review seed mismatch"
    assert sources["phase04_summary_sha256"] == pins["phase04_summary_sha256"], "Review overlay pin mismatch"
    assert file_hash(backup) == metadata["packaged_file_sha256"][backup.name], "Review backup changed"
    rows, baseline = _development_rows(current), _development_rows(backup)
    assert rows and rows.keys() == baseline.keys(), "Development review QIDs changed"
    for qid, row in rows.items():
        assert all(row[k] == baseline[qid][k] for k in metadata["immutable_columns"]), "Development question changed"
    return rows, sources


def development_scope(pins, sources):
    return {"partition": "dev", "snapshot_id": pins["base_identity"], "snapshot_as_of_utc": None,
             "sample_seed": pins["sample_seed"], "product": "Firefox",
             "api_pilot_id": pins["phase04_run"].rstrip("/").split("/")[-1],
             "population_manifest_sha256": sources["population_manifest_declared_sha256"]}


def load_review(folder, pins, seed):
    rows, sources = development_rows(folder, pins, seed)
    scope = development_scope(pins, sources)
    groups = defaultdict(list)
    for qid, row in rows.items():
        decision = row["decision"]
        if decision == "REJECT":
            continue
        q = {"qid": qid, "question": row["question"], "scope": scope}
        item = {**q, "family": row["family"], "gold": json.loads(row["typed_candidate_gold_json"]),
                "evidence": [{"id": ev["evidence_id"]} for ev in json.loads(row["source_evidence_compact_json"])]}
        if decision == "PENDING":
            assert row["required"] == "NO" and item["family"] != "F5", "Required development review is pending"
        else:
            item["gold"] = p5.approved_gold(item, row)
        groups[item["family"]].append((q, item))
    assert groups, "Review bundle has no retained development questions"
    # Take one question from each family before taking the next from any family.
    ordered = [pair for batch in zip_longest(*(groups[f] for f in sorted(groups))) for pair in batch if pair]
    questions, gold = zip(*ordered)
    return list(questions), list(gold), sources


def verify_sample(folder, pins, sources):
    manifest = p5.read(folder / "manifest.json")
    assert manifest["state"] == "COMPLETE" and manifest["prefix_only"] is False, "Incomplete sample export"
    assert manifest["sample_seed"] == pins["sample_seed"], "Sample seed mismatch"
    assert manifest["source_base_identity"] == pins["base_identity"], "Sample base pin mismatch"
    identity = manifest["identity"]
    assert identity["base_manifest_sha256"] == sources["phase03b_manifest_sha256"], "Review base manifest differs"
    assert identity["history_summary_sha256"] == pins["phase04_summary_sha256"], "Sample overlay pin mismatch"
    assert manifest["counts"]["sample_membership"] == pins["base_counts"]["sample_membership"], "Sample size differs"
    hashes = {}
    for name in SAMPLE_FILES[1:]:
        path = folder / name
        expected = manifest["files"][name]
        assert path.stat().st_size == expected["bytes"], "Sample file size changed: " + name
        hashes[name] = file_hash(path)
        assert hashes[name] == expected["sha256"], "Sample file changed: " + name
    return hashes


def load_practice(folder, pins, seed, population, sample_hashes):
    checkpoint, candidates = (folder / name for name in PRACTICE_FILES)
    saved = p5.read(checkpoint)
    identity = saved["identity"]
    assert saved["state"] == "COMPLETE", "Practice supplement is unfinished"
    assert identity["sample_sha256"] == sample_hashes, "Practice supplement belongs to another sample"
    assert identity["source_pins_sha256"] == p5.digest(pins) and identity["seed"] == seed, "Practice source mismatch"
    assert file_hash(candidates) == saved["candidates_sha256"], "Practice candidates changed"
    gold = p5.read(candidates)
    assert gold and len({q["qid"] for q in gold}) == len(gold), "Empty or duplicate practice questions"
    assert all(q["qid"].startswith("dev_supp_") and q["family"] == "F1" and q["split"] == "dev"
               and q["scope"]["partition"] == "dev" and q["scope"]["population_manifest_sha256"] == population
               and len(q["bug_ids"]) == 1 and p5.partition(seed, q["bug_ids"][0]) == "dev"
               for q in gold), "Invalid development practice item"
    return [{k: q[k] for k in ("qid", "question", "scope")} for q in gold], gold
