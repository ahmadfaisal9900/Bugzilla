"""Phase 5: deterministic, provenance-bound candidates; human-gated freeze.

No network or model inference. Full jobs belong in the user's terminal.
"""
import argparse
import csv
import gzip
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from bugzilla_qa.data import phase04 as p4, normalize
from bugzilla_qa.data.normalize import digest, file_hash, write_json

if not __debug__:
    raise RuntimeError("Phase 5 integrity checks require Python without -O")

VERSION = "phase05-v1"
FAMILIES = tuple("F" + str(i) for i in range(1, 7))
UNKNOWN = "cannot be established from the specified evidence"
FIELDS = ("product", "component", "snapshot_status", "snapshot_resolution")
USER_COLUMNS = ("decision", "reviewer", "reviewed_at_utc", "source_checked",
                "rationale_present", "corrected_gold_json", "corrected_question", "note",
                "issue_type_observed", "second_reviewer", "second_decision")
REASON = re.compile(r"[^.!?\n]*(?:because|due to|blocked by|waiting for|delayed by)[^.!?\n]*[.!?]?", re.I)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def safe(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", str(text))
    return re.sub(r"(?<!\w)@[A-Za-z][\w.-]*", "[handle]", text)


def order(seed, value):
    return digest([seed, str(value)])


def partition(seed, bug):
    return "dev" if int(order(seed, bug)[:12], 16) % 5 == 0 else "test"


def dictionaries(db, sql, params=()):
    cur = db.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def dt(value):
    parsed = p4.parse_utc(value.isoformat() if isinstance(value, datetime) else value)
    if parsed is None:
        raise ValueError("Missing or invalid UTC timestamp")
    return parsed


def version_hash():
    return digest([file_hash(Path(__file__)), file_hash(Path(p4.__file__)), file_hash(Path(normalize.__file__))])


def paths(root, pins):
    return root / pins["base_run"], root / pins["phase04_run"]


def verify_inputs(root, pins, full_hash=False):
    """Small Phase 4 artifact/cache audit; large base hash only at terminal freeze."""
    base, overlay = paths(root, pins)
    bm, sm = read(base / "manifest.json"), read(base / "sample_manifest.json")
    summary, cp = read(overlay / "summary.json"), read(overlay / "checkpoint.json")
    assert bm["state"] == "COMPLETE" and bm["identity_hash"] == pins["base_identity"]
    assert bm["identity"]["options"]["limit"] is None, "Limited source import is ineligible"
    assert sm["identity_hash"] == bm["identity_hash"] and sm["seed"] == pins["sample_seed"]
    assert summary["state"] == cp["state"] == "COMPLETE", "Phase 4 must be complete"
    assert summary["baseline_run_id"] == base.name
    assert summary["candidate_manifest_sha256"] == cp["candidate_manifest_sha256"] == pins["candidate_identity"]
    assert file_hash(overlay / "summary.json") == pins["phase04_summary_sha256"]
    assert summary["candidate_count"] == summary["candidate_count_requested"] == len(cp["candidate_results"])
    for name, meta in summary["artifacts"].items():
        path = overlay / meta["path"]
        assert path.parent == overlay and path.stat().st_size == meta["size_bytes"]
        assert file_hash(path) == meta["sha256"], "Changed Phase 4 artifact: " + name
    artifact = bm["artifacts"]["canonical.duckdb"]
    dbpath = base / "canonical.duckdb"
    assert dbpath.stat().st_size == artifact["bytes"]
    if full_hash:
        assert file_hash(dbpath) == artifact["sha256"], "Changed canonical database"
    db = duckdb.connect(str(dbpath), read_only=True)
    db.execute("SET TimeZone='UTC'")
    db.execute("SET memory_limit='512MB'")
    try:
        counts = {t: db.execute("SELECT count(*) FROM " + t).fetchone()[0]
                  for t in ("bugs", "comments", "sample_membership", "field_changes")}
        for t, expected in pins["base_counts"].items():
            assert counts[t] == expected, "Unexpected canonical count: " + t
        source_values = {r["bug_id"]: r for r in dictionaries(db, "SELECT bug_id, product, component, snapshot_status, snapshot_resolution, opened_at_utc::VARCHAR AS opened_at_utc FROM bugs WHERE bug_id IN (SELECT unnest(?))", [[str(x) for x in cp["candidate_results"]]])}
        creations = dict(db.execute("SELECT bug_id, opened_at_utc::VARCHAR FROM bugs WHERE bug_id IN (SELECT unnest(?))",
                                   [[str(x) for x in cp["candidate_results"]]]).fetchall())
        metrics, parsed_count = {}, 0
        for meta in summary["api_response_manifest"]:
            path = Path(meta["cache_path"])
            if not path.is_absolute():
                path = root / path
            assert path.resolve().is_relative_to((root / "outputs/phase04/api_cache").resolve())
            with gzip.open(path, "rt", encoding="utf-8") as f:
                env = json.load(f)
            assert hashlib.sha256(env["body_utf8"].encode()).hexdigest() == env["body_sha256"] == meta["raw_sha256"]
            assert env["requested_bug_id"] == meta["bug_id"]
            assert env["url"] == meta["url"]
            assert meta["url"].split("?", 1)[0] == f"{p4.BASE_URL}/bug/{meta['bug_id']}" + ("" if meta["endpoint"] == "bug" else "/" + meta["endpoint"])
            assert env["fetched_at_utc"] == meta["fetched_at_utc"] and env["status_code"] == meta["status_code"]
            if meta["endpoint"] == "bug" and meta["status_code"] == 200:
                current, error = p4.parse_current_bug(json.loads(env["body_utf8"]), meta["bug_id"], meta["fetched_at_utc"])
                saved = cp["candidate_results"][str(meta["bug_id"])]
                assert error is None and all(saved["current_metadata"].get(k) == v for k,v in current.items())
                assert saved["current_metadata"]["fetched_at_utc"] == meta["fetched_at_utc"]
                assert p4.consistency_differences(source_values[str(meta["bug_id"])], current) == saved["source_consistency_differences"]
            if meta["endpoint"] != "history" or meta["status_code"] != 200:
                continue
            bug = str(meta["bug_id"])
            parsed = p4.parse_api_history(json.loads(env["body_utf8"]), int(bug),
                         created_at=str(creations[bug]), observed_at=meta["fetched_at_utc"])
            saved = cp["candidate_results"][bug]
            assert parsed["changes"] == saved["changes"], "Cached history differs from parsed checkpoint"
            assert {k: v for k, v in parsed.items() if k != "changes"} == saved["history"]
            metric = p4.classify_first_fixed(parsed, str(creations[bug]))
            assert metric == saved["fix_metric"]
            metrics[bug] = metric
            parsed_count += parsed["state"] == "PARSED"
        overlay_db = duckdb.connect(str(overlay / "api_enrichment.duckdb"), read_only=True)
        try:
            stored = dictionaries(overlay_db, "SELECT * FROM field_changes")
        finally:
            overlay_db.close()
        assert len(stored) == summary["field_change_rows"]
        assert Counter((str(e["bug_id"]), e["content_sha256"]) for e in stored) == Counter((bug, p4.digest(e)) for bug,r in cp["candidate_results"].items() for e in r["changes"])
        assert all(dt(e["event_time_utc"]) <= dt(e["observed_at_utc"]) <= dt(e["ingested_at_utc"]) for e in stored)
        assert parsed_count == summary["parseable_histories"]
        assert sum(m["state"] == "VALID_EVENT_TIME" for m in metrics.values()) == summary["valid_f2_cases"]
    finally:
        db.close()
    # The source manifests and compact checkpoint are fixed as well as the DB artifacts.
    files = [base / n for n in ("manifest.json", "sample_manifest.json", "qc_report.json")]
    files += [overlay / n for n in ("summary.json", "checkpoint.json")]
    return {"state": "VERIFIED_PILOT_INPUT", "base_counts": counts,
            "histories": summary["successful_histories"], "valid_f2": summary["valid_f2_cases"],
            "conflict_free_unambiguous_first_fixed": sum(r["fix_metric"]["state"] == "VALID_EVENT_TIME" and not r.get("source_consistency_differences") and not r["history"].get("same_time_groups") for r in cp["candidate_results"].values()),
            "field_changes": summary["field_change_rows"], "snapshot_as_of_utc": None,
            "small_file_hashes": {str(p.relative_to(root)): file_hash(p) for p in files},
            "base_database_sha256": artifact["sha256"], "base_hash_recomputed": full_hash,
            "source_pins_sha256": digest(pins)}


def evidence(row, key, fields=None):
    return {"id": str(row[key]), "bug_id": str(row["bug_id"]),
            "source_dataset": row["source_dataset"], "source_row_key": row["source_row_key"],
            "source_url": row["source_url"],
            "content_hash": row.get("content_hash", row.get("content_sha256")),
            "raw_field_mapping": json.loads(row["raw_field_mapping"]) if isinstance(row.get("raw_field_mapping"), str) else row.get("raw_field_mapping"),
            "field_hash": digest(fields or {}), "fields": fields or {},
            "event_time_utc": str(row.get("event_time_utc")) if row.get("event_time_utc") else None,
            "observed_at_utc": str(row["observed_at_utc"]),
            "ingested_at_utc": str(row["ingested_at_utc"])}


def check_item(item):
    assert item["family"] in FAMILIES and item["evidence"]
    assert not any(x in item["question"].lower() for x in ("typed_gold", "template_id", "select count(", "gold answer:"))
    assert item["scope"]["snapshot_as_of_utc"] is None, "Archive snapshot date is UNKNOWN"
    for e in item["evidence"]:
        assert all(e.get(k) for k in ("id", "source_dataset", "source_row_key", "source_url", "content_hash"))
        assert e["field_hash"] == digest(e["fields"])
        observed, ingested = dt(e["observed_at_utc"]), dt(e["ingested_at_utc"])
        assert observed <= ingested, "Observation after ingestion"
        if e.get("event_time_utc"):
            assert dt(e["event_time_utc"]) <= observed, "Future event leakage"
        if item.get("as_of"):
            assert observed <= dt(item["as_of"]) and ingested <= dt(item["as_of"])
            assert not e.get("event_time_utc") or dt(e["event_time_utc"]) <= dt(item["as_of"])
    assert "@" not in json.dumps(item.get("gold")), "Identity in gold"
    assert not re.search(r"(?i)(gold\s*(?:answer|=|:)|answer\s*(?:is|=|:))", item["question"]), "Answer leakage in wording"
    return True


def make_item(family, template, question, gold, bug_ids, ev, scope, seed, validator, sql=None, coverage=None):
    item = {"family": family, "template_id": VERSION + ":" + template,
            "question": question, "gold": gold, "answerability": "ANSWERABLE",
            "bug_ids": sorted(set(map(str, bug_ids))), "scope": scope, "as_of": None,
            "evidence": ev, "seed": seed, "version": VERSION, "validator": validator,
            "sql": sql, "source_coverage": {"evidence_records": len(ev), "population": scope["corpus"], "snapshot_as_of": "UNKNOWN", **(coverage or {})}, "human_review_state": "PENDING_POLICY_REVIEW"}
    item["qid"] = "q_" + digest([family, template, question, scope, seed])[:20]
    check_item(item)
    return item


def build_candidates(root, pins, seed=317, per_family=30, f5_target=30, limit=None):
    """Read only canonical sample rows; source CSVs are never opened."""
    base, overlay = paths(root, pins)
    cp = read(overlay / "checkpoint.json")
    api = duckdb.connect(str(overlay / "api_enrichment.duckdb"), read_only=True)
    api_events = dictionaries(api, "SELECT * FROM field_changes")
    event_index = {(str(e["bug_id"]), e["event_index"], e["change_index"]): e for e in api_events}
    db = duckdb.connect(str(base / "canonical.duckdb"), read_only=True)
    db.execute("SET TimeZone='UTC'")
    db.execute("SET memory_limit='512MB'")
    try:
        rows = dictionaries(db, """SELECT b.* REPLACE(b.opened_at_utc::VARCHAR AS opened_at_utc,
           b.snapshot_as_of_utc::VARCHAR AS snapshot_as_of_utc, b.last_change_at_utc::VARCHAR AS last_change_at_utc,
           b.event_time_utc::VARCHAR AS event_time_utc, b.observed_at_utc::VARCHAR AS observed_at_utc,
           b.ingested_at_utc::VARCHAR AS ingested_at_utc), s.normalized_fields FROM bugs b
           JOIN sample_membership m USING(bug_id) JOIN source_records s USING(source_record_id)
           WHERE NOT EXISTS(SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
                AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT') ORDER BY b.bug_id""")
        bugs = {r["bug_id"]: r for r in rows}
        for r in rows:
            payload = json.loads(r["normalized_fields"])
            assert digest(payload) == r["content_hash"]
            assert all(str(payload[k]) == str(r[k]) for k in FIELDS), "Source/field mismatch"
        partition_ids = {sp: sorted(b for b in bugs if partition(seed, b) == sp) for sp in ("dev", "test")}
        scope_base = {"population_manifest_sha256": digest(partition_ids),"corpus": "broad BugsRepo metadata; frozen Firefox sample (not curated 119585 or CTQRS)",
                      "snapshot_id": pins["base_identity"], "snapshot_as_of_utc": None,
                      "api_pilot_id": overlay.name, "experiment": "controlled evidence addition/refresh",
                      "product": "Firefox", "sample_seed": pins["sample_seed"],
                      "issue_type": "tracker issues; enhancement type not retained, UNKNOWN"}
        items = []
        used = defaultdict(set)
        limits = {f: min(per_family, limit) if limit is not None else per_family for f in FAMILIES}
        limits["F5"] = min(limits["F5"], f5_target)
        quotas = {f: {"dev": int(math.ceil(n / 5)), "test": n - int(math.ceil(n / 5))} for f, n in limits.items()}
        counts = Counter()

        def add(f, template, text, gold, parent, ev, validator, sql=None, coverage=None, others=()):
            split = partition(seed, parent)
            ids = [str(parent)] + list(map(str, others))
            if any(partition(seed, b) != split for b in ids) or parent in used[f] or counts[f, split] >= quotas[f][split]:
                return
            scope = {**scope_base, "partition": split, "partition_rule": "SHA256(seed,bug_id) modulo 5; dev=0"}
            coverage = {"parent_snapshot_status": bugs[str(parent)]["snapshot_status"], "parent_snapshot_resolution": bugs[str(parent)]["snapshot_resolution"], **(coverage or {})}
            item = make_item(f, template, text, gold, ids, ev, scope, seed, validator, sql, coverage)
            item["split"] = split
            items.append(item); used[f].add(parent); counts[f, split] += 1

        unknown_f2 = Counter()
        for bug in sorted(bugs, key=lambda x: order(seed, x)):
            r = bugs[bug]; src = json.loads(r["normalized_fields"])
            field = FIELDS[1:][int(order(seed, bug)[-2:], 16) % len(FIELDS[1:])]
            if r[field] is not None and r[field] != "UNKNOWN":
                ev = evidence(r, "source_record_id", {field: r[field]})
                add("F1", "snapshot_" + field,
                    f"In the frozen broad-metadata archive record for Firefox bug {bug} (snapshot date UNKNOWN), what is the recorded {field.replace('snapshot_', '')}?",
                    {"type": "string", "value": r[field]}, bug, [ev], "canonical field equals retained normalized source field")
            result = cp["candidate_results"].get(bug)
            if not result or result["history"].get("state") != "PARSED" or result.get("source_consistency_differences") or result["history"].get("same_time_groups"):
                continue
            evs = []
            changes = result["changes"]
            if not r["opened_at_utc"] or any(dt(x["event_time_utc"]) < dt(r["opened_at_utc"]) for x in changes):
                continue
            # Prefer first-FIXED durations; otherwise count explicit REOPENED transitions.
            fixed = [x for x in changes if x["field_name"] == "resolution" and x["new_value"] == p4.canonical("FIXED") and x["old_value"] != p4.canonical("FIXED")]
            reopen = [x for x in changes if x["field_name"] == "status" and x["new_value"] == p4.canonical("REOPENED") and x["old_value"] != p4.canonical("REOPENED")]
            metric = result["fix_metric"]
            if metric["state"] == "VALID_EVENT_TIME" and fixed:
                first = min(dt(x["event_time_utc"]) for x in fixed)
                seconds = (first - dt(r["opened_at_utc"])).total_seconds()
                assert seconds >= 0 and abs(seconds / 86400 - metric["elapsed_calendar_days"]) < 1e-8
                template, question = "first_fixed", f"Using the verified dated API history and filing time for Firefox bug {bug}, how many elapsed calendar hours passed before its FIRST explicit FIXED transition (not engineer work hours)?"
                gold = {"type": "calendar_duration", "seconds": seconds, "hours": seconds / 3600, "days": seconds / 86400,
                        "first_fixed_at_utc": first.isoformat(), "tolerance_seconds": 1}
                sql_first = api.execute("SELECT min(event_time_utc) FROM field_changes WHERE bug_id=? AND field_name='resolution' AND new_value=? AND old_value!=?", [int(bug), p4.canonical("FIXED"), p4.canonical("FIXED")]).fetchone()[0]
                assert dt(sql_first) == first
                selected = fixed
            elif reopen:
                template, question = "reopen_count", f"How many explicit transitions into REOPENED are recorded in the verified API history of Firefox bug {bug}? Count events, not snapshot status."
                gold = {"type": "integer", "value": len(reopen)}
                assert len(reopen) <= result["history"]["reopened_count"]
                assert api.execute("SELECT count(*) FROM field_changes WHERE bug_id=? AND field_name='status' AND new_value=? AND old_value!=?", [int(bug), p4.canonical("REOPENED"), p4.canonical("REOPENED")]).fetchone()[0] == len(reopen)
                selected = reopen
            else:
                sp = partition(seed, bug)
                if unknown_f2[sp] >= (1 if sp == "dev" else 5):
                    continue
                unknown_f2[sp] += 1
                template, question = "unknown_first_fixed", f"Can the specified archive and verified API history establish elapsed calendar time to the FIRST FIXED transition for Firefox bug {bug}?"
                gold = {"type": "unknown", "value": UNKNOWN, "reason": "No qualifying verified FIXED transition"}
                selected = []
            evs.append(evidence(r, "source_record_id", {"opened_at_utc": str(r["opened_at_utc"])}))
            for change in selected:
                stored = event_index[bug, change["event_index"], change["change_index"]]
                assert stored["content_sha256"] == p4.digest(change)
                evs.append(evidence(stored, "source_row_key", {k: stored[k] for k in ("field_name", "old_value", "new_value")}))
            # Checkpoint hash pins complete histories including the absence of a qualifying event.
            evs.append({"id": "history:" + bug, "bug_id": bug, "source_dataset": "bugzilla_rest_history",
              "source_row_key": "response:" + result["history_fetch"]["raw_sha256"], "source_url": f"{p4.BASE_URL}/bug/{bug}/history",
              "content_hash": result["history_fetch"]["raw_sha256"], "fields": {"transitions": selected, "history_state": result["history"]["state"]},
              "field_hash": digest({"transitions": selected, "history_state": result["history"]["state"]}),
              "event_time_utc": None, "observed_at_utc": result["history_fetch"]["fetched_at_utc"],
              "ingested_at_utc": cp["updated_at_utc"]})
            for x in changes:
                assert dt(x["event_time_utc"]) <= dt(result["history_fetch"]["fetched_at_utc"])
            add("F2", template, question, gold, bug, evs, "independent transition minimum/count and Python UTC subtraction equals Phase4 metric",
                coverage={"history": "VERIFIED_API", "snapshot_state_not_used": True})

        # F3 counts use disjoint, explicitly named sampled-ID partitions. SQL vs Python set.
        groups = defaultdict(set)
        for bug, r in bugs.items():
            sp = partition(seed, bug)
            year = dt(r["opened_at_utc"]).year if r["opened_at_utc"] else None
            for k, value in (("component", r["component"]), ("status", r["snapshot_status"]), ("creation_year", year)):
                if value is not None: groups[sp, k, str(value)].add(bug)
        for (sp, field, value), ids in sorted(groups.items(), key=lambda x: order(seed, x[0])):
            if counts["F3", sp] >= quotas["F3"][sp]: continue
            selected_rows = sorted(ids, key=lambda b: order(seed, b))
            scope = {**scope_base, "partition": sp, "partition_rule": "SHA256(seed,bug_id) modulo 5; dev=0",
                     "included_bug_ids_sha256": digest(sorted(bugs)), "filter": {field: value},
                     "denominator": sum(partition(seed, b) == sp for b in bugs),
                     "exclusions": "metadata conflict parents excluded"}
            column = {"component": "component", "status": "snapshot_status", "creation_year": "year(opened_at_utc)"}[field]
            sql = f"SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND {column} = ?"
            universe = sorted(b for b in bugs if partition(seed, b) == sp)
            count = db.execute(sql, [universe, int(value) if field == "creation_year" else value]).fetchone()[0]
            assert count == len(set(ids)), (sp, field, value, count, len(ids))
            if count == len(universe): continue  # denominator must not directly disclose gold
            ev = evidence(bugs[selected_rows[0]], "source_record_id", {"membership_sha256": digest(sorted(ids)), "filter": {field: value}})
            aggregate_receipt = {**ev, "id": "population:" + scope["population_manifest_sha256"],
                 "source_dataset": "canonical_manifest", "source_row_key": pins["base_identity"] + ":" + sp,
                 "content_hash": file_hash(base / "manifest.json"), "source_url": "https://zenodo.org/records/15004067",
                 "raw_field_mapping": {"partition": "population_manifest.json", "query": "audited canonical SQL"},
                 "fields": {"canonical_manifest": str((base / "manifest.json").relative_to(root)), "denominator_ids_sha256": digest(universe), "matched_ids_sha256": digest(sorted(ids))}}
            aggregate_receipt["field_hash"] = digest(aggregate_receipt["fields"])
            question = f"Within the frozen broad-metadata Firefox sample's {sp} partition (seed {seed}; {scope['denominator']} distinct eligible bugs), how many distinct bug IDs have recorded {field} {value}?" + (" Filter uses filing year, not a status-change year." if field == "creation_year" else " Snapshot date is UNKNOWN.")
            item = make_item("F3", "count_" + field, question, {"type": "integer", "value": count}, ids,
                             [ev, aggregate_receipt], scope, seed, "SQL COUNT(DISTINCT) equals independent Python set cardinality",
                             {"query": sql, "parameters": [universe, int(value) if field == "creation_year" else value]},
                             {"denominator": len(universe), "matching_bug_ids_sha256": digest(sorted(ids))})
            item["split"] = sp; items.append(item); counts["F3", sp] += 1

        link_rows = dictionaries(db, """SELECT l.* REPLACE(event_time_utc::VARCHAR AS event_time_utc,
          observed_at_utc::VARCHAR AS observed_at_utc, ingested_at_utc::VARCHAR AS ingested_at_utc) FROM bug_links l JOIN sample_membership m USING(bug_id)
                                        WHERE l.target_bug_id IS NOT NULL ORDER BY l.link_key""")
        links = defaultdict(list)
        for l in link_rows:
            if l["bug_id"] in bugs: links[l["bug_id"], l["relation"]].append(l)
        for (bug, relation), edges in sorted(links.items(), key=lambda x: order(seed, x[0])):
            targets = sorted({e["target_bug_id"] for e in edges}, key=int)
            actual = set(x[0] for x in db.execute("SELECT DISTINCT target_bug_id FROM bug_links WHERE bug_id=? AND relation=? AND target_bug_id IS NOT NULL", [bug, relation]).fetchall())
            assert actual == set(targets)
            source_targets = {str(e["target_bug_id"]) for e in json.loads(bugs[bug]["normalized_fields"])["recorded_links"] if e["relation"] == relation and e.get("target_bug_id")}
            if source_targets != actual: continue  # conflict variants must not contribute edges
            ev = [evidence(e, "link_key", {"relation": relation, "target_bug_id": e["target_bug_id"]}) for e in edges]
            add("F4", "recorded_targets", f"Which target bug IDs does the frozen archive explicitly record for relation {relation} from Firefox bug {bug}? List the complete recorded ID set; snapshot date and historical validity are UNKNOWN.",
                {"type": "id_set", "value": targets}, bug, ev, "SQL distinct target set equals Python set and retained metadata links",
                others=targets, coverage={"historical_validity": "UNKNOWN", "url_only_targets_excluded": True})

        # Only CSV comments from the FIXED-selected subpopulation. Stream, never load bodies en masse.
        sql = """SELECT c.* REPLACE(c.event_time_utc::VARCHAR AS event_time_utc,
          c.observed_at_utc::VARCHAR AS observed_at_utc, c.ingested_at_utc::VARCHAR AS ingested_at_utc), s.normalized_fields FROM comments c JOIN sample_membership m USING(bug_id)
           JOIN bugs b USING(bug_id) JOIN source_records s ON s.source_record_id=c.source_record_id WHERE c.private_flag=false AND c.text_availability='AVAILABLE'
           AND b.snapshot_resolution='FIXED' AND c.body IS NOT NULL
           AND regexp_matches(c.body, '(?i)because|due to|blocked by|waiting for|delayed by')
           AND NOT EXISTS (SELECT 1 FROM comments v WHERE v.bug_id=c.bug_id AND v.comment_id=c.comment_id
             AND v.event_time_utc=c.event_time_utc AND v.body IS DISTINCT FROM c.body)
           ORDER BY md5(c.comment_key || ?)"""
        cur = db.execute(sql, [str(seed)]); names = [x[0] for x in cur.description]
        while True:
            batch = cur.fetchmany(64)
            if not batch: break
            for values in batch:
                c = dict(zip(names, values)); bug = c["bug_id"]
                if bug not in bugs or bug in used["F5"]: continue
                src_comment = json.loads(c["normalized_fields"])
                assert digest(c["body"]) == src_comment["body_hash"]
                assert c["content_hash"] == digest({k: c[k] for k in ("comment_key", "bug_id", "comment_id", "body", "private_flag")})
                match = REASON.search(safe(c["body"]))
                if not match: continue
                snippet = match.group().strip()
                assert snippet in safe(c["body"]), "Excerpt must come from the sanitized evidence"
                if not 20 <= len(snippet) <= 600: continue
                ev = evidence(c, "comment_key", {"excerpt": snippet, "body_sha256": hashlib.sha256(c["body"].encode()).hexdigest(), "private_flag": False})
                text = f"For Firefox bug {bug}, what reason or constraint does cited comment {c['comment_id'] or c['comment_key'][:12]} explicitly state? Use only that comment; a rationale requires human source review. This is the FIXED-selected CSV-comment subgroup."
                add("F5", "explicit_rationale_candidate", text, {"type": "supported_explanation", "claims": [{"text": snippet, "evidence_id": ev["id"]}]}, bug, [ev], "public provenance/excerpt assertion only; ALL causal gold requires human source review",
                    coverage={"subpopulation": "FIXED_SELECTED_CSV_ONLY", "unresolved_generalization": False})
            if sum(counts["F5", s] for s in ("dev", "test")) >= limits["F5"]: break

        for bug in sorted(bugs, key=lambda b: order(seed + 1, b)):
            r = bugs[bug]
            ev = evidence(r, "source_record_id", {"available_fields": list(FIELDS), "engineer_hours_field": "ABSENT", "snapshot_as_of_utc": r["snapshot_as_of_utc"]})
            assert not any("work_hour" in x or "engineer_hour" in x for x in r)
            if db.execute("SELECT count(*) FROM comments WHERE bug_id=? AND regexp_matches(coalesce(body,''), '(?i)(spent|worked|person|engineer).{0,35}(hours?|hrs?)')", [bug]).fetchone()[0]:
                continue  # avoid an accidental explicit effort statement
            if api.execute("SELECT count(*) FROM api_comments WHERE json_extract_string(row_json,'$.bug_id')=? AND regexp_matches(row_json::VARCHAR, '(?i)(spent|worked|person|engineer).{0,35}(hours?|hrs?)')", [bug]).fetchone()[0]:
                continue
            kind = "engineer_hours" if int(order(seed, bug)[-1], 16) % 2 else "export_timestamp"
            if kind == "export_timestamp": assert r["snapshot_as_of_utc"] is None
            add("F6", kind, f"How many engineer work hours were spent on Firefox bug {bug}, according only to the specified frozen archive and selective API evidence? Elapsed calendar time is a different quantity.",
                {"type": "unanswerable", "value": UNKNOWN, "missing_evidence": "No measured engineer-hours/work log" if kind == "engineer_hours" else "Original CSV export timestamp is UNKNOWN"}, bug, [ev], "schema absence assertion; bounded evidence scope, no global absence claim")
        normalized = [re.sub(r"\s+", " ", q["question"].casefold()) for q in items]
        assert len(normalized) == len(set(normalized)), "Duplicate question"
        assert not ({b for q in items if q["split"] == "dev" for b in q["bug_ids"]} &
                    {b for q in items if q["split"] == "test" for b in q["bug_ids"]}), "Parent/target split leakage"
        return items, []
    finally:
        db.close()
        api.close()


def render(q, variant):
    """Three manually authored wording forms; model inference never sees template IDs."""
    bug = q["evidence"][0]["bug_id"]
    prefix = {"dev": "Using the specified frozen evidence, ",
              "test": "Consult the named archive/evidence version. ",
              "challenge": "Answer only within the named evidence collection. "}[variant]
    f = q["family"]
    if f == "F1":
        field = next(iter(q["evidence"][0]["fields"])).replace("snapshot_", "")
        wording = {"dev": f"what {field} is recorded for Firefox bug {bug}?",
                   "test": f"Return Firefox issue {bug}'s archive-recorded {field}.",
                   "challenge": f"Read Firefox issue {bug}'s entry and report its {field} field as recorded there."}[variant]
        return prefix + wording + " The source snapshot date is UNKNOWN."
    if f == "F2":
        if "first_fixed" in q["template_id"]:
            wording = {"dev": f"how many calendar hours elapsed from filing to the FIRST evidenced FIXED transition for Firefox bug {bug}?",
                       "test": f"For Firefox issue {bug}, subtract its filing timestamp from its earliest verified resolution-to-FIXED event; give calendar hours.",
                       "challenge": f"What calendar duration, in hours, separates creation of Firefox issue {bug} and its first substantiated FIXED resolution event?"}[variant]
        else:
            wording = {"dev": f"how many explicit transitions into REOPENED occur for Firefox bug {bug}?",
                       "test": f"Count recorded REOPENED-entry events for Firefox issue {bug}.",
                       "challenge": f"For Firefox issue {bug}, give the number of history entries that explicitly change status to REOPENED."}[variant]
        return prefix + wording + " Use only verified API history and filing evidence; an unsupported result is UNKNOWN. Calendar duration does not measure engineer work hours."
    if f == "F3":
        field, value = next(iter(q["scope"]["filter"].items()))
        sp, n = q["split"], q["scope"]["denominator"]
        wording = {"dev": f"how many distinct Firefox bug IDs have {field}={value} in the {sp} partition?",
                   "test": f"Count unique Firefox issue IDs matching {field}={value} within partition {sp}.",
                   "challenge": f"For partition {sp}, return the distinct-ID total for Firefox records whose {field} equals {value}."}[variant]
        return prefix + wording + f" Corpus: eligible broad-metadata frozen sample, seed {q['seed']}, partition denominator {n}. " + ("Year filters refer to filing, not resolution." if field == "creation_year" else "Snapshot date is UNKNOWN.")
    if f == "F4":
        rel = q["evidence"][0]["fields"]["relation"]
        wording = {"dev": f"which target bug IDs are explicitly recorded for {rel} from Firefox bug {bug}?",
                   "test": f"Return the complete numeric target set in Firefox issue {bug}'s recorded {rel} relation.",
                   "challenge": f"Read the {rel} field for Firefox issue {bug}; list every recorded numeric target ID, with duplicates removed."}[variant]
        return prefix + wording + " Historical validity and source snapshot date are UNKNOWN; URL-only targets are outside this question."
    if f == "F5":
        ref = q["evidence"][0]["id"]
        wording = {"dev": f"what reason or constraint is explicitly stated in cited comment {ref} for Firefox bug {bug}?",
                   "test": f"Summarize the stated rationale or constraint in comment {ref} on Firefox issue {bug}.",
                   "challenge": f"For Firefox issue {bug}, identify only the constraint or reason that comment {ref} actually expresses; map each claim to that comment."}[variant]
        return prefix + wording + " Scope: FIXED-selected CSV-comment subgroup. If no rationale is supported, state that the evidence is insufficient."
    if "export_timestamp" in q["template_id"]:
        text = {"dev": f"what exact UTC export timestamp establishes the archived fields for Firefox bug {bug}?",
                "test": f"Establish the original CSV snapshot's exact UTC export time for Firefox issue {bug}.",
                "challenge": f"At what precise UTC instant were Firefox issue {bug}'s archived CSV values exported, according to the supplied provenance?"}[variant]
        return prefix + text + " Local observation and ingestion timestamps identify different events."
    wording = {"dev": f"how many engineer work hours were spent on Firefox bug {bug}?",
               "test": f"Establish the measured developer effort, in work hours, for Firefox issue {bug} from these records alone.",
               "challenge": f"Do these records establish measured engineer-hours for Firefox issue {bug}; if so, give that effort figure?"}[variant]
    return prefix + wording + " Elapsed calendar duration is a different quantity."


def complete_candidates(*args, **kwargs):
    items, _ = build_candidates(*args, **kwargs)
    for q in items:
        q["template_id"] += ":" + q["split"]
        q["question"] = render(q, q["split"])
        q["qid"] = "q_" + digest([q["template_id"], q["question"], q["scope"], q["seed"]])[:20]
        if q["gold"]["type"] in ("unknown", "unanswerable"):
            q["answerability"] = "INSUFFICIENT_SPECIFIED_EVIDENCE"
        if q["family"] == "F5":
            q["answerability"] = "PENDING_HUMAN_RATIONALE_REVIEW"
        check_item(q)
    challenges = []
    seed = kwargs.get("seed", 317)
    for f in FAMILIES:
        eligible = [q for q in items if q["family"] == f and q["split"] == "test"]
        if eligible:
            q = min(eligible, key=lambda q: order(seed, q["qid"]))
            ch = {**q, "qid": "challenge_" + q["qid"][2:], "variant_of": q["qid"],
                  "question": render(q, "challenge"), "challenge_origin": "agent_authored; PENDING human wording review"}
            check_item(ch); challenges.append(ch)
    return items, challenges


def summary(items, challenges, target):
    return {"target_per_family": target, "candidates": len(items),
            "by_family": {f: sum(q["family"] == f for q in items) for f in FAMILIES},
            "by_split": dict(Counter(q["split"] for q in items)),
            "by_family_and_type": dict(Counter(q["family"] + ":" + q["gold"]["type"] for q in items)),
            "challenge_candidates": len(challenges), "target_180_guaranteed": False,
            "parent_outcomes_by_family_question_denominator": dict(Counter(q["family"] + ":" + str(q["source_coverage"].get("parent_snapshot_status")) + "/" + str(q["source_coverage"].get("parent_snapshot_resolution")) for q in items if q["family"] != "F3")),
            "shortfall_by_family": {f: max(0, target - sum(q["family"] == f for q in items)) for f in FAMILIES},
            "as_of_question_count": sum(q.get("as_of") is not None for q in items),
            "temporal_coverage": "event-duration/reopen only; historical snapshot cutoffs unsupported; roadmap 48-cutoff target not claimed",
            "eligibility_limits": "F2 needs conflict-free ordered histories (unknown cases capped at six); F4 complete target sets must stay within one partition; F5 needs a public explicit-rationale candidate and human review",
            "f5_population": "FIXED_SELECTED_CSV_ONLY; no unresolved explanation generalization",
            "issue_type": "UNKNOWN in canonical model; includes possible enhancements; no defect-only claim",
            "source_population": "broad metadata source, Firefox sample; not curated 119585 or CTQRS",
            "state": "AWAITING_HUMAN_REVIEW"}


def generate(args, root, pins):
    options = {"seed": args.seed, "per_family": args.per_family, "f5_target": args.f5_target, "limit": args.limit}
    identity = {"version": VERSION, "code_hash": version_hash(), "source_pins": pins, "options": options}
    run = args.output / ("run-" + digest(identity)[:16])
    if args.dry_run:
        return {"state": "DRY_RUN", "run": str(run.relative_to(root)), "options": options, "network_requests": 0}
    if run.exists() and (run / "manifest.json").exists():
        assert args.resume, "Existing output: use --resume; never overwrite a benchmark"
        m = read(run / "manifest.json")
        assert m["identity"] == identity
        for n, h in m["artifacts"].items(): assert file_hash(run / n) == h
        return read(run / "summary.json")
    run.mkdir(parents=True, exist_ok=True)
    verification = verify_inputs(root, pins)
    write_json(run / "generation_checkpoint.json", {"state": "GENERATING", "identity": identity, "started_at_utc": stamp()})
    items, challenges = complete_candidates(root, pins, **options)
    write_json(run / "candidates.json", items); write_json(run / "challenge_candidates.json", challenges)
    write_json(run / "input_verification.json", verification)
    base, _ = paths(root, pins)
    conn = duckdb.connect(str(base / "canonical.duckdb"), read_only=True)
    try:
        eligible = [r[0] for r in conn.execute("""SELECT b.bug_id FROM bugs b JOIN sample_membership m USING(bug_id)
           WHERE NOT EXISTS(SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT')""").fetchall()]
    finally:
        conn.close()
    populations = {sp: sorted(b for b in eligible if partition(args.seed, b) == sp) for sp in ("dev", "test")}
    assert all(q["scope"]["population_manifest_sha256"] == digest(populations) for q in items)
    write_json(run / "population_manifest.json", {"members": populations, "sha256": digest(populations), "seed": args.seed, "source_identity": pins["base_identity"], "exclusions": "parents with conflicting metadata variants"})
    report = summary(items, challenges, args.per_family)
    report.update(run=str(run.relative_to(root)), seed=args.seed, limited_prefix=args.limit is not None, base_counts=verification["base_counts"])
    write_json(run / "summary.json", report)
    manifest = {"identity": identity, "generated_at_utc": stamp(), "state": "CANDIDATES_READY",
                "artifacts": {n: file_hash(run / n) for n in ("candidates.json", "challenge_candidates.json", "input_verification.json", "population_manifest.json", "summary.json")}}
    write_json(run / "manifest.json", manifest)
    write_json(run / "generation_checkpoint.json", {"state": "CANDIDATES_READY", "identity": identity})
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "LATEST_RUN").write_text(run.name + "\n")
    return report


