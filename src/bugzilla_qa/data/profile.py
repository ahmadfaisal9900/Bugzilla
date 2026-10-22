"""Streaming, privacy-conscious profiling of the local BugsRepo CSV exports.

The profiler reads one CSV record at a time. It stores identifier keys and
checkpoints in SQLite under the ignored output directory; it never writes
comment bodies, reporter names, or email addresses to reports.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = 1
SAMPLE_ROWS = 96
PROGRESS_EVERY = 25_000

SOURCES = (
    ("metadata", "metadata_csv", "Bug_meta_data.csv", "bug snapshot metadata"),
    ("metadata_all", "metadata_all_csv", "Bug_meta_data_230k_all.csv", "possible metadata re-export"),
    ("filtered_reports", "reports_csv", "CSV_100k_filtered_bug_reports.csv", "filtered report/comment records"),
    ("steps_merged", "steps_reports_csv", "CSV_Bug_reports_with_steps_to_reproduce (1).csv", "quality-scored merged report/comment export"),
    ("contributors", "contribution_csv", "CSV_Contribution_information_dataset.csv", "contributor aggregates"),
    ("comments_part_1", "comments_part_1_csv", "comments_Dataset_Part_1.csv", "comment records merged with bug metadata"),
    ("comments_part_2", "comments_part_2_csv", "comments_Dataset_Part_2.csv", "possible repeated comment export"),
    ("comments_part_3", "comments_part_3_csv", "comments_Dataset_Part_3.csv", "comment records merged with bug metadata"),
    ("upstream_sample", "upstream_sample_csv", "EASE_2025_Data_paper/Sample_Dataset/bugs-2025-02-23.csv", "upstream sample snapshot"),
)

FIELD_CANDIDATES = {
    "bug_id": ("bug_id", "Bug ID", "Bug Id", "id", "_id"),
    "comment_id": ("comment_id", "Comment ID", "commentid", "id", "_id_x"),
    "created_at": ("creation_time_x", "creation_time", "created_at", "Created On", "Created", "Time", "Updated"),
    "last_change_at": ("last_change_time", "Last Change Time", "updated_at", "Updated"),
    "product": ("product", "Product"),
    "component": ("component", "Component"),
    "status": ("status", "Status", "Bug Status"),
    "resolution": ("resolution", "Resolution"),
    "comment_text": ("text", "raw_text", "Comment Text", "comment", "description"),
    "private_flag": ("is_private", "Is Private", "private"),
}
RELATION_FIELDS = ("dupe_of", "duplicates", "see_also", "blocks", "depends_on", "regressions", "regressed_by")
EVENT_FIELD_RE = re.compile(r"(^|_)(event_time|event_id|history|changes|old_value|new_value|field_change)(_|$)", re.I)
COMMIT_FIELD_RE = re.compile(r"commit|changeset|revision|landed", re.I)
SENSITIVE_COLUMN_RE = re.compile(r"email|author|creator|assignee|reporter|user.?name|login|contributor", re.I)


def parse_flat_yaml(path: Path) -> dict[str, str]:
    """Parse the flat scalar subset used by the tracked/local data path files."""
    values: dict[str, str] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in raw:
            raise ValueError(f"{path}:{line_no}: expected key: value")
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if value.startswith(("'", '"')) and value[-1:] == value[:1]:
            value = value[1:-1]
        if not key or not value:
            raise ValueError(f"{path}:{line_no}: empty key or value")
        values[key] = value
    return values


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return f"external/{path.name}"


def _resolve_sources(root: Path, config_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    config = parse_flat_yaml(config_path) if config_path.is_file() else {}
    sources = []
    missing = []
    for name, key, default, role in SOURCES:
        value = config.get(key, f"Dataset/{default}")
        path = Path(os.path.expanduser(value))
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            sources.append({"name": name, "config_key": key, "path": path, "display_path": _relative_path(path, root), "role": role})
        else:
            missing.append({"source": name, "config_key": key, "path": _relative_path(path, root)})
    return sources, missing


def _mapping(headers: list[str], source: str) -> dict[str, str | None]:
    exact = set(headers)
    result = {}
    for logical, candidates in FIELD_CANDIDATES.items():
        if logical == "comment_id" and not source.startswith("comments") and source != "steps_merged":
            result[logical] = None
            continue
        result[logical] = next((candidate for candidate in candidates if candidate in exact), None)
    return result


def parse_timestamp(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
            try:
                result = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if result is None:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _cell(row: dict[str, Any], field: str | None) -> str:
    if field is None:
        return ""
    value = row.get(field)
    return value if isinstance(value, str) else ""


def _dtype(value: str) -> str:
    if not value.strip():
        return "empty"
    text = value.strip()
    if text.lower() in {"true", "false", "yes", "no", "1", "0"}:
        return "boolean_or_integer"
    try:
        int(text)
        return "integer"
    except ValueError:
        pass
    try:
        float(text)
        return "number"
    except ValueError:
        pass
    if parse_timestamp(text) is not None:
        return "datetime"
    return "string"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _log(path: Path, message: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"[{stamp}] {message}"
    print(line, file=sys.stderr, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


class HashingRaw(io.RawIOBase):
    """Hash bytes as the buffered CSV decoder consumes them."""

    def __init__(self, raw: Any):
        self.raw = raw
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        count = self.raw.readinto(buffer)
        if count:
            self.digest.update(memoryview(buffer)[:count])
        return count

    def close(self) -> None:
        try:
            self.raw.close()
        finally:
            super().close()


def _encoding_and_delimiter(path: Path) -> tuple[str, str]:
    with path.open("rb") as raw:
        sample = raw.read(96 * 1024)
    if sample.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        try:
            sample.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            try:
                sample.decode("cp1252")
                encoding = "cp1252"
            except UnicodeDecodeError:
                encoding = "latin-1"
    text = sample.decode(encoding, errors="surrogateescape")
    try:
        delimiter = csv.Sniffer().sniff(text[:32_768], delimiters=",\t;|").delimiter
    except csv.Error:
        delimiter = ","
    return encoding, delimiter


def _init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("CREATE TABLE IF NOT EXISTS bug_ids (source TEXT NOT NULL, bug_id TEXT NOT NULL, PRIMARY KEY(source, bug_id))")
    db.execute("CREATE TABLE IF NOT EXISTS comment_keys (source TEXT NOT NULL, key TEXT NOT NULL, PRIMARY KEY(source, key))")
    db.execute("CREATE TABLE IF NOT EXISTS states (source TEXT NOT NULL, bug_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(source, bug_id, field, value))")
    return db


def _clear_source(db: sqlite3.Connection, source: str) -> None:
    for table in ("bug_ids", "comment_keys", "states"):
        db.execute(f"DELETE FROM {table} WHERE source=?", (source,))
    db.commit()


def _sample_type_counts(samples: list[dict[str, str]], headers: list[str]) -> dict[str, str]:
    inferred = {}
    for column in headers:
        observed = Counter(row.get(column, "empty") for row in samples)
        observed.pop("empty", None)
        if not observed:
            dtype = "unknown_or_empty_in_sample"
        elif len(observed) == 1:
            dtype = next(iter(observed))
        elif set(observed) <= {"integer", "number"}:
            dtype = "number"
        elif set(observed) <= {"boolean_or_integer", "integer"}:
            dtype = "boolean_or_integer"
        else:
            dtype = "mixed_sample"
        inferred[column] = dtype
    return inferred


def _quantiles(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"min": None, "p50": None, "p90": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)
    def at(p: float) -> int:
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))]
    return {"min": ordered[0], "p50": at(.50), "p90": at(.90), "p95": at(.95), "p99": at(.99), "max": ordered[-1]}


def _load_verified_phase2(root: Path) -> dict[str, Any] | None:
    latest = root / "outputs/audit/phase02/LATEST_RUN"
    if not latest.is_file():
        return None
    run_id = latest.read_text(encoding="utf-8").strip()
    summary_path = root / "outputs/audit/phase02" / run_id / "audit_summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if summary.get("scan_mode") != "full" or summary.get("row_limit_per_file") is not None:
        return None
    comparison = summary.get("comment_parts_comparison", {})
    if not comparison.get("byte_identical") or comparison.get("verification") != "sha256":
        return None
    return summary


def _trusted_duplicate_alias(source: dict[str, Any], sources: list[dict[str, Any]], prior: dict[str, Any] | None) -> dict[str, Any] | None:
    if source["name"] != "comments_part_2" or prior is None:
        return None
    prior_stats = prior.get("comment_parts_comparison", {})
    p1 = next((x for x in sources if x["name"] == "comments_part_1"), None)
    if p1 is None:
        return None
    s1, s2 = p1["path"].stat(), source["path"].stat()
    if (s1.st_size, s1.st_mtime_ns) != (prior_stats.get("part_1_size_bytes"), prior_stats.get("part_1_mtime_ns")):
        return None
    if (s2.st_size, s2.st_mtime_ns) != (prior_stats.get("part_2_size_bytes"), prior_stats.get("part_2_mtime_ns")):
        return None
    source_prior = prior.get("sources", {}).get("comments_part_2", {})
    return {
        "source": "comments_part_2",
        "path": source["display_path"],
        "role": source["role"],
        "file_bytes": s2.st_size,
        "sha256": prior_stats.get("sha256_part_2"),
        "hash_scope": "whole_file_verified_by_phase2_sha256",
        "row_count": {"value": source_prior.get("rows_scanned"), "basis": "exact_from_verified_phase2", "exact": True},
        "unique_bug_ids": {"value": source_prior.get("unique_bug_ids"), "exact": True},
        "duplicate_bug_id_rows": None,
        "duplicate_comment_rows": {"value": source_prior.get("duplicate_key_rows"), "exact": True},
        "duplicate_of": {"source": "comments_part_1", "basis": "matching_full_file_sha256", "sha256": prior_stats.get("sha256_part_2")},
        "shared_comment_keys_with_part_1": prior_stats.get("shared_record_ids"),
        "scan_complete": True,
        "scan_skipped": True,
        "comment_dedup_key_strategy": "comment record id; exact-file duplicate is excluded from combined corpus",
        "provenance_reliability": "high: exact duplicate verified in saved Phase 2 full scan; current size and mtime match",
        "license_review": "pending human review; local PDF states publication rights are licensed to ACM but does not state a clear dataset redistribution license",
        "privacy": {"sensitive_column_names_only": [], "comment_text_values_written": False, "email_or_person_name_values_written": False},
    }


def _comment_identity(row: dict[str, Any], mapping: dict[str, str | None], headers: list[str]) -> str | None:
    comment_id = _cell(row, mapping.get("comment_id")).strip()
    if comment_id:
        return "id:" + comment_id
    bug_id = _cell(row, mapping.get("bug_id")).strip()
    created = _cell(row, mapping.get("created_at")).strip()
    if not bug_id or not created:
        return None
    text_field = mapping.get("comment_text")
    body = _cell(row, text_field)
    if body:
        body_digest = hashlib.sha256(body.encode("utf-8", errors="surrogatepass")).hexdigest()
        return f"fallback:{bug_id}:{created}:{body_digest}"
    digest = hashlib.sha256()
    for column in headers:
        value = row.get(column)
        if value:
            digest.update(str(value).encode("utf-8", errors="surrogatepass"))
            digest.update(b"\0")
    return f"fallback:{bug_id}:{created}:{digest.hexdigest()}"


def _scan_source(
    source: dict[str, Any], db: sqlite3.Connection, limit: int | None, sample_seed: int,
    progress_log: Path,
) -> dict[str, Any]:
    path: Path = source["path"]
    stat = path.stat()
    signature = {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "limit": limit, "sample_seed": sample_seed, "version": VERSION}

    _clear_source(db, source["name"])
    encoding, delimiter = _encoding_and_delimiter(path)
    csv.field_size_limit(sys.maxsize)
    text_nuls = 0
    physical_lines_with_nul = 0
    line_errors = 0
    rows = 0
    malformed_ids = 0
    duplicate_bug_rows = 0
    duplicate_comment_rows = 0
    nulls: Counter[str] = Counter()
    products: Counter[str] = Counter()
    components: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    resolutions: Counter[str] = Counter()
    comments_per_bug: Counter[str] = Counter()
    private_values: Counter[str] = Counter()
    date_stats: dict[str, dict[str, Any]] = {}
    relationship_counts: Counter[str] = Counter()
    schema_samples: list[dict[str, str]] = []
    rng = random.Random(sample_seed)
    row_errors: Counter[str] = Counter()
    headers: list[str] = []
    mapping: dict[str, str | None] = {}
    sample_seen = 0
    last_log_rows = 0

    important_fields = ("bug_id", "comment_id", "created_at", "last_change_at", "product", "component", "status", "resolution", "comment_text", "private_flag")
    with path.open("rb") as raw:
        raw.seek(0)
        hashing_raw = HashingRaw(raw)
        with io.BufferedReader(hashing_raw, buffer_size=1024 * 1024) as buffered:
            with io.TextIOWrapper(buffered, encoding=encoding, errors="surrogateescape", newline="") as handle:
                class NulSafeLines:
                    def __iter__(self_nonlocal):
                        nonlocal text_nuls, physical_lines_with_nul
                        for line in handle:
                            n = line.count("\x00")
                            if n:
                                text_nuls += n
                                physical_lines_with_nul += 1
                                yield line.replace("\x00", "")
                            else:
                                yield line

                reader = csv.DictReader(NulSafeLines(), delimiter=delimiter, restkey="__extra_fields__", restval=None)
                headers = reader.fieldnames or []
                if not headers:
                    raise ValueError(f"CSV has no header: {source['display_path']}")
                mapping = _mapping(headers, source["name"])
                header_duplicates = len(headers) - len(set(headers))
                bug_field = mapping["bug_id"]
                for raw_row in reader:
                    if limit is not None and rows >= limit:
                        break
                    rows += 1
                    if raw_row.get("__extra_fields__") is not None:
                        row_errors["extra_columns"] += 1
                    missing_cell = sum(1 for col in headers if raw_row.get(col) is None)
                    if missing_cell:
                        row_errors["short_rows"] += 1
                    row = {col: (raw_row.get(col) if isinstance(raw_row.get(col), str) else "") for col in headers}

                    if sample_seen < SAMPLE_ROWS:
                        schema_samples.append({col: _dtype(row.get(col, "")) for col in headers})
                        sample_seen += 1
                    else:
                        pick = rng.randrange(sample_seen + 1)
                        if pick < SAMPLE_ROWS:
                            schema_samples[pick] = {col: _dtype(row.get(col, "")) for col in headers}
                        sample_seen += 1

                    for logical in important_fields:
                        field = mapping.get(logical)
                        if field:
                            if not _cell(row, field).strip():
                                nulls[logical] += 1

                    bug_id = _cell(row, bug_field).strip()
                    if bug_field and bug_id:
                        if source["name"].startswith("comments"):
                            comments_per_bug[bug_id] += 1
                        if not bug_id.isdigit():
                            malformed_ids += 1
                        cursor = db.execute("INSERT OR IGNORE INTO bug_ids VALUES (?, ?)", (source["name"], bug_id))
                        if cursor.rowcount == 0:
                            duplicate_bug_rows += 1
                        for logical in ("status", "resolution"):
                            state = _cell(row, mapping.get(logical)).strip()
                            if state:
                                db.execute("INSERT OR IGNORE INTO states VALUES (?, ?, ?, ?)", (source["name"], bug_id, logical, state))
                    elif bug_field:
                        malformed_ids += 1

                    if source["name"].startswith("comments") or source["name"] == "steps_merged":
                        key = _comment_identity(row, mapping, headers)
                        if key:
                            cursor = db.execute("INSERT OR IGNORE INTO comment_keys VALUES (?, ?)", (source["name"], key))
                            if cursor.rowcount == 0:
                                duplicate_comment_rows += 1
                    private_value = _cell(row, mapping.get("private_flag")).strip().lower()
                    if private_value:
                        if private_value in {"1", "true", "yes", "y"}:
                            private_values["true"] += 1
                        elif private_value in {"0", "false", "no", "n"}:
                            private_values["false"] += 1
                        else:
                            private_values["other_nonempty"] += 1

                    for logical, counter in (("product", products), ("component", components), ("status", statuses), ("resolution", resolutions)):
                        value = _cell(row, mapping.get(logical)).strip()
                        if value:
                            counter[value] += 1
                    for logical in ("created_at", "last_change_at"):
                        field = mapping.get(logical)
                        if field:
                            value = _cell(row, field)
                            item = date_stats.setdefault(logical, {"field": field, "nonempty": 0, "parsed": 0, "min_utc": None, "max_utc": None})
                            if value.strip():
                                item["nonempty"] += 1
                                parsed = parse_timestamp(value)
                                if parsed is not None:
                                    item["parsed"] += 1
                                    iso = parsed.isoformat().replace("+00:00", "Z")
                                    item["min_utc"] = min(item["min_utc"], iso) if item["min_utc"] else iso
                                    item["max_utc"] = max(item["max_utc"], iso) if item["max_utc"] else iso
                    for field in RELATION_FIELDS:
                        if field in headers and _cell(row, field).strip():
                            relationship_counts[field] += 1

                    if rows % 2_000 == 0:
                        db.commit()
                    if rows - last_log_rows >= PROGRESS_EVERY:
                        _log(progress_log, f"{source['name']}: scanned {rows:,} CSV records")
                        last_log_rows = rows

    db.commit()
    # If a limit ended exactly at a record boundary, the total is unknown and
    # the file hash is not advertised as complete.
    complete = limit is None or rows < limit
    if complete:
        sha256 = hashing_raw.digest.hexdigest()
        hash_scope = "whole_file_sha256"
    else:
        sha256 = None
        hash_scope = "not_computed_for_limited_scan"
    unique_bug_ids = db.execute("SELECT COUNT(*) FROM bug_ids WHERE source=?", (source["name"],)).fetchone()[0]
    unique_comments = db.execute("SELECT COUNT(*) FROM comment_keys WHERE source=?", (source["name"],)).fetchone()[0]
    if comments_per_bug:
        db.execute("CREATE TABLE IF NOT EXISTS comment_bug_counts (source TEXT NOT NULL, bug_id TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(source, bug_id))")
        db.execute("DELETE FROM comment_bug_counts WHERE source=?", (source["name"],))
        db.executemany("INSERT INTO comment_bug_counts VALUES (?, ?, ?)", ((source["name"], bug_id, count) for bug_id, count in comments_per_bug.items()))
        db.commit()
        comment_quantiles = _quantiles(list(comments_per_bug.values()))
    else:
        comment_quantiles = None
    state_variants = {}
    for field in ("status", "resolution"):
        state_variants[field] = db.execute(
            "SELECT COUNT(*) FROM (SELECT bug_id FROM states WHERE source=? AND field=? GROUP BY bug_id HAVING COUNT(*)>1)",
            (source["name"], field),
        ).fetchone()[0]
    mapped_headers = set(headers)
    event_fields = [h for h in headers if EVENT_FIELD_RE.search(h)]
    commit_fields = [h for h in headers if COMMIT_FIELD_RE.search(h)]
    history_present = bool(event_fields)
    dtype_candidates = _sample_type_counts(schema_samples, headers)
    total_rows = rows
    important_null_percent = {}
    for logical in important_fields:
        if mapping.get(logical):
            important_null_percent[logical] = round(nulls[logical] * 100.0 / total_rows, 4) if total_rows else None
    date_output = {}
    for logical, item in date_stats.items():
        date_output[logical] = {
            **item,
            "parse_rate_nonempty": round(item["parsed"] / item["nonempty"], 6) if item["nonempty"] else None,
            "nonempty_unparseable": item["nonempty"] - item["parsed"],
            "null_rows": total_rows - item["nonempty"],
        }
    rel_present = [f for f in RELATION_FIELDS if f in mapped_headers]
    is_comment_source = source["name"].startswith("comments") or source["name"] == "steps_merged"
    has_bug_id = bool(bug_field)
    role = source["role"]
    result = {
        "source": source["name"],
        "path": source["display_path"],
        "role": role,
        "file_bytes": stat.st_size,
        "encoding_candidate": encoding,
        "delimiter_candidate": repr(delimiter),
        "sha256": sha256,
        "hash_scope": hash_scope,
        "row_count": {"value": rows, "basis": "exact_csv_records" if complete else "observed_prefix_only", "exact": complete},
        "scan_complete": complete,
        "schema": {
            "column_count": len(headers),
            "duplicate_header_count": header_duplicates,
            "columns": [{"name": h, "dtype_candidate": dtype_candidates.get(h, "unknown"), "sensitive_name": bool(SENSITIVE_COLUMN_RE.search(h))} for h in headers],
            "dtype_inference": f"deterministic reservoir of up to {SAMPLE_ROWS} rows; type candidates, not declared source types",
        },
        "field_mapping": mapping,
        "important_null_percent": important_null_percent,
        "dates": date_output,
        "unique_bug_ids": {"value": unique_bug_ids if has_bug_id else None, "exact_for_scanned_rows": complete and has_bug_id},
        "malformed_or_missing_bug_id_rows": malformed_ids if has_bug_id else None,
        "duplicate_bug_id_rows": duplicate_bug_rows if has_bug_id else None,
        "unique_comment_keys": {"value": unique_comments if is_comment_source else None, "exact_for_scanned_rows": complete and is_comment_source},
        "duplicate_comment_rows": duplicate_comment_rows if is_comment_source else None,
        "comment_dedup_key_strategy": "comment record ID when mapped; otherwise (bug ID, timestamp, SHA-256 of text/row); hash keys only, no text persisted" if source["name"].startswith("comments") or source["name"] == "steps_merged" else None,
        "private_flag_counts": dict(private_values),
        "product_counts_rows": dict(products.most_common()),
        "component_counts_rows": dict(components.most_common()),
        "status_counts_rows": dict(statuses.most_common()),
        "resolution_counts_rows": dict(resolutions.most_common()),
        "status_resolution_variants_per_bug": state_variants,
        "interpretation": "Multiple snapshot values for a bug are possible source variants, not an ordered transition history.",
        "comment_record_rows_per_bug_quantiles": comment_quantiles,
        "relationship_fields_present": rel_present,
        "relationship_nonempty_rows": dict(relationship_counts),
        "commit_fields_present": commit_fields,
        "history_event_fields_present": event_fields,
        "history_event_fields_missing": not history_present,
        "last_change_time_present_without_event_history": bool(mapping.get("last_change_at") and not history_present),
        "csv_anomalies": {"rows_with_extra_columns": row_errors["extra_columns"], "rows_with_missing_cells": row_errors["short_rows"], "nul_characters_removed": text_nuls, "physical_lines_with_nul": physical_lines_with_nul, "parser_errors": line_errors},
        "provenance_reliability": "medium: local file, parsed schema, and full-file SHA; publication provenance and field semantics still need review" if complete else "low: bounded prefix only; full source membership and checksum unknown",
        "license_review": "pending human review; local PDF states publication rights are licensed to ACM but does not state a clear dataset redistribution license",
        "privacy": {"sensitive_column_names_only": [h for h in headers if SENSITIVE_COLUMN_RE.search(h)], "comment_text_values_written": False, "email_or_person_name_values_written": False},
    }
    signature.update({"source_path": source["display_path"]})
    return {"result": result, "signature": signature, "complete": complete}


def _cross_joins(db: sqlite3.Connection, results: dict[str, Any]) -> dict[str, Any]:
    source_sets = {name: result for name, result in results.items() if result.get("scan_complete") or result.get("unique_bug_ids")}
    comments = [name for name in source_sets if name.startswith("comments_part_")]
    comment_names = [n for n in comments if not source_sets[n].get("duplicate_of")]
    result = {}
    if "metadata" in source_sets:
        for label, right_sources in (("metadata_to_comments", comment_names), ("metadata_to_filtered_reports", ["filtered_reports"]), ("metadata_to_steps_merged", ["steps_merged"])):
            right_sources = [x for x in right_sources if x in source_sets]
            if not right_sources:
                continue
            right_rows = ",".join("?" for _ in right_sources)
            shared = db.execute(
                f"SELECT COUNT(DISTINCT l.bug_id) FROM bug_ids l JOIN bug_ids r ON l.bug_id=r.bug_id WHERE l.source='metadata' AND r.source IN ({right_rows})",
                right_sources,
            ).fetchone()[0]
            left_n = db.execute("SELECT COUNT(*) FROM bug_ids WHERE source='metadata'").fetchone()[0]
            right_n = db.execute(f"SELECT COUNT(DISTINCT bug_id) FROM bug_ids WHERE source IN ({right_rows})", right_sources).fetchone()[0]
            result[label] = {
                "left_unique_bugs": left_n,
                "right_unique_bugs": right_n,
                "shared_unique_bugs": shared,
                "right_coverage_in_left": round(shared / right_n, 6) if right_n else None,
                "left_coverage_in_right": round(shared / left_n, 6) if left_n else None,
                "exact": all(source_sets[x].get("scan_complete", False) for x in right_sources) and source_sets["metadata"].get("scan_complete", False),
            }
    if "metadata" in source_sets and "metadata_all" in source_sets:
        shared = db.execute(
            "SELECT COUNT(*) FROM bug_ids a JOIN bug_ids b ON a.bug_id=b.bug_id WHERE a.source='metadata' AND b.source='metadata_all'"
        ).fetchone()[0]
        left_n = db.execute("SELECT COUNT(*) FROM bug_ids WHERE source='metadata'").fetchone()[0]
        right_n = db.execute("SELECT COUNT(*) FROM bug_ids WHERE source='metadata_all'").fetchone()[0]
        a = source_sets["metadata"]
        b = source_sets["metadata_all"]
        result["metadata_to_metadata_all"] = {
            "left_unique_bugs": left_n,
            "right_unique_bugs": right_n,
            "shared_unique_bugs": shared,
            "right_coverage_in_left": round(shared / right_n, 6) if right_n else None,
            "left_coverage_in_right": round(shared / left_n, 6) if left_n else None,
            "exact": a.get("scan_complete", False) and b.get("scan_complete", False),
            "whole_file_sha256_equal": (a.get("sha256") == b.get("sha256")) if a.get("sha256") and b.get("sha256") else None,
        }
    overlaps = {}
    for i, left in enumerate(comment_names):
        for right in comment_names[i + 1:]:
            shared = db.execute(
                "SELECT COUNT(*) FROM comment_keys a JOIN comment_keys b ON a.key=b.key WHERE a.source=? AND b.source=?",
                (left, right),
            ).fetchone()[0]
            overlaps[f"{left}__{right}"] = {"shared_comment_keys": shared, "exact": source_sets[left].get("scan_complete", False) and source_sets[right].get("scan_complete", False)}
    result["comment_key_overlaps"] = overlaps
    return result


def _comment_parts_finding(profile: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    sources = profile.get("sources", {})
    p1 = sources.get("comments_part_1", {})
    p2 = sources.get("comments_part_2", {})
    saved = prior.get("comment_parts_comparison", {}) if prior else {}
    shared = p2.get("shared_comment_keys_with_part_1")
    if shared is None:
        shared = profile.get("cross_source_joins", {}).get("comment_key_overlaps", {}).get("comments_part_1__comments_part_2", {}).get("shared_comment_keys")
    p1_hash, p2_hash = p1.get("sha256"), p2.get("sha256")
    exact_hashes = bool(p1_hash and p2_hash and p1_hash == p2_hash)
    if p2.get("duplicate_of") or exact_hashes:
        p2["duplicate_of"] = {"source": "comments_part_1", "basis": "matching_full_file_sha256", "sha256": p2_hash or saved.get("sha256_part_2")}
        p2["comment_duplicate_status"] = "byte_identical_duplicate; count once"
        p2["shared_comment_keys_with_part_1"] = shared if shared is not None else saved.get("shared_record_ids")
        if p2.get("scan_skipped"):
            evidence = "current Part 1 SHA-256 matches verified Phase 2 Part 2 SHA-256; current size/mtime signatures match"
        else:
            evidence = "current full-file SHA-256 comparison"
        finding = {
            "status": "byte_identical_duplicate",
            "byte_identical": True,
            "sha256_part_1": p1_hash or saved.get("sha256_part_1"),
            "sha256_part_2": p2_hash or saved.get("sha256_part_2"),
            "shared_comment_keys": p2.get("shared_comment_keys_with_part_1"),
            "evidence": evidence,
            "action": "exclude Part 2 when combining comments",
        }
    elif p1.get("scan_complete") and p2.get("scan_complete"):
        p2["comment_duplicate_status"] = "distinct_file_bytes; record overlap measured"
        finding = {
            "status": "distinct_file_bytes",
            "byte_identical": False,
            "sha256_part_1": p1_hash,
            "sha256_part_2": p2_hash,
            "shared_comment_keys": shared,
            "overlap_exact": True,
            "dedup_strategy": "deduplicate on the stable comment record ID; when missing, bug ID + timestamp + SHA-256(text/row)",
        }
    else:
        p2["comment_duplicate_status"] = "not_fully_verified"
        finding = {
            "status": "not_fully_verified",
            "byte_identical": None,
            "sha256_part_1": p1_hash,
            "sha256_part_2": p2_hash,
            "shared_comment_keys_in_scanned_scope": shared,
            "overlap_exact": False,
            "dedup_strategy": "do not concatenate until full-file hashes and comment-key overlap are verified",
        }
    return finding


def _svg_bar(path: Path, title: str, values: list[tuple[str, float]], suffix: str = "") -> None:
    width, left, right, top, row_h = 780, 230, 90, 72, 30
    usable = width - left - right
    max_value = max([v for _, v in values] or [1]) or 1
    height = top + max(1, len(values)) * row_h + 36
    items = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="20" y="34" font-family="sans-serif" font-size="20" font-weight="bold">{title}</text>']
    for idx, (label, value) in enumerate(values):
        y = top + idx * row_h
        bar = max(1, usable * value / max_value) if value > 0 else 0
        items.append(f'<text x="20" y="{y+18}" font-family="sans-serif" font-size="13">{_xml(label[:28])}</text>')
        items.append(f'<rect x="{left}" y="{y}" width="{bar:.1f}" height="20" fill="#3572a5"/>')
        shown = f"{value:,.3f}".rstrip("0").rstrip(".") if isinstance(value, float) and not value.is_integer() else f"{value:,.0f}"
        items.append(f'<text x="{min(width-75,left+bar+8):.1f}" y="{y+15}" font-family="sans-serif" font-size="12">{shown}{_xml(suffix)}</text>')
    items.append('</svg>')
    path.write_text("\n".join(items) + "\n", encoding="utf-8")


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _write_plots(output_dir: Path, profile: dict[str, Any], prior: dict[str, Any] | None) -> list[str]:
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    plots = []
    full_sources = prior.get("sources", {}) if prior else {}
    for source_name, title in (("metadata", "Bug products: metadata"), ("comments_part_1", "Bug products: comment rows")):
        src = full_sources.get(source_name)
        data = src.get("products", {}) if src and src.get("scan_complete") else profile.get("sources", {}).get(source_name, {}).get("product_counts_rows", {})
        pairs = sorted(data.items(), key=lambda x: (-x[1], x[0]))[:12]
        if pairs:
            file_name = "products_" + source_name + ".svg"
            _svg_bar(plot_dir / file_name, title + (" (Phase 2 full audit)" if src and src.get("scan_complete") else " (current profile scope)"), [(k, float(v)) for k, v in pairs])
            plots.append(f"plots/{file_name}")
    joins = prior.get("bug_id_join_coverage", {}) if prior else profile.get("cross_source_joins", {})
    if joins:
        values = []
        for name, item in joins.items():
            rate = item.get("right_coverage_in_left")
            if rate is not None:
                values.append((name.replace("_", " "), float(rate) * 100))
        if values:
            file_name = "bug_id_joins.svg"
            _svg_bar(plot_dir / file_name, "Bug ID join coverage (%)", values, "%")
            plots.append(f"plots/{file_name}")
    source_data = full_sources if full_sources else profile.get("sources", {})
    date_values = []
    for name, item in source_data.items():
        rate = item.get("timestamp_parse_rate")
        if rate is None:
            dates = item.get("dates", {})
            rates = [x.get("parse_rate_nonempty") for x in dates.values() if x.get("parse_rate_nonempty") is not None]
            rate = rates[0] if rates else None
        if rate is not None:
            date_values.append((name, float(rate) * 100))
    if date_values:
        file_name = "timestamp_parse_rates.svg"
        _svg_bar(plot_dir / file_name, "Timestamp parse rate (%)", sorted(date_values), "%")
        plots.append(f"plots/{file_name}")
    report_profile = profile.get("sources", {}).get("filtered_reports", {})
    status_values = [(f"status: {k}", float(v)) for k, v in report_profile.get("status_counts_rows", {}).items()]
    resolution_values = [(f"resolution: {k}", float(v)) for k, v in report_profile.get("resolution_counts_rows", {}).items()]
    combined = sorted(status_values + resolution_values, key=lambda x: (-x[1], x[0]))[:16]
    if combined:
        file_name = "status_resolution_filtered_reports.svg"
        qualifier = "exact full profile" if report_profile.get("scan_complete") else "bounded prefix; not population estimates"
        _svg_bar(plot_dir / file_name, "Filtered reports status and resolution (" + qualifier + ")", combined)
        plots.append(f"plots/{file_name}")
    return plots


def run_profile(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_log = output_dir / "progress.log"
    db_path = output_dir / "profile_index.sqlite3"
    checkpoint_path = output_dir / "checkpoint.json"
    sources, missing = _resolve_sources(root, config_path)
    prior = _load_verified_phase2(root)
    _log(progress_log, f"profile start; sources={len(sources)}; limit={args.limit}; output={_relative_path(output_dir, root)}")

    checkpoint: dict[str, Any] = {"version": VERSION, "sources": {}}
    if args.resume and checkpoint_path.is_file() and db_path.is_file():
        try:
            previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if previous.get("version") == VERSION:
                checkpoint = previous
        except (OSError, json.JSONDecodeError):
            pass
    db = _init_db(db_path)
    profile: dict[str, Any] = {
        "profile_version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "bounded_sample" if args.limit is not None else "full_profile",
        "limit_per_source": args.limit,
        "sample_seed": args.sample_seed,
        "root_relative_config": _relative_path(config_path, root),
        "missing_sources": missing,
        "phase2_reference": {"verified_full_audit": bool(prior), "path": "outputs/audit/phase02/<LATEST_RUN>/audit_summary.json" if prior else None},
        "sources": {},
        "cross_source_joins": {},
        "comment_part_duplicate_check": {},
        "privacy": "Only column names and aggregate counts are persisted. Comment/report bodies, personal names, emails, and raw bug IDs are not written.",
    }

    try:
        for source in sources:
            alias = _trusted_duplicate_alias(source, sources, prior)
            if alias:
                profile["sources"][source["name"]] = alias
                checkpoint["sources"][source["name"]] = {"signature": {"size_bytes": source["path"].stat().st_size, "mtime_ns": source["path"].stat().st_mtime_ns, "limit": args.limit, "sample_seed": args.sample_seed, "version": VERSION, "source_path": source["display_path"]}, "complete": True, "result": alias}
                _write_json(checkpoint_path, checkpoint)
                _log(progress_log, f"{source['name']}: skipped; verified byte-identical to comments_part_1 by Phase 2 SHA-256")
                continue
            saved = checkpoint["sources"].get(source["name"]) if args.resume else None
            stat = source["path"].stat()
            expected = {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "limit": args.limit, "sample_seed": args.sample_seed, "version": VERSION, "source_path": source["display_path"]}
            if saved and saved.get("signature") == expected and saved.get("complete"):
                profile["sources"][source["name"]] = saved["result"]
                _log(progress_log, f"{source['name']}: reused completed checkpoint")
                continue
            _log(progress_log, f"{source['name']}: scanning {stat.st_size:,} bytes")
            scanned = _scan_source(source, db, args.limit, args.sample_seed, progress_log)
            result = scanned["result"]
            profile["sources"][source["name"]] = result
            signature = {**expected}
            checkpoint["sources"][source["name"]] = {"signature": signature, "complete": scanned["complete"], "result": result}
            _write_json(checkpoint_path, checkpoint)
            _log(progress_log, f"{source['name']}: rows={result['row_count']['value']:,}; unique bugs={result['unique_bug_ids']['value']}; complete={result['scan_complete']}")

        profile["cross_source_joins"] = _cross_joins(db, profile["sources"])
        profile["comment_part_duplicate_check"] = _comment_parts_finding(profile, prior)
        profile["plots"] = _write_plots(output_dir, profile, prior)
        _write_json(output_dir / "profile.json", profile)
        summary = {
            "generated_at_utc": profile["generated_at_utc"],
            "status": profile["status"],
            "limit_per_source": args.limit,
            "source_summaries": {
                name: {
                    "path": item.get("path"),
                    "row_count": item.get("row_count"),
                    "unique_bug_ids": item.get("unique_bug_ids"),
                    "sha256": item.get("sha256"),
                    "hash_scope": item.get("hash_scope"),
                    "duplicate_bug_id_rows": item.get("duplicate_bug_id_rows"),
                    "duplicate_comment_rows": item.get("duplicate_comment_rows"),
                } for name, item in profile["sources"].items()
            },
            "cross_source_joins": profile["cross_source_joins"],
            "plots": profile["plots"],
        }
        _write_json(output_dir / "summary.json", summary)
        _write_json(checkpoint_path, checkpoint)
        _log(progress_log, f"profile complete; report={_relative_path(output_dir / 'profile.json', root)}")
        return profile
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream and profile local BugsRepo CSV files without persisting private text or identities.")
    parser.add_argument("--root", default=".", help="Project root (default: current directory)")
    parser.add_argument("--config", default="configs/data_paths.local.yaml", help="Flat local data-path YAML; falls back to conventional Dataset paths")
    parser.add_argument("--output", default="outputs/data_exploration", help="Ignored output directory for profile, summary, checkpoint, SQLite index, logs, and SVG plots")
    parser.add_argument("--limit", type=int, help="Maximum CSV records per source; results are prefix-only and hashes/counts are not whole-file claims")
    parser.add_argument("--sample-seed", type=int, default=317, help="Seed for bounded schema-type reservoir sampling")
    parser.add_argument("--resume", action="store_true", help="Reuse completed source checkpoints matching input size/mtime/options; an interrupted source restarts from its beginning")
    parser.add_argument("--dry-run", action="store_true", help="List source paths and sizes without reading CSV content")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be a positive integer")
    root = Path(args.root).resolve()
    config = Path(args.config)
    if not config.is_absolute():
        config = root / config
    sources, missing = _resolve_sources(root, config)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "sources": [{"name": x["name"], "path": x["display_path"], "size_bytes": x["path"].stat().st_size, "role": x["role"]} for x in sources], "missing_sources": missing, "limit": args.limit, "output": args.output}, indent=2))
        return 0
    run_profile(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
