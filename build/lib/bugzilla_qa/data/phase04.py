"""Phase 4: plan and selectively enrich the verified BugsRepo sample.

Planning and temporal QC are offline. Network access is only available through
the explicit user-run smoke/enrichment commands; this module never uses auth.
"""
from __future__ import annotations

import argparse
import email.utils
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://bugzilla.mozilla.org/rest"
USER_AGENT = "BugzillaHistoryCourseProject/0.1 (public unauthenticated research client)"
VERSION = 1
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_SMOKE_IDS = 10
MAX_RETRIES = 3  # retries after the initial request; maximum total attempts = 4
SENSITIVE_FIELDS = {"assigned_to", "reporter", "qa_contact", "cc", "creator", "commenter"}
EMAIL_RE = re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")
def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso_utc(value):
    parsed = parse_utc(value) if isinstance(value, str) else value
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") if parsed else None


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha256_bytes(canonical(value).encode("ascii"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def redact_emails(value):
    return EMAIL_RE.sub("[redacted-email]", value or "")


def pseudonym(value):
    if not value:
        return None
    # No raw actor/login field is written to normalized study tables/reports.
    return "actor_" + sha256_bytes(str(value).strip().casefold().encode("utf-8"))[:16]


def baseline_paths(root, run_id=None):
    base = Path(root) / "outputs/normalization/phase03b"
    if run_id is None:
        pointer = base / "LATEST_RUN"
        if not pointer.is_file():
            raise ValueError("Phase 3B LATEST_RUN is missing")
        run_id = pointer.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"run-[A-Za-z0-9T_-]+", run_id):
        raise ValueError("Invalid Phase 3B run ID")
    run = base / run_id
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("state") != "COMPLETE" or manifest.get("identity", {}).get("options", {}).get("limit") is not None:
        raise ValueError("Phase 4 requires a completed unlimited Phase 3B run")
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    sample = json.loads((run / "sample_manifest.json").read_text(encoding="utf-8"))
    qc = json.loads((run / "qc_report.json").read_text(encoding="utf-8"))
    if summary.get("identity_hash") != manifest.get("identity_hash") or sample.get("identity_hash") != manifest.get("identity_hash"):
        raise ValueError("Phase 3B summary/sample identity does not match its manifest")
    if len(sample.get("members", [])) != summary.get("sample_count"):
        raise ValueError("Phase 3B sample manifest count is inconsistent")
    return run, manifest, summary, qc, sample


def _hash_order(seed, bug_id):
    return sha256_bytes(f"{seed}:{bug_id}".encode("ascii"))


def _tags(row):
    tags = ["outcome:" + row["snapshot_status"] + "/" + (row["snapshot_resolution"] or "UNKNOWN")]
    status, resolution = row["snapshot_status"], row["snapshot_resolution"]
    if resolution == "FIXED":
        tags.append("positive:fixed")
    if status == "REOPENED":
        tags.append("negative:reopened")
    if status == "NEW":
        tags.append("negative:new")
    if resolution == "DUPLICATE":
        tags.append("negative:duplicate")
    if resolution == "INCOMPLETE":
        tags.append("negative:incomplete")
    if row["link_count"]:
        tags.append("links:explicit_source")
    tags.append("comments:present" if row["comment_count"] else "comments:absent")
    if row.get("missing_text_count", 0):
        tags.append("comments:text_missing")
    tags.append("year:" + str(row["year"] or "UNKNOWN"))
    tags.append("component:" + (row["component"] or "UNKNOWN"))
    return tags


def choose_candidates(rows, seed, count):
    if count > len(rows):
        raise ValueError(f"Requested {count} candidates from only {len(rows)} sampled bugs")
    by_outcome = defaultdict(list)
    by_tag = defaultdict(list)
    for row in rows:
        row["tags"] = _tags(row)
        row["tie"] = _hash_order(seed, row["bug_id"])
        by_outcome[(row["snapshot_status"], row["snapshot_resolution"] or "UNKNOWN")].append(row)
        for tag in row["tags"]:
            by_tag[tag].append(row)
    if len(by_outcome) > count:
        raise ValueError("Candidate size cannot cover every observed status/resolution stratum")
    selected, selected_ids = [], set()

    def add(row):
        if row["bug_id"] not in selected_ids and len(selected) < count:
            selected.append(row)
            selected_ids.add(row["bug_id"])

    # Keep each local outcome stratum represented in both the 50-bug pilot and
    # the larger planned cohort before optimizing time/component/link coverage.
    for outcome in sorted(by_outcome):
        add(min(by_outcome[outcome], key=lambda r: r["tie"]))
    for tag in ("positive:fixed", "negative:reopened", "negative:new", "negative:duplicate",
                "negative:incomplete", "links:explicit_source", "comments:present", "comments:absent"):
        candidates = by_tag.get(tag, [])
        if candidates:
            add(min(candidates, key=lambda r: (r["bug_id"] in selected_ids, r["tie"])))

    tag_counts = Counter(tag for row in selected for tag in row["tags"])
    while len(selected) < count:
        best, best_score = None, None
        for row in rows:
            if row["bug_id"] in selected_ids:
                continue
            # Inverse coverage weight favors underrepresented outcomes, years,
            # components, comment presence and explicitly linked bugs.
            weights = [(tag, 4.0 if tag.startswith("outcome:") else
                        3.0 if tag.startswith("year:") or tag.startswith("component:") else
                        2.0 if tag == "links:explicit_source" else 1.5)
                       for tag in row["tags"]]
            score = sum(weight / (1 + tag_counts[tag]) for tag, weight in weights)
            candidate_score = (score, row["tie"])
            if best_score is None or candidate_score[0] > best_score[0] or (
                    candidate_score[0] == best_score[0] and candidate_score[1] < best_score[1]):
                best, best_score = row, candidate_score
        add(best)
        tag_counts.update(best["tags"])
    return selected


def query_plan(root, baseline_run_id=None, seed=317, pilot_size=50, study_size=200):
    if not 50 <= pilot_size <= 50:
        raise ValueError("The Phase 4 pilot is fixed at 50 candidates")
    if not 100 <= study_size <= 300:
        raise ValueError("Study cohort must be configurable from 100 through 300 candidates")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("Install DuckDB 1.4.4 in this interpreter: python -m pip install duckdb==1.4.4") from exc
    run, manifest, summary, qc, sample = baseline_paths(root, baseline_run_id)
    db = duckdb.connect(str(run / "canonical.duckdb"), read_only=True)
    try:
        rows = db.execute("""WITH comments_by_bug AS (
              SELECT bug_id,count(*) AS comment_count,
                     count(*) FILTER(WHERE body IS NOT NULL AND length(trim(body))>0) AS text_available_count
              FROM comments GROUP BY bug_id
            ), links_by_bug AS (
              SELECT bug_id,count(*) AS link_count FROM bug_links GROUP BY bug_id
            )
            SELECT b.bug_id,b.product,b.component,CAST(b.opened_at_utc AS VARCHAR) AS opened_at_utc,
                   coalesce(b.snapshot_status,'UNKNOWN') AS snapshot_status,
                   b.snapshot_resolution,coalesce(c.comment_count,0) AS comment_count,
                   coalesce(c.text_available_count,0) AS text_available_count,
                   coalesce(l.link_count,0) AS link_count
            FROM sample_membership s JOIN bugs b USING(bug_id)
            LEFT JOIN comments_by_bug c USING(bug_id)
            LEFT JOIN links_by_bug l USING(bug_id)
            WHERE b.product='Firefox'
            ORDER BY b.bug_id""").fetchall()
        names = [column[0] for column in db.description]
        sampled = []
        for values in rows:
            row = dict(zip(names, values))
            opened = parse_utc(row.get("opened_at_utc")) if row.get("opened_at_utc") else None
            row["year"] = opened.year if opened else None
            row["comment_count"] = int(row["comment_count"])
            row["text_available_count"] = int(row["text_available_count"])
            row["missing_text_count"] = row["comment_count"] - row["text_available_count"]
            row["link_count"] = int(row["link_count"])
            sampled.append(row)
        stats = db.execute("""SELECT count(*) AS bugs,
            count(*) FILTER(WHERE summary IS NOT NULL) AS summary_present,
            count(*) FILTER(WHERE product IS NOT NULL) AS product_present,
            count(*) FILTER(WHERE component IS NOT NULL) AS component_present,
            count(*) FILTER(WHERE snapshot_status IS NOT NULL) AS status_present,
            count(*) FILTER(WHERE opened_at_utc IS NOT NULL) AS creation_present,
            count(*) FILTER(WHERE snapshot_resolution='FIXED') AS fixed_snapshot,
            count(*) FILTER(WHERE snapshot_status='REOPENED') AS reopened_snapshot,
            count(*) FILTER(WHERE snapshot_status IN ('NEW','ASSIGNED','UNCONFIRMED')) AS open_snapshot
            FROM sample_membership s JOIN bugs b USING(bug_id)
            WHERE b.product='Firefox'""").fetchone()
        stats_names = [x[0] for x in db.description]
        sample_summary = dict(zip(stats_names, stats))
        local_f4 = db.execute("""SELECT count(*) AS edges,
            count(*) FILTER(WHERE target_in_corpus) AS target_in_corpus,
            count(*) FILTER(WHERE NOT target_in_corpus) AS target_outside_corpus
            FROM bug_links l JOIN sample_membership s USING(bug_id)""").fetchone()
        f4_names = [x[0] for x in db.description]
        f4_sample = dict(zip(f4_names, local_f4))
        local_f2 = db.execute("SELECT count(*) FROM field_changes").fetchone()[0]
    finally:
        db.close()
    if len(sampled) < study_size:
        raise ValueError(f"Only {len(sampled)} Firefox sample bugs available; study target is {study_size}")
    chosen = choose_candidates(sampled, seed, study_size)
    entries = []
    for rank, row in enumerate(chosen, 1):
        entries.append({
            "bug_id": row["bug_id"], "rank": rank, "pilot": rank <= pilot_size,
            "study": True, "product": row["product"], "component": row["component"],
            "year": row["year"], "snapshot_status": row["snapshot_status"],
            "snapshot_resolution": row["snapshot_resolution"],
            "csv_comment_count": row["comment_count"],
            "csv_text_available_count": row["text_available_count"],
            "csv_missing_text_count": row["missing_text_count"],
            "explicit_link_count": row["link_count"],
            "tags": row["tags"],
        })
    pilot = entries[:pilot_size]
    result = {
        "schema_version": 1, "planner_version": VERSION,
        "baseline_run_id": run.name, "baseline_manifest_identity": manifest["identity_hash"],
        "baseline_duckdb_path": str((run / "canonical.duckdb").relative_to(Path(root))),
        "sample_manifest_seed": sample["seed"], "planner_seed": seed,
        "sampled_universe_bugs": len(sampled), "pilot_size": pilot_size,
        "study_size": study_size, "network_calls_default": {
            "pilot_required_history_and_metadata": 2 * len(pilot),
            "pilot_missing_comment_requests_if_enabled": sum(_needs_comments(x) for x in pilot),
            "pilot_expected_total_with_missing_comments": 2 * len(pilot) + sum(_needs_comments(x) for x in pilot),
            "pilot_worst_case_four_attempts_each": 4 * (2 * len(pilot) + sum(_needs_comments(x) for x in pilot)),
            "study_required_history_and_metadata": 2 * len(entries),
            "study_missing_comment_requests_if_enabled": sum(_needs_comments(x) for x in entries),
            "study_expected_total_with_missing_comments": 2 * len(entries) + sum(_needs_comments(x) for x in entries),
            "study_worst_case_four_attempts_each": 4 * (2 * len(entries) + sum(_needs_comments(x) for x in entries)),
            "meaning": "GET attempts, including retries; comments only for candidate bugs with zero or empty CSV comment bodies",
        },
        "local_evidence": {
            "F1": {"sampled_firefox_field_coverage": sample_summary,
                   "supported": "Archive-recorded snapshot lookup; not authoritative current or historical-as-of status."},
            "F2": {"canonical_field_changes": local_f2, "exact_first_fixed_from_csv": 0,
                   "state": "UNKNOWN until parseable, audited API history is ingested."},
            "F3": {"supported": "Deterministic aggregates over frozen canonical source/product/status/resolution and explicit denominator."},
            "F4": {"sampled_bug_link_counts": f4_sample,
                   "full_canonical_link_count": summary["table_counts"]["bug_links"],
                   "supported": "Recorded source links and whether targets are in corpus; no historical validity."},
        },
        "candidates": entries,
        "candidate_manifest_sha256": None,
    }
    result["candidate_manifest_sha256"] = digest({k: v for k, v in result.items() if k != "candidate_manifest_sha256"})
    evidence = {k: v for k, v in result.items() if k != "candidates"}
    evidence["candidate_tags_coverage"] = dict(Counter(tag for row in entries for tag in row["tags"]))
    evidence["candidate_outcome_strata"] = len({tag for row in entries for tag in row["tags"] if tag.startswith("outcome:")})
    evidence["missing_comment_candidates"] = result["network_calls_default"]["study_missing_comment_requests_if_enabled"]
    return result, evidence


def command_plan(args):
    root = Path(args.root).resolve()
    manifest, evidence = query_plan(root, args.baseline_run, args.seed, args.pilot_size, args.study_size)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "baseline_run_id": manifest["baseline_run_id"],
                          "sampled_universe_bugs": manifest["sampled_universe_bugs"],
                          "pilot_size": manifest["pilot_size"], "study_size": manifest["study_size"],
                          "request_estimates": manifest["network_calls_default"],
                          "local_evidence": manifest["local_evidence"],
                          "candidate_tags_coverage": evidence["candidate_tags_coverage"]}, indent=2))
        return
    base = root / "outputs/phase04/candidates"
    base.mkdir(parents=True, exist_ok=True)
    run_id = "plan-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + str(os.getpid())
    out = base / run_id
    out.mkdir()
    write_json(out / "candidate_manifest.json", manifest)
    write_json(out / "evidence_gap_report.json", evidence)
    (base / "LATEST_RUN.tmp").write_text(run_id + "\n", encoding="utf-8")
    (base / "LATEST_RUN.tmp").replace(base / "LATEST_RUN")
    print(json.dumps({"state": "PLAN_READY", "run_id": run_id,
                      "candidate_manifest": str(out / "candidate_manifest.json"),
                      "evidence_gap_report": str(out / "evidence_gap_report.json"),
                      "pilot_expected_requests": manifest["network_calls_default"]["pilot_expected_total_with_missing_comments"],
                      "study_expected_requests": manifest["network_calls_default"]["study_expected_total_with_missing_comments"]}, indent=2))