def load_run(args):
    run = args.run if args.run else args.output / (args.output / "LATEST_RUN").read_text().strip()
    m = read(run / "manifest.json")
    assert m["identity"]["code_hash"] == version_hash(), "Code changed; generate a new version"
    assert m["identity"]["options"]["seed"] == args.seed, "Seed mismatch"
    for n, h in m["artifacts"].items(): assert file_hash(run / n) == h, "Changed candidate artifact: " + n
    return run, m, read(run / "candidates.json"), read(run / "challenge_candidates.json")


def review_policy(items, challenges, prior, seed):
    retained = [q for q in items if prior.get(q["qid"], {}).get("decision") != "REJECT"]
    required = {q["qid"] for q in retained if q["family"] == "F5"}
    for family in ("F1", "F2", "F3", "F4", "F6"):
        rows = sorted((q for q in retained if q["family"] == family), key=lambda q: order(seed + 19, q["qid"]))
        n = min(len(rows), 6 if family == "F6" else math.ceil(len(rows) * .2))
        required.update(q["qid"] for q in rows[:n])
    retained_ids = {q["qid"] for q in retained}
    required.update(q["qid"] for q in challenges if q["variant_of"] in retained_ids and prior.get(q["qid"], {}).get("decision") != "REJECT")
    return required


