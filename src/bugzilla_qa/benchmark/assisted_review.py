"""Offline, read-only Phase 5 evidence checks and sanitized review packets.

This tool produces deterministic checks and source packets. It does not approve,
correct, reject, freeze, regenerate, or send questions to a model/API.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import duckdb

from bugzilla_qa.benchmark import phase05
from bugzilla_qa.data import phase04 as p4
from bugzilla_qa.data.normalize import digest, file_hash, write_json

VERSION = "phase05-assisted-review-v1"
STATIC_COLUMNS = ("qid", "family", "split", "required", "optional_second_rater",
                  "question", "suggested_gold_json", "evidence_json", "query_json", "rubric")
QUEUE_COLUMNS = STATIC_COLUMNS + phase05.USER_COLUMNS
BASE_DUCKDB_REL = "outputs/normalization/phase03b/run-20261022T023542Z-1182018/canonical.duckdb"
LIKELY_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:['’][A-Za-z]+)?\b")
UPPER_NAME_RE = re.compile(r"\b[A-Z][A-Z'-]{2,}(?:\s+[A-Z][A-Z'-]{2,})+\b")
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z][\w.-]*")
URL_RE = re.compile(r"https?://[^\s<>\]\[(){}]+", re.I)
EFFORT_RE = r"(?i)(spent|worked|person|engineer).{0,35}(hours?|hrs?)"
SAFE_CAPITALIZED = {
    "a", "about", "after", "again", "all", "also", "an", "and", "any", "api", "are", "as",
    "at", "because", "before", "both", "browser", "bug", "bugzilla", "but", "by", "can", "cannot",
    "chrome", "css", "current", "did", "do", "does", "dom", "each", "engine", "even", "expected",
    "first", "firefox", "for", "from", "get", "has", "have", "he", "hello", "here", "hi", "how",
    "however", "https", "i", "if", "in", "instead", "is", "it", "javascript", "just", "linux", "macos",
    "maybe", "mozilla", "must", "my", "new", "next", "no", "not", "now", "of", "on", "one", "only",
    "or", "other", "our", "please", "probably", "release", "same", "since", "so", "some", "still",
    "such", "thanks", "that", "the", "their", "then", "there", "these", "they", "this", "those",
    "through", "to", "today", "try", "ui", "unless", "until", "url", "use", "using", "was", "we",
    "web", "were", "what", "when", "where", "which", "while", "who", "why", "will", "with", "would",
    "yes", "you", "your", "json", "http", "https", "html", "css", "sql", "utc", "qa", "ctqrs",
    "android", "ios", "rust", "python", "windows", "xul", "gecko", "thunderbird", "webrender", "nimbus",
    "settings", "system", "preferences", "toolkit", "core", "desktop", "nightly", "beta", "console",
}
NAME_GREETING_RE = re.compile(r"(?i)\b(hi|hello|dear|thanks|regards|best|sincerely|cheers)[,!]?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
SIGNOFF_LINE_RE = re.compile(r"(?im)^\s*(?:--\s*)?(?:thanks|regards|best|sincerely|cheers|thank you)[,!]?\s*$\n?[^\n]{0,100}")
CODE_OR_LOG_RE = re.compile(r"(?im)(```|^\s{4,}\S|\bTraceback \(most recent call last\)|\b(?:ERROR|WARN|INFO):|\b(?:at|from) [\w.$]+\([^\n]*:\d+\)|(?:[A-Za-z0-9_.-]+/){2,}[A-Za-z0-9_.-]+|\b\w+\.(?:js|mjs|cpp|h|py|rs|log)\b)")
RATIONALE_MARKERS_RE = re.compile(r"(?i)\b(?:because|due to|blocked by|waiting for|delayed by|reason is|caused by)\b")
HEDGE_RE = re.compile(r"(?i)\b(?:maybe|might|could|possibly|perhaps|unclear|not sure|depending on|seems?)\b")
CONTRADICTION_RE = re.compile(r"(?i)\b(?:not because|not due to|isn't due to|is not due to|not the reason|unrelated to)\b")
TRIVIAL_BECAUSE_RE = re.compile(r"(?i)\bbecause\s+(?:it is|it's|that is|that's|of this|we can|i can|it helps|it works|it does)\b")


def utc(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def status(checks):
    """FAIL dominates, then UNKNOWN; empty/missing evidence never passes."""
    if any(value is False for value in checks):
        return "FAIL"
    if not checks or any(value is None for value in checks):
        return "UNKNOWN"
    return "PASS"


def safe_comment_text(value):
    """Conservatively scrub contact handles and likely person/proper-name tokens."""
    text = EMAIL_RE.sub("[email]", value or "")
    text = HANDLE_RE.sub("[handle]", text)
    text = re.sub(r"(?im)^\s*--\s*[^\n]*$", "[signature redacted]", text)
    text = SIGNOFF_LINE_RE.sub("[sign-off redacted]", text)
    text = NAME_GREETING_RE.sub(lambda m: m.group(1) + " [possible name]", text)
    text = UPPER_NAME_RE.sub("[possible name]", text)

    def scrub_token(match):
        word = match.group(0)
        if word.casefold() in SAFE_CAPITALIZED:
            return word
        # An uppercase token followed by a lower-case suffix can be a project
        # identifier; redact it unless the initial is in the technical allowlist.
        return "[possible name]"

    text = LIKELY_NAME_RE.sub(scrub_token, text)
    text = re.sub(r"(?:\[possible name\]\s*){2,}", "[possible name] ", text)
    return text.strip()


def context_excerpt(full_text, candidate_text, max_chars=5200, radius=1800):
    """Show the full sanitized comment when short, otherwise bounded context."""
    clean = safe_comment_text(full_text)
    if len(clean) <= max_chars:
        return clean, {"mode": "full_sanitized_comment", "start": 0, "end": len(clean)}
    needle = safe_comment_text(candidate_text).strip()
    pos = clean.casefold().find(needle.casefold()) if needle else -1
    if pos < 0:
        # The candidate clause may have been shortened or redacted. Keep a
        # bounded source excerpt instead of fabricating a match.
        start, end = 0, min(max_chars, len(clean))
        mode = "bounded_comment_prefix_candidate_not_located"
    else:
        start = max(0, pos - radius)
        end = min(len(clean), pos + len(needle) + radius)
        if end - start > max_chars:
            start = max(0, pos - max_chars // 2)
            end = min(len(clean), start + max_chars)
        mode = "candidate_with_bounded_context"
    return clean[start:end], {"mode": mode, "start": start, "end": end}


def scrub_strings(value):
    if isinstance(value, str):
        return safe_comment_text(value)
    if isinstance(value, list):
        return [scrub_strings(x) for x in value]
    if isinstance(value, dict):
        return {k: scrub_strings(v) for k, v in value.items()}
    return value


def f5_flags(candidate, full_text, source_url):
    flags = []
    claim = " ".join(str(x.get("text", "")) for x in candidate.get("gold", {}).get("claims", []))
    excerpt = safe_comment_text(claim)
    body = safe_comment_text(full_text)
    if len(excerpt.strip()) < 55:
        flags.append({"code": "short_fragment", "detail": "Candidate rationale clause is short; inspect surrounding text."})
    if CODE_OR_LOG_RE.search(full_text or ""):
        flags.append({"code": "log_or_code", "detail": "Source contains code, path, stack, or log patterns that can be mistaken for rationale."})
    parsed = urlparse(source_url or "")
    if parsed.scheme != "https" or parsed.hostname != "bugzilla.mozilla.org" or not parsed.path.startswith("/show_bug.cgi"):
        flags.append({"code": "malformed_source_url", "detail": "Source URL is not the expected HTTPS Bugzilla comment URL."})
    body_urls = URL_RE.findall(full_text or "")
    if any((urlparse(x.rstrip(".,;!?:")).scheme not in ("http", "https") or
            not urlparse(x.rstrip(".,;!?:")).hostname) for x in body_urls):
        flags.append({"code": "malformed_body_url", "detail": "At least one URL-like token does not parse cleanly."})
    if TRIVIAL_BECAUSE_RE.search(body):
        flags.append({"code": "trivial_because", "detail": "A 'because' construction may state an obvious or non-causal reason."})
    markers = list(RATIONALE_MARKERS_RE.finditer(body))
    if len(markers) > 1 or re.search(r"(?i)\b(?:but|although|however)\b.{0,120}\b(?:because|due to)\b", body):
        flags.append({"code": "multiple_interpretations", "detail": "Multiple rationale cues or contrastive clauses may support different readings."})
    if HEDGE_RE.search(body):
        flags.append({"code": "hedged_or_ambiguous", "detail": "Comment uses uncertain language; preserve its qualification."})
    if not excerpt or excerpt.casefold() not in body.casefold():
        flags.append({"code": "candidate_excerpt_not_located", "detail": "Suggested clause was not found literally after privacy scrubbing; compare the source."})
    if CONTRADICTION_RE.search(body) or (markers and not re.search(r"(?i)\b(?:because|due to|blocked by|waiting for|delayed by)\b\s+\S{12}", body)):
        flags.append({"code": "missing_or_contradictory_rationale", "detail": "A negation or incomplete rationale cue needs direct human interpretation."})
    return flags


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _dicts(db, sql, params=()):
    cur = db.execute(sql, params)
    cols = [x[0] for x in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _rel(path, root):
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _source(path, root, sha=None, **extra):
    value = {"path": _rel(path, root)}
    if sha:
        value["sha256"] = sha
    value.update(extra)
    return value


def _load_inputs(root, run_path):
    run = run_path if run_path.is_absolute() else root / run_path
    manifest = _read_json(run / "manifest.json")
    candidates = _read_json(run / "candidates.json")
    challenges = _read_json(run / "challenge_candidates.json")
    pins = _read_json(root / "configs/phase05_sources.json")
    base, overlay = phase05.paths(root, pins)
    queue_path = run / "review_queue.csv"
    backup_path = run / "review_queue.pre_review_backup.csv"
    with queue_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        queue = list(reader)
    backup_sha = file_hash(backup_path) if backup_path.is_file() else None
    queue_sha = file_hash(queue_path)
    population = _read_json(run / "population_manifest.json")
    input_verification = _read_json(run / "input_verification.json")
    base_manifest_path = base / "manifest.json"
    base_manifest = _read_json(base_manifest_path)
    base_db_path = base / "canonical.duckdb"
    canonical_artifact = base_manifest.get("artifacts", {}).get("canonical.duckdb", {})
    phase04_summary_path = overlay / "summary.json"
    phase04_summary = _read_json(phase04_summary_path)
    api_overlay_path = overlay / "api_enrichment.duckdb"
    api_overlay_manifest = phase04_summary.get("artifacts", {}).get("api_enrichment.duckdb", {})
    api_overlay_sha_observed = file_hash(api_overlay_path) if api_overlay_path.is_file() else None
    small_source_hashes = input_verification.get("small_file_hashes", {})
    small_source_hashes_verified = all((root / name).is_file() and file_hash(root / name) == sha
        for name, sha in small_source_hashes.items())
    integrity = {
        "run_id": run.name,
        "queue_sha256": queue_sha,
        "backup_path": _rel(backup_path, root),
        "backup_sha256": backup_sha,
        "queue_backup_byte_identical": backup_sha == queue_sha if backup_sha else False,
        "queue_header": list(header),
        "queue_header_matches_validator": header == QUEUE_COLUMNS,
        "queue_decision_counts": dict(Counter(r.get("decision", "") for r in queue)),
        "queue_decisions_in_validator_enum": all(r.get("decision") in ("PENDING", "APPROVE", "CORRECT", "REJECT") for r in queue),
        "queue_qids": len(queue),
        "candidate_count": len(candidates),
        "challenge_count": len(challenges),
        "seed": manifest["identity"]["options"]["seed"],
        "source_pins_sha256": digest(pins),
        "candidate_hash": file_hash(run / "candidates.json"),
        "challenge_hash": file_hash(run / "challenge_candidates.json"),
        "generation_manifest_sha256": file_hash(run / "manifest.json"),
        "input_verification_sha256": file_hash(run / "input_verification.json"),
        "population_manifest_sha256": file_hash(run / "population_manifest.json"),
        "base_manifest_sha256": file_hash(base_manifest_path),
        "phase04_summary_sha256": file_hash(phase04_summary_path),
        "phase04_summary_sha256_expected": pins.get("phase04_summary_sha256"),
        "api_overlay_sha256_observed": api_overlay_sha_observed,
        "api_overlay_sha256_expected": api_overlay_manifest.get("sha256"),
        "small_source_hashes_verified": small_source_hashes_verified,
        "small_source_hashes": small_source_hashes,
        "canonical_database_sha256_expected": input_verification.get("base_database_sha256"),
        "canonical_database_hash_recomputed": False,
        "canonical_database_size_bytes": base_db_path.stat().st_size if base_db_path.is_file() else None,
        "canonical_database_manifest_bytes": canonical_artifact.get("bytes"),
        "population_partition_counts": {k: len(v) for k, v in population["members"].items()},
        "population_manifest_declared_sha256": population.get("sha256"),
    }
    qids = [q["qid"] for q in candidates + challenges]
    qid_membership = sorted((q["qid"], q["family"], q["split"], sorted(q["bug_ids"])) for q in candidates + challenges)
    integrity["qid_split_membership_sha256"] = digest(qid_membership)
    integrity["candidate_split_counts"] = dict(Counter(q["split"] for q in candidates))
    integrity["challenge_split_counts"] = dict(Counter(q["split"] for q in challenges))
    integrity["queue_matches_candidate_qids"] = (len(set(qids)) == len(qids) == len(queue) and
        set(qids) == {r.get("qid") for r in queue})
    integrity["queue_rows_all_present"] = all(set(row) == set(QUEUE_COLUMNS) for row in queue)
    q_by_id = {q["qid"]: q for q in candidates + challenges}
    static_rows_match = True
    for row in queue:
        q = q_by_id.get(row.get("qid"))
        if q is None:
            static_rows_match = False
            continue
        try:
            expected_evidence = [{"id": e["id"], "url": e["source_url"],
                "fields": e["fields"], "source_hash": e["content_hash"]} for e in q["evidence"]]
            static_rows_match = static_rows_match and all((
                row.get("family") == q["family"], row.get("split") == q["split"],
                row.get("question") == q["question"],
                json.loads(row.get("suggested_gold_json", "null")) == q["gold"],
                json.loads(row.get("evidence_json", "null")) == expected_evidence,
                json.loads(row.get("query_json", "null")) == q.get("sql"),
                row.get("rubric") == ("Every causal claim must be explicitly stated and mapped to the cited comment; rationale_present YES required."
                    if q["family"] == "F5" else q["validator"]),
            ))
        except (json.JSONDecodeError, KeyError, TypeError):
            static_rows_match = False
    integrity["queue_static_candidate_rows_match"] = static_rows_match
    for name, sha in manifest["artifacts"].items():
        integrity.setdefault("generation_artifacts_verified", True)
        if file_hash(run / name) != sha:
            integrity["generation_artifacts_verified"] = False
    integrity["source_pin_identity_matches"] = manifest["identity"]["source_pins"] == pins
    integrity["generation_state_candidates_ready"] = manifest.get("state") == "CANDIDATES_READY"
    integrity["population_manifest_hash_matches"] = population.get("sha256") == digest(population.get("members"))
    integrity["canonical_database_manifest_pin_matches"] = (
        input_verification.get("base_database_sha256") == canonical_artifact.get("sha256") and
        base_db_path.is_file() and base_db_path.stat().st_size == canonical_artifact.get("bytes"))
    integrity["phase04_summary_pin_matches"] = file_hash(phase04_summary_path) == pins.get("phase04_summary_sha256")
    integrity["api_overlay_hash_matches_phase04_manifest"] = api_overlay_sha_observed == api_overlay_manifest.get("sha256")
    integrity["expected_cardinalities_match"] = len(candidates) == 169 and len(challenges) == 6 and len(queue) == 175
    integrity["expected_partitions_match"] = integrity["population_partition_counts"] == {"dev": 592, "test": 2408}
    return run, manifest, candidates, challenges, queue, population, pins, base, overlay, integrity


def _bug(db, bug_id):
    rows = _dicts(db, """SELECT b.* REPLACE(
       strftime(b.opened_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS opened_at_utc,
       strftime(b.snapshot_as_of_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS snapshot_as_of_utc),
       s.normalized_fields, s.entity_content_hash, s.disposition AS source_disposition,
       s.content_hash AS raw_record_hash
       FROM bugs b JOIN source_records s USING(source_record_id)
       WHERE b.bug_id=? AND s.entity_type='bugs' AND s.disposition='NORMALIZED' LIMIT 1""", [str(bug_id)])
    return rows[0] if rows else None


def _provenance_ok(e, row):
    return (e.get("id") == row.get("source_record_id") and
            e.get("content_hash") == row.get("entity_content_hash") and
            e.get("source_row_key") == row.get("source_row_key") and
            e.get("source_url") == row.get("source_url"))


def validate_f1(q, db, root):
    e = q["evidence"][0]
    bug = e.get("bug_id")
    r = _bug(db, bug)
    if not r:
        return {"status": "UNKNOWN", "checks": {"canonical_bug_record": None}, "sources": []}
    keys = list(e.get("fields", {}))
    if len(keys) != 1 or keys[0] not in {"product", "component", "snapshot_status", "snapshot_resolution"}:
        return {"status": "FAIL", "checks": {"field_allowlist": False}, "sources": []}
    field = keys[0]
    payload = json.loads(r["normalized_fields"])
    actual = r[field]
    checks = {
        "source_provenance_matches": _provenance_ok(e, r),
        "retained_source_payload_hash_matches": digest(payload) == r["entity_content_hash"],
        "canonical_equals_retained_source_payload": str(actual) == str(payload.get(field)),
        "question_evidence_field_equals_canonical": str(e["fields"][field]) == str(actual),
        "typed_gold_equals_canonical": q["gold"] == {"type": "string", "value": actual},
        "snapshot_date_remains_unknown": q["scope"].get("snapshot_as_of_utc") is None and r["snapshot_as_of_utc"] is None,
        "question_qualifies_unknown_snapshot_date": "snapshot date is unknown" in q.get("question", "").casefold(),
    }
    return {"status": status(list(checks.values())), "checks": checks,
            "value": actual, "field": field,
            "sources": [_source(Path(root) / BASE_DUCKDB_REL, root,
                entity_id=e["id"], source_row_key=e["source_row_key"], content_hash=e["content_hash"],
                source_url=e["source_url"], table="bugs+source_records",
                canonical_manifest_sha256=file_hash(root / "outputs/normalization/phase03b/run-20261022T023542Z-1182018/manifest.json")) ]}


def _history_envelope(root, result, bug):
    fetch = result.get("history_fetch") or {}
    cache = Path(fetch.get("cache_path", ""))
    if not cache.is_absolute():
        cache = root / cache
    if not cache.is_file():
        return None, {"cache_exists": False, "cache_path": _rel(cache, root)}
    try:
        with gzip.open(cache, "rt", encoding="utf-8") as handle:
            envelope = json.load(handle)
        body = envelope.get("body_utf8", "").encode("utf-8")
        raw_sha = hashlib.sha256(body).hexdigest()
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {"cache_decodable": False, "cache_path": _rel(cache, root)}
    checks = {
        "cache_body_hash_matches_envelope": raw_sha == envelope.get("body_sha256"),
        "cache_body_hash_matches_checkpoint": raw_sha == fetch.get("raw_sha256"),
        "endpoint_status_200": envelope.get("status_code") == 200 and fetch.get("status_code") == 200,
        "requested_bug_matches": str(envelope.get("requested_bug_id")) == str(bug),
        "endpoint_url_matches": envelope.get("url") == fetch.get("url") and envelope.get("endpoint") == "history",
        "public_endpoint_visibility": envelope.get("source_visibility") == "public_endpoint_response",
        "fetched_at_matches_checkpoint": envelope.get("fetched_at_utc") == fetch.get("fetched_at_utc"),
    }
    return (payload, {**checks, "cache_path": _rel(cache, root), "raw_sha256": raw_sha,
                      "fetched_at_utc": envelope.get("fetched_at_utc"), "source_visibility": envelope.get("source_visibility")})


def validate_f2(q, base_db, api_db, checkpoint, root, base_field_changes):
    bug = str(q["bug_ids"][0])
    result = checkpoint.get("candidate_results", {}).get(bug)
    if not result:
        return {"status": "UNKNOWN", "checks": {"saved_history_result": None}, "sources": [],
                "interpretation": "No saved history result; absence is not a zero-event history."}
    history_fetch = result.get("history_fetch") or {}
    payload, cache_check = _history_envelope(root, result, bug)
    if payload is None:
        return {"status": "UNKNOWN", "checks": {"saved_public_history_cache": None}, "cache": cache_check,
                "sources": [_source(root / "outputs/phase04/enrichment" / "cohort-8bb3150d29a598d8" / "checkpoint.json", root,
                                     bug_id=bug, response_sha256=history_fetch.get("raw_sha256"))],
                "interpretation": "No verified cached history body; do not interpret null/missing as zero events."}
    opened = _bug(base_db, bug)
    if not opened:
        return {"status": "UNKNOWN", "checks": {"canonical_creation_time": None}, "cache": cache_check, "sources": []}
    parsed = p4.parse_api_history(payload, int(bug), opened.get("opened_at_utc"), history_fetch.get("fetched_at_utc"))
    creation_evidence = next((e for e in q["evidence"] if e.get("source_dataset") == "metadata"), None)
    creation_provenance_ok = bool(creation_evidence) and _provenance_ok(creation_evidence, opened) and (
        creation_evidence.get("fields", {}).get("opened_at_utc") == opened.get("opened_at_utc"))
    saved_changes = result.get("changes")
    overlay_rows = _dicts(api_db, "SELECT * FROM field_changes WHERE bug_id=? ORDER BY event_time_utc,event_index,change_index", [int(bug)])
    overlay_by_key = {(int(x["event_index"]), int(x["change_index"])): x for x in overlay_rows}
    matching_overlay = all(
        (int(x["event_index"]), int(x["change_index"])) in overlay_by_key and
        overlay_by_key[(int(x["event_index"]), int(x["change_index"]))]["content_sha256"] == p4.digest(x)
        for x in parsed.get("changes", []))
    overlay_cardinality = len(overlay_rows) == len(parsed.get("changes", []))
    expected_receipt = next((e for e in q["evidence"] if e.get("id") == "history:" + bug), None)
    event_evidence = [e for e in q["evidence"] if e.get("source_dataset") == "bugzilla_rest_history" and e.get("id") != "history:" + bug]
    selected_events_ok = True
    for e in event_evidence:
        row = next((x for x in overlay_rows if x["source_row_key"] == e.get("id")), None)
        selected_events_ok = selected_events_ok and bool(row) and row["content_sha256"] == e.get("content_hash")
        if row:
            selected_events_ok = selected_events_ok and all(row.get(k) == v for k, v in e.get("fields", {}).items())
    if expected_receipt:
        selected_events_ok = selected_events_ok and expected_receipt.get("content_hash") == history_fetch.get("raw_sha256")
        selected_events_ok = selected_events_ok and expected_receipt.get("source_row_key") == "response:" + str(history_fetch.get("raw_sha256"))
        selected_events_ok = selected_events_ok and expected_receipt.get("fields", {}).get("history_state") == parsed.get("state")
    receipt_time_ok = bool(expected_receipt) and (
        expected_receipt.get("observed_at_utc") == history_fetch.get("fetched_at_utc") and
        utc(expected_receipt.get("observed_at_utc")) is not None and
        utc(expected_receipt.get("ingested_at_utc")) is not None and
        utc(expected_receipt.get("observed_at_utc")) <= utc(expected_receipt.get("ingested_at_utc")))
    complete = (parsed.get("state") == "PARSED" and parsed.get("chronology_ok") is True and
                parsed.get("malformed_count") == 0 and parsed.get("reordered") is False and
                parsed.get("future_event_after_observed_at") is False and parsed.get("same_time_groups") == 0)
    all_event_times_valid = all(utc(x.get("event_time_utc")) is not None and
        utc(x.get("event_time_utc")) <= utc(x.get("observed_at_utc")) <= utc(x.get("ingested_at_utc"))
        for x in overlay_rows)
    fixed = [x for x in parsed.get("changes", []) if x.get("field_name") == "resolution" and
             x.get("new_value") == p4.canonical("FIXED") and x.get("old_value") != p4.canonical("FIXED")]
    reopen = [x for x in parsed.get("changes", []) if x.get("field_name") == "status" and
              x.get("new_value") == p4.canonical("REOPENED") and x.get("old_value") != p4.canonical("REOPENED")]
    created = utc(opened.get("opened_at_utc"))
    fixed_eligible = [x for x in fixed if utc(x["event_time_utc"]) is not None and created is not None and utc(x["event_time_utc"]) >= created]
    first = min((utc(x["event_time_utc"]) for x in fixed_eligible), default=None)
    metric = result.get("fix_metric") or {}
    checks = {
        "cached_public_response_hash_and_identity": all(v for k, v in cache_check.items() if isinstance(v, bool)),
        "history_reparsed_from_saved_response": parsed.get("state") == result.get("history", {}).get("state") and parsed.get("changes") == saved_changes,
        "complete_ordered_history": complete,
        "overlay_matches_all_parsed_timestamped_events": matching_overlay and overlay_cardinality,
        "selected_event_and_receipt_evidence_matches": selected_events_ok and expected_receipt is not None,
        "creation_time_source_record_matches_canonical": creation_provenance_ok,
        "history_observed_and_ingested_times_match_receipt": receipt_time_ok,
        "event_observed_before_ingestion": all_event_times_valid,
        "phase03b_field_changes_empty_is_not_used_as_history": base_field_changes == 0,
        "archive_api_creation_consistency_has_no_conflict": result.get("source_consistency_differences") == [],
        "archive_snapshot_date_remains_unknown": q.get("scope", {}).get("snapshot_as_of_utc") is None,
    }
    answer = q.get("gold", {})
    independent = {"history_state": parsed.get("state"), "event_count": len(parsed.get("changes", [])),
                   "first_fixed_event_utc": first.isoformat().replace("+00:00", "Z") if first else None,
                   "explicit_reopened_entries": len(reopen), "base_field_changes": base_field_changes,
                   "api_overlay_event_rows": len(overlay_rows)}
    if answer.get("type") == "calendar_duration":
        if first is None or created is None:
            checks["first_fixed_answer_recomputes"] = False
        else:
            seconds = (first - created).total_seconds()
            hours = seconds / 3600.0
            days = seconds / 86400.0
            stored_time = utc(answer.get("first_fixed_at_utc"))
            checks["first_fixed_answer_recomputes"] = (
                answer.get("seconds") == seconds and math.isclose(answer.get("hours", math.nan), hours, rel_tol=0, abs_tol=1e-12) and
                math.isclose(answer.get("days", math.nan), days, rel_tol=0, abs_tol=1e-12) and stored_time == first and
                metric.get("state") == "VALID_EVENT_TIME" and math.isclose(metric.get("elapsed_calendar_days", math.nan), days, rel_tol=0, abs_tol=1e-10))
            independent.update({"elapsed_seconds": seconds, "elapsed_calendar_hours": hours, "elapsed_calendar_days": days})
    elif answer.get("type") == "integer":
        expected = len(reopen)
        checks["reopened_count_recomputes"] = answer.get("value") == expected
        independent["expected_reopened_count"] = expected
    elif answer.get("type") == "unknown":
        # An explicit, complete history with zero qualifying FIXED events is
        # distinguishable from a missing/null history. Gold remains UNKNOWN.
        checks["unknown_gold_is_supported"] = complete and first is None and not reopen and answer.get("value") == phase05.UNKNOWN
        independent["unknown_reason"] = "Complete saved public history has no qualifying FIXED event; no event time is imputed."
    else:
        checks["supported_answer_type"] = False
    fatal_checks = ("cached_public_response_hash_and_identity", "history_reparsed_from_saved_response",
                    "overlay_matches_all_parsed_timestamped_events", "selected_event_and_receipt_evidence_matches")
    if any(checks.get(key) is False for key in fatal_checks):
        final_status = "FAIL"
    elif not complete or not all_event_times_valid:
        final_status = "UNKNOWN"
    else:
        final_status = status(list(checks.values()))
    sources = [_source(root / "outputs/phase04/enrichment/cohort-8bb3150d29a598d8/checkpoint.json", root,
                       sha=file_hash(root / "outputs/phase04/enrichment/cohort-8bb3150d29a598d8/checkpoint.json"), bug_id=bug,
                       response_sha256=history_fetch.get("raw_sha256")),
               _source(root / "outputs/phase04/enrichment/cohort-8bb3150d29a598d8/api_enrichment.duckdb", root,
                       bug_id=bug, table="field_changes", event_rows=len(overlay_rows))]
    return {"status": final_status, "checks": checks, "independent_recomputation": independent,
            "cache": cache_check, "sources": sources,
            "interpretation": "Phase 3B field_changes=0 is an empty archive table; timestamped Phase 4 history response and overlay are independently checked."}


def _load_population_rows(base_db, population, seed):
    members = population.get("members", {})
    all_ids = sorted(set(map(str, members.get("dev", []) + members.get("test", []))))
    rows = _dicts(base_db, """SELECT b.bug_id,b.product,b.component,b.snapshot_status,
       b.snapshot_resolution,strftime(b.opened_at_utc,'%Y-%m-%dT%H:%M:%S.%fZ') AS opened_at_utc,
       NOT EXISTS(SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
         AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT') AS conflict_free
       FROM bugs b JOIN sample_membership m USING(bug_id)
       WHERE b.bug_id IN (SELECT unnest(?)) ORDER BY b.bug_id""", [all_ids])
    by_id = {str(r["bug_id"]): r for r in rows}
    return by_id


def validate_f3(q, db, root, population, pop_rows, pop_integrity,
                expected_partition_counts=None):
    scope = q.get("scope", {})
    split = scope.get("partition")
    universe = sorted(map(str, population.get("members", {}).get(split, [])))
    expected_partition_counts = expected_partition_counts or {"dev": 592, "test": 2408}
    filt = scope.get("filter", {})
    checks = {
        "partition_name_supported": split in ("dev", "test"),
        "partition_denominator_exact": scope.get("denominator") == len(universe) == expected_partition_counts.get(split),
        "question_seed_matches_run": scope.get("sample_seed") == 317,
        "question_states_partition_and_denominator": split in q.get("question", "") and str(len(universe)) in q.get("question", ""),
        "creation_year_is_filing_year_when_used": (not filt or next(iter(filt)) != "creation_year" or
            "filing year" in q.get("question", "").casefold()),
        "all_partition_members_present": all(x in pop_rows for x in universe),
        "all_members_are_firefox_and_conflict_free": all(pop_rows.get(x, {}).get("product") == "Firefox" and
            pop_rows.get(x, {}).get("conflict_free") is True for x in universe),
        "partition_rule_matches_seed": all(phase05.partition(317, x) == split for x in universe),
        "population_manifest_integrity": pop_integrity,
        "eligible_sample_membership_hash_matches": scope.get("included_bug_ids_sha256") == digest(sorted(
            map(str, population.get("members", {}).get("dev", []) + population.get("members", {}).get("test", [])))),
    }
    if len(filt) != 1 or next(iter(filt), None) not in ("component", "status", "creation_year"):
        checks["supported_filter"] = False
        return {"status": status(list(checks.values())), "checks": checks, "sources": []}
    key, value = next(iter(filt.items()))
    sql_column = {"component": "component", "status": "snapshot_status", "creation_year": "year(opened_at_utc)"}[key]
    expected_sql = f"SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND {sql_column} = ?"
    sql_obj = q.get("sql") or {}
    params = sql_obj.get("parameters") or []
    checks["audited_sql_template_exact"] = sql_obj.get("query") == expected_sql and len(params) == 2 and list(map(str, params[0])) == universe
    if not checks["audited_sql_template_exact"]:
        return {"status": status(list(checks.values())), "checks": checks, "sources": []}
    filter_value = int(value) if key == "creation_year" else value
    matches = set()
    for bug in universe:
        row = pop_rows.get(bug)
        if not row:
            continue
        current = row["component"] if key == "component" else row["snapshot_status"] if key == "status" else (utc(row["opened_at_utc"]).year if utc(row["opened_at_utc"]) else None)
        if current == filter_value:
            matches.add(bug)
    sql_count = db.execute(expected_sql, [universe, filter_value]).fetchone()[0]
    q_ids = set(map(str, q.get("bug_ids", [])))
    gold_count = (q.get("gold") or {}).get("value")
    checks.update({
        "independent_python_set_equals_candidate_members": matches == q_ids,
        "sql_count_equals_python_set_cardinality": int(sql_count) == len(matches),
        "typed_gold_equals_both_routes": gold_count == len(matches) == int(sql_count),
        "candidate_matching_id_hash_matches": q.get("source_coverage", {}).get("matching_bug_ids_sha256") == digest(sorted(matches)),
    })
    return {"status": status(list(checks.values())), "checks": checks,
            "independent_recomputation": {"partition": split, "denominator": len(universe),
                "denominator_ids_sha256": digest(universe), "matching_distinct_ids": len(matches),
                "matching_ids_sha256": digest(sorted(matches)), "sql_count": int(sql_count), "python_count": len(matches)},
            "sources": [_source(root / BASE_DUCKDB_REL, root, table="bugs+sample_membership",
                canonical_manifest_sha256=file_hash(root / "outputs/normalization/phase03b/run-20261022T023542Z-1182018/manifest.json"),
                partition=split, population_manifest_sha256=population.get("sha256"))]}


def validate_f4(q, db, root):
    parent = str(q["evidence"][0].get("bug_id"))
    relation = q["evidence"][0].get("fields", {}).get("relation")
    if not relation:
        return {"status": "UNKNOWN", "checks": {"relation_field": None}, "sources": []}
    rows = _dicts(db, """SELECT link_key,bug_id,target_bug_id,relation,source_record_id,source_row_key,
       source_url,content_hash FROM bug_links WHERE bug_id=? AND relation=? AND target_bug_id IS NOT NULL ORDER BY link_key""",
       [parent, relation])
    canonical_targets = {str(r["target_bug_id"]) for r in rows}
    source_bug = _bug(db, parent)
    if source_bug:
        payload = json.loads(source_bug["normalized_fields"])
        raw_targets = {str(x["target_bug_id"]) for x in payload.get("recorded_links", [])
                       if x.get("relation") == relation and x.get("target_bug_id") is not None}
    else:
        raw_targets = set()
    cited_keys = {str(e.get("id")) for e in q["evidence"]}
    canonical_keys = {str(x["link_key"]) for x in rows}
    targets = sorted(canonical_targets, key=lambda x: int(x))
    q_targets = sorted(map(str, q.get("gold", {}).get("value", [])), key=lambda x: int(x))
    expected_bug_ids = {parent, *canonical_targets}
    checks = {
        "parent_canonical_source_record": source_bug is not None,
        "retained_parent_payload_hash_matches": bool(source_bug) and
            digest(json.loads(source_bug["normalized_fields"])) == source_bug["entity_content_hash"],
        "explicit_numeric_target_set_equals_retained_source": canonical_targets == raw_targets,
        "cited_edge_keys_cover_complete_relation": cited_keys == canonical_keys,
        "cited_edge_provenance_matches": all(
            (e := next((x for x in q["evidence"] if str(x.get("id")) == str(r["link_key"])), None)) is not None and
            e.get("bug_id") == str(r["bug_id"]) and e.get("source_row_key") == r["source_row_key"] and
            e.get("source_url") == r["source_url"] and e.get("content_hash") == r["content_hash"] and
            e.get("fields", {}).get("relation") == r["relation"] and
            str(e.get("fields", {}).get("target_bug_id")) == str(r["target_bug_id"])
            for r in rows),
        "typed_gold_is_complete_target_set": targets == q_targets,
        "bug_ids_cover_parent_and_targets": set(map(str, q.get("bug_ids", []))) == expected_bug_ids,
        "all_related_ids_share_declared_partition": all(phase05.partition(317, x) == q["split"] for x in expected_bug_ids),
        "no_url_only_edges_counted": all(x.get("target_bug_id") is not None for x in rows),
        "question_limits_to_recorded_snapshot_edges": q.get("scope", {}).get("snapshot_as_of_utc") is None and
            "historical validity are unknown" in q.get("question", "").casefold(),
    }
    return {"status": status(list(checks.values())), "checks": checks,
            "independent_recomputation": {"parent_bug_id": parent, "relation": relation,
                "target_count": len(canonical_targets), "targets": targets,
                "target_set_sha256": digest(targets), "url_only_excluded": True,
                "historical_validity": "UNKNOWN"},
            "sources": [_source(root / BASE_DUCKDB_REL, root, table="bug_links+source_records",
                canonical_manifest_sha256=file_hash(root / "outputs/normalization/phase03b/run-20261022T023542Z-1182018/manifest.json"),
                parent_bug_id=parent, edge_keys=sorted(canonical_keys), target_set_sha256=digest(targets))]}


def validate_f6(q, base_db, api_db, root):
    bug = str(q["bug_ids"][0])
    row = _bug(base_db, bug)
    if not row:
        return {"status": "UNKNOWN", "checks": {"canonical_bug_record": None}, "sources": []}
    kind = q.get("template_id", "")
    expected_unknown = (q.get("gold") or {}).get("value") == phase05.UNKNOWN
    checks = {"gold_uses_bounded_unanswerable_language": expected_unknown,
              "scope_is_explicit": bool(q.get("scope", {}).get("corpus")) and q["scope"].get("snapshot_as_of_utc") is None}
    if "engineer_hours" in kind:
        columns = {x[1].casefold() for x in base_db.execute("PRAGMA table_info('bugs')").fetchall()}
        no_hours_field = not any("hour" in c or "effort" in c or "worklog" in c for c in columns)
        csv_mentions = base_db.execute("SELECT count(*) FROM comments WHERE bug_id=? AND regexp_matches(coalesce(body,''), ?)",
                                       [bug, EFFORT_RE]).fetchone()[0]
        api_mentions = api_db.execute("SELECT count(*) FROM api_comments WHERE json_extract_string(row_json,'$.bug_id')=? AND regexp_matches(row_json::VARCHAR, ?)",
                                      [bug, EFFORT_RE]).fetchone()[0]
        candidate_fields = q.get("evidence", [{}])[0].get("fields", {})
        checks.update({"candidate_metadata_claims_no_effort_field": candidate_fields.get("engineer_hours_field") == "ABSENT" and
                           not any("hour" in str(x).casefold() or "effort" in str(x).casefold() for x in candidate_fields.get("available_fields", [])),
                       "no_measurement_field_in_canonical_bug_schema": no_hours_field,
                       "no_effort_pattern_in_specified_comment_records": csv_mentions == 0 and api_mentions == 0})
        bug_text_mentions = base_db.execute("""SELECT count(*) FROM bugs WHERE bug_id=? AND
            (regexp_matches(coalesce(summary,''), ?) OR regexp_matches(coalesce(description,''), ?))""",
            [bug, EFFORT_RE, EFFORT_RE]).fetchone()[0]
        checks["no_effort_pattern_in_bug_summary_or_description"] = bug_text_mentions == 0
        if csv_mentions or api_mentions or bug_text_mentions:
            result_status = "UNKNOWN"
        else:
            result_status = status(list(checks.values()))
        counts = {"canonical_comment_effort_pattern_matches": int(csv_mentions),
                  "phase04_public_comment_effort_pattern_matches": int(api_mentions),
                  "bug_summary_description_effort_pattern_matches": int(bug_text_mentions)}
    elif "export_timestamp" in kind:
        candidate_fields = q.get("evidence", [{}])[0].get("fields", {})
        checks.update({"candidate_metadata_preserves_unknown_snapshot": candidate_fields.get("snapshot_as_of_utc") is None,
                       "archive_snapshot_as_of_is_null": row["snapshot_as_of_utc"] is None,
                       "gold_describes_unknown_source_export_time": "timestamp" in str(q["gold"].get("missing_evidence", "")).casefold()})
        result_status = status(list(checks.values()))
        counts = {"snapshot_as_of_utc": None}
    else:
        checks["recognized_f6_type"] = False
        result_status = "FAIL"
        counts = {}
    return {"status": result_status, "checks": checks, "bounded_evidence_screen": counts,
            "sources": [_source(root / BASE_DUCKDB_REL, root, table="bugs+comments",
                bug_id=bug, schema="canonical public archive",
                canonical_manifest_sha256=file_hash(root / "outputs/normalization/phase03b/run-20261022T023542Z-1182018/manifest.json")),
                _source(root / "outputs/phase04/enrichment/cohort-8bb3150d29a598d8/api_enrichment.duckdb", root,
                        table="api_comments", scope="pinned public API overlay")],
            "interpretation": "PASS means the specified local sources do not establish the requested quantity; it is not a claim that no external answer exists."}


def _comment_packet(q, db, root):
    e = q["evidence"][0]
    rows = _dicts(db, """SELECT c.comment_key,c.bug_id,c.comment_id,c.private_flag,c.source_record_id,
       c.source_dataset,c.source_row_key,c.source_url,strftime(c.event_time_utc,'%Y-%m-%dT%H:%M:%S.%fZ') AS event_time_utc,
       strftime(c.observed_at_utc,'%Y-%m-%dT%H:%M:%S.%fZ') AS observed_at_utc,
       strftime(c.ingested_at_utc,'%Y-%m-%dT%H:%M:%S.%fZ') AS ingested_at_utc,c.text_availability,
       c.raw_field_mapping,c.content_hash,s.content_hash AS raw_source_row_hash,
       s.entity_content_hash,s.normalized_fields,s.disposition
       FROM comments c JOIN source_records s ON s.source_record_id=c.source_record_id
       WHERE c.comment_key=? LIMIT 2""", [e["id"]])
    if len(rows) != 1:
        return {"status": "UNKNOWN", "checks": {"unique_comment_source_row": False}, "packet": None}
    r = rows[0]
    privacy_checks = {"explicitly_public_comment": r["private_flag"] is False,
                      "text_availability_public_and_available": r["text_availability"] == "AVAILABLE"}
    if not all(privacy_checks.values()):
        # Do not select a body from a private, withheld, or unknown-privacy row.
        return {"status": "FAIL", "checks": privacy_checks, "packet": None,
                "privacy_provenance": {"private_flag": r["private_flag"], "text_availability": r["text_availability"]}}
    bodies = _dicts(db, """SELECT body FROM comments WHERE comment_key=?
        AND private_flag=false AND text_availability='AVAILABLE' AND body IS NOT NULL LIMIT 2""", [e["id"]])
    if len(bodies) != 1:
        return {"status": "UNKNOWN", "checks": {"eligible_public_comment_body": False}, "packet": None,
                "privacy_provenance": {"private_flag": False, "text_availability": "AVAILABLE"}}
    r["body"] = bodies[0]["body"]
    raw_body = r["body"] or ""
    payload = json.loads(r["normalized_fields"])
    actual_body_sha = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
    body_payload_hash = digest(raw_body)
    content_hash = digest({k: r[k] for k in ("comment_key", "bug_id", "comment_id", "body", "private_flag")})
    checks = {
        **privacy_checks,
        "body_present": bool(raw_body.strip()),
        "candidate_comment_key_matches": r["comment_key"] == e.get("id"),
        "candidate_content_hash_matches": r["content_hash"] == e.get("content_hash") == content_hash,
        "raw_body_sha_matches_candidate_evidence": actual_body_sha == e.get("fields", {}).get("body_sha256"),
        "source_normalized_body_hash_matches": payload.get("body_hash") == body_payload_hash,
        "source_record_links_comment_entity": r["entity_content_hash"] == content_hash,
        "source_row_key_and_url_match": r["source_row_key"] == e.get("source_row_key") and r["source_url"] == e.get("source_url"),
        "source_dataset_matches": r["source_dataset"] == e.get("source_dataset"),
        "event_time_matches": str(r["event_time_utc"]) == str(e.get("event_time_utc")),
        "not_private_or_unknown_source_tier": r["source_dataset"] in ("comments_part_1", "comments_part_3") and r["disposition"] == "NORMALIZED",
    }
    if not checks["explicitly_public_comment"] or not checks["text_availability_public_and_available"]:
        return {"status": "FAIL", "checks": checks, "packet": None,
                "privacy_provenance": {"private_flag": r["private_flag"], "text_availability": r["text_availability"]}}
    if not all(checks.values()):
        return {"status": status(list(checks.values())), "checks": checks, "packet": None,
                "privacy_provenance": {"private_flag": False, "text_availability": r["text_availability"]}}
    claim = " ".join(x.get("text", "") for x in q.get("gold", {}).get("claims", []))
    excerpt, excerpt_meta = context_excerpt(raw_body, claim)
    flags = f5_flags(q, raw_body, r["source_url"])
    item_packet = {
        "packet_version": VERSION, "qid": q["qid"], "family": "F5", "split": q["split"],
        "question": safe_comment_text(q["question"]), "suggested_gold_json": {
            **q["gold"], "claims": [{**claim, "text": safe_comment_text(claim.get("text", ""))}
                for claim in q.get("gold", {}).get("claims", [])]},
        "codex_recommendation": {"state": "NOT_REVIEWED", "decision": None,
                                 "note": "A model may recommend; only a human enters review_queue.csv decisions."},
        "deterministic_source_check": {"status": "PASS", "checks": checks},
        "evidence": {"comment_id": r["comment_id"], "comment_key": r["comment_key"],
            "comment_content_hash": r["content_hash"], "full_body_sha256": actual_body_sha,
            "source_record_id": r["source_record_id"], "source_row_key": r["source_row_key"],
            "raw_source_row_hash": r["raw_source_row_hash"], "source_url": r["source_url"],
            "event_time_utc": r["event_time_utc"], "observed_at_utc": r["observed_at_utc"],
            "ingested_at_utc": r["ingested_at_utc"],
            "privacy_provenance": {"source_dataset": r["source_dataset"], "private_flag": False,
                "text_availability": "AVAILABLE", "privacy_is_explicitly_public": True,
                "identity_scrubbing": "emails, handles, signatures, and likely name/proper-noun tokens replaced heuristically",
                "body_chars_read": len(raw_body), "body_chars_emitted": len(excerpt),
                "raw_comment_body_written": False},
            "excerpt": excerpt, "excerpt_bounds": excerpt_meta},
        "heuristic_flags": flags,
        "heuristics_are_advisory": True,
        "human_rubric": "Verify that each candidate causal/rationale claim is explicitly stated in this comment, retain uncertainty and scope, and reject if the cited text only mentions an unrelated implementation detail.",
    }
    item_packet = scrub_strings(item_packet)
    # A second pass ensures common contact patterns were not left in the packet.
    packet_text = json.dumps(item_packet, ensure_ascii=False)
    leaks = bool(EMAIL_RE.search(packet_text) or HANDLE_RE.search(packet_text))
    checks["packet_contact_pattern_scrubbed"] = not leaks
    if leaks:
        item_packet["evidence"]["excerpt"] = EMAIL_RE.sub("[email]", item_packet["evidence"]["excerpt"])
        item_packet["evidence"]["excerpt"] = HANDLE_RE.sub("[handle]", item_packet["evidence"]["excerpt"])
        item_packet["deterministic_source_check"]["checks"]["packet_contact_pattern_scrubbed"] = False
        item_packet["deterministic_source_check"]["status"] = "FAIL"
    return {"status": status(list(checks.values())), "checks": checks, "packet": item_packet,
            "privacy_provenance": {"private_flag": False, "text_availability": "AVAILABLE",
                                   "source_dataset": r["source_dataset"], "source_url": r["source_url"]},
            "sources": [_source(root / BASE_DUCKDB_REL, root, table="comments+source_records",
                canonical_manifest_sha256=file_hash(root / "outputs/normalization/phase03b/run-20261022T023542Z-1182018/manifest.json"),
                source_row_key=r["source_row_key"], comment_key=r["comment_key"],
                comment_content_hash=r["content_hash"], full_body_sha256=actual_body_sha,
                raw_source_row_hash=r["raw_source_row_hash"], source_url=r["source_url"])],
            "heuristic_flag_count": len(flags), "heuristic_flag_codes": [x["code"] for x in flags]}


def validate_item(q, base_db, api_db, checkpoint, population, pop_rows, pop_integrity, root, base_field_changes):
    family = q["family"]
    if family == "F1":
        return validate_f1(q, base_db, root), None
    if family == "F2":
        return validate_f2(q, base_db, api_db, checkpoint, root, base_field_changes), None
    if family == "F3":
        return validate_f3(q, base_db, root, population, pop_rows, pop_integrity), None
    if family == "F4":
        return validate_f4(q, base_db, root), None
    if family == "F5":
        result = _comment_packet(q, base_db, root)
        report = {k: v for k, v in result.items() if k != "packet"}
        # Automated source integrity is separate from subjective gold review.
        report["semantic_review_state"] = "PENDING_HUMAN_SOURCE_REVIEW"
        report["status"] = "UNKNOWN" if result.get("status") == "PASS" else result.get("status", "UNKNOWN")
        return report, result.get("packet")
    if family == "F6":
        return validate_f6(q, base_db, api_db, root), None
    return {"status": "UNKNOWN", "checks": {"known_family": False}, "sources": []}, None


def evidence_integrity(q):
    evidence = q.get("evidence", [])
    field_hashes = [e.get("field_hash") == digest(e.get("fields", {})) for e in evidence]
    provenance = [all(e.get(k) for k in ("id", "source_dataset", "source_row_key", "source_url", "content_hash"))
                  for e in evidence]
    times = []
    for e in evidence:
        event = utc(e.get("event_time_utc")) if e.get("event_time_utc") else None
        observed = utc(e.get("observed_at_utc"))
        ingested = utc(e.get("ingested_at_utc"))
        if (e.get("event_time_utc") and event is None) or observed is None or ingested is None:
            times.append(None)
        else:
            times.append(ingested >= observed and (event is None or event <= observed))
    time_state = status(times) if times else "UNKNOWN"
    checks = {"all_evidence_field_hashes_match": all(field_hashes) if field_hashes else None,
              "all_evidence_has_source_identity_and_hash": all(provenance) if provenance else None,
              "event_observation_ingestion_order_is_valid": True if time_state == "PASS" else
                  False if time_state == "FAIL" else None}
    result_status = status(list(checks.values()))
    return {"status": result_status, "checks": checks}


def _load_checkpoint(path):
    state = _read_json(path)
    if state.get("state") != "COMPLETE":
        raise ValueError("Pinned Phase 4 checkpoint is not COMPLETE")
    return state


def prepare(args):
    root = args.root.resolve()
    run_input = Path(args.run)
    run, gen_manifest, candidates, challenges, queue, population, pins, base, overlay, integrity = _load_inputs(root, run_input)
    all_items = candidates + challenges
    item_by_id = {q["qid"]: q for q in all_items}
    queue_by_id = {r["qid"]: r for r in queue}
    qids = [r["qid"] for r in queue]
    selected_qids = qids[:args.limit] if args.limit else qids
    identity_seed = {"version": VERSION, "run_id": run.name, "queue_sha256": integrity["queue_sha256"],
        "backup_sha256": integrity["backup_sha256"], "generation_manifest_sha256": integrity["generation_manifest_sha256"],
        "candidate_hash": integrity["candidate_hash"], "challenge_hash": integrity["challenge_hash"],
        "source_pins_sha256": integrity["source_pins_sha256"], "seed": gen_manifest["identity"]["options"]["seed"],
        "limit": args.limit, "batch": args.batch, "code_sha256": file_hash(Path(__file__))}
    identity = digest(identity_seed)
    output_root = args.output.resolve()
    prep = output_root / (run.name + "-" + identity[:12])
    critical_integrity = ["queue_header_matches_validator", "queue_matches_candidate_qids", "queue_rows_all_present",
        "queue_static_candidate_rows_match", "queue_decisions_in_validator_enum", "generation_artifacts_verified", "source_pin_identity_matches",
        "generation_state_candidates_ready", "population_manifest_hash_matches", "small_source_hashes_verified",
        "canonical_database_manifest_pin_matches", "phase04_summary_pin_matches",
        "api_overlay_hash_matches_phase04_manifest", "expected_cardinalities_match", "expected_partitions_match"]
    if args.dry_run:
        return {"state": "DRY_RUN", "benchmark_run": str(run.relative_to(root)), "prep_run": str(prep.relative_to(root)),
            "selected_qids": len(selected_qids), "queue_rows": len(queue), "f5_selected": sum(item_by_id[q]["family"] == "F5" for q in selected_qids),
            "limit": args.limit, "batch": args.batch, "queue_sha256": integrity["queue_sha256"],
            "backup_sha256": integrity["backup_sha256"], "input_integrity": integrity,
            "integrity_failures": [k for k in critical_integrity if not integrity.get(k)],
            "network_requests": 0, "writes": 0}
    failed_identity = [k for k in critical_integrity if not integrity.get(k)]
    if failed_identity:
        raise ValueError("Input integrity failed: " + ", ".join(failed_identity))
    backup_path = run / "review_queue.pre_review_backup.csv"
    if not backup_path.is_file():
        raise ValueError("Review backup is missing; preserve the original queue before preparing packets")
    prep.mkdir(parents=True, exist_ok=True)
    manifest_path = prep / "manifest.json"
    checkpoint_path = prep / "checkpoint.json"
    if manifest_path.exists():
        if not args.resume:
            raise FileExistsError("Prep output exists; pass --resume to continue without overwriting packets")
        prior = _read_json(manifest_path)
        if prior.get("identity") != identity_seed:
            raise ValueError("Existing prep output belongs to different queue/source inputs")
    else:
        write_json(manifest_path, {"state": "RUNNING", "version": VERSION, "identity": identity_seed,
            "identity_sha256": identity, "benchmark_run": run.name,
            "input_integrity": integrity, "started_at_utc": datetime.now(timezone.utc).isoformat()})
    progress = _read_json(checkpoint_path) if checkpoint_path.exists() else {"identity_sha256": identity, "completed": {}, "state": "RUNNING"}
    if progress.get("identity_sha256") != identity:
        raise ValueError("Checkpoint identity mismatch")
    # A pinned Phase 4 checkpoint and database are read-only. The validator
    # replays only saved public responses; no request is sent.
    checkpoint = _load_checkpoint(overlay / "checkpoint.json")
    base_db = duckdb.connect(str(base / "canonical.duckdb"), read_only=True)
    api_db = duckdb.connect(str(overlay / "api_enrichment.duckdb"), read_only=True)
    base_db.execute("SET TimeZone='UTC'")
    base_db.execute("SET memory_limit='512MB'")
    base_field_changes = base_db.execute("SELECT count(*) FROM field_changes").fetchone()[0]
    pm_integrity = (population.get("sha256") == digest(population.get("members")) and
                    {k: len(v) for k, v in population.get("members", {}).items()} == {"dev": 592, "test": 2408})
    pop_rows = _load_population_rows(base_db, population, gen_manifest["identity"]["options"]["seed"])
    db_population_integrity = len(pop_rows) == sum(len(x) for x in population["members"].values()) and all(
        phase05.partition(gen_manifest["identity"]["options"]["seed"], bug) == split
        for split, ids in population["members"].items() for bug in ids)
    pm_integrity = pm_integrity and db_population_integrity
    reports = progress.get("reports", {})
    flagged = 0
    try:
        for offset in range(0, len(selected_qids), args.batch):
            batch_qids = selected_qids[offset:offset + args.batch]
            batch_id = offset // args.batch + 1
            packet_dir = prep / "packets" / ("batch-%04d" % batch_id)
            packet_dir.mkdir(parents=True, exist_ok=True)
            for qid in batch_qids:
                q = item_by_id[qid]
                packet_path = packet_dir / (qid + ".json")
                prior_item = progress.get("completed", {}).get(qid)
                if prior_item:
                    if not packet_path.is_file() or file_hash(packet_path) != prior_item.get("packet_sha256"):
                        raise ValueError("A completed packet changed; preserving it: " + qid)
                    reports[qid] = prior_item["validation"]
                    flagged += len(reports[qid].get("heuristic_flag_codes", []))
                    continue
                validation, f5_packet = validate_item(q, base_db, api_db, checkpoint, population, pop_rows,
                    pm_integrity, root, base_field_changes)
                evidence_qc = evidence_integrity(q)
                validation["evidence_integrity"] = evidence_qc
                if evidence_qc["status"] == "FAIL":
                    validation["status"] = "FAIL"
                elif evidence_qc["status"] == "UNKNOWN" and validation.get("status") == "PASS":
                    validation["status"] = "UNKNOWN"
                packet = {"packet_version": VERSION, "qid": qid, "family": q["family"], "split": q["split"],
                    "question": safe_comment_text(q["question"]),
                    "suggested_gold": scrub_strings(q["gold"]) if q["family"] == "F5" else q["gold"], "scope": q["scope"],
                    "evidence_refs": [{k: (scrub_strings(e.get(k)) if q["family"] == "F5" else e.get(k))
                        for k in ("id", "bug_id", "source_dataset", "source_row_key", "source_url", "content_hash", "event_time_utc", "observed_at_utc", "ingested_at_utc", "fields")} for e in q["evidence"]],
                    "deterministic_validation": validation,
                    "codex_recommendation": {"state": "NOT_REVIEWED", "decision": None,
                        "instruction": "Provide a recommendation only; do not write human review decisions or claim human source review."}}
                if f5_packet:
                    packet["f5_full_comment_packet"] = f5_packet
                write_json(packet_path, packet)
                packet_hash = file_hash(packet_path)
                reports[qid] = {"family": q["family"], "split": q["split"], "status": validation.get("status", "UNKNOWN"),
                    "checks": validation.get("checks", {}), "sources": validation.get("sources", []),
                    "semantic_review_state": validation.get("semantic_review_state"),
                    "heuristic_flag_codes": validation.get("heuristic_flag_codes", []),
                    "packet_path": _rel(packet_path, root), "packet_sha256": packet_hash}
                flagged += len(reports[qid].get("heuristic_flag_codes", []))
                progress.setdefault("completed", {})[qid] = {"packet_sha256": packet_hash, "validation": reports[qid]}
                progress["reports"] = reports
                progress["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
                write_json(checkpoint_path, progress)
            print("[assisted-review] prepared batch %04d (%d/%d qids)" % (batch_id,
                min(offset + len(batch_qids), len(selected_qids)), len(selected_qids)), file=sys.stderr, flush=True)
    finally:
        base_db.close()
        api_db.close()
    if file_hash(run / "review_queue.csv") != integrity["queue_sha256"]:
        raise RuntimeError("Review queue changed during prep; no queue edits were made by this tool")
    status_counts = Counter(reports[q].get("status", "UNKNOWN") for q in selected_qids if q in reports)
    family_counts = {f: dict(Counter(reports[q].get("status", "UNKNOWN") for q in selected_qids
        if q in reports and reports[q].get("family") == f)) for f in ("F1", "F2", "F3", "F4", "F5", "F6")}
    flag_codes = Counter(code for q in selected_qids if q in reports for code in reports[q].get("heuristic_flag_codes", []))
    flagged_qids = [q for q in selected_qids if q in reports and reports[q].get("heuristic_flag_codes")]
    report = {"state": ("PREFIX_PREPARED" if args.limit is not None else "PREPARED") if len(reports) >= len(selected_qids) else "PARTIAL",
        "benchmark_run": run.name, "prep_run": str(prep.relative_to(root)), "seed": gen_manifest["identity"]["options"]["seed"],
        "selected_qids": len(selected_qids), "limited_prefix": args.limit is not None,
        "benchmark_qids": len(candidates), "challenge_qids": len(challenges),
        "f5_packets": sum(item_by_id[q]["family"] == "F5" for q in selected_qids),
        "queue_sha256": integrity["queue_sha256"], "backup_sha256": integrity["backup_sha256"],
        "queue_backup_byte_identical": integrity["queue_backup_byte_identical"],
        "candidate_sha256": integrity["candidate_hash"], "challenge_sha256": integrity["challenge_hash"],
        "qid_split_membership_sha256": integrity["qid_split_membership_sha256"],
        "candidate_split_counts": integrity["candidate_split_counts"],
        "challenge_split_counts": integrity["challenge_split_counts"],
        "population_manifest_sha256": population.get("sha256"), "population_partition_counts": integrity["population_partition_counts"],
        "input_integrity": integrity, "base_field_changes": base_field_changes,
        "status_counts": dict(status_counts), "status_counts_by_family": family_counts,
        "f5_heuristic_flag_count": sum(flag_codes.values()), "f5_flagged_qid_count": len(flagged_qids),
        "f5_flag_codes": dict(flag_codes), "f5_flagged_qids": flagged_qids,
        "per_item_report": str((prep / "validation_report.json").relative_to(root)),
        "packet_directory": str((prep / "packets").relative_to(root)),
        "human_review_state": "NOT_SIGNED; Codex recommendations are not independent annotation",
        "network_requests": 0}
    write_json(prep / "validation_report.json", {"version": VERSION, "benchmark_run": run.name,
        "input_integrity": integrity, "per_item": {q: reports[q] for q in selected_qids if q in reports}})
    write_json(prep / "summary.json", report)
    progress.update(state="COMPLETE" if len(reports) >= len(selected_qids) else "PARTIAL", reports=reports,
                    updated_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(checkpoint_path, progress)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--run", type=Path, default=Path("outputs/benchmark/phase05/run-65c5be3381f66811"))
    p.add_argument("--output", type=Path, default=Path("outputs/benchmark/phase05/agent_review_prep"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, help="Prepare only the first N queue rows; output remains a marked prefix.")
    p.add_argument("--batch", type=int, default=10, help="QIDs per output batch directory (default: 10).")
    p.add_argument("--resume", action="store_true", help="Resume only matching inputs and checksummed packets.")
    args = p.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        p.error("--limit must be positive")
    if args.batch <= 0:
        p.error("--batch must be positive")
    result = prepare(args)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