def parse_api_history(payload, requested_id, created_at=None, observed_at=None):
    """Validate Bugzilla's documented bugs[].history[] shape and normalize events."""
    bugs = payload.get("bugs") if isinstance(payload, dict) else None
    if not isinstance(bugs, list) or len(bugs) != 1 or not isinstance(bugs[0], dict):
        return {"state": "UNKNOWN", "error": "unexpected_history_shape", "changes": [],
                "event_count": 0, "reordered": False, "same_time_groups": 0,
                "first_fixed_at_utc": None, "reopened_count": 0}
    bug = bugs[0]
    if str(bug.get("id")) != str(requested_id) or not isinstance(bug.get("history"), list):
        return {"state": "UNKNOWN", "error": "history_bug_id_or_list_mismatch", "changes": [],
                "event_count": 0, "reordered": False, "same_time_groups": 0,
                "first_fixed_at_utc": None, "reopened_count": 0}
    raw_events = bug["history"]
    parsed_events = []
    malformed = 0
    for index, event in enumerate(raw_events):
        when = iso_utc(event.get("when")) if isinstance(event, dict) else None
        changes = event.get("changes") if isinstance(event, dict) else None
        if when is None or not isinstance(changes, list):
            malformed += 1
            continue
        for change_index, change in enumerate(changes):
            if not isinstance(change, dict) or not isinstance(change.get("field_name"), str):
                malformed += 1
                continue
            field = change["field_name"]
            old = change.get("removed")
            new = change.get("added")
            # Actor fields and e-mail-looking values are never copied verbatim
            # to the normalized study overlay.
            if field in SENSITIVE_FIELDS:
                old, new = pseudonym(old), pseudonym(new)
            else:
                old = redact_emails(canonical(old)) if old is not None else None
                new = redact_emails(canonical(new)) if new is not None else None
            parsed_events.append({
                "bug_id": int(requested_id), "event_time_utc": when,
                "event_index": index, "change_index": change_index,
                "field_name": field, "old_value": old, "new_value": new,
                "actor_pseudonym": pseudonym(event.get("who")),
                "source_endpoint": "history", "source_visibility": "public_response",
            })
    original_times = [parse_utc(event["event_time_utc"]) for event in parsed_events]
    reordered = any(a > b for a, b in zip(original_times, original_times[1:]))
    event_times = []
    for event in raw_events:
        when = iso_utc(event.get("when")) if isinstance(event, dict) else None
        if when is not None:
            event_times.append(parse_utc(when))
    times = Counter(x for x in event_times if x is not None)
    same_time_groups = sum(1 for n in times.values() if n > 1)
    # Sort for downstream use but preserve original sequence indices and mark
    # same-time ambiguity rather than inventing an ordering.
    parsed_events.sort(key=lambda x: (x["event_time_utc"], x["event_index"], x["change_index"]))
    seen_changes, unique_events = set(), []
    duplicate_change_count = 0
    for event in parsed_events:
        key = (event["event_time_utc"], event["field_name"], event["old_value"],
               event["new_value"], event["actor_pseudonym"])
        if key in seen_changes:
            duplicate_change_count += 1
            continue
        seen_changes.add(key)
        unique_events.append(event)
    parsed_events = unique_events
    created = parse_utc(created_at) if created_at else None
    observed = parse_utc(observed_at) if observed_at else None
    valid_times = all(parse_utc(event["event_time_utc"]) is not None for event in parsed_events)
    future_event = bool(observed and any(parse_utc(event["event_time_utc"]) > observed for event in parsed_events))
    chronology_ok = not reordered and valid_times and not malformed and not future_event
    eligible_fixed = []
    reopened_count = 0
    for event in parsed_events:
        field, new, old = event["field_name"], event["new_value"], event["old_value"]
        if field == "resolution" and new == canonical("FIXED") and old != canonical("FIXED"):
            event_time = parse_utc(event["event_time_utc"])
            if event_time and (created is None or event_time >= created):
                eligible_fixed.append(event_time)
        if field == "status" and new == canonical("REOPENED"):
            reopened_count += 1
    first_fixed = min(eligible_fixed).isoformat(timespec="microseconds").replace("+00:00", "Z") if eligible_fixed else None
    return {
        "state": "PARSED" if chronology_ok else "PARTIAL",
        "error": None if chronology_ok else "malformed_or_reordered_history",
        "changes": parsed_events, "event_count": len(raw_events),
        "parsed_event_count": len({x["event_index"] for x in parsed_events}),
        "malformed_count": malformed, "duplicate_change_count": duplicate_change_count,
        "reordered": reordered,
        "future_event_after_observed_at": future_event,
        "same_time_groups": same_time_groups, "first_fixed_at_utc": first_fixed,
        "reopened_count": reopened_count,
        "chronology_ok": chronology_ok,
    }


