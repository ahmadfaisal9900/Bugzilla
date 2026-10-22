import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "data_audit"
sys.path.insert(0, str(ROOT / "src"))

from data.audit import run_audit


class DataAuditTests(unittest.TestCase):
    def test_fixture_has_twenty_rows(self):
        total = 0
        for path in sorted(FIXTURES.glob("*.csv")):
            with path.open(newline="", encoding="utf-8") as handle:
                total += sum(1 for _ in csv.DictReader(handle))
        self.assertEqual(total, 20)

    def test_streaming_audit_metrics_and_part_comparison(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config = temp / "paths.yaml"
            config.write_text(
                "\n".join(
                    f"{key}: {FIXTURES / filename}"
                    for key, filename in (
                        ("metadata_csv", "metadata.csv"),
                        ("reports_csv", "reports.csv"),
                        ("comments_part_1_csv", "comments_part_1.csv"),
                        ("comments_part_2_csv", "comments_part_2.csv"),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            report = run_audit(
                SimpleNamespace(
                    config=str(config),
                    root=str(ROOT),
                    output_dir=str(temp / "outputs"),
                    limit=None,
                    progress_every=0,
                    resume=False,
                    skip_checksum=False,
                    skip=set(),
                )
            )

            metadata = report["files"]["metadata"]
            self.assertEqual(metadata["rows_scanned"], 5)
            self.assertEqual(metadata["unique_bug_ids"], 4)
            self.assertEqual(metadata["duplicates"]["duplicate_key_rows"], 1)
            self.assertAlmostEqual(metadata["timestamp_parse_rate"]["rate"], 0.8)
            self.assertEqual(metadata["field_mapping"]["bug_id"], "id")
            self.assertIn("event_time", metadata["missing_history_event_fields"])

            comments = report["files"]["comments_part_1"]
            self.assertEqual(comments["duplicates"]["duplicate_key_rows"], 1)
            self.assertEqual(comments["privacy"]["private_true_rows"], 1)
            self.assertIn("creator_email", comments["privacy"]["sensitive_column_names"])
            self.assertEqual(report["comment_parts_comparison"]["verification"], "sha256")
            self.assertFalse(report["comment_parts_comparison"]["byte_identical"])
            self.assertEqual(report["comment_parts_comparison"]["shared_record_ids"], 1)
            self.assertEqual(
                report["bug_id_join_coverage"]["metadata_to_reports"]["shared_unique_bug_ids"], 2
            )
            summary = json.loads((temp / "outputs" / "audit_summary.json").read_text())
            self.assertEqual(summary["scan_mode"], "full")

    def test_limited_scan_is_not_reported_as_full(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config = temp / "paths.yaml"
            config.write_text(
                "\n".join(
                    f"{key}: {FIXTURES / filename}"
                    for key, filename in (
                        ("metadata_csv", "metadata.csv"),
                        ("reports_csv", "reports.csv"),
                        ("comments_part_1_csv", "comments_part_1.csv"),
                        ("comments_part_2_csv", "comments_part_2.csv"),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            report = run_audit(
                SimpleNamespace(
                    config=str(config),
                    root=str(ROOT),
                    output_dir=str(temp / "outputs"),
                    limit=2,
                    progress_every=0,
                    resume=False,
                    skip_checksum=False,
                    skip=set(),
                )
            )
            self.assertEqual(report["scan_mode"], "limited_or_partial")
            self.assertEqual(report["files"]["metadata"]["rows_scanned"], 2)
            self.assertFalse(report["files"]["metadata"]["scan_complete"])
            self.assertEqual(report["comment_parts_comparison"]["verification"], "skipped")

    def test_embedded_nul_is_removed_and_counted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            reports = temp / "reports_with_nul.csv"
            reports.write_bytes(
                (FIXTURES / "reports.csv").read_bytes().replace(
                    b"Fixture report one", b"Fixture \x00 report one", 1
                )
            )
            config = temp / "paths.yaml"
            config.write_text(
                "\n".join(
                    (
                        f"metadata_csv: {FIXTURES / 'metadata.csv'}",
                        f"reports_csv: {reports}",
                        f"comments_part_1_csv: {FIXTURES / 'comments_part_1.csv'}",
                        f"comments_part_2_csv: {FIXTURES / 'comments_part_2.csv'}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            report = run_audit(
                SimpleNamespace(
                    config=str(config),
                    root=str(ROOT),
                    output_dir=str(temp / "outputs"),
                    limit=None,
                    progress_every=0,
                    resume=False,
                    skip_checksum=False,
                    skip=set(),
                )
            )
            result = report["files"]["reports"]
            self.assertEqual(result["rows_scanned"], 5)
            self.assertEqual(result["input_sanitization"]["nul_characters_removed"], 1)
            self.assertEqual(result["input_sanitization"]["physical_lines_with_nul"], 1)


if __name__ == "__main__":
    unittest.main()