def queue_read(path):
    if not path.exists(): return {}
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len({r["qid"] for r in rows}) == len(rows), "Duplicate review ID"
    return {r["qid"]: r for r in rows}


def prepare_review(args):
    if args.dry_run: return {"state": "DRY_RUN", "output": str(args.output), "requires": "generated candidates; human reviews remain PENDING"}
    run, m, items, challenges = load_run(args)
    if args.dry_run: return {"state": "DRY_RUN", "review_target": str(run / "review_queue.csv")}
    path = run / "review_queue.csv"
    assert not (run / "FROZEN").exists(), "Locked release: do not regenerate its review sheet"
    if path.exists(): assert args.resume, "Existing review sheet: use --resume to preserve edits"
    prior = queue_read(path); required = review_policy(items, challenges, prior, args.seed)
    rows = []
    for q in items + challenges:
        old = prior.get(q["qid"], {})
        ev = [{"id": e["id"], "url": e["source_url"], "fields": e["fields"], "source_hash": e["content_hash"]} for e in q["evidence"]]
        row = {"qid": q["qid"], "family": q["family"], "split": q["split"],
               "required": "YES" if q["qid"] in required else "NO", "optional_second_rater": "YES" if int(order(args.seed + 7, q["qid"])[:4], 16) % 5 == 0 else "NO",
               "question": q["question"], "suggested_gold_json": json.dumps(q["gold"], sort_keys=True),
               "evidence_json": json.dumps(ev, sort_keys=True),
               "query_json": json.dumps(q.get("sql"), sort_keys=True),
               "rubric": "Every causal claim must be explicitly stated and mapped to the cited comment; rationale_present YES required." if q["family"] == "F5" else q["validator"]}
        row.update({k: old.get(k, "PENDING" if k == "decision" else "") for k in USER_COLUMNS})
        rows.append(row)
    if args.limit is not None:
        rows = rows[:args.limit]
        assert set(prior) <= {r["qid"] for r in rows}, "A limited preview must not discard existing reviews"
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["qid"]); w.writeheader(); w.writerows(rows)
    tmp.replace(path)
    text = ["<!doctype html><meta charset='utf-8'><title>Phase 5 local review</title>",
            "<h1>Candidate review — PENDING until signed</h1><p>Edit review_queue.csv. Approve/correct/reject only after checking evidence links. All F5 and challenge gold require source review. No model evaluation has run.</p>"]
    for r in rows:
        text.append("<article><h2>" + html.escape(r["qid"] + " " + r["family"]) + "</h2><p>" + html.escape(r["question"]) + "</p><pre>" + html.escape(r["suggested_gold_json"]) + "</pre><pre>" + html.escape(r["query_json"]) + "</pre>")
        for e in json.loads(r["evidence_json"]):
            text.append('<p><a rel="noreferrer" href="' + html.escape(e["url"], quote=True) + '">source</a></p><pre>' + html.escape(json.dumps(e, indent=2)) + '</pre>')
        text.append("<p>Required: " + r["required"] + "; decision: " + html.escape(r["decision"]) + "</p></article>")
    (run / "review.html").write_text("\n".join(text), encoding="utf-8")
    signoff = run / "review_signoff.json"
    if not signoff.exists():
        write_json(signoff, {"reviewer": "", "reviewed_at_utc": None, "approve_freeze": False,
                 "acknowledge_actual_reduced_coverage": False, "source_population": "broad metadata; F5 FIXED-selected",
                 "attestation": "I checked mandatory sources and all retained F5 rationale/claims, and approved challenge wording. Test gold will not be used for method tuning."})
    report = {"state": "AWAITING_HUMAN_REVIEW", "queue_rows": len(rows), "required_rows": len(required), "seed": args.seed,
              "queue": str(path), "html": str(run / "review.html"), "second_rater": "optional; not an agreement result"}
    write_json(run / "review_summary.json", report)
    return report