def classify_first_fixed(history, created_at, current_resolution=None):
    """A valid F2 timestamp requires a complete, ordered history and creation time."""
    created = parse_utc(created_at) if created_at else None
    if not created or not history.get("chronology_ok"):
        return {"state": "UNKNOWN", "first_fixed_at_utc": None, "elapsed_calendar_days": None}
    first = history.get("first_fixed_at_utc")
    if first is None:
        # No observed FIXED transition is not evidence that none ever occurred.
        return {"state": "UNKNOWN", "first_fixed_at_utc": None, "elapsed_calendar_days": None}
    first_dt = parse_utc(first)
    if not first_dt or first_dt < created:
        return {"state": "UNKNOWN", "first_fixed_at_utc": None, "elapsed_calendar_days": None}
    return {"state": "VALID_EVENT_TIME", "first_fixed_at_utc": first,
            "elapsed_calendar_days": (first_dt - created).total_seconds() / 86400.0}


def parse_current_bug(payload, requested_id, observed_at=None):
    bugs = payload.get("bugs") if isinstance(payload, dict) else None
    if not isinstance(bugs, list) or len(bugs) != 1 or not isinstance(bugs[0], dict):
        return None, "unexpected_bug_shape"
    bug = bugs[0]
    if str(bug.get("id")) != str(requested_id):
        return None, "bug_id_mismatch"
    keep = ("id", "creation_time", "last_change_time", "product", "component",
            "status", "resolution", "is_open")
    current = {key: bug.get(key) for key in keep}
    current["missing_fields"] = [key for key in keep if key not in bug]
    current["creation_time"] = iso_utc(current["creation_time"])
    current["last_change_time"] = iso_utc(current["last_change_time"])
    observed = parse_utc(observed_at) if observed_at else None
    current["timestamp_qc"] = {}
    for key in ("creation_time", "last_change_time"):
        value = parse_utc(current[key]) if current[key] else None
        current["timestamp_qc"][key] = ("MISSING_OR_INVALID" if value is None else
            "AFTER_OBSERVATION" if observed and value > observed else "VALID")
    current["source_endpoint"] = "bug"
    current["source_visibility"] = "public_response"
    error = "missing_fields:" + ",".join(current["missing_fields"]) if current["missing_fields"] else None
    return current, error


def consistency_differences(snapshot, current):
    """Record comparisons without treating source-time disagreement as corruption."""
    mapping = {"snapshot_status": "status", "snapshot_resolution": "resolution",
               "product": "product", "component": "component"}
    diffs = []
    for source_key, current_key in mapping.items():
        old = snapshot.get(source_key)
        new = current.get(current_key)
        if old is not None and new is not None and str(old) != str(new):
            diffs.append({"field": current_key, "snapshot_value": old, "refresh_value": new,
                          "interpretation": "source_time_difference_requires_review"})
    if snapshot.get("opened_at_utc") and current.get("creation_time"):
        if iso_utc(snapshot["opened_at_utc"]) != current["creation_time"]:
            diffs.append({"field": "creation_time", "interpretation": "timestamp_disagreement"})
    return diffs


def parse_comments(payload, requested_id, observed_at=None):
    """Keep public comment metadata only; private/unknown bodies are withheld."""
    bugs = payload.get("bugs") if isinstance(payload, dict) else None
    node = bugs.get(str(requested_id)) if isinstance(bugs, dict) else None
    comments = node.get("comments") if isinstance(node, dict) else None
    if not isinstance(comments, list):
        return [], {"error": "unexpected_comment_shape", "public": 0,
                    "withheld": 0, "invalid_timestamp": 0}
    kept, withheld, invalid_timestamp, duplicate_rows = [], 0, 0, 0
    seen_comments = set()
    for comment in comments:
        if not isinstance(comment, dict):
            withheld += 1
            continue
        if comment.get("is_private") is not False:
            withheld += 1
            continue
        created = iso_utc(comment.get("creation_time"))
        observed = parse_utc(observed_at) if observed_at else None
        created_dt = parse_utc(created) if created else None
        if observed and (created_dt is None or created_dt > observed):
            invalid_timestamp += 1
            continue
        body = comment.get("text") if isinstance(comment.get("text"), str) else ""
        row = {"bug_id": int(requested_id), "comment_id": comment.get("id"),
                     "creation_time_utc": created,
                     "text_sha256": sha256_bytes(body.encode("utf-8")),
                     "text_available": bool(body),
                     "text": redact_emails(body),
                     "source_endpoint": "comment", "source_visibility": "public"}
        key = (row["bug_id"], str(row["comment_id"]) if row["comment_id"] is not None else None,
               row["creation_time_utc"], row["text_sha256"])
        if key in seen_comments:
            duplicate_rows += 1
            continue
        seen_comments.add(key)
        kept.append(row)
    return kept, {"error": None, "public": len(kept), "withheld": withheld,
                  "invalid_timestamp": invalid_timestamp, "duplicate_rows": duplicate_rows}


def parse_link_changes(changes, link_fields=None):
    """Extract targets only from explicitly configured relationship fields."""
    link_fields = link_fields or {}
    found = []
    for change in changes:
        field = change["field_name"]
        if field not in link_fields:
            continue
        for direction, value in (("removed", change["old_value"]), ("added", change["new_value"])):
            if not value:
                continue
            # Values are JSON strings produced above; parse without guessing a
            # relationship direction or interpreting unrelated numbers.
            try:
                decoded = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                decoded = value
            values = decoded if isinstance(decoded, list) else [decoded]
            for target in values:
                if isinstance(target, int) or (isinstance(target, str) and target.isdigit()):
                    target_id = int(target)
                elif isinstance(target, str):
                    match = re.search(r"(?:show_bug\.cgi\?id=|/bug/)(\d+)", target)
                    target_id = int(match.group(1)) if match else None
                else:
                    target_id = None
                if target_id:
                    found.append({"source_bug_id": change["bug_id"], "target_bug_id": target_id,
                                  "relation_field": field, "relation": link_fields[field],
                                  "event_time_utc": change["event_time_utc"],
                                  "source_endpoint": "history", "value_side": direction})
    return found


class RequestBudgetExceeded(RuntimeError):
    pass


