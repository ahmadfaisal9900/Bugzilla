"""Phase 3B: bounded-memory canonical ingestion from verified Phase 3A inputs.

Raw CSVs are opened read-only. DuckDB, checkpoints, text, and Parquet exports
belong only in the ignored versioned output directory.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import itertools
import json
import re
import sys
import tempfile
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .profile import HashingRaw, _encoding_and_delimiter, parse_flat_yaml

VERSION = 1
NULLS = {"", "nan", "none", "null", "nat", "<na>"}
STATUSES = {"UNCONFIRMED", "NEW", "ASSIGNED", "REOPENED", "RESOLVED", "VERIFIED", "CLOSED"}
RELATIONS = {"blocks": "blocks", "depends_on": "depends_on", "dupe_of": "duplicate_of",
             "duplicates": "has_duplicate", "regressed_by": "regressed_by",
             "regressions": "regresses", "see_also": "see_also"}
PATH_KEYS = {"metadata": "metadata_csv", "comments_part_1": "comments_part_1_csv",
             "comments_part_2": "comments_part_2_csv", "comments_part_3": "comments_part_3_csv",
             "filtered_reports": "reports_csv", "steps_merged": "steps_reports_csv"}
COMMON = {
    "source_record_id": "VARCHAR", "source_dataset": "VARCHAR",
    "source_row_key": "VARCHAR", "source_url": "VARCHAR",
    "event_time_utc": "TIMESTAMPTZ", "observed_at_utc": "TIMESTAMPTZ",
    "ingested_at_utc": "TIMESTAMPTZ", "text_availability": "VARCHAR",
    "raw_field_mapping": "JSON", "content_hash": "VARCHAR",
}
FIELDS = {
    "bugs": {"bug_id": "VARCHAR", "product": "VARCHAR", "component": "VARCHAR",
             "summary": "VARCHAR", "description": "VARCHAR", "opened_at_utc": "TIMESTAMPTZ",
             "snapshot_status": "VARCHAR", "snapshot_resolution": "VARCHAR",
             "snapshot_assignee": "VARCHAR",
             "snapshot_as_of_utc": "TIMESTAMPTZ", "last_change_at_utc": "TIMESTAMPTZ",
             "history_state": "VARCHAR"},
    "comments": {"comment_key": "VARCHAR", "bug_id": "VARCHAR", "comment_id": "VARCHAR",
                 "body": "VARCHAR", "private_flag": "BOOLEAN"},
    "field_changes": {"change_key": "VARCHAR", "bug_id": "VARCHAR", "field_name": "VARCHAR",
                      "old_value": "VARCHAR", "new_value": "VARCHAR"},
    "bug_links": {"link_key": "VARCHAR", "bug_id": "VARCHAR", "target_bug_id": "VARCHAR",
                  "target_url": "VARCHAR", "relation": "VARCHAR", "target_in_corpus": "BOOLEAN",
                  "historical_validity": "VARCHAR"},
    "documents": {"document_id": "VARCHAR", "bug_id": "VARCHAR", "kind": "VARCHAR",
                  "dataset_tier": "VARCHAR", "body": "VARCHAR", "temporal_state": "VARCHAR"},
    "quality_records": {"quality_key": "VARCHAR", "bug_id": "VARCHAR",
                        "body": "VARCHAR", "quality_flags": "JSON", "dataset_tier": "VARCHAR"},
    "source_records": {"record_key": "VARCHAR", "bug_id": "VARCHAR",
                       "source_row_number": "BIGINT", "entity_type": "VARCHAR",
                       "entity_key": "VARCHAR", "entity_content_hash": "VARCHAR",
                       "disposition": "VARCHAR", "reason": "VARCHAR", "notes": "JSON",
                       "normalized_fields": "JSON"},
}
KEYS = {name: next(iter(fields)) for name, fields in FIELDS.items()}
SCHEMAS = {name: {**fields, **COMMON} for name, fields in FIELDS.items()}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def log(message):
    print(f"[{now()}] {message}", file=sys.stderr, flush=True)


def clean(value):
    value = "" if value is None else str(value).strip()
    return None if value.casefold() in NULLS else value


def bug_id(value):
    value = clean(value)
    if value is not None and re.fullmatch(r"[0-9]+\.0+", value):
        value = value.split(".", 1)[0]
    if value is None or not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        return None
    return str(int(value))


def utc(value):
    value = clean(value)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A naive date is not evidence of a UTC event.
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def label(value):
    value = clean(value)
    if value is None:
        return "UNKNOWN"
    return " ".join(unicodedata.normalize("NFC", value).split())


def product(value):
    value = label(value)
    return {"firefox": "Firefox", "core": "Core", "toolkit": "Toolkit"}.get(value.casefold(), value)


def relative(path, root):
    path = Path(path).resolve()
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return "external/" + path.name


def load_selection(root, config, selection, qc_dir, include_quality=False):
    """Read only small QC/config files and input stat metadata; no CSV scan."""
    root = Path(root).resolve()
    config = parse_flat_yaml(Path(config))
    selection_path = Path(selection)
    selection = json.loads(selection_path.read_text())
    qc_dir = Path(qc_dir)
    qc = json.loads((qc_dir / "profile.json").read_text())
    checkpoint = json.loads((qc_dir / "checkpoint.json").read_text())
    if qc.get("status") != "full_profile" or qc.get("limit_per_source") is not None:
        raise ValueError("Phase 3A QC must be a completed unlimited profile")
    if utc(qc.get("generated_at_utc")) is None:
        raise ValueError("Phase 3A observation timestamp must include a valid timezone")
    names = selection["base"] + (selection["optional_quality"] if include_quality else [])
    specs = []
    for name in names:
        report = qc["sources"][name]
        signature = checkpoint["sources"][name]["signature"]
        path = Path(config[PATH_KEYS[name]])
        path = path if path.is_absolute() else root / path
        stat = path.stat()
        if not report.get("scan_complete") or not report["row_count"]["exact"]:
            raise ValueError(f"{name}: QC is not complete")
        if report.get("hash_scope") != "whole_file_sha256" or not re.fullmatch(r"[0-9a-f]{64}", report.get("sha256", "")):
            raise ValueError(f"{name}: full input hash missing")
        if (stat.st_size, stat.st_mtime_ns) != (signature["size_bytes"], signature["mtime_ns"]):
            raise ValueError(f"{name}: input changed since Phase 3A; re-audit before ingestion")
        if relative(path, root) != report["path"] or report["path"] != signature["source_path"]:
            raise ValueError(f"{name}: configured path differs from audited path")
        if report.get("history_event_fields_present"):
            raise ValueError(f"{name}: unexpected history schema needs an explicit reviewed adapter")
        specs.append({
            "name": name, "path": str(path.resolve()), "relative_path": report["path"],
            "sha256": report["sha256"], "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "audited_rows": report["row_count"]["value"],
            "mapping": report["field_mapping"],
            "headers": [x["name"] for x in report["schema"]["columns"]],
            "tier": "BASE" if name in selection["base"] else "QUALITY",
            "observed_at_utc": utc(qc["generated_at_utc"]),
        })
    comparison = qc.get("comment_part_duplicate_check", {})
    if not comparison.get("byte_identical") or comparison.get("sha256_part_1") != comparison.get("sha256_part_2"):
        raise ValueError("Part 2 exclusion requires verified equal whole-file hashes")
    # Check the excluded copy's current signature, without re-reading its bytes.
    alias = qc["sources"]["comments_part_2"]
    sig = checkpoint["sources"]["comments_part_2"]["signature"]
    path = Path(config[PATH_KEYS["comments_part_2"]])
    path = path if path.is_absolute() else root / path
    stat = path.stat()
    if relative(path, root) != alias["path"] or alias["path"] != sig["source_path"]:
        raise ValueError("Excluded Part 2 path differs from audited path")
    if (stat.st_size, stat.st_mtime_ns) != (sig["size_bytes"], sig["mtime_ns"]):
        raise ValueError("Excluded Part 2 changed since its duplicate proof")
    if alias["sha256"] != comparison["sha256_part_1"]:
        raise ValueError("Inconsistent duplicate proof")
    return specs, {
        "qc_path": relative(qc_dir / "profile.json", root),
        "qc_sha256": file_hash(qc_dir / "profile.json"),
        "selection_sha256": file_hash(selection_path),
        "excluded": selection["excluded"],
        "excluded_duplicate_rows": alias["row_count"]["value"],
        "duplicate_proof": comparison,
    }


def init_db(db):
    db.execute("SET TimeZone='UTC'")
    db.execute("SET threads=1")
    for table, columns in SCHEMAS.items():
        fields = ", ".join(f'"{name}" {kind}' for name, kind in columns.items())
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} ({fields}, PRIMARY KEY("{KEYS[table]}"))')
    db.execute("""CREATE TABLE IF NOT EXISTS ingestion_state
        (source_dataset VARCHAR PRIMARY KEY, row_number BIGINT, complete BOOLEAN,
         verified_sha256 VARCHAR, sanitation JSON)""")
    db.execute("""CREATE TABLE IF NOT EXISTS provenance
        (source_dataset VARCHAR PRIMARY KEY, relative_path VARCHAR, sha256 VARCHAR,
         observed_at_utc TIMESTAMPTZ, snapshot_as_of_utc TIMESTAMPTZ,
         size_bytes BIGINT, mtime_ns BIGINT, dataset_tier VARCHAR, raw_field_mapping JSON)""")
    db.execute("""CREATE TABLE IF NOT EXISTS run_manifest
        (manifest_hash VARCHAR PRIMARY KEY, created_at_utc TIMESTAMPTZ, config JSON)""")
    db.execute("""CREATE OR REPLACE MACRO documents_as_of(t) AS TABLE
        SELECT * FROM documents WHERE dataset_tier='BASE' AND temporal_state='SUPPORTED'
        AND text_availability='AVAILABLE' AND event_time_utc<=t AND observed_at_utc<=t""")
    db.execute("""CREATE OR REPLACE MACRO field_changes_as_of(t) AS TABLE
        SELECT * FROM field_changes WHERE event_time_utc<=t AND observed_at_utc<=t""")
    # Both views depend exclusively on explicit resolution-change events.
    metrics = """SELECT b.bug_id,
        min(f.event_time_utc) FILTER (WHERE f.field_name='resolution'
            AND upper(f.new_value)='FIXED' AND coalesce(upper(f.old_value),'')<>'FIXED'
            AND f.event_time_utc>=b.opened_at_utc) AS first_fixed_at_utc,
        epoch(first_fixed_at_utc-b.opened_at_utc)/86400.0 AS first_fixed_calendar_days,
        CASE WHEN first_fixed_at_utc IS NULL THEN 'UNKNOWN' ELSE 'KNOWN' END AS fix_duration_state,
        CASE WHEN count(*) FILTER (WHERE f.field_name='status' AND upper(f.new_value)='REOPENED')>0
             THEN true ELSE NULL END AS reopened_observed,
        'UNKNOWN' AS developer_hours
        FROM {bugs} b LEFT JOIN {events} f ON b.bug_id=f.bug_id GROUP BY b.bug_id,b.opened_at_utc"""
    db.execute("CREATE OR REPLACE VIEW fix_metrics AS " + metrics.format(bugs="bugs", events="field_changes"))
    db.execute("CREATE OR REPLACE MACRO fix_metrics_as_of(t) AS TABLE " +
               metrics.format(bugs="(SELECT * FROM bugs WHERE opened_at_utc<=t AND observed_at_utc<=t)",
                              events="field_changes_as_of(t)"))


def source_url(parent, row):
    url = f"https://bugzilla.mozilla.org/show_bug.cgi?id={parent}" if parent else None
    count = clean(row.get("count"))
    return url + "#c" + str(int(count)) if url and count and count.isdigit() else url


def parse_links(row):
    links, malformed = [], 0
    for column, relation in RELATIONS.items():
        raw = clean(row.get(column))
        if not raw or raw in ("[]", "{}"):
            continue
        try:
            values = json.loads(raw)
        except (ValueError, TypeError):
            try:
                values = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                values = raw
        values = values if isinstance(values, (list, tuple)) else [values]
        for value in values:
            target = bug_id(value)
            target_url = None
            if target is None and isinstance(value, str):
                parsed = urlparse(value)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    target_url = value
                    if parsed.hostname == "bugzilla.mozilla.org" and parsed.path == "/show_bug.cgi":
                        target = bug_id(parse_qs(parsed.query).get("id", [None])[0])
            if target is None and target_url is None:
                malformed += 1
            else:
                links.append({"target_bug_id": target, "target_url": target_url, "relation": relation})
    return links, malformed


def normalize_row(spec, row, ordinal, ingested_at, width_error=False):
    """Pure row adapter. It never invents field changes or historical states."""
    mapping = {**spec["mapping"], "summary": "summary", "description": None,
               "relationships": list(RELATIONS)}
    parent = bug_id(row.get(mapping.get("bug_id")))
    event = utc(row.get(mapping.get("created_at")))
    raw_hash = digest({str(k) if k is not None else "__extra_fields__": v for k, v in row.items()})
    row_key = f'{spec["sha256"]}:{ordinal:020d}'
    record_id = digest([spec["name"], row_key])
    common = {
        "source_record_id": record_id, "source_dataset": spec["name"],
        "source_row_key": row_key, "source_url": source_url(parent, row),
        "event_time_utc": event, "observed_at_utc": spec["observed_at_utc"],
        "ingested_at_utc": ingested_at, "text_availability": "UNKNOWN",
        "raw_field_mapping": mapping, "content_hash": raw_hash,
    }
    record = {"record_key": record_id, "bug_id": parent, "source_row_number": ordinal,
              "entity_type": None, "entity_key": None, "entity_content_hash": None,
              "disposition": "CANDIDATE", "reason": None, "notes": [], "normalized_fields": {}, **common}
    result = defaultdict(list)
    result["source_records"].append(record)
    if width_error or parent is None:
        record.update(disposition="QUARANTINED", reason="column_width" if width_error else "invalid_bug_id")
        return result
    status = clean(row.get(mapping.get("status")))
    status = status.upper() if status else None
    resolution = clean(row.get(mapping.get("resolution")))
    resolution = resolution.upper() if resolution else None
    if status and status not in STATUSES:
        record.update(disposition="QUARANTINED", reason="invalid_snapshot_status")
        return result
    def add_entity(table, payload, entity_common):
        content = digest(payload)
        entity = {**payload, **entity_common, "content_hash": content}
        result[table].append(entity)
        record.update(entity_type=table, entity_key=entity[KEYS[table]],
                      entity_content_hash=content, normalized_fields=payload,
                      text_availability=entity_common["text_availability"])
        return entity
    if spec["name"] == "metadata":
        links, malformed = parse_links(row)
        if malformed:
            record["notes"].append("malformed_relationship_values:" + str(malformed))
        if event is None:
            record["notes"].append("missing_or_invalid_creation_timezone")
        if clean(row.get(mapping.get("last_change_at"))) and utc(row.get(mapping.get("last_change_at"))) is None:
            record["notes"].append("invalid_last_change_timestamp")
        summary = clean(row.get("summary"))
        available = "AVAILABLE" if summary else "EMPTY"
        payload = {
            "bug_id": parent, "product": product(row.get(mapping.get("product"))),
            "component": label(row.get(mapping.get("component"))), "summary": summary,
            "description": None, "opened_at_utc": event, "snapshot_status": status or "UNKNOWN",
            "snapshot_resolution": resolution, "snapshot_as_of_utc": None,
            "snapshot_assignee": None,
            "last_change_at_utc": utc(row.get(mapping.get("last_change_at"))), "history_state": "UNKNOWN",
        }
        entity = add_entity("bugs", payload, {**common, "text_availability": available})
        entity["content_hash"] = digest({**payload, "recorded_links": links})
        record["entity_content_hash"] = entity["content_hash"]
        for link in links:
            key = digest([parent, link])
            result["bug_links"].append({
                "link_key": key, "bug_id": parent, **link, "target_in_corpus": False,
                "historical_validity": "UNKNOWN", **common,
                "event_time_utc": None, "text_availability": "EMPTY", "content_hash": digest(link),
            })
        result["documents"].append({
            "document_id": digest(["bug_snapshot", parent]), "bug_id": parent, "kind": "bug_snapshot",
            "dataset_tier": "BASE", "body": summary, "temporal_state": "UNKNOWN",
            **entity_common_for_doc(entity), "event_time_utc": None,
        })
        # Relationship variants participate in conflict detection, not inferred history.
        record["normalized_fields"] = {**payload, "recorded_links": links}
    else:
        if event is None:
            record.update(disposition="QUARANTINED", reason="invalid_event_timestamp_or_timezone")
            return result
        body = row.get(mapping.get("comment_text"), "") or ""
        private_raw = clean(row.get(mapping.get("private_flag")))
        private = (False if private_raw and private_raw.casefold() in ("false", "0", "no")
                   else True if private_raw and private_raw.casefold() in ("true", "1", "yes") else None)
        availability = ("WITHHELD_PRIVATE" if private is True else "WITHHELD_UNKNOWN_PRIVACY"
                        if private is None else "AVAILABLE" if body.strip() else "EMPTY")
        visible_body = body if availability == "AVAILABLE" else None
        comment_id = clean(row.get(mapping.get("comment_id")))
        # Preserve different parents, times, IDs, and content versions.
        key = digest([parent, comment_id, event, digest(body), private])
        entity_common = {**common, "text_availability": availability}
        if spec["tier"] == "QUALITY":
            table = "quality_records"
            payload = {"quality_key": key, "bug_id": parent, "body": visible_body,
                       "dataset_tier": "QUALITY", "quality_flags": {
                           "contains_steps_to_reproduce": clean(row.get("contains_steps_to_reproduce")),
                           "snapshot_status": status, "snapshot_resolution": resolution,
                       }}
        else:
            table = "comments"
            payload = {"comment_key": key, "bug_id": parent, "comment_id": comment_id,
                       "body": visible_body, "private_flag": private}
        entity = add_entity(table, payload, entity_common)
        record["normalized_fields"] = {"bug_id": parent, "comment_id": comment_id,
                                       "event_time_utc": event, "body_hash": digest(body)}
        result["documents"].append({
            "document_id": digest([table, key]), "bug_id": parent, "kind": table,
            "dataset_tier": spec["tier"], "body": visible_body,
            "temporal_state": "SUPPORTED" if availability == "AVAILABLE" else "UNKNOWN",
            **entity_common_for_doc(entity),
        })
    return result


def entity_common_for_doc(entity):
    return {name: entity[name] for name in COMMON}


def batch_insert(db, table, rows, scratch):
    if not rows:
        return
    # A typed NDJSON batch avoids one Python -> DuckDB SQL call per CSV row.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", dir=scratch,
                                     encoding="utf-8", delete=False) as handle:
        path = Path(handle.name)
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    try:
        columns = "{" + ",".join(f"'{name}':'{kind}'" for name, kind in SCHEMAS[table].items()) + "}"
        query = f"SELECT * FROM read_json(?, format='newline_delimited', columns={columns}, maximum_object_size=67108864)"
        key = KEYS[table]
        query = (f"SELECT * EXCLUDE(rn) FROM (SELECT *, row_number() OVER "
                 f"(PARTITION BY {key} ORDER BY source_row_key) AS rn FROM ({query})) WHERE rn=1")
        if table in ("comments", "quality_records"):
            query = f"SELECT * FROM ({query}) q WHERE EXISTS (SELECT 1 FROM bugs b WHERE b.bug_id=q.bug_id)"
        if table == "bug_links":
            query = f"SELECT * FROM ({query}) q WHERE EXISTS (SELECT 1 FROM bugs b WHERE b.source_record_id=q.source_record_id)"
        if table == "documents":
            query = f"""SELECT * FROM ({query}) q WHERE source_record_id IN
                (SELECT source_record_id FROM bugs UNION ALL SELECT source_record_id FROM comments
                 UNION ALL SELECT source_record_id FROM quality_records)"""
        db.execute(f"INSERT OR IGNORE INTO {table} BY NAME {query}", [str(path)])
    finally:
        # Remove only this newly created scratch batch, never an input or export.
        path.unlink()


def flush(db, queues, spec, watermark, sanitation, scratch):
    db.execute("BEGIN")
    try:
        for table in ("source_records", "bugs", "comments", "quality_records", "field_changes", "bug_links", "documents"):
            batch_insert(db, table, queues.get(table, []), scratch)
        for table in ("bugs", "comments", "quality_records"):
            key = KEYS[table]
            db.execute(f"""UPDATE source_records AS s SET disposition=CASE
                WHEN t.source_record_id=s.source_record_id THEN 'NORMALIZED'
                WHEN t.content_hash=s.entity_content_hash THEN 'DUPLICATE'
                ELSE 'CONFLICT_VARIANT' END
                FROM {table} t WHERE s.entity_type=? AND s.entity_key=t.{key}
                AND s.source_dataset=? AND s.disposition='CANDIDATE'""", [table, spec["name"]])
        db.execute("""UPDATE source_records SET disposition='QUARANTINED',reason='orphan_parent'
            WHERE source_dataset=? AND disposition='CANDIDATE'""", [spec["name"]])
        db.execute("""INSERT OR REPLACE INTO ingestion_state VALUES (?,?,false,NULL,?)""",
                   [spec["name"], watermark, canonical_json(dict(sanitation))])
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def ingest_source(db, spec, args, scratch, ingested_at):
    existing = db.execute("SELECT row_number,complete FROM ingestion_state WHERE source_dataset=?", [spec["name"]]).fetchone()
    if existing and existing[1]:
        log(spec["name"] + ": skip completed source")
        return
    skip = existing[0] if existing else 0
    queues = defaultdict(list)
    sanitation = Counter()
    encoding, delimiter = _encoding_and_delimiter(Path(spec["path"]))
    csv.field_size_limit(sys.maxsize)
    log(f'{spec["name"]}: stream; committed rows={skip}; limit={args.limit}')
    with Path(spec["path"]).open("rb") as raw:
        hashing = HashingRaw(raw)
        with io.TextIOWrapper(io.BufferedReader(hashing), encoding=encoding, errors="replace", newline="") as text:
            def lines():
                for line in text:
                    sanitation["nul_characters_removed"] += line.count("\x00")
                    sanitation["replacement_characters"] += line.count("\ufffd")
                    yield line.replace("\x00", "")
            reader = csv.DictReader(lines(), delimiter=delimiter)
            if reader.fieldnames != spec["headers"]:
                raise ValueError(spec["name"] + ": header differs from Phase 3A")
            ordinal = 0
            for ordinal, row in enumerate(itertools.islice(reader, args.limit), 1):
                if ordinal <= skip:
                    continue
                bad_width = None in row or any(value is None for value in row.values())
                normalized = normalize_row(spec, row, ordinal, ingested_at, bad_width)
                for table, values in normalized.items():
                    queues[table].extend(values)
                if ordinal % args.chunk_size == 0:
                    flush(db, queues, spec, ordinal, sanitation, scratch)
                    queues.clear()
                    log(f'{spec["name"]}: checkpoint {ordinal:,} rows')
            if queues:
                flush(db, queues, spec, ordinal, sanitation, scratch)
    if args.limit is None:
        actual = hashing.digest.hexdigest()
        if actual != spec["sha256"] or ordinal != spec["audited_rows"]:
            raise ValueError(spec["name"] + ": streamed hash/count does not match Phase 3A; outputs are not validated")
        stat = Path(spec["path"]).stat()
        if (stat.st_size, stat.st_mtime_ns) != (spec["size_bytes"], spec["mtime_ns"]):
            raise ValueError(spec["name"] + ": input changed during ingestion")
        db.execute("INSERT OR REPLACE INTO ingestion_state VALUES (?,?,true,?,?)",
                   [spec["name"], ordinal, actual, canonical_json(dict(sanitation))])
    else:
        db.execute("INSERT OR REPLACE INTO ingestion_state VALUES (?,?,false,NULL,?)",
                   [spec["name"], ordinal, canonical_json(dict(sanitation))])
    log(f'{spec["name"]}: finished {ordinal:,} logical records; full_hash_verified={args.limit is None}')


def make_sample(db, target, seed, selected_product):
    db.execute("CREATE TABLE IF NOT EXISTS sample_membership (bug_id VARCHAR PRIMARY KEY,seed BIGINT,stratum VARCHAR)")
    if db.execute("SELECT count(*) FROM sample_membership").fetchone()[0]:
        return
    query = """SELECT bug_id,
        concat(product,'|',component,'|',coalesce(cast(year(opened_at_utc) AS VARCHAR),'UNKNOWN'),
               '|',snapshot_status,'|',coalesce(snapshot_resolution,'NONE')) AS stratum,
        sha256(? || ':' || bug_id) AS seeded_order,
        row_number() OVER (PARTITION BY snapshot_status,coalesce(snapshot_resolution,'NONE')
                           ORDER BY sha256(? || ':' || bug_id)) AS outcome_rank,
        row_number() OVER (PARTITION BY product,component,year(opened_at_utc),snapshot_status,snapshot_resolution
                           ORDER BY sha256(? || ':' || bug_id)) AS stratum_rank
        FROM bugs WHERE (?='ALL' OR product=?)"""
    params = [str(seed)] * 3 + [selected_product] * 2
    outcomes = db.execute("""SELECT count(*) FROM (SELECT DISTINCT snapshot_status,snapshot_resolution
        FROM bugs WHERE (?='ALL' OR product=?))""", [selected_product] * 2).fetchone()[0]
    if target < outcomes:
        raise ValueError(f"sample target {target} is smaller than {outcomes} outcome strata; increase it")
    rows = db.execute(f"""SELECT bug_id,stratum FROM ({query})
        ORDER BY CASE WHEN outcome_rank=1 THEN 0 ELSE 1 END,stratum_rank,seeded_order,bug_id LIMIT ?""",
                      params + [target]).fetchall()
    if rows:
        db.executemany("INSERT INTO sample_membership VALUES (?,?,?)", [(b, seed, s) for b, s in rows])


def rows_as_dicts(db, sql, params=None):
    result = db.execute(sql, params or [])
    names = [x[0] for x in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def qc_report(db, specs, args):
    sources = {}
    for spec in specs:
        dispositions = dict(db.execute("""SELECT disposition,count(*) FROM source_records
            WHERE source_dataset=? GROUP BY disposition""", [spec["name"]]).fetchall())
        state = db.execute("SELECT row_number,complete,verified_sha256,sanitation FROM ingestion_state WHERE source_dataset=?",
                           [spec["name"]]).fetchone()
        observed_rows = state[0]
        if sum(dispositions.values()) != observed_rows:
            raise ValueError(spec["name"] + ": source row accounting failed")
        sources[spec["name"]] = {
            "audited_original_rows": spec["audited_rows"], "scanned_rows": observed_rows,
            "scope": "FULL_VERIFIED" if state[1] else "BOUNDED_PREFIX",
            "dispositions": dispositions, "accounting_ok": True, "verified_sha256": state[2],
            "sanitation": json.loads(state[3]),
        }
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in FIELDS}
    orphans = db.execute("SELECT count(*) FROM comments c LEFT JOIN bugs b USING(bug_id) WHERE b.bug_id IS NULL").fetchone()[0]
    dangling_docs = db.execute("SELECT count(*) FROM documents d LEFT JOIN source_records s USING(source_record_id) WHERE s.record_key IS NULL").fetchone()[0]
    if orphans or dangling_docs:
        raise ValueError("Canonical parent/provenance join QC failed")
    result = {
        "state": "BOUNDED_PREFIX" if args.limit else "NORMALIZED_FULL_INPUTS",
        "sources": sources, "table_counts": counts,
        "quarantine_reasons": dict(db.execute("SELECT reason,count(*) FROM source_records WHERE disposition='QUARANTINED' GROUP BY reason").fetchall()),
        "orphan_comments_in_canonical": orphans,
        "orphan_source_records": db.execute("SELECT count(*) FROM source_records WHERE reason='orphan_parent'").fetchone()[0],
        "comment_parent_join_coverage": 1.0 if counts["comments"] else None,
        "incoming_comment_parent_joins": rows_as_dicts(db, """SELECT s.source_dataset,
            count(*) AS valid_comment_source_rows, count(b.bug_id) AS joined_source_rows,
            count(DISTINCT s.bug_id) AS distinct_source_bugs,
            count(DISTINCT b.bug_id) AS distinct_joined_bugs
            FROM source_records s LEFT JOIN bugs b ON b.bug_id=s.bug_id
            WHERE s.entity_type='comments' GROUP BY s.source_dataset"""),
        "bugs_with_comments": db.execute("SELECT count(DISTINCT bug_id) FROM comments").fetchone()[0],
        "bug_comment_coverage": (db.execute("SELECT count(DISTINCT bug_id) FROM comments").fetchone()[0]
                                 / counts["bugs"]) if counts["bugs"] else None,
        "missing_history_bugs": db.execute("SELECT count(*) FROM bugs WHERE history_state='UNKNOWN'").fetchone()[0],
        "unknown_fix_durations": db.execute("SELECT count(*) FROM fix_metrics WHERE fix_duration_state='UNKNOWN'").fetchone()[0],
        "comment_id_versions": db.execute("""SELECT count(*) FROM (SELECT bug_id,comment_id FROM comments
            WHERE comment_id IS NOT NULL GROUP BY bug_id,comment_id HAVING count(*)>1)""").fetchone()[0],
        "product_counts": dict(db.execute("SELECT product,count(*) FROM bugs GROUP BY product").fetchall()),
        "outcome_counts": rows_as_dicts(db, "SELECT snapshot_status,snapshot_resolution,count(*) AS bugs FROM bugs GROUP BY ALL"),
        "sample_product": args.product, "sample_seed": args.sample_seed, "sample_target": args.sample_target,
        "sample_count": db.execute("SELECT count(*) FROM sample_membership").fetchone()[0],
        "sample_outcomes": rows_as_dicts(db, """SELECT b.snapshot_status,b.snapshot_resolution,count(*) AS bugs
            FROM bugs b JOIN sample_membership s USING(bug_id) GROUP BY ALL"""),
        "links_by_relation": dict(db.execute("SELECT relation,count(*) FROM bug_links GROUP BY relation").fetchall()),
        "target_links_outside_corpus": db.execute("SELECT count(*) FROM bug_links WHERE NOT target_in_corpus").fetchone()[0],
        "timestamp_invalid_source_rows": db.execute("SELECT count(*) FROM source_records WHERE reason='invalid_event_timestamp_or_timezone'").fetchone()[0],
        "event_timestamp_coverage": rows_as_dicts(db, """SELECT source_dataset,count(*) AS source_rows,
            count(event_time_utc) AS valid_utc_event_rows FROM source_records GROUP BY source_dataset"""),
        "unknown_product_bugs": db.execute("SELECT count(*) FROM bugs WHERE product='UNKNOWN'").fetchone()[0],
        "unknown_component_bugs": db.execute("SELECT count(*) FROM bugs WHERE component='UNKNOWN'").fetchone()[0],
        "privacy": dict(db.execute("SELECT text_availability,count(*) FROM comments GROUP BY text_availability").fetchall()),
        "F2": "UNKNOWN without explicit qualifying resolution transitions; no CSV history synthesized",
        "F4": "Recorded snapshot links only; historical validity and past target statuses remain UNKNOWN",
        "developer_hours": "UNKNOWN; never inferred from elapsed calendar days",
    }
    if args.cutoff:
        result["explicit_cutoff_utc"] = utc(args.cutoff)
        result["visible_base_documents_at_cutoff"] = db.execute(
            "SELECT count(*) FROM documents_as_of(?::TIMESTAMPTZ)", [utc(args.cutoff)]).fetchone()[0]
    return result


def examples(db, seed):
    rows = rows_as_dicts(db, """SELECT b.bug_id,b.product,b.component,b.snapshot_status,b.snapshot_resolution,
        cast(b.opened_at_utc AS VARCHAR) AS creation_utc, b.history_state,
        f.fix_duration_state,coalesce(c.n,0) AS comments,coalesce(l.n,0) AS links
        FROM bugs b JOIN fix_metrics f USING(bug_id)
        LEFT JOIN (SELECT bug_id,count(*) n FROM comments GROUP BY bug_id) c USING(bug_id)
        LEFT JOIN (SELECT bug_id,count(*) n FROM bug_links GROUP BY bug_id) l USING(bug_id)
        ORDER BY sha256(? || ':' || b.bug_id) LIMIT 20""", [str(seed)])
    for row in rows:
        row["bug_alias"] = "B-" + digest([seed, row.pop("bug_id")])[:12]
    return rows


def export_parquet(db, output):
    export = output / "exports" / ("export-" + uuid.uuid4().hex[:12])
    export.mkdir(parents=True)
    tables = list(FIELDS) + ["provenance", "run_manifest", "sample_membership"]
    for table in tables:
        folder = export / table
        folder.mkdir()
        count = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if table in FIELDS and count:
            db.execute(f"""COPY (SELECT *,source_dataset AS partition_source FROM {table})
                TO ? (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(partition_source))""", [str(folder)])
        else:
            db.execute(f"COPY {table} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(folder / "part-00000.parquet")])
    return export


def normalize(args):
    duckdb = None
    if not args.dry_run:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("Install the free pinned dependency: python -m pip install duckdb==1.4.4") from exc
    root = Path(args.root).resolve()
    qc_dir = Path(args.qc_dir) if args.qc_dir else root / "outputs/data_exploration" / (
        root / "outputs/data_exploration/LATEST_RUN").read_text().strip()
    if not qc_dir.is_absolute():
        qc_dir = root / qc_dir
    config = Path(args.config)
    config = config if config.is_absolute() else root / config
    selection = Path(args.selection)
    selection = selection if selection.is_absolute() else root / selection
    specs, evidence = load_selection(root, config, selection, qc_dir, args.include_quality)
    evidence["selection_sha256"] = file_hash(selection)
    options = {name: getattr(args, name) for name in
               ("limit", "sample_seed", "sample_target", "product", "include_quality", "cutoff", "chunk_size", "memory_limit")}
    identity = {"version": VERSION, "sources": [{k: v for k, v in s.items() if k != "path"} for s in specs],
                "options": options, "qc": evidence, "code_sha256": file_hash(__file__),
                "duckdb_version": duckdb.__version__ if duckdb else "not_required_for_dry_run"}
    if args.dry_run:
        print(json.dumps({"dry_run": True, "selected_sources": [
                          {k: v for k, v in s.items() if k != "headers"} for s in identity["sources"]],
                          "excluded": evidence["excluded"], "options": options}, indent=2))
        return None
    output = Path(args.output)
    output = output if output.is_absolute() else root / output
    if output.resolve() == root or (root / "Dataset").resolve() in [output.resolve(), *output.resolve().parents]:
        raise ValueError("Output must be a separate run directory outside Dataset")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    identity_hash = digest(identity)
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if not args.resume:
            raise ValueError("Run already exists: use --resume or a new versioned output directory")
        if previous["identity_hash"] != identity_hash:
            raise ValueError("Resume options, code, QC, or input signatures changed; start a new run")
        if previous["state"] == "COMPLETE":
            for name, artifact in previous["artifacts"].items():
                path = output / name
                if not path.is_file() or path.stat().st_size != artifact["bytes"]:
                    raise ValueError("Completed artifact is missing or changed; preserve this run and start a new version")
            log("Run already complete; reused unchanged run without reimport or re-export")
            return json.loads((output / "qc_report.json").read_text())
        manifest = previous
    else:
        if args.resume:
            raise ValueError("Cannot resume without an existing manifest")
        if any((output / name).exists() for name in ("canonical.duckdb", "exports", "qc_report.json")):
            raise ValueError("Existing outputs without a manifest; preserve them and choose a new run directory")
        manifest = {"identity_hash": identity_hash, "identity": identity,
                    "ingested_at_utc": now(), "state": "INGESTING"}
        write_json(manifest_path, manifest)
    scratch = output / "scratch"
    scratch.mkdir(exist_ok=True)
    db_path = output / "canonical.duckdb"
    db = duckdb.connect(str(db_path))
    try:
        db.execute("SET memory_limit=?", [args.memory_limit])
        db.execute("SET temp_directory=?", [str(scratch / "spill")])
        init_db(db)
        db.execute("INSERT OR IGNORE INTO run_manifest VALUES (?,?,?)",
                   [identity_hash, manifest["ingested_at_utc"], canonical_json(identity)])
        for spec in specs:
            db.execute("INSERT OR IGNORE INTO provenance VALUES (?,?,?,?,NULL,?,?,?,?)",
                       [spec["name"], spec["relative_path"], spec["sha256"], spec["observed_at_utc"],
                        spec["size_bytes"], spec["mtime_ns"], spec["tier"], canonical_json(spec["mapping"])])
            ingest_source(db, spec, args, scratch, manifest["ingested_at_utc"])
        db.execute("UPDATE bug_links SET target_in_corpus=EXISTS(SELECT 1 FROM bugs WHERE bugs.bug_id=bug_links.target_bug_id)")
        make_sample(db, args.sample_target, args.sample_seed, args.product)
        qc = qc_report(db, specs, args)
        example_rows = examples(db, args.sample_seed)
        sample = rows_as_dicts(db, "SELECT * FROM sample_membership ORDER BY bug_id")
        export = export_parquet(db, output)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    write_json(output / "qc_report.json", qc)
    write_json(output / "anonymized_examples.json", example_rows)
    write_json(output / "sample_manifest.json", {
        "seed": args.sample_seed, "target": args.sample_target, "product": args.product,
        "algorithm": "SHA-256 seeded order; preserve each status/resolution outcome, then round-robin component/year/outcome strata",
        "members": sample, "identity_hash": identity_hash,
    })
    files = [db_path, output / "qc_report.json", output / "anonymized_examples.json", output / "sample_manifest.json"]
    files.extend(sorted(export.rglob("*.parquet")))
    artifacts = {relative(p, output): {"sha256": file_hash(p), "bytes": p.stat().st_size} for p in files}
    manifest.update(state="COMPLETE", completed_at_utc=now(), artifacts=artifacts,
                    parquet_version=relative(export, output))
    write_json(manifest_path, manifest)
    write_json(output / "summary.json", {"state": qc["state"], "table_counts": qc["table_counts"],
               "missing_history_bugs": qc["missing_history_bugs"], "sample_count": qc["sample_count"],
               "identity_hash": identity_hash, "manifest": "manifest.json", "qc": "qc_report.json"})
    log("Complete: query canonical.duckdb; inspect qc_report.json and manifest.json before Phase 4")
    return qc


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".")
    p.add_argument("--config", default="configs/data_paths.local.yaml")
    p.add_argument("--selection", default="configs/phase03b_sources.json")
    p.add_argument("--qc-dir", help="Completed Phase 3A run; defaults to its LATEST_RUN")
    p.add_argument("--output", default="outputs/normalization/phase03b/manual")
    p.add_argument("--limit", type=int, help="Bounded prefix per selected source; never a full-run result")
    p.add_argument("--chunk-size", type=int, default=2000)
    p.add_argument("--sample-seed", type=int, default=317)
    p.add_argument("--sample-target", type=int, default=3000, help="Planning target; fewer bugs are allowed")
    p.add_argument("--product", default="Firefox", help="Sample product; ALL retains all products in sampling")
    p.add_argument("--cutoff", help="Optional explicit UTC as-of QC query; no T0/T1 is chosen by default")
    p.add_argument("--memory-limit", default="512MB")
    p.add_argument("--include-quality", action="store_true", help="Keep optional audited quality records separate from the base")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if any(value is not None and value < 1 for value in (args.limit, args.chunk_size, args.sample_target)):
        raise SystemExit("Limits, chunk size, and target must be positive")
    if args.cutoff and utc(args.cutoff) is None:
        raise SystemExit("--cutoff must include an explicit timezone")
    normalize(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
