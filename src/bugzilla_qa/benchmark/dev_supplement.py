"""Build a separate F1 practice set from the original development population."""
import argparse
import json
import sys
from pathlib import Path

import duckdb

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data.normalize import file_hash, write_json

DEFAULT_RUN = Path("outputs/benchmark/phase05/run-65c5be3381f66811")
ROWS_SQL = """
    SELECT b.bug_id, b.source_record_id, b.product, b.component,
           b.snapshot_status, b.snapshot_resolution, b.source_dataset,
           b.source_row_key, b.source_url, b.content_hash, b.raw_field_mapping,
           strftime(b.event_time_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS event_time_utc,
           strftime(b.observed_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS observed_at_utc,
           strftime(b.ingested_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS ingested_at_utc,
           s.normalized_fields
    FROM bugs b JOIN sample_membership m USING(bug_id)
    JOIN source_records s USING(source_record_id)
    WHERE NOT EXISTS (SELECT 1 FROM source_records v WHERE v.bug_id = b.bug_id
        AND v.source_dataset = 'metadata' AND v.disposition = 'CONFLICT_VARIANT')
"""


def build(db_path, original, pins, seed, limit):
    development = [q for q in original if q["split"] == "dev"]
    existing = [q for q in development if q["family"] == "F1"]
    assert existing, "The original run must contain F1 development questions"
    scope = existing[0]["scope"]
    assert all(q["scope"] == scope for q in existing), "Original F1 development scopes differ"
    assert scope["partition"] == "dev" and scope["snapshot_id"] == pins["base_identity"]
    used = {bug for q in existing for bug in q["bug_ids"]}
    with duckdb.connect(str(db_path), read_only=True) as db:
        db.execute("SET TimeZone='UTC'")
        db.execute("SET memory_limit='512MB'")
        rows = p5.dictionaries(db, ROWS_SQL)
    ids = {split: sorted(r["bug_id"] for r in rows if p5.partition(seed, r["bug_id"]) == split)
           for split in ("dev", "test")}
    assert p5.digest(ids) == scope["population_manifest_sha256"], "Source population changed"
    eligible = set(ids["dev"]) - used
    items = []
    for row in sorted(rows, key=lambda r: p5.order(seed, r["bug_id"])):
        bug = row["bug_id"]
        if bug not in eligible:
            continue
        fields = [field for field in p5.FIELDS[1:] if row[field] not in (None, "", "UNKNOWN")]
        if not fields:
            continue
        field = fields[len(items) % len(fields)]
        value = row[field]
        source = json.loads(row["normalized_fields"])
        assert p5.digest(source) == row["content_hash"] and source[field] == value, "Source/field mismatch"
        evidence = p5.evidence(row, "source_record_id", {field: value})
        item = p5.make_item("F1", "dev_supplement_" + field,
                            f"Report the recorded {field} for Firefox bug {bug}.",
                            {"type": "string", "value": value}, [bug], [evidence], scope, seed,
                            "canonical field equals retained normalized source field")
        item.update(split="dev", human_review_state="PRACTICE_ONLY; SOURCE_CHECKED_AUTOMATICALLY")
        item["question"] = p5.render(item, "dev")
        item["qid"] = "dev_supp_" + p5.digest([item["question"], scope, seed])[:20]
        p5.check_item(item)
        items.append(item)
        if len(items) == limit:
            break
    assert {q["qid"] for q in items}.isdisjoint(q["qid"] for q in development), "Duplicate development QID"
    wording = {q["question"].casefold() for q in development}
    assert wording.isdisjoint(q["question"].casefold() for q in items), "Duplicate development wording"
    return items


def generate(args):
    root = args.root.resolve()
    run = (root / args.run).resolve()
    pins = p5.read(root / args.sources)
    base, _ = p5.paths(root, pins)
    db_path = base / "canonical.duckdb"
    folder = (root / "outputs/benchmark/phase05").resolve()
    dest = folder / f"dev-supplement-{args.limit}"
    assert not dest.is_symlink() and dest != run, "Choose an unused supplement output"
    candidates = run / "candidates.json"
    required = [candidates, run / "manifest.json", db_path, base / "manifest.json"]
    missing = [str(path) for path in required if not path.is_file()]
    report = {"state": "BLOCKED" if missing else "DRY_RUN", "missing_inputs": missing,
              "started_at_utc": p5.stamp(), "network_requests": 0, "limit": args.limit, "output": str(dest)}
    if missing or args.dry_run:
        return {**report, "finished_at_utc": p5.stamp()}

    manifest = p5.read(run / "manifest.json")
    base_manifest = p5.read(base / "manifest.json")
    opts = manifest["identity"]["options"]
    assert manifest["state"] == "CANDIDATES_READY" and opts["limit"] is None, "Use the full original generation"
    assert manifest["identity"]["source_pins"] == pins, "Source pins differ from the original run"
    assert base_manifest["state"] == "COMPLETE" and base_manifest["identity_hash"] == pins["base_identity"]
    assert db_path.stat().st_size == base_manifest["artifacts"]["canonical.duckdb"]["bytes"], "Canonical DB size changed"
    original_hash = file_hash(candidates)
    assert original_hash == manifest["artifacts"]["candidates.json"], "Original candidates changed"
    identity = {"parent_candidates_sha256": original_hash, "source_pins_sha256": p5.digest(pins),
                "code_sha256": file_hash(Path(__file__)), "seed": opts["seed"], "limit": args.limit}

    checkpoint = dest / "checkpoint.json"
    payload = dest / "candidates.json"
    summary = dest / "summary.json"
    if dest.exists():
        assert args.resume, "Output exists; use --resume to validate or finish the supplement"
        if checkpoint.exists():
            previous = p5.read(checkpoint)
            assert previous["identity"] == identity, "Supplement checkpoint inputs changed"
            if previous["state"] == "COMPLETE":
                assert file_hash(payload) == previous["candidates_sha256"], "Supplement candidates changed"
                assert file_hash(summary) == previous["summary_sha256"], "Supplement summary changed"
                return p5.read(summary)
        else:
            assert not any(dest.iterdir()), "Existing output has no supplement checkpoint"
    else:
        dest.mkdir(parents=True)
    write_json(checkpoint, {"state": "GENERATING", "identity": identity, "started_at_utc": report["started_at_utc"]})
    items = build(db_path, p5.read(candidates), pins, opts["seed"], args.limit)
    write_json(payload, items)
    report.update(state="PRACTICE_ONLY", split="dev", family="F1", questions=len(items),
                  candidates_sha256=file_hash(payload), finished_at_utc=p5.stamp(), **identity)
    write_json(summary, report)
    write_json(checkpoint, {"state": "COMPLETE", "identity": identity,
                            "candidates_sha256": report["candidates_sha256"], "summary_sha256": file_hash(summary)})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--sources", type=Path, default=Path("configs/phase05_sources.json"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    report = generate(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(report["state"] == "BLOCKED")


if __name__ == "__main__":
    sys.exit(main())