class PublicBugzillaClient:
    """Unauthenticated, paced GET client. Inject opener/sleeper for tests."""

    def __init__(self, cache_dir, checkpoint, max_requests, timeout=30, pace_seconds=1.0,
                 opener=None, sleeper=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.checkpoint = checkpoint
        self.max_requests = int(max_requests)
        self.timeout = timeout
        self.pace_seconds = max(0.0, float(pace_seconds))
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper

    @staticmethod
    def _shape(payload):
        if not isinstance(payload, dict):
            return "non_object"
        bugs = payload.get("bugs")
        if isinstance(bugs, list):
            return "bugs_list:" + ("empty" if not bugs else ",".join(sorted(bugs[0].keys())[:12]) if isinstance(bugs[0], dict) else "item")
        if isinstance(bugs, dict):
            return "bugs_map"
        return "keys:" + ",".join(sorted(payload.keys())[:12])

    def _cache_path(self, bug_id, endpoint, attempt=None):
        suffix = f".attempt-{attempt:02d}" if attempt is not None else ""
        return self.cache_dir / str(bug_id) / (endpoint + suffix + ".json.gz")

    def get_json(self, bug_id, endpoint):
        url = f"{BASE_URL}/bug/{int(bug_id)}" + ("" if endpoint == "bug" else f"/{endpoint}")
        if endpoint == "bug":
            fields = "id,creation_time,last_change_time,product,component,status,resolution,is_open"
            url += "?include_fields=" + urllib.parse.quote(fields, safe=",")
        last_error = None
        for retry_number in range(1, MAX_RETRIES + 2):
            if self.checkpoint["requests_made"] >= self.max_requests:
                raise RequestBudgetExceeded("--max-requests budget exhausted")
            if self.checkpoint["requests_made"] > 0 and self.pace_seconds:
                self.sleeper(self.pace_seconds)
            self.checkpoint["requests_made"] += 1
            self.checkpoint["last_request_started_at_utc"] = utc_now()
            write_json(self.checkpoint["path"], self.checkpoint)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            status, headers, raw, error = None, {}, b"", None
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    status = int(response.status)
                    headers = dict(response.headers.items())
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    error = "response_too_large"
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                headers = dict(exc.headers.items()) if exc.headers else {}
                raw = exc.read(MAX_RESPONSE_BYTES + 1)
                error = f"http_{status}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                error = "network_error:" + type(exc).__name__
            fetched = utc_now()
            payload = None
            if status is not None and 200 <= status < 300 and error is None:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    error = "invalid_json"
            elif status is not None and error is None:
                error = f"http_{status}"
            if status is not None:
                prior_attempts = sum(1 for row in self.checkpoint.get("request_attempts", [])
                                     if row.get("bug_id") == int(bug_id) and row.get("endpoint") == endpoint)
                attempt_number = prior_attempts + 1
                envelope = {"url": url, "requested_bug_id": int(bug_id),
                            "endpoint": endpoint, "fetched_at_utc": fetched,
                            "attempt_number": attempt_number,
                            "status_code": status, "response_shape": self._shape(payload),
                            "client_schema_version": VERSION,
                            "bugzilla_server_version": headers.get("X-Bugzilla-Version") or
                                (payload.get("version") if isinstance(payload, dict) else None),
                            "source_visibility": "public_endpoint_response",
                            "error_label": error, "body_sha256": sha256_bytes(raw),
                            "body_utf8": raw.decode("utf-8", errors="replace")}
                for cache_path in (self._cache_path(bug_id, endpoint, attempt_number),
                                   self._cache_path(bug_id, endpoint)):
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temp = cache_path.with_suffix(cache_path.suffix + ".tmp")
                    with gzip.open(temp, "wt", encoding="utf-8") as stream:
                        json.dump(envelope, stream, ensure_ascii=True)
                    temp.replace(cache_path)
            item = {"bug_id": int(bug_id), "endpoint": endpoint, "url": url,
                    "fetched_at_utc": fetched, "status_code": status,
                    "response_shape": self._shape(payload), "cache_path": str(self._cache_path(bug_id, endpoint)),
                    "attempt_cache_path": str(self._cache_path(bug_id, endpoint,
                        sum(1 for row in self.checkpoint.get("request_attempts", [])
                            if row.get("bug_id") == int(bug_id) and row.get("endpoint") == endpoint) + 1)),
                    "raw_sha256": sha256_bytes(raw) if raw else None,
                    "source_visibility": "public_endpoint_response", "error_label": error,
                    "attempt": sum(1 for row in self.checkpoint.get("request_attempts", [])
                                   if row.get("bug_id") == int(bug_id) and row.get("endpoint") == endpoint) + 1,
                    "retry_number": retry_number}
            self.checkpoint.setdefault("request_attempts", []).append({k: v for k, v in item.items() if k != "payload"})
            write_json(self.checkpoint["path"], self.checkpoint)
            if payload is not None:
                item["payload"] = payload
                safe_item = {k: v for k, v in item.items() if k != "payload"}
                self.checkpoint["completed_endpoints"][f"{bug_id}:{endpoint}"] = safe_item
                self.checkpoint["endpoint_metadata"][f"{bug_id}:{endpoint}"] = safe_item
                write_json(self.checkpoint["path"], self.checkpoint)
                return item
            last_error = item
            retryable = status == 429 or (status is not None and 500 <= status <= 599) or status is None
            if not retryable or retry_number == MAX_RETRIES + 1:
                self.checkpoint["endpoint_metadata"][f"{bug_id}:{endpoint}"] = {k: v for k, v in item.items() if k != "payload"}
                write_json(self.checkpoint["path"], self.checkpoint)
                return item
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            delay = None
            if retry_after:
                try:
                    delay = max(0.0, float(retry_after))
                except ValueError:
                    try:
                        retry_dt = email.utils.parsedate_to_datetime(retry_after)
                        if retry_dt.tzinfo is None:
                            retry_dt = retry_dt.replace(tzinfo=timezone.utc)
                        delay = max(0.0, (retry_dt - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        delay = None
            if delay is None:
                delay = min(30.0, 2 ** (retry_number - 1))
            self.sleeper(delay)
        return last_error

    def cached_result(self, bug_id, endpoint):
        path = self._cache_path(bug_id, endpoint)
        if not path.is_file():
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                envelope = json.load(stream)
            body = envelope.get("body_utf8", "").encode("utf-8")
            if sha256_bytes(body) != envelope.get("body_sha256") or envelope.get("status_code") != 200:
                return None
            payload = json.loads(body.decode("utf-8"))
            item = dict(self.checkpoint.get("completed_endpoints", {}).get(f"{bug_id}:{endpoint}", {}))
            item["payload"] = payload
            return item
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None


def _read_candidate_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = manifest.get("candidates")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Candidate manifest has no candidates")
    if len(entries) > 300:
        raise ValueError("Phase 4 enrichment is hard-capped at 300 candidate bugs")
    try:
        bug_ids = [int(row["bug_id"]) for row in entries]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Candidate manifest contains an invalid bug ID") from exc
    if any(bug_id <= 0 for bug_id in bug_ids) or len(set(bug_ids)) != len(bug_ids):
        raise ValueError("Candidate IDs must be unique positive integers")
    check = digest({k: v for k, v in manifest.items() if k != "candidate_manifest_sha256"})
    if check != manifest.get("candidate_manifest_sha256"):
        raise ValueError("Candidate manifest hash mismatch")
    return manifest


def _run_dir(root, manifest):
    key = manifest["candidate_manifest_sha256"][:16]
    return Path(root) / "outputs/phase04/enrichment" / ("cohort-" + key)


def _load_checkpoint(path, run_dir, manifest, resume):
    if path.exists():
        if not resume:
            raise FileExistsError(f"Run exists; pass --resume to continue: {run_dir}")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("candidate_manifest_sha256") != manifest["candidate_manifest_sha256"]:
            raise ValueError("Checkpoint candidate manifest differs")
        state["path"] = str(path)
        return state
    state = {"schema_version": 1, "state": "RUNNING", "created_at_utc": utc_now(),
             "updated_at_utc": utc_now(), "candidate_manifest_sha256": manifest["candidate_manifest_sha256"],
             "baseline_run_id": manifest["baseline_run_id"], "requests_made": 0,
             "completed_endpoints": {}, "endpoint_metadata": {}, "candidate_results": {},
             "path": str(path)}
    write_json(path, state)
    return state


def _source_rows(root, manifest):
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB 1.4.4 is required for Phase 4 source comparisons") from exc
    db_path = Path(root) / manifest["baseline_duckdb_path"]
    db = duckdb.connect(str(db_path), read_only=True)
    try:
        ids = [str(x["bug_id"]) for x in manifest["candidates"]]
        # The query is constrained to the explicit manifest, at most 300 IDs.
        rows = db.execute("SELECT bug_id,product,component,snapshot_status,snapshot_resolution,CAST(opened_at_utc AS VARCHAR) FROM bugs WHERE bug_id IN (SELECT unnest(?))", [ids]).fetchall()
        result = {int(r[0]): {"bug_id": int(r[0]), "product": r[1], "component": r[2],
                            "snapshot_status": r[3], "snapshot_resolution": r[4],
                            "opened_at_utc": iso_utc(r[5])} for r in rows}
        comments = db.execute("""SELECT bug_id,comment_id,CAST(event_time_utc AS VARCHAR),
            CASE WHEN body IS NOT NULL AND length(trim(body))>0 THEN sha256(body) ELSE NULL END,
            body IS NOT NULL AND length(trim(body))>0
            FROM comments WHERE bug_id IN (SELECT unnest(?))""", [ids]).fetchall()
        index = defaultdict(list)
        for bug_id, comment_id, event_time, body_hash, has_text in comments:
            index[(int(bug_id), str(comment_id) if comment_id is not None else None)].append({
                "event_time_utc": iso_utc(event_time), "text_sha256": body_hash,
                "text_available": bool(has_text)})
        result["_base_comment_index"] = index
        return result
    finally:
        db.close()


def _endpoint_item(state, bug_id, endpoint):
    return state.get("completed_endpoints", {}).get(f"{bug_id}:{endpoint}")


def _needs_comments(candidate):
    return not candidate.get("csv_comment_count", 0) or int(candidate.get("csv_missing_text_count", 0)) > 0


def _endpoint_is_terminal(metadata):
    status = metadata.get("status_code")
    return status == 200 or (status is not None and 400 <= status < 500 and status != 429) or metadata.get("error_label") in (
        "invalid_json", "response_too_large")


def _candidate_comment_done(state, candidate):
    if not _needs_comments(candidate):
        return True
    bug_id = int(candidate["bug_id"])
    metadata = state.get("endpoint_metadata", {}).get(f"{bug_id}:comment", {})
    if metadata.get("status_code") == 200:
        result = state.get("candidate_results", {}).get(str(bug_id), {})
        return result.get("comment_qc", {}).get("error") is None
    return _endpoint_is_terminal(metadata) and metadata.get("status_code") != 200


def _candidate_complete(state, candidate, comments_enabled):
    bug_id = int(candidate["bug_id"])
    result = state.get("candidate_results", {}).get(str(bug_id), {})
    history_fetch, metadata_fetch = result.get("history_fetch", {}), result.get("metadata_fetch", {})
    return (history_fetch.get("status_code") == 200 and history_fetch.get("error_label") is None and
            metadata_fetch.get("status_code") == 200 and metadata_fetch.get("error_label") is None and
            result.get("metadata_error") is None and result.get("current_metadata") is not None and
            (not comments_enabled or _candidate_comment_done(state, candidate)))


def run_enrichment(args):
    root = Path(args.root).resolve()
    manifest = _read_candidate_manifest(args.manifest)
    entries = manifest["candidates"][:args.limit] if args.limit is not None else manifest["candidates"]
    if args.pilot:
        entries = [x for x in entries if x.get("pilot")]
        if args.limit is not None:
            entries = entries[:args.limit]
    run_dir = _run_dir(root, manifest)
    cache_dir = root / "outputs/phase04/api_cache"
    state_path = run_dir / "checkpoint.json"
    source_rows = _source_rows(root, manifest)
    if args.dry_run:
        requested = [x["bug_id"] for x in entries]
        missing_comments = sum(_needs_comments(x) for x in entries) if args.fetch_missing_comments else 0
        print(json.dumps({"dry_run": True, "candidate_count": len(entries), "bug_ids": requested,
                          "http_gets_without_retries": 2 * len(entries) + missing_comments,
                          "max_requests": args.max_requests, "comments_enabled": args.fetch_missing_comments,
                          "checkpoint": str(state_path), "cache": str(cache_dir)}, indent=2))
        return
    if args.max_requests is None or args.max_requests < 1:
        raise ValueError("Live enrichment requires an explicit positive --max-requests cap")
    run_dir.mkdir(parents=True, exist_ok=True)
    state = _load_checkpoint(state_path, run_dir, manifest, args.resume)
    if args.resume and state.get("state") == "COMPLETE":
        complete = all(_candidate_complete(state, x, args.fetch_missing_comments) for x in entries)
        if complete:
            prior_summary = run_dir / "summary.json"
            if prior_summary.is_file():
                print(json.dumps({"state": "ALREADY_COMPLETE", "run_dir": str(run_dir),
                                  "summary": str(prior_summary), "requests_made": state["requests_made"]}, indent=2))
                return
    state.pop("path", None)
    state["path"] = str(state_path)
    state["state"] = "RUNNING"
    client = PublicBugzillaClient(cache_dir, state, args.max_requests,
                                  timeout=args.timeout, pace_seconds=args.pace_seconds)
    for candidate_index, candidate in enumerate(entries, 1):
        bug_id = int(candidate["bug_id"])
        print(f"[{utc_now()}] Phase 4 candidate {candidate_index}/{len(entries)} bug_id={bug_id}", flush=True)
        result = state["candidate_results"].setdefault(str(bug_id), {"bug_id": bug_id})
        # History is intentionally first: it is the only source of field-change event times.
        for endpoint in ("history", "bug"):
            prior_completed = _endpoint_item(state, bug_id, endpoint)
            if prior_completed:
                response = client.cached_result(bug_id, endpoint)
            else:
                response = None
            prior = state.get("endpoint_metadata", {}).get(f"{bug_id}:{endpoint}", {})
            if prior_completed and response is None:
                result["resume_cache_error"] = f"missing_or_invalid_cache:{endpoint}"
            if response is None and prior and _endpoint_is_terminal(prior) and prior.get("status_code") != 200:
                continue
            if response is None:
                try:
                    response = client.get_json(bug_id, endpoint)
                except RequestBudgetExceeded:
                    state["state"] = "INTERRUPTED_REQUEST_BUDGET"
                    break
            if response and response.get("payload") is not None:
                payload = response["payload"]
                if endpoint == "history":
                    created = source_rows.get(bug_id, {}).get("opened_at_utc")
                    parsed = parse_api_history(payload, bug_id, created, response.get("fetched_at_utc"))
                    result["history"] = {k: v for k, v in parsed.items() if k != "changes"}
                    result["changes"] = parsed.get("changes", [])
                    result["history_fetch"] = {k: v for k, v in response.items() if k != "payload"}
                else:
                    current, error = parse_current_bug(payload, bug_id, response.get("fetched_at_utc"))
                    result["current_metadata"] = current
                    result["metadata_error"] = error
                    result["metadata_fetch"] = {k: v for k, v in response.items() if k != "payload"}
                    if current:
                        result["source_consistency_differences"] = consistency_differences(source_rows.get(bug_id, {}), current)
                state["updated_at_utc"] = utc_now()
                write_json(state_path, state)
        if state.get("state") == "INTERRUPTED_REQUEST_BUDGET":
            break
        if args.fetch_missing_comments and _needs_comments(candidate) and not result.get("comments_fetch"):
            cached = client.cached_result(bug_id, "comment") if _endpoint_item(state, bug_id, "comment") else None
            if cached:
                response = cached
            else:
                prior = state.get("endpoint_metadata", {}).get(f"{bug_id}:comment", {})
                response = None
                if not (prior and _endpoint_is_terminal(prior) and prior.get("status_code") != 200):
                    try:
                        response = client.get_json(bug_id, "comment")
                    except RequestBudgetExceeded:
                        state["state"] = "INTERRUPTED_REQUEST_BUDGET"
                        break
                    if response and response.get("payload") is not None:
                        comments, qc = parse_comments(response["payload"], bug_id, response.get("fetched_at_utc"))
                        result["public_comments"] = comments
                        result["comment_qc"] = qc
                        result["comments_fetch"] = {k: v for k, v in response.items() if k != "payload"}
            if response and response.get("payload") is not None and not result.get("comments_fetch"):
                comments, qc = parse_comments(response["payload"], bug_id, response.get("fetched_at_utc"))
                result["public_comments"] = comments
                result["comment_qc"] = qc
                result["comments_fetch"] = {k: v for k, v in response.items() if k != "payload"}
        if result.get("history"):
            result["fix_metric"] = classify_first_fixed(result["history"],
                (result.get("current_metadata") or {}).get("creation_time") or source_rows.get(bug_id, {}).get("opened_at_utc"),
                (result.get("current_metadata") or {}).get("resolution"))
        state["updated_at_utc"] = utc_now()
        write_json(state_path, state)
    if state.get("state") == "RUNNING":
        state["state"] = "COMPLETE" if all(
            _candidate_complete(state, x, args.fetch_missing_comments) for x in entries) else "PARTIAL"
    state["updated_at_utc"] = utc_now()
    state["candidate_count_requested"] = len(entries)
    state["request_budget_cap"] = args.max_requests
    write_json(state_path, state)
    build_enrichment_outputs(root, run_dir, manifest, state, source_rows, args.link_field)
    latest_temp = run_dir.parent / "LATEST_RUN.tmp"
    latest_temp.write_text(run_dir.name + "\n", encoding="utf-8")
    latest_temp.replace(run_dir.parent / "LATEST_RUN")
    print(json.dumps({"state": state["state"], "run_dir": str(run_dir),
                      "requests_made": state["requests_made"], "request_cap": args.max_requests,
                      "candidate_count": len(entries), "summary": str(run_dir / "summary.json")}, indent=2))


def build_enrichment_outputs(root, run_dir, manifest, state, source_rows, link_field_args=()):
    links_config = {}
    for item in link_field_args or ():
        if "=" not in item:
            raise ValueError("--link-field must use FIELD=RELATION")
        field, relation = item.split("=", 1)
        links_config[field] = relation
    field_changes, link_changes, refreshes, comments = [], [], [], []
    duplicate_comments_skipped, source_conflict_comments, empty_text_filled = 0, 0, 0
    invalid_link_timestamps = 0
    candidate_index = {int(x["bug_id"]): x for x in manifest.get("candidates", [])}
    for bug_text, result in state.get("candidate_results", {}).items():
        bug_id = int(bug_text)
        history = result.get("history", {})
        fetched = result.get("history_fetch", {}).get("fetched_at_utc")
        for index, change in enumerate(result.get("changes", [])):
            source_key = digest({"bug_id": bug_id, "event_index": change["event_index"],
                                 "change_index": change["change_index"], "change": change})
            record = {"bug_id": bug_id, "source_dataset": "bugzilla_rest_history",
                      "source_row_key": source_key, "source_url": f"{BASE_URL}/bug/{bug_id}/history",
                      "event_time_utc": change["event_time_utc"], "observed_at_utc": fetched,
                      "ingested_at_utc": state.get("updated_at_utc"), "text_available": False,
                      "raw_field_mapping": {"when": "event_time_utc", "field_name": "field_name",
                                            "removed": "old_value", "added": "new_value"},
                      "content_sha256": digest(change), "field_name": change["field_name"],
                      "old_value": change["old_value"], "new_value": change["new_value"],
                      "actor_pseudonym": change["actor_pseudonym"], "event_index": change["event_index"],
                      "change_index": change["change_index"], "history_state": history.get("state")}
            field_changes.append(record)
        fetched_dt = parse_utc(fetched) if fetched else None
        created_dt = parse_utc(source_rows.get(bug_id, {}).get("opened_at_utc"))
        link_changes_raw = parse_link_changes(result.get("changes", []), links_config)
        parsed_links = []
        for link in link_changes_raw:
            event_dt = parse_utc(link.get("event_time_utc"))
            if event_dt is None or (fetched_dt and event_dt > fetched_dt) or (created_dt and event_dt < created_dt):
                invalid_link_timestamps += 1
                continue
            parsed_links.append(link)
        for link in parsed_links:
            link["source_dataset"] = "bugzilla_rest_history"
            link["source_url"] = f"{BASE_URL}/bug/{bug_id}/history"
            link["observed_at_utc"] = fetched
            link["ingested_at_utc"] = state.get("updated_at_utc")
            link["text_available"] = False
            link["raw_field_mapping"] = {"field_name": "relation_field",
                                          "removed_or_added": "target_bug_id",
                                          "when": "event_time_utc"}
            link["content_sha256"] = digest(link)
            link["source_row_key"] = digest(link)
        link_changes.extend(parsed_links)
        current = result.get("current_metadata")
        if current:
            refresh = dict(current)
            refresh.update({"bug_id": bug_id, "observed_at_utc": result.get("metadata_fetch", {}).get("fetched_at_utc"),
                            "source_url": f"{BASE_URL}/bug/{bug_id}",
                            "source_dataset": "bugzilla_rest_current_refresh",
                            "source_row_key": digest({"bug_id": bug_id, "metadata": current}),
                            "event_time_utc": None,
                            "ingested_at_utc": state.get("updated_at_utc"),
                            "text_available": False,
                            "raw_field_mapping": {"id": "bug_id", "creation_time": "creation_time",
                                                  "last_change_time": "last_change_time", "product": "product",
                                                  "component": "component", "status": "status",
                                                  "resolution": "resolution", "is_open": "is_open"},
                            "content_sha256": digest(current),
                            "snapshot_as_of_utc": None})
            refreshes.append(refresh)
        comment_fetch = result.get("comments_fetch", {})
        for comment in result.get("public_comments", []):
            base_versions = source_rows.get("_base_comment_index", {}).get(
                (bug_id, str(comment.get("comment_id")) if comment.get("comment_id") is not None else None), [])
            api_event = iso_utc(comment.get("creation_time_utc"))
            exact = any(x.get("event_time_utc") == api_event and
                        x.get("text_sha256") == comment.get("text_sha256") for x in base_versions)
            if exact:
                duplicate_comments_skipped += 1
                continue
            if any(not x.get("text_available") for x in base_versions):
                empty_text_filled += 1
            elif base_versions:
                source_conflict_comments += 1
            row = dict(comment)
            row.update({"source_dataset": "bugzilla_rest_comment",
                        "source_url": f"{BASE_URL}/bug/{bug_id}/comment",
                        "event_time_utc": row.get("creation_time_utc"),
                        "observed_at_utc": comment_fetch.get("fetched_at_utc"),
                        "ingested_at_utc": state.get("updated_at_utc"),
                        "source_row_key": digest({"bug_id": bug_id, "comment_id": row.get("comment_id"),
                                                   "creation_time_utc": row.get("creation_time_utc"),
                                                   "text_sha256": row.get("text_sha256")}),
                        "raw_field_mapping": {"id": "comment_id", "creation_time": "event_time_utc",
                                              "text": "text", "is_private": "visibility"},
                        "content_sha256": row.get("text_sha256")})
            row["fills_empty_csv_text"] = any(not x.get("text_available") for x in base_versions)
            row["source_conflict"] = bool(base_versions and not row["fills_empty_csv_text"])
            comments.append(row)
    # Metadata fetch provenance lives beside its normalized payload.
    for bug_text, result in state.get("candidate_results", {}).items():
        current = result.get("current_metadata")
        fetch = result.get("metadata_fetch") or state.get("endpoint_metadata", {}).get(f"{bug_text}:bug")
        if current and fetch:
            current["fetched_at_utc"] = fetch.get("fetched_at_utc")
            result["metadata_fetch"] = fetch
    # Rebuild these bounded outputs atomically from the checkpoint; base Phase 3B
    # artifacts remain immutable and are never rewritten.
    imported = import_field_changes(field_changes)
    rejected_report = {"rejected_count": imported["rejected_count"],
                       "rejections_by_reason": dict(Counter(x["reason"] for x in imported["rejected"])),
                       "rejected_row_numbers": [x["row"] for x in imported["rejected"]]}
    field_changes = imported["accepted"]
    field_path = run_dir / "field_changes.jsonl"
    temp_field = field_path.with_suffix(".jsonl.tmp")
    with temp_field.open("w", encoding="utf-8") as stream:
        for row in field_changes:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")
    temp_field.replace(field_path)
    link_path = run_dir / "api_link_changes.json"
    write_json(link_path, link_changes)
    refresh_path = run_dir / "api_bug_refresh.json"
    write_json(refresh_path, refreshes)
    comment_path = run_dir / "api_comments.json"
    write_json(comment_path, comments)
    rejected_path = run_dir / "field_changes_rejected.json"
    write_json(rejected_path, rejected_report)
    _write_overlay_duckdb(run_dir / "api_enrichment.duckdb", field_changes, refreshes, link_changes, comments)
    summary = {
        "schema_version": 1, "state": state.get("state"), "run_id": run_dir.name,
        "generated_at_utc": utc_now(), "started_at_utc": state.get("created_at_utc"),
        "updated_at_utc": state.get("updated_at_utc"),
        "log_path": os.environ.get("PHASE04_LOG_PATH"),
        "baseline_run_id": manifest["baseline_run_id"],
        "candidate_manifest_sha256": manifest["candidate_manifest_sha256"],
        "candidate_count": len(state.get("candidate_results", {})),
        "candidate_count_requested": state.get("candidate_count_requested"),
        "successful_histories": sum(x.get("history_fetch", {}).get("status_code") == 200 and
                                     not x.get("history_fetch", {}).get("error_label")
                                     for x in state.get("candidate_results", {}).values()),
        "successful_current_metadata": sum(x.get("metadata_fetch", {}).get("status_code") == 200 and
                                            not x.get("metadata_fetch", {}).get("error_label") and
                                            x.get("metadata_error") is None and x.get("current_metadata") is not None
                                            for x in state.get("candidate_results", {}).values()),
        "current_metadata_parse_errors": sum(x.get("metadata_error") is not None
                                              for x in state.get("candidate_results", {}).values()),
        "inaccessible_history_responses": sum(state.get("endpoint_metadata", {}).get(
            f"{x.get('bug_id')}:history", {}).get("status_code") in (403, 404, 410)
            for x in state.get("candidate_results", {}).values()),
        "history_error_labels": dict(Counter(meta.get("error_label") or "none"
            for key, meta in state.get("endpoint_metadata", {}).items() if key.endswith(":history"))),
        "parseable_histories": sum(x.get("history", {}).get("state") == "PARSED"
                                    for x in state.get("candidate_results", {}).values()),
        "reordered_history_responses": sum(bool(x.get("history", {}).get("reordered"))
                                            for x in state.get("candidate_results", {}).values()),
        "same_time_history_event_groups": sum(x.get("history", {}).get("same_time_groups", 0)
                                               for x in state.get("candidate_results", {}).values()),
        "duplicate_history_changes_deduplicated": sum(x.get("history", {}).get("duplicate_change_count", 0)
                                                       for x in state.get("candidate_results", {}).values()),
        "malformed_history_fields": sum(x.get("history", {}).get("malformed_count", 0)
                                         for x in state.get("candidate_results", {}).values()),
        "history_events_after_observation": sum(bool(x.get("history", {}).get("future_event_after_observed_at"))
                                                for x in state.get("candidate_results", {}).values()),
        "parseable_fixed_transitions": sum(bool(x.get("history", {}).get("first_fixed_at_utc"))
                                            for x in state.get("candidate_results", {}).values()),
        "valid_f2_cases": sum(x.get("fix_metric", {}).get("state") == "VALID_EVENT_TIME"
                              for x in state.get("candidate_results", {}).values()),
        "unknown_or_insufficient_f2_cases": max(0, state.get("candidate_count_requested", 0) - sum(
            x.get("fix_metric", {}).get("state") == "VALID_EVENT_TIME"
            for x in state.get("candidate_results", {}).values())),
        "reopened_events": sum(x.get("history", {}).get("reopened_count", 0)
                               for x in state.get("candidate_results", {}).values()),
        "source_consistency_differences": sum(len(x.get("source_consistency_differences", []))
                                              for x in state.get("candidate_results", {}).values()),
        "current_metadata_timestamp_anomalies": sum(sum(v != "VALID" for v in
            (x.get("current_metadata", {}).get("timestamp_qc") or {}).values())
            for x in state.get("candidate_results", {}).values()),
        "field_change_rows": len(field_changes), "explicit_link_events": len(link_changes),
        "field_change_rows_rejected": imported["rejected_count"],
        "field_change_rejections_by_reason": rejected_report["rejections_by_reason"],
        "field_name_counts": dict(Counter(row["field_name"] for row in field_changes)),
        "api_link_timestamp_rejections": invalid_link_timestamps,
        "configured_link_fields": links_config,
        "source_candidates_with_csv_links": sum(bool(candidate_index.get(int(bug_id), {}).get("explicit_link_count"))
                                                  for bug_id in state.get("candidate_results", {})),
        "candidate_ids_with_parsed_api_links": len({x["source_bug_id"] for x in link_changes}),
        "comment_endpoint_error_labels": dict(Counter(meta.get("error_label") or "none"
            for key, meta in state.get("endpoint_metadata", {}).items() if key.endswith(":comment"))),
        "comment_response_parse_errors": sum(x.get("comment_qc", {}).get("error") is not None
                                              for x in state.get("candidate_results", {}).values()),
        "public_comments": len(comments),
        "duplicate_rows_in_api_comment_response": sum(x.get("comment_qc", {}).get("duplicate_rows", 0)
                                                       for x in state.get("candidate_results", {}).values()),
        "duplicate_api_comments_matching_csv_skipped": duplicate_comments_skipped,
        "api_comments_filling_empty_csv_text": empty_text_filled,
        "api_comments_retained_as_source_conflicts": source_conflict_comments,
        "withheld_private_or_unknown_comments": sum(x.get("comment_qc", {}).get("withheld", 0)
                                                     for x in state.get("candidate_results", {}).values()),
        "comments_rejected_for_timestamp": sum(x.get("comment_qc", {}).get("invalid_timestamp", 0)
                                                for x in state.get("candidate_results", {}).values()),
        "requests_made_including_retries": state.get("requests_made", 0),
        "request_cap": state.get("request_budget_cap"),
        "timestamp_semantics": {"event_time": "API history event when", "observed_at": "response fetched_at_utc",
                                "ingested_at": "local normalization checkpoint time"},
        "source_snapshot_as_of_utc": None,
        "artifacts": {p.name: {"path": p.name, "size_bytes": p.stat().st_size,
                               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in (field_path, link_path, refresh_path, comment_path, rejected_path,
                                run_dir / "api_enrichment.duckdb")
                      if p.is_file()},
        "api_response_manifest": [meta for meta in state.get("endpoint_metadata", {}).values()],
        "request_attempts_by_status": dict(Counter(str(x.get("status_code") or "NETWORK_ERROR")
                                                     for x in state.get("request_attempts", []))),
        "warning": "Current API metadata is an observed refresh, not the archive snapshot and not an earlier T0.",
    }
    write_json(run_dir / "summary.json", summary)
    # Checkpoint is machine-local/ignored; never write its raw history values to tracked documentation.
    state.pop("path", None)
    write_json(run_dir / "checkpoint.json", state)
    return summary


FIELD_CHANGE_REQUIRED = {"bug_id", "source_dataset", "source_row_key", "source_url",
                         "event_time_utc", "observed_at_utc", "ingested_at_utc",
                         "text_available", "raw_field_mapping", "content_sha256", "field_name"}


def import_field_changes(records):
    """Validate canonical Phase 4 history rows before loading a sidecar store."""
    seen = set()
    accepted = []
    rejected = []
    for index, row in enumerate(records):
        missing = sorted(FIELD_CHANGE_REQUIRED - set(row))
        if missing:
            rejected.append({"row": index, "reason": "missing_required_fields", "fields": missing})
            continue
        if (not isinstance(row["bug_id"], int) or not row["source_row_key"] or
                not re.fullmatch(r"[0-9a-f]{64}", str(row["content_sha256"])) or
                not isinstance(row["raw_field_mapping"], dict) or
                not isinstance(row["text_available"], bool) or
                not str(row["source_url"]).startswith(BASE_URL + "/bug/")):
            rejected.append({"row": index, "reason": "invalid_identity_or_hash"})
            continue
        event, observed, ingested = (parse_utc(row[x]) for x in
                                     ("event_time_utc", "observed_at_utc", "ingested_at_utc"))
        if (event is None or observed is None or ingested is None or event > observed or
                ingested < observed):
            rejected.append({"row": index, "reason": "invalid_or_future_event_timestamp"})
            continue
        if row["source_row_key"] in seen:
            rejected.append({"row": index, "reason": "duplicate_source_row_key"})
            continue
        seen.add(row["source_row_key"])
        accepted.append(row)
    return {"accepted": accepted, "rejected": rejected,
            "accepted_count": len(accepted), "rejected_count": len(rejected)}


def _write_overlay_duckdb(path, field_changes, refreshes, link_changes, comments):
    """Build a separate, reproducible queryable API overlay; never alters Phase 3B."""
    try:
        import duckdb
    except ImportError:
        return False
    path = Path(path)
    db = duckdb.connect(str(path))
    try:
        db.execute("CREATE OR REPLACE TABLE field_changes AS SELECT * FROM (SELECT 1 AS _empty) WHERE false")
        if field_changes:
            valid = import_field_changes(field_changes)
            if valid["rejected"]:
                raise ValueError(f"Rejected {valid['rejected_count']} field-change rows")
            columns = sorted(field_changes[0])
            db.execute("DROP TABLE field_changes")
            types = []
            for name in columns:
                if name == "bug_id" or name in ("event_index", "change_index"):
                    typ = "BIGINT"
                elif name == "text_available":
                    typ = "BOOLEAN"
                elif name == "raw_field_mapping":
                    typ = "JSON"
                else:
                    typ = "VARCHAR"
                types.append('"' + name + '" ' + typ)
            db.execute("CREATE TABLE field_changes (" + ",".join(types) + ")")
            placeholders = ",".join("?" for _ in columns)
            quoted_columns = ",".join('"' + name + '"' for name in columns)
            for row in field_changes:
                values = [json.dumps(row[name], sort_keys=True) if name == "raw_field_mapping" else row.get(name)
                          for name in columns]
                db.execute(f"INSERT INTO field_changes ({quoted_columns}) VALUES ({placeholders})", values)
        for table, rows in (("api_bug_refresh", refreshes), ("api_link_changes", link_changes),
                            ("api_comments", comments)):
            db.execute(f"CREATE OR REPLACE TABLE {table} (row_json JSON)")
            for row in rows:
                db.execute(f"INSERT INTO {table} VALUES (?)", [json.dumps(row, ensure_ascii=True)])
    finally:
        db.close()
    return True


def temporal_eligibility(records, cutoff, mode="strict"):
    cutoff_dt = parse_utc(cutoff)
    if cutoff_dt is None:
        raise ValueError("Cutoff must be an ISO-8601 timestamp with timezone")
    if mode not in ("strict", "retrospective-replay"):
        raise ValueError("Mode must be strict or retrospective-replay")
    eligible, excluded = [], Counter()
    for row in records:
        event = parse_utc(row.get("event_time_utc"))
        observed = parse_utc(row.get("observed_at_utc"))
        ingested = parse_utc(row.get("ingested_at_utc"))
        if event is None:
            excluded["missing_or_invalid_event_time"] += 1
            continue
        if event > cutoff_dt:
            excluded["event_after_cutoff"] += 1
            continue
        if mode == "strict":
            if observed is None or observed > cutoff_dt:
                excluded["not_observed_by_cutoff"] += 1
                continue
            if ingested is None or ingested > cutoff_dt:
                excluded["not_ingested_by_cutoff"] += 1
                continue
        else:
            # This is a historical replay assumption, not evidence of past
            # system availability. Observed/ingested dates remain reported.
            pass
        eligible.append(row)
    return {"mode": mode, "cutoff_utc": cutoff_dt.isoformat().replace("+00:00", "Z"),
            "eligible_count": len(eligible), "excluded_counts": dict(excluded),
            "eligible_source_row_keys": [x.get("source_row_key") for x in eligible],
            "interpretation": ("Observed and ingested by cutoff; strict availability evidence for this API overlay only."
                if mode == "strict" else
                "RETROSPECTIVE REPLAY: event dates are replayed retrospectively; this does not prove availability by cutoff.")}


def command_temporal_qc(args):
    root = Path(args.root).resolve()
    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    if run_dir is None:
        base = root / "outputs/phase04/enrichment"
        if not (base / "LATEST_RUN").is_file():
            raise ValueError("No Phase 4 LATEST_RUN; pass --run-dir after enrichment")
        run_dir = base / (base / "LATEST_RUN").read_text(encoding="utf-8").strip()
    source_files = {"field_changes": run_dir / "field_changes.jsonl",
                    "api_comments": run_dir / "api_comments.json",
                    "api_link_changes": run_dir / "api_link_changes.json"}
    source_rows = {}
    for name, path in source_files.items():
        if not path.is_file():
            source_rows[name] = []
            continue
        if path.suffix == ".jsonl":
            raw_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            raw_rows = json.loads(path.read_text(encoding="utf-8"))
        # Whitelist timestamps and stable keys so comment bodies or field values
        # can never enter the QC report or terminal summary.
        source_rows[name] = [{key: row.get(key) for key in
            ("source_row_key", "event_time_utc", "observed_at_utc", "ingested_at_utc")}
            for row in raw_rows if isinstance(row, dict)]
    by_source = {}
    all_rows = []
    for name, rows in source_rows.items():
        result = temporal_eligibility(rows, args.cutoff, args.mode)
        by_source[name] = {"input_count": len(rows), "eligible_count": result["eligible_count"],
                           "excluded_counts": result["excluded_counts"]}
        all_rows.extend(rows)
    report = temporal_eligibility(all_rows, args.cutoff, args.mode)
    refresh_path = run_dir / "api_bug_refresh.json"
    refresh_rows = json.loads(refresh_path.read_text(encoding="utf-8")) if refresh_path.is_file() else []
    cutoff_dt = parse_utc(args.cutoff)
    refresh_counts = Counter()
    for row in refresh_rows:
        observed, ingested = parse_utc(row.get("observed_at_utc")), parse_utc(row.get("ingested_at_utc"))
        if observed is None or ingested is None:
            refresh_counts["missing_or_invalid_availability_time"] += 1
        elif observed <= cutoff_dt and ingested <= cutoff_dt:
            refresh_counts["available_as_current_refresh_by_cutoff"] += 1
        else:
            refresh_counts["not_available_by_cutoff"] += 1
    report.update({"run_dir": str(run_dir), "event_evidence_by_source": by_source,
                   "current_refresh_rows": len(refresh_rows),
                   "current_refresh_availability_counts": dict(refresh_counts),
                   "field_changes_input": source_files["field_changes"].name if source_files["field_changes"].exists() else None,
                   "generated_at_utc": utc_now(), "log_path": os.environ.get("PHASE04_LOG_PATH"),
                   "candidate_status_snapshot_cutoff_proven": False,
                   "api_current_metadata_eligible_as_historical": False,
                   "csv_comment_historical_availability_proven": False,
                   "source_snapshot_as_of_utc": None})
    if args.dry_run:
        print(json.dumps({"dry_run": True, **{k: v for k, v in report.items()
                                               if k != "eligible_source_row_keys"}}, indent=2))
        return
    out = run_dir / "temporal_qc" / (args.mode + "-" + args.cutoff.replace(":", "").replace("-", ""))
    out.mkdir(parents=True, exist_ok=True)
    report["report_json"] = "temporal_qc.json"
    write_json(out / "temporal_qc.json", report)
    print(json.dumps({"state": "COMPLETE", "report": str(out / "temporal_qc.json"),
                      "eligible_count": report["eligible_count"], "mode": args.mode,
                      "cutoff_utc": report["cutoff_utc"]}, indent=2))


def _latest_candidate_manifest(root):
    base = Path(root) / "outputs/phase04/candidates"
    pointer = base / "LATEST_RUN"
    if not pointer.is_file():
        raise ValueError("No candidate plan. First run phase04 plan to create one.")
    return base / pointer.read_text(encoding="utf-8").strip() / "candidate_manifest.json"


def build_parser():
    parser = argparse.ArgumentParser(description="Bounded Phase 4 Bugzilla evidence enrichment (network commands are user-run only).")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="offline local evidence gap and deterministic candidate plan")
    plan.add_argument("--root", default=".")
    plan.add_argument("--baseline-run")
    plan.add_argument("--seed", type=int, default=317)
    plan.add_argument("--pilot-size", type=int, default=50)
    plan.add_argument("--study-size", type=int, default=200)
    plan.add_argument("--dry-run", action="store_true")
    plan.set_defaults(func=command_plan)

    def enrich_args(p, smoke=False):
        p.add_argument("--root", default=".")
        p.add_argument("--manifest")
        p.add_argument("--pilot", action="store_true")
        if not smoke:
            p.add_argument("--limit", type=int)
        p.add_argument("--max-requests", type=int)
        p.add_argument("--resume", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--no-comments", dest="fetch_missing_comments", action="store_false")
        p.set_defaults(fetch_missing_comments=not smoke)
        p.add_argument("--timeout", type=int, default=30)
        p.add_argument("--pace-seconds", type=float, default=1.0)
        p.add_argument("--link-field", action="append", default=[], metavar="FIELD=RELATION")
        if smoke:
            p.add_argument("--max-ids", "--limit", type=int, choices=range(5, MAX_SMOKE_IDS + 1), default=5)
            p.set_defaults(pilot=True, limit=None)
        p.set_defaults(func=command_enrich)

    smoke = sub.add_parser("smoke", help="user-run, public API shape smoke; capped at 5-10 IDs")
    enrich_args(smoke, smoke=True)
    enrich = sub.add_parser("enrich", help="user-run selective API enrichment")
    enrich_args(enrich)
    enrich.add_argument("--study", action="store_true", help="select full planned candidate cohort (default selects pilot)")

    temporal = sub.add_parser("temporal-qc", help="offline event/observed/ingested cutoff eligibility")
    temporal.add_argument("--root", default=".")
    temporal.add_argument("--run-dir")
    temporal.add_argument("--cutoff", required=True)
    temporal.add_argument("--mode", choices=("strict", "retrospective-replay"), default="strict")
    temporal.add_argument("--dry-run", action="store_true")
    temporal.set_defaults(func=command_temporal_qc)
    return parser


def command_enrich(args):
    if args.command == "smoke":
        requested = args.max_ids
        args.limit = requested
        args.pilot = True
        args.fetch_missing_comments = False
        if args.max_requests is None:
            args.max_requests = 8 * requested
        if args.max_requests > 8 * requested:
            raise ValueError("Smoke request cap must not exceed four attempts per endpoint")
    if getattr(args, "study", False):
        args.pilot = False
    elif args.command == "enrich":
        args.pilot = True
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")
    if args.max_requests is None and not args.dry_run:
        raise ValueError("User-run network access requires explicit --max-requests")
    if args.manifest is None:
        args.manifest = str(_latest_candidate_manifest(args.root))
    run_enrichment(args)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, RuntimeError, FileExistsError, RequestBudgetExceeded) as exc:
        parser.exit(2, f"phase04: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
