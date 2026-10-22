#!/usr/bin/env python3
"""Streaming, local-only audit of the configured Bugzilla CSV sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATASETS = (
    ("metadata", "metadata_csv"),
    ("reports", "reports_csv"),
    ("comments_part_1", "comments_part_1_csv"),
    ("comments_part_2", "comments_part_2_csv"),
    ("upstream_sample", "upstream_sample_csv"),
)

FIELD_CANDIDATES = {
    "bug_id": ("bug_id", "Bug ID", "bugid", "id", "_id"),
    "record_id": ("comment_id", "Comment ID", "id", "_id", "bug_id", "Bug ID"),
    "created_at": (
        "creation_time", "creation_time_x", "created_at", "Created", "created", "Updated"
    ),
    "product": ("product", "Product"),
    "component": ("component", "Component"),
    "status": ("status", "Status"),
    "resolution": ("resolution", "Resolution"),
    "text": ("text", "raw_text", "Comment Text", "description", "Summary"),
    "private_flag": ("is_private", "Is Private", "private"),
}
EVENT_FIELDS = (
    "event_time", "event_id", "field", "old_value", "new_value", "changes", "history"
)
SENSITIVE_NAME_RE = re.compile(r"email|author|creator|assignee|reporter|user|login", re.I)


def parse_flat_yaml(path: Path) -> dict[str, str]:
    """Read the small flat key: scalar config subset used by data_paths files."""
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in raw:
            raise ValueError(f"{path}:{line_number}: expected key: value")
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key or not value:
            raise ValueError(f"{path}:{line_number}: empty key or value")
        if value.startswith(("'", '"')) and value[-1:] == value[:1]:
            value = value[1:-1]
        # This intentionally supports only flat scalar paths, not general YAML.
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def resolve_path(value: str, root: Path) -> Path:
    candidate = Path(os.path.expanduser(value))
    return candidate if candidate.is_absolute() else root / candidate


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def map_fields(headers: Iterable[str]) -> dict[str, str | None]:
    present = set(headers)
    result: dict[str, str | None] = {}
    for logical, candidates in FIELD_CANDIDATES.items():
        result[logical] = next((candidate for candidate in candidates if candidate in present), None)
    return result


def _cell(row: dict[str, Any], field: str | None) -> str:
    if field is None:
        return ""
    value = row.get(field)
    return value if isinstance(value, str) else ""


def parse_timestamp(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _log(message: str) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


def _init_index(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("CREATE TABLE IF NOT EXISTS bug_ids (source TEXT NOT NULL, bug_id TEXT NOT NULL, PRIMARY KEY(source, bug_id))")
    db.execute("CREATE TABLE IF NOT EXISTS seen_records (source TEXT NOT NULL, record_id TEXT NOT NULL, PRIMARY KEY(source, record_id))")
    db.commit()
    return db


def _choose_mapping(headers: list[str]) -> dict[str, str | None]:
    return map_fields(headers)


def _scan_file(
    label: str,
    path: Path,
    display_path: str,
    db: sqlite3.Connection,
    limit: int | None,
    progress_every: int,
) -> dict[str, Any]:
    file_stat = path.stat()
    db.execute("DELETE FROM bug_ids WHERE source=?", (label,))
    db.execute("DELETE FROM seen_records WHERE source=?", (label,))
    db.commit()

    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8-sig", errors="surrogateescape", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        mapping = _choose_mapping(headers)
        if not headers:
            raise ValueError(f"{path} has no CSV header")

        row_count = 0
        duplicates = 0
        private_true = 0
        nonempty = Counter()
        products = Counter()
        timestamp_nonempty = 0
        timestamp_parsed = 0
        timestamp_field = mapping["created_at"]
        bug_field = mapping["bug_id"]
        record_field = mapping["record_id"]
        private_field = mapping["private_flag"]
        product_field = mapping["product"]

        for row in reader:
            row_count += 1
            for logical in ("bug_id", "record_id", "created_at", "product", "component", "status", "resolution", "text", "private_flag"):
                field = mapping[logical]
                if field and _cell(row, field).strip():
                    nonempty[logical] += 1

            if bug_field:
                bug_id = _cell(row, bug_field).strip()
                if bug_id:
                    db.execute("INSERT OR IGNORE INTO bug_ids VALUES (?, ?)", (label, bug_id))
            if record_field:
                record_id = _cell(row, record_field).strip()
                if record_id:
                    cursor = db.execute("INSERT OR IGNORE INTO seen_records VALUES (?, ?)", (label, record_id))
                    if cursor.rowcount == 0:
                        duplicates += 1
            if timestamp_field:
                timestamp = _cell(row, timestamp_field).strip()
                if timestamp:
                    timestamp_nonempty += 1
                    if parse_timestamp(timestamp) is not None:
                        timestamp_parsed += 1
            if product_field:
                product = _cell(row, product_field).strip()
                if product:
                    products[product] += 1
            if private_field:
                flag = _cell(row, private_field).strip().lower()
                if flag in ("1", "true", "yes", "y"):
                    private_true += 1

            if row_count % 5000 == 0:
                db.commit()
            if progress_every and row_count % progress_every == 0:
                _log(f"{label}: scanned {row_count:,} rows")
            if limit is not None and row_count >= limit:
                break
        db.commit()

    scan_complete = limit is None or row_count < limit
    # Reaching precisely --limit is conservatively marked limited. This avoids
    # claiming EOF without reading one more row.
    if limit is not None and row_count >= limit:
        scan_complete = False
    unique_bug_ids = db.execute("SELECT COUNT(*) FROM bug_ids WHERE source=?", (label,)).fetchone()[0]
    sensitive_columns = [header for header in headers if SENSITIVE_NAME_RE.search(header)]
    privacy_status = (
        "private flag present; minimize/pseudonymize contributor fields before research use"
        if mapping["private_flag"] or sensitive_columns
        else "no recognized private or contributor-identifying columns detected"
    )
    normalized_headers = {_normalize(header) for header in headers}
    present_event_fields = [name for name in EVENT_FIELDS if _normalize(name) in normalized_headers]
    missing_event_fields = [name for name in EVENT_FIELDS if _normalize(name) not in normalized_headers]
    return {
        "source": label,
        "path": display_path,
        "size_bytes": file_stat.st_size,
        "mtime_ns": file_stat.st_mtime_ns,
        "rows_scanned": row_count,
        "scan_complete": scan_complete,
        "schema": {"column_count": len(headers), "columns": headers},
        "field_mapping": mapping,
        "nonempty_rows_by_field": dict(nonempty),
        "empty_rows_by_field": {
            logical: row_count - nonempty[logical]
            for logical, field in mapping.items()
            if field is not None
        },
        "timestamp_parse_rate": {
            "field": timestamp_field,
            "nonempty_values": timestamp_nonempty,
            "parsed_values": timestamp_parsed,
            "rate": (timestamp_parsed / timestamp_nonempty) if timestamp_nonempty else None,
        },
        "unique_bug_ids": unique_bug_ids,
        "duplicates": {
            "key_field": record_field,
            "duplicate_key_rows": duplicates,
        },
        "product_breakdown": dict(sorted(products.items())),
        "privacy": {
            "private_flag_field": private_field,
            "private_true_rows": private_true,
            "sensitive_column_names": sensitive_columns,
            "handling": privacy_status,
        },
        "history_event_fields_present": present_event_fields,
        "missing_history_event_fields": missing_event_fields,
        "license_review": "manual source/license and redistribution review required; this audit does not grant rights",
        "read_complete": scan_complete,
    }


def _coverage(db: sqlite3.Connection, left: tuple[str, ...], right: tuple[str, ...]) -> dict[str, Any]:
    left_ids = {r[0] for source in left for r in db.execute("SELECT bug_id FROM bug_ids WHERE source=?", (source,))}
    right_ids = {r[0] for source in right for r in db.execute("SELECT bug_id FROM bug_ids WHERE source=?", (source,))}
    intersection = len(left_ids & right_ids)
    return {
        "left_unique_bug_ids": len(left_ids),
        "right_unique_bug_ids": len(right_ids),
        "shared_unique_bug_ids": intersection,
        "right_coverage_in_left": (intersection / len(right_ids)) if right_ids else None,
    }


def _comment_parts_comparison(
    db: sqlite3.Connection,
    paths: dict[str, Path],
    hash_enabled: bool,
    prior: dict[str, Any] | None,
    parts_complete: bool,
) -> dict[str, Any]:
    left, right = paths["comments_part_1"], paths["comments_part_2"]
    sizes_match = left.stat().st_size == right.stat().st_size
    comparison: dict[str, Any] = {
        "part_1_size_bytes": left.stat().st_size,
        "part_2_size_bytes": right.stat().st_size,
        "part_1_mtime_ns": left.stat().st_mtime_ns,
        "part_2_mtime_ns": right.stat().st_mtime_ns,
        "sizes_match": sizes_match,
        "sha256_part_1": None,
        "sha256_part_2": None,
        "byte_identical": None,
        "verification": "skipped",
        "shared_record_ids": None,
    }
    if (
        prior
        and prior.get("verification") == "sha256"
        and prior.get("part_1_size_bytes") == comparison["part_1_size_bytes"]
        and prior.get("part_2_size_bytes") == comparison["part_2_size_bytes"]
        and prior.get("part_1_mtime_ns") == comparison["part_1_mtime_ns"]
        and prior.get("part_2_mtime_ns") == comparison["part_2_mtime_ns"]
    ):
        comparison.update(prior)
    elif hash_enabled:
        if sizes_match:
            comparison["sha256_part_1"] = _sha256(left)
            comparison["sha256_part_2"] = _sha256(right)
            comparison["byte_identical"] = comparison["sha256_part_1"] == comparison["sha256_part_2"]
            comparison["verification"] = "sha256"
        else:
            # Unequal sizes establish that the files are not byte-identical.
            comparison["byte_identical"] = False
            comparison["verification"] = "size-mismatch"
    common = db.execute(
        "SELECT COUNT(*) FROM seen_records a INNER JOIN seen_records b ON a.record_id=b.record_id WHERE a.source=? AND b.source=?",
        ("comments_part_1", "comments_part_2"),
    ).fetchone()[0]
    comparison["shared_record_ids"] = common
    comparison["shared_record_ids_scope"] = "full files" if parts_complete else "limited scans"
    if comparison["byte_identical"] is True:
        comparison["interpretation"] = "files are byte-identical; count once in any combined corpus"
    elif comparison["byte_identical"] is False:
        comparison["interpretation"] = "files differ at byte level; inspect shared record IDs before combining"
    else:
        comparison["interpretation"] = "not verified; matching sizes do not establish equality"
    return comparison


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).expanduser().resolve()
    root = Path(args.root).expanduser().resolve()
    config = parse_flat_yaml(config_path)
    paths: dict[str, Path] = {}
    display_paths: dict[str, str] = {}
    for label, key in DATASETS:
        if label == "upstream_sample" and key not in config:
            continue
        if key not in config:
            raise ValueError(f"missing {key} in {config_path}")
        paths[label] = resolve_path(config[key], root).resolve()
        try:
            display_paths[label] = str(paths[label].relative_to(root))
        except ValueError:
            display_paths[label] = str(paths[label])
    for label, _ in DATASETS:
        if label not in paths:
            continue
        if label in args.skip:
            continue
        if not paths[label].is_file():
            raise FileNotFoundError(f"{label}: configured CSV does not exist: {paths[label]}")

    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "checkpoint.json"
    index_path = out / "id_index.sqlite3"
    resume_state: dict[str, Any] = {}
    if args.resume and state_path.exists() and index_path.exists():
        resume_state = json.loads(state_path.read_text(encoding="utf-8"))
    elif args.resume and state_path.exists() != index_path.exists():
        _log("checkpoint/index mismatch; starting a clean index for this output directory")
        for path in (state_path, index_path, Path(str(index_path) + "-wal"), Path(str(index_path) + "-shm")):
            if path.exists():
                path.unlink()
    if not args.resume:
        for path in (state_path, index_path, Path(str(index_path) + "-wal"), Path(str(index_path) + "-shm")):
            if path.exists():
                path.unlink()
        resume_state = {}

    db = _init_index(index_path)
    file_results: dict[str, Any] = dict(resume_state.get("files", {}))
    for label, _ in DATASETS:
        if label not in paths:
            continue
        if label in args.skip:
            continue
        stat = paths[label].stat()
        previous = file_results.get(label, {})
        if (
            args.resume
            and args.limit is None
            and previous.get("scan_complete") is True
            and previous.get("path") == display_paths[label]
            and previous.get("size_bytes") == stat.st_size
            and previous.get("mtime_ns") == stat.st_mtime_ns
        ):
            _log(f"{label}: skipped (completed checkpoint is current)")
            continue
        if args.limit is None:
            _log(f"{label}: scanning {paths[label].name} ({stat.st_size:,} bytes)")
        else:
            _log(f"{label}: scanning first {args.limit:,} rows of {paths[label].name}")
        result = _scan_file(label, paths[label], display_paths[label], db, args.limit, args.progress_every)
        file_results[label] = result
        _write_json(state_path, {"updated_at": _now_utc(), "files": file_results})

    # Join metrics are meaningful when the related sources were scanned in this run
    # or loaded from a complete checkpoint.
    has = set(file_results)
    joins: dict[str, Any] = {}
    if {"metadata", "reports"} <= has:
        joins["metadata_to_reports"] = _coverage(db, ("metadata",), ("reports",))
    if {"metadata", "comments_part_1", "comments_part_2"} <= has:
        joins["metadata_to_comment_parts_union"] = _coverage(
            db, ("metadata",), ("comments_part_1", "comments_part_2")
        )
    if {"reports", "comments_part_1", "comments_part_2"} <= has:
        joins["reports_to_comment_parts_union"] = _coverage(
            db, ("reports",), ("comments_part_1", "comments_part_2")
        )

    prior_parts = resume_state.get("comment_parts_comparison") if args.resume else None
    expected_labels = set(paths)
    full_scan = args.limit is None and not args.skip and all(
        file_results.get(label, {}).get("scan_complete") is True for label in expected_labels
    )
    hash_enabled = not args.skip_checksum and args.limit is None
    if args.skip_checksum:
        hash_enabled = False
    parts_complete = all(
        file_results.get(label, {}).get("scan_complete") is True
        for label in ("comments_part_1", "comments_part_2")
    )
    comparison = (
        _comment_parts_comparison(db, paths, hash_enabled, prior_parts, parts_complete)
        if {"comments_part_1", "comments_part_2"} <= has
        else None
    )
    if args.limit is not None and not args.skip_checksum:
        _log("checksum skipped automatically for limited scans; use an unlimited run to verify the full files")

    license_readme = "Dataset/EASE_2025_Data_paper/README.md"
    report = {
        "generated_at": _now_utc(),
        "project_root": str(root),
        "config_file": str(config_path),
        "scan_mode": "full" if full_scan else "limited_or_partial",
        "row_limit_per_file": args.limit,
        "skipped_sources": sorted(args.skip),
        "files": file_results,
        "bug_id_join_coverage": joins,
        "comment_parts_comparison": comparison,
        "license_privacy": {
            "review_status": "pending manual confirmation for source license, dataset terms, and redistribution",
            "upstream_readme": license_readme,
            "sensitive_content_policy": "do not print or commit row text, emails, usernames, or raw identifiers",
        },
        "history_event_coverage": {
            "status": "measured by source header presence only; row-level event semantics are not inferred",
            "required_fields": list(EVENT_FIELDS),
            "note": "Current-state status/resolution fields do not substitute for ordered history events.",
        },
        "audit_limits": [
            "The audit reads CSV rows in a stream and stores distinct IDs in an ignored SQLite index.",
            "Resume skips only complete, unchanged source files; an interrupted source restarts from row one.",
            "A limited scan is not a whole-dataset row count or checksum.",
            "License and privacy authorization require human review; this report is not a legal determination.",
        ],
    }
    _write_json(out / "audit_report.json", report)
    summary = {
        "generated_at": report["generated_at"],
        "scan_mode": report["scan_mode"],
        "row_limit_per_file": args.limit,
        "skipped_sources": sorted(args.skip),
        "sources": {
            label: {
                "path": values.get("path"),
                "rows_scanned": values.get("rows_scanned"),
                "scan_complete": values.get("scan_complete"),
                "columns": values.get("schema", {}).get("column_count"),
                "timestamp_parse_rate": values.get("timestamp_parse_rate", {}).get("rate"),
                "unique_bug_ids": values.get("unique_bug_ids"),
                "duplicate_key_rows": values.get("duplicates", {}).get("duplicate_key_rows"),
                "products": values.get("product_breakdown"),
            }
            for label, values in file_results.items()
        },
        "bug_id_join_coverage": joins,
        "comment_parts_comparison": comparison,
        "license_review_status": "pending manual confirmation",
        "history_event_coverage": "header presence reported; validate semantics before research use",
    }
    _write_json(out / "audit_summary.json", summary)
    _write_json(state_path, {"updated_at": report["generated_at"], "files": file_results, "comment_parts_comparison": comparison})
    db.close()
    _log(f"wrote {out / 'audit_report.json'} and {out / 'audit_summary.json'}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/data_paths.local.yaml")
    parser.add_argument("--root", default=".", help="Project root used to resolve relative data paths")
    parser.add_argument("--output-dir", default="outputs/audit/phase02")
    parser.add_argument("--limit", type=int, help="scan at most N data rows per CSV")
    parser.add_argument("--progress-every", type=int, default=100000)
    parser.add_argument("--resume", action="store_true", help="reuse completed unchanged files from checkpoint")
    parser.add_argument("--skip-checksum", action="store_true", help="do not SHA-256 compare comments Parts 1 and 2")
    parser.add_argument("--skip", action="append", default=[], help="skip a dataset label; repeat or comma-separate labels")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.progress_every < 0:
        parser.error("--progress-every cannot be negative")
    args.skip = {part.strip() for entry in args.skip for part in entry.split(",") if part.strip()}
    unknown = args.skip - {label for label, _ in DATASETS}
    if unknown:
        parser.error(f"unknown --skip dataset label(s): {', '.join(sorted(unknown))}")
    try:
        run_audit(args)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        _log(f"audit failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
