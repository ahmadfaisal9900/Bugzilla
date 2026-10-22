"""Tiny synthetic inputs only: these tests never open the downloaded Dataset."""
import csv
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import duckdb
from bugzilla_qa.data import normalize as n
from bugzilla_qa.data.profile import _mapping

ROOT = Path(__file__).resolve().parents[1]


def fixture(root):
    metadata = []
    outcomes = [("RESOLVED", "FIXED"), ("REOPENED", ""), ("RESOLVED", "DUPLICATE"),
                ("RESOLVED", "INVALID"), ("NEW", "")]
    for i in range(1, 25):
        status, resolution = outcomes[(i - 1) % len(outcomes)]
        metadata.append({
            "id": str(i), "product": "Core" if i == 24 else " Firefox ",
            "component": "UI" if i % 2 else "DOM", "summary": "Synthetic summary " + str(i),
            "creation_time": "2024-01-01T01:00:00+01:00", "status": status,
            "resolution": resolution, "last_change_time": "2024-01-11T00:00:00Z",
            "blocks": "[2, 999]" if i == 1 else "[]",
            "dupe_of": "1.0" if i == 3 else "", "depends_on": "[]",
            "see_also": "['https://example.test/issue/one']" if i == 1 else "[]",
        })
    metadata += [dict(metadata[0]), {**metadata[0], "status": "NEW", "resolution": ""},
                 {**metadata[0], "id": "NaN"}]
    def comment(cid, bid, body, timestamp="2024-01-02T00:00:00Z", private="False"):
        return {"id": str(cid), "bug_id": str(bid), "creation_time_x": timestamp,
                "text": body, "is_private": private, "status": "RESOLVED", "resolution": "FIXED"}
    first = comment(500, 1, 'First line\nsecond, quoted "note"')
    p1 = [first, dict(first), comment(501, 1, "Separate legitimate comment"),
          comment(500, 1, "Distinct edited content with the same comment ID"),
          comment(502, 2, "private secret", private="True"),
          comment(503, 3, "unknown privacy secret", private=""),
          comment(504, 9999, "orphan"), comment(505, "NaN", "bad ID"),
          comment(506, 1, "bad date", timestamp="NaN")]
    p3 = [dict(first), comment(507, 2, "A reopened bug's comment"),
          comment(508, 1, "Future comment", timestamp="2030-01-01T00:00:00Z")]
    quality = [{"bug_id": "1", "creation_time": "2024-01-02T00:00:00Z", "text": "Optional report",
                "status": "RESOLVED", "resolution": "FIXED", "contains_steps_to_reproduce": "True"},
               {"bug_id": "1", "creation_time": "broken", "text": "Bad quality row",
                "status": "FALSE", "resolution": "", "contains_steps_to_reproduce": "False"}]
    data = {"metadata": metadata, "comments_part_1": p1, "comments_part_3": p3,
            "filtered_reports": quality, "steps_merged": [first]}
    config, sources, states = [], {}, {}
    for name, rows in data.items():
        path = root / (name + ".csv")
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        config.append(f"{n.PATH_KEYS[name]}: {path.name}")
        stat = path.stat()
        sources[name] = {
            "path": path.name, "scan_complete": True, "hash_scope": "whole_file_sha256",
            "sha256": n.file_hash(path), "row_count": {"exact": True, "value": len(rows)},
            "field_mapping": _mapping(list(rows[0]), name),
            "schema": {"columns": [{"name": col} for col in rows[0]]},
            "history_event_fields_present": [],
        }
        states[name] = {"signature": {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                     "source_path": path.name}}
    duplicate = root / "comments_part_2.csv"
    duplicate.write_bytes((root / "comments_part_1.csv").read_bytes())
    config.append(f"comments_part_2_csv: {duplicate.name}")
    stat = duplicate.stat()
    sources["comments_part_2"] = {
        "sha256": n.file_hash(duplicate), "row_count": {"value": len(p1)}, "path": duplicate.name}
    states["comments_part_2"] = {"signature": {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                            "source_path": duplicate.name}}
    qc_dir = root / "qc"
    qc_dir.mkdir()
    n.write_json(qc_dir / "profile.json", {
        "status": "full_profile", "limit_per_source": None, "sources": sources,
        "generated_at_utc": "2026-10-22T01:56:55Z",
        "comment_part_duplicate_check": {
            "byte_identical": True, "sha256_part_1": sources["comments_part_1"]["sha256"],
            "sha256_part_2": sources["comments_part_2"]["sha256"],
        },
    })
    n.write_json(qc_dir / "checkpoint.json", {"sources": states})
    (root / "paths.yaml").write_text("\n".join(config) + "\n")
    return SimpleNamespace(
        root=str(root), config=str(root / "paths.yaml"),
        selection=str(ROOT / "configs/phase03b_sources.json"), qc_dir=str(qc_dir),
        output=str(root / "run"), limit=None, chunk_size=4, sample_seed=317,
        sample_target=20, product="Firefox", cutoff=None, memory_limit="256MB",
        include_quality=False, resume=False, dry_run=False,
    )