def approved_gold(q, row):
    decision = row.get("decision", "PENDING")
    assert decision in ("APPROVE", "CORRECT"), "Pending review: " + q["qid"]
    assert row.get("reviewer", "").strip() and row.get("source_checked") == "YES", "Unsigned source review"
    dt(row.get("reviewed_at_utc"))
    if row.get("second_reviewer") and row.get("second_decision") not in ("", decision):
        assert "ADJUDICATED" in row.get("note", ""), "Second-rater disagreement needs documented adjudication"
    assert decision != "CORRECT" or row.get("corrected_gold_json") or (q.get("variant_of") and row.get("corrected_question")), "Correction requires an explicit corrected value"
    gold = json.loads(row["corrected_gold_json"]) if decision == "CORRECT" and row.get("corrected_gold_json") else q["gold"]
    if q["family"] == "F5":
        assert row.get("rationale_present") == "YES", "Subjective rationale not signed off"
        assert gold.get("type") == "supported_explanation" and gold.get("claims")
        ids = {e["id"] for e in q["evidence"]}
        assert all(c.get("text", "").strip() and c.get("evidence_id") in ids for c in gold["claims"])
        assert "@" not in json.dumps(gold), "Redact contributor identities in gold"
    else:
        assert gold == q["gold"], "Factual correction disagrees with recomputation; fix source/validator and regenerate"
    if q.get("variant_of"):
        assert row.get("source_checked") == "YES"
    return gold


def jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, sort_keys=True, default=str) + "\n")


def validate_freeze(args, root, pins):
    if args.dry_run: return {"state": "DRY_RUN", "requires": "full generation, all mandatory source reviews, global signed approval, data hashes and gold recomputation"}
    run, m, items, challenges = load_run(args)
    assert args.limit is None and m["identity"]["options"]["limit"] is None, "Never freeze a limited prefix"
    assert m["identity"]["source_pins"] == pins, "Source pin changed"
    if args.dry_run: return {"state": "DRY_RUN", "requires": "All F5, 20% F1–F4, six F6, challenge review, global signoff, independent recomputation and source hashes"}
    reviews = queue_read(run / "review_queue.csv")
    assert all(r.get("decision") in ("PENDING", "APPROVE", "CORRECT", "REJECT") for r in reviews.values()), "Invalid review decision"
    required = review_policy(items, challenges, reviews, args.seed)
    assert all(q in reviews for q in required), "Incomplete review queue; prepare-review --resume"
    signoff = read(run / "review_signoff.json")
    assert signoff.get("approve_freeze") is True and signoff.get("acknowledge_actual_reduced_coverage") is True
    assert signoff.get("reviewer", "").strip(); dt(signoff.get("reviewed_at_utc"))
    # User-terminal only: rehash the large canonical DB once at freeze; never trust a size match alone.
    verified = verify_inputs(root, pins, full_hash=True)
    assert verified["small_file_hashes"] == read(run / "input_verification.json")["small_file_hashes"]
    fresh, fresh_ch = complete_candidates(root, pins, **m["identity"]["options"])
    assert digest(fresh) == digest(items) and digest(fresh_ch) == digest(challenges), "Gold/source recomputation mismatch"
    retained, retained_ch = [], []
    for q in items + challenges:
        r = reviews.get(q["qid"], {})
        if r.get("decision") == "REJECT": continue
        if q.get("variant_of") and not any(x["qid"] == q["variant_of"] for x in retained): continue
        out = dict(q)
        if q["qid"] in required or r.get("decision") in ("APPROVE", "CORRECT"):
            out["gold"] = approved_gold(q, r)
            out["human_review_state"] = "SIGNED_SOURCE_REVIEW"
            out["reviewer"] = r["reviewer"]
            if q.get("variant_of") and r.get("corrected_question"):
                out["question"] = r["corrected_question"].strip()
        else:
            out["human_review_state"] = "AUTO_VALIDATED; NOT_SELECTED_FOR_HUMAN_SPOTCHECK"
        if out["family"] == "F5": out["answerability"] = "HUMAN_SUPPORTED"
        if q.get("variant_of"):
            parent = next(x for x in retained if x["qid"] == q["variant_of"])
            assert out["gold"] == parent["gold"], "Challenge gold must match its reviewed parent"
        check_item(out)
        (retained_ch if q.get("variant_of") else retained).append(out)
    assert len(retained_ch) >= min(3, len(challenges)), "Too few reviewed challenge questions"
    assert len({q["question"].casefold() for q in retained + retained_ch}) == len(retained + retained_ch), "Duplicate final wording"
    frozen_id = digest([m, file_hash(run / "review_queue.csv"), file_hash(run / "review_signoff.json")])[:16]
    dest = run / ("frozen-" + frozen_id)
    if (run / "FROZEN").exists():
        assert (run / "FROZEN").read_text().strip() == dest.name, "Locked test already exists: changed review requires a new generation version, never replace the release"
    if dest.exists() and (dest / "manifest.json").exists():
        assert args.resume, "Frozen release exists; use --resume for checksum-only validation"
        frozen = read(dest / "manifest.json")
        for n, h in frozen["sha256"].items(): assert file_hash(dest / n) == h
        return frozen
    dest.mkdir(exist_ok=True)
    for split in ("dev", "test", "challenge"):
        selected = retained_ch if split == "challenge" else [q for q in retained if q["split"] == split]
        jsonl(dest / (split + ".questions.jsonl"),
              [{"qid": q["qid"], "question": q["question"], "scope": q["scope"]} for q in selected])
        jsonl(dest / (split + ".gold.jsonl"), selected)
    report = summary(retained, retained_ch, m["identity"]["options"]["per_family"])
    report.update(state="FROZEN_HUMAN_SIGNED", frozen_id=frozen_id, source_hashes=verified,
                  review_policy="all F5, 20% F1–F4, min(6,F6 count), all challenge; optional second rater",
                  review_signoff_sha256=file_hash(run / "review_signoff.json"), review_queue_sha256=file_hash(run / "review_queue.csv"))
    report["human_observed_issue_types_reviewed_only"] = dict(Counter(reviews[q["qid"]].get("issue_type_observed") or "UNKNOWN" for q in retained if q["human_review_state"] == "SIGNED_SOURCE_REVIEW"))
    write_json(dest / "quality_report.json", report)
    frozen = {"state": "FROZEN_HUMAN_SIGNED", "id": frozen_id, "created_at_utc": stamp(),
              "sha256": {p.name: file_hash(p) for p in sorted(dest.iterdir()) if p.name != "manifest.json"},
              "test_checksum_policy": "Never overwrite or tune on test; changes require a new version and documented amendment"}
    write_json(dest / "manifest.json", frozen)
    (run / "FROZEN").write_text(dest.name + "\n")
    return frozen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify-inputs", "generate", "prepare-review", "validate-freeze"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-pins", type=Path, default=Path("configs/phase05_sources.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/benchmark/phase05"))
    parser.add_argument("--run", type=Path)
    parser.add_argument("--seed", type=int, default=317)
    parser.add_argument("--per-family", type=int, default=30)
    parser.add_argument("--f5-target", type=int, default=30)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    assert args.per_family > 0 and 0 <= args.f5_target <= args.per_family
    assert args.limit is None or args.limit > 0
    root = args.root.resolve()
    args.output = (root / args.output).resolve()
    if args.run: args.run = (root / args.run).resolve()
    pins = read(root / args.source_pins)
    if args.command == "verify-inputs": result = {"state": "DRY_RUN"} if args.dry_run else verify_inputs(root, pins)
    elif args.command == "generate": result = generate(args, root, pins)
    elif args.command == "prepare-review": result = prepare_review(args)
    else: result = validate_freeze(args, root, pins)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
