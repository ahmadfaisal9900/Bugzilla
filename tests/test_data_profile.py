import csv
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "data_profile"
sys.path.insert(0, str(ROOT / "src"))

from bugzilla_qa.data.profile import run_profile


class DataProfileTests(unittest.TestCase):
    def _config(self, temp: Path) -> Path:
        keys = {
            "metadata_csv": "metadata.csv",
            "reports_csv": "reports.csv",
            "comments_part_1_csv": "comments_part_1.csv",
            "comments_part_2_csv": "comments_part_2.csv",
            "comments_part_3_csv": "comments_part_3.csv",
        }
        config = temp / "data_paths.yaml"
        config.write_text(
            "\n".join(f"{key}: {FIXTURES / name}" for key, name in keys.items()) + "\n",
            encoding="utf-8",
        )
        return config

    def test_fixture_is_twenty_rows_with_overlap_and_malformed_dates(self):
        total = 0
        for path in FIXTURES.glob("*.csv"):
            with path.open(encoding="utf-8", newline="") as handle:
                total += sum(1 for _ in csv.DictReader(handle))
        self.assertEqual(total, 20)
        self.assertIn("broken-time", (FIXTURES / "comments_part_1.csv").read_text())

    def test_profile_streams_overlaps_and_sanitizes_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config = self._config(temp)
            args = SimpleNamespace(
                root=str(temp), config=str(config), output=str(temp / "out"), limit=None,
                sample_seed=317, resume=False,
            )
            profile = run_profile(args)
            self.assertEqual(profile["sources"]["metadata"]["row_count"]["value"], 5)
            self.assertEqual(profile["sources"]["metadata"]["unique_bug_ids"]["value"], 4)
            self.assertEqual(profile["sources"]["metadata"]["duplicate_bug_id_rows"], 1)
            self.assertEqual(profile["sources"]["metadata"]["malformed_or_missing_bug_id_rows"], 1)
            self.assertEqual(profile["sources"]["metadata"]["dates"]["created_at"]["nonempty_unparseable"], 1)
            self.assertEqual(profile["sources"]["comments_part_1"]["duplicate_comment_rows"], 1)
            self.assertEqual(profile["sources"]["comments_part_1"]["comment_record_rows_per_bug_quantiles"]["min"], 2)
            self.assertEqual(profile["sources"]["comments_part_1"]["sha256"], hashlib.sha256((FIXTURES / "comments_part_1.csv").read_bytes()).hexdigest())
            self.assertEqual(profile["sources"]["comments_part_1"]["private_flag_counts"]["true"], 2)
            overlap = profile["cross_source_joins"]["comment_key_overlaps"]
            self.assertEqual(overlap["comments_part_1__comments_part_2"]["shared_comment_keys"], 1)
            self.assertEqual(overlap["comments_part_2__comments_part_3"]["shared_comment_keys"], 1)
            self.assertEqual(profile["comment_part_duplicate_check"]["status"], "distinct_file_bytes")
            self.assertEqual(profile["comment_part_duplicate_check"]["shared_comment_keys"], 1)
            self.assertEqual(profile["cross_source_joins"]["metadata_to_comments"]["shared_unique_bugs"], 3)
            self.assertFalse(profile["sources"]["metadata"]["dates"]["created_at"]["parse_rate_nonempty"] == 1.0)

            report_text = (temp / "out" / "profile.json").read_text(encoding="utf-8")
            for private_value in ("private@example.test", "Alice", "first harmless note", "quoted note line one"):
                self.assertNotIn(private_value, report_text)
            self.assertTrue((temp / "out" / "summary.json").is_file())
            self.assertTrue((temp / "out" / "checkpoint.json").is_file())

            args.resume = True
            resumed = run_profile(args)
            self.assertEqual(resumed["sources"]["metadata"]["row_count"]["value"], 5)

    def test_limited_profile_labels_prefix_and_omits_whole_file_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            args = SimpleNamespace(
                root=str(temp), config=str(self._config(temp)), output=str(temp / "out"),
                limit=2, sample_seed=17, resume=False,
            )
            profile = run_profile(args)
            source = profile["sources"]["metadata"]
            self.assertEqual(source["row_count"], {"value": 2, "basis": "observed_prefix_only", "exact": False})
            self.assertIsNone(source["sha256"])
            self.assertEqual(source["hash_scope"], "not_computed_for_limited_scan")

    def test_nul_encoding_and_column_width_anomalies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            nul_csv = temp / "metadata_nul.csv"
            nul_csv.write_bytes((FIXTURES / "metadata.csv").read_bytes().replace(b"Firefox", b"Fire\x00fox", 1))
            legacy_csv = temp / "contributors_legacy.csv"
            legacy_csv.write_bytes(b"User ID,User Name,Comments Made\n1,Jos\xe9,3\n2,Short\n3,Extra,4,overflow\n")
            config = temp / "paths.yaml"
            config.write_text(
                f"metadata_csv: {nul_csv}\ncontribution_csv: {legacy_csv}\n",
                encoding="utf-8",
            )
            profile = run_profile(SimpleNamespace(
                root=str(temp), config=str(config), output=str(temp / "out"),
                limit=None, sample_seed=11, resume=False,
            ))
            metadata = profile["sources"]["metadata"]
            contributor = profile["sources"]["contributors"]
            self.assertEqual(metadata["csv_anomalies"]["nul_characters_removed"], 1)
            self.assertEqual(contributor["encoding_candidate"], "cp1252")
            self.assertEqual(contributor["csv_anomalies"]["rows_with_missing_cells"], 1)
            self.assertEqual(contributor["csv_anomalies"]["rows_with_extra_columns"], 1)
            self.assertNotIn("José", (temp / "out" / "profile.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