class NormalizeTests(unittest.TestCase):
    def test_dry_run_and_bounded_limit_do_not_claim_full_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = fixture(root)
            args.dry_run = True
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                n.normalize(args)
            self.assertTrue(json.loads(captured.getvalue())["dry_run"])
            self.assertFalse((root / "run").exists())
            args.dry_run, args.limit = False, 5
            report = n.normalize(args)
            self.assertEqual(report["state"], "BOUNDED_PREFIX")
            self.assertEqual(report["table_counts"]["bugs"], 5)
            self.assertTrue(all(s["scanned_rows"] <= 5 and s["verified_sha256"] is None
                                and s["scope"] == "BOUNDED_PREFIX" for s in report["sources"].values()))
            self.assertIsNone(n.utc("2024-01-01T00:00:00"))
            self.assertIsNone(n.bug_id("NaN"))
            self.assertEqual(n.bug_id("001.0"), "1")

    def test_canonical_accounting_multiline_nan_duplicates_and_parquet(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = fixture(root)
            originals = {p.name: n.file_hash(p) for p in root.glob("*.csv")}
            report = n.normalize(args)
            self.assertEqual(report["table_counts"]["bugs"], 24)
            self.assertEqual(report["table_counts"]["comments"], 7)
            self.assertEqual(report["table_counts"]["field_changes"], 0)
            self.assertEqual(report["unknown_fix_durations"], 24)
            self.assertEqual(report["orphan_source_records"], 1)
            self.assertEqual(report["comment_id_versions"], 1)
            self.assertEqual(report["sample_count"], 20)
            self.assertGreater(len(report["sample_outcomes"]), 1)
            self.assertEqual(report["sources"]["metadata"]["dispositions"]["DUPLICATE"], 1)
            self.assertEqual(report["sources"]["metadata"]["dispositions"]["CONFLICT_VARIANT"], 1)
            self.assertEqual(report["sources"]["comments_part_3"]["dispositions"]["DUPLICATE"], 1)
            self.assertEqual({p.name: n.file_hash(p) for p in root.glob("*.csv")}, originals)
            db = duckdb.connect(str(root / "run/canonical.duckdb"), read_only=True)
            db.execute("SET TimeZone='UTC'")
            self.assertEqual(db.execute("SELECT body FROM comments WHERE comment_id='500' ORDER BY length(body)").fetchall()[0][0],
                             'First line\nsecond, quoted "note"')
            self.assertIsNone(db.execute("SELECT body FROM comments WHERE comment_id='502'").fetchone()[0])
            self.assertEqual(db.execute("SELECT opened_at_utc::VARCHAR FROM bugs WHERE bug_id='1'").fetchone()[0],
                             "2024-01-01 00:00:00+00")
            self.assertEqual(db.execute("SELECT count(*) FROM documents_as_of('2024-12-31'::TIMESTAMPTZ)").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM documents_as_of('2027-01-01'::TIMESTAMPTZ)").fetchone()[0], 4)
            self.assertNotIn("comments_part_2", report["sources"])
            manifest = json.loads((root / "run/manifest.json").read_text())
            export = root / "run" / manifest["parquet_version"]
            self.assertEqual(db.execute("SELECT count(*) FROM read_parquet(?)",
                                       [str(export / "comments/**/*.parquet")]).fetchone()[0], 7)
            self.assertEqual(db.execute("SELECT count(*) FROM read_parquet(?)",
                                       [str(export / "field_changes/*.parquet")]).fetchone()[0], 0)
            db.close()
            for path, evidence in manifest["artifacts"].items():
                self.assertEqual(n.file_hash(root / "run" / path), evidence["sha256"])
            examples = json.loads((root / "run/anonymized_examples.json").read_text())
            self.assertEqual(len(examples), 20)
            self.assertTrue(all("bug_id" not in row and "summary" not in row for row in examples))
            sample = (root / "run/sample_manifest.json").read_bytes()
            args.resume = True
            n.normalize(args)
            self.assertEqual((root / "run/sample_manifest.json").read_bytes(), sample)
            self.assertEqual(len(list((root / "run/exports").iterdir())), 1)
            # New version, same seed: stable sample and canonical composite keys.
            args.resume = False
            args.output = str(root / "run2")
            n.normalize(args)
            second = json.loads((root / "run2/sample_manifest.json").read_text())
            self.assertEqual(second["members"], json.loads(sample)["members"])

    def test_reopening_duplicate_invalid_and_future_fix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = fixture(root)
            n.normalize(args)
            db = duckdb.connect(str(root / "run/canonical.duckdb"))
            rows = [
                ("f1", "1", "resolution", "", "FIXED", "2024-01-05T00:00:00Z"),
                ("r1", "1", "status", "RESOLVED", "REOPENED", "2024-01-07T00:00:00Z"),
                ("f2", "1", "resolution", "", "FIXED", "2024-01-09T00:00:00Z"),
                ("d1", "3", "resolution", "", "DUPLICATE", "2024-01-02T00:00:00Z"),
                ("i1", "4", "resolution", "", "INVALID", "2024-01-02T00:00:00Z"),
                ("future", "2", "resolution", "", "FIXED", "2030-01-02T00:00:00Z"),
            ]
            db.executemany("""INSERT INTO field_changes
                (change_key,bug_id,field_name,old_value,new_value,event_time_utc,observed_at_utc)
                VALUES (?,?,?,?,?,?,'2026-10-22T01:56:55Z')""", rows)
            self.assertEqual(db.execute("SELECT first_fixed_calendar_days,reopened_observed FROM fix_metrics WHERE bug_id='1'").fetchone(), (4.0, True))
            for parent in ("3", "4"):
                self.assertEqual(db.execute("SELECT fix_duration_state FROM fix_metrics WHERE bug_id=?", [parent]).fetchone()[0], "UNKNOWN")
            self.assertEqual(db.execute("SELECT fix_duration_state FROM fix_metrics_as_of('2027-01-01'::TIMESTAMPTZ) WHERE bug_id='2'").fetchone()[0], "UNKNOWN")
            self.assertEqual(db.execute("SELECT count(*) FROM fix_metrics_as_of('2024-12-31'::TIMESTAMPTZ)").fetchone()[0], 0)
            db.close()

    def test_transactional_resume_and_optional_quality_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = fixture(root)
            real_flush = n.flush
            def interrupt(*a, **kw):
                real_flush(*a, **kw)
                raise RuntimeError("fixture interrupted after committed chunk")
            with patch.object(n, "flush", side_effect=interrupt):
                with self.assertRaisesRegex(RuntimeError, "fixture interrupted"):
                    n.normalize(args)
            args.resume = True
            result = n.normalize(args)
            self.assertEqual(result["sources"]["metadata"]["scanned_rows"], 27)
            self.assertEqual(result["table_counts"]["source_records"], 39)
            self.assertEqual(result["table_counts"]["quality_records"], 0)
            args.resume, args.include_quality, args.output = False, True, str(root / "quality-run")
            quality = n.normalize(args)
            self.assertEqual(quality["table_counts"]["bugs"], 24)
            self.assertEqual(quality["table_counts"]["comments"], 7)
            self.assertEqual(quality["table_counts"]["quality_records"], 2)

    def test_changed_inputs_and_existing_run_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = fixture(root)
            n.normalize(args)
            with self.assertRaisesRegex(ValueError, "already exists"):
                n.normalize(args)
            path = root / "metadata.csv"
            original_stat = path.stat()
            path.write_bytes(path.read_bytes().replace(b"Synthetic summary", b"Different summary", 1))
            os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            args.output = str(root / "tampered")
            with self.assertRaisesRegex(ValueError, "hash/count"):
                n.normalize(args)
            self.assertEqual(json.loads((root / "tampered/manifest.json").read_text())["state"], "INGESTING")


if __name__ == "__main__":
    unittest.main()
