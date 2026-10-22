"""Mocked Phase 4 parser, retry, privacy, temporal and resume tests; no live API."""
import gzip
import hashlib
import json
import contextlib
import io
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bugzilla_qa.data import phase04 as p4


def history(changes, when="2024-01-03T00:00:00Z", who="person@example.test"):
    return {"bugs": [{"id": 10, "history": [{"when": when, "who": who, "changes": changes}]}]}


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size]


class Phase04Tests(unittest.TestCase):
    def test_candidate_selection_is_seeded_and_covers_outcome_groups(self):
        rows = []
        outcomes = [("RESOLVED", "FIXED"), ("REOPENED", ""), ("NEW", ""),
                    ("RESOLVED", "DUPLICATE"), ("RESOLVED", "INCOMPLETE")]
        for i in range(100):
            status, resolution = outcomes[i % len(outcomes)]
            rows.append({"bug_id": i + 1, "snapshot_status": status,
                         "snapshot_resolution": resolution, "component": f"C{i % 7}",
                         "year": 2020 + i % 5, "comment_count": i % 3,
                         "missing_text_count": i % 4 == 0, "link_count": i % 2})
        first = p4.choose_candidates([dict(x) for x in rows], 317, 50)
        second = p4.choose_candidates([dict(x) for x in rows], 317, 50)
        self.assertEqual([x["bug_id"] for x in first], [x["bug_id"] for x in second])
        self.assertEqual(len({x["bug_id"] for x in first}), 50)
        groups = {(x["snapshot_status"], x["snapshot_resolution"] or "UNKNOWN") for x in first}
        self.assertEqual(len(groups), 5)
        tags = {tag for row in first for tag in row["tags"]}
        self.assertIn("positive:fixed", tags)
        self.assertIn("negative:reopened", tags)
        self.assertIn("negative:duplicate", tags)
        self.assertIn("negative:incomplete", tags)

    def test_history_fixed_duplicate_reopen_same_time_and_reordering(self):
        payload = {"bugs": [{"id": 10, "history": [
            {"when": "2024-01-03T00:00:00Z", "who": "a@example.test", "changes": [
                {"field_name": "resolution", "removed": "", "added": "FIXED"},
                {"field_name": "status", "removed": "NEW", "added": "RESOLVED"}]},
            {"when": "2024-01-04T00:00:00Z", "who": "b@example.test", "changes": [
                {"field_name": "status", "removed": "RESOLVED", "added": "REOPENED"}]},
            {"when": "2024-01-05T00:00:00Z", "who": "c@example.test", "changes": [
                {"field_name": "resolution", "removed": "FIXED", "added": "DUPLICATE"}]},
            {"when": "2024-01-06T00:00:00Z", "who": "d@example.test", "changes": [
                {"field_name": "resolution", "removed": "DUPLICATE", "added": "FIXED"}]},
        ]}]}
        parsed = p4.parse_api_history(payload, 10, "2024-01-01T00:00:00Z", "2024-01-10T00:00:00Z")
        self.assertEqual(parsed["state"], "PARSED")
        self.assertEqual(parsed["same_time_groups"], 0)
        self.assertEqual(parsed["reopened_count"], 1)
        self.assertEqual(parsed["first_fixed_at_utc"], "2024-01-03T00:00:00.000000Z")
        self.assertEqual(p4.classify_first_fixed(parsed, "2024-01-01T00:00:00Z")["elapsed_calendar_days"], 2.0)
        self.assertTrue(all("@" not in (x.get("actor_pseudonym") or "") for x in parsed["changes"]))
        same = p4.parse_api_history(payload, 10, "2024-01-01T00:00:00Z", "2024-01-10T00:00:00Z")
        self.assertTrue(same["chronology_ok"])
        reordered_payload = {"bugs": [{"id": 10, "history": [
            {"when": "2024-01-04T00:00:00Z", "who": "a", "changes": [{"field_name": "status", "removed": "", "added": "REOPENED"}]},
            {"when": "2024-01-02T00:00:00Z", "who": "b", "changes": [{"field_name": "resolution", "removed": "", "added": "FIXED"}]},
        ]}]}
        reordered = p4.parse_api_history(reordered_payload, 10, "2024-01-01T00:00:00Z")
        self.assertTrue(reordered["reordered"])
        self.assertEqual(p4.classify_first_fixed(reordered, "2024-01-01T00:00:00Z")["state"], "UNKNOWN")

    def test_missing_shape_same_time_and_future_event_are_unknown_or_flagged(self):
        self.assertEqual(p4.parse_api_history({"bugs": []}, 10)["state"], "UNKNOWN")
        repeated = {"bugs": [{"id": 10, "history": [
            {"when": "2024-01-02T00:00:00Z", "who": "a", "changes": [{"field_name": "status", "removed": "NEW", "added": "ASSIGNED"}]},
            {"when": "2024-01-02T00:00:00Z", "who": "b", "changes": [{"field_name": "status", "removed": "ASSIGNED", "added": "RESOLVED"}]},
        ]}]}
        parsed = p4.parse_api_history(repeated, 10, "2024-01-01T00:00:00Z", "2024-01-03T00:00:00Z")
        self.assertEqual(parsed["same_time_groups"], 1)
        self.assertEqual(parsed["state"], "PARSED")
        future = p4.parse_api_history(history([{"field_name": "resolution", "removed": "", "added": "FIXED"}],
                                               "2027-01-01T00:00:00Z"), 10,
                                      "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        self.assertTrue(future["future_event_after_observed_at"])
        self.assertEqual(p4.classify_first_fixed(future, "2024-01-01T00:00:00Z")["state"], "UNKNOWN")
        duplicate_only = p4.parse_api_history(history([{"field_name": "resolution", "removed": "", "added": "DUPLICATE"}]),
                                               10, "2024-01-01T00:00:00Z")
        self.assertIsNone(duplicate_only["first_fixed_at_utc"])
        self.assertEqual(p4.classify_first_fixed(duplicate_only, "2024-01-01T00:00:00Z")["state"], "UNKNOWN")
        repeated_change = {"bugs": [{"id": 10, "history": [
            {"when": "2024-01-02T00:00:00Z", "who": "actor", "changes": [{"field_name": "resolution", "removed": "", "added": "FIXED"}]},
            {"when": "2024-01-02T00:00:00Z", "who": "actor", "changes": [{"field_name": "resolution", "removed": "", "added": "FIXED"}]},
        ]}]}
        deduped = p4.parse_api_history(repeated_change, 10, "2024-01-01T00:00:00Z")
        self.assertEqual(deduped["duplicate_change_count"], 1)
        self.assertEqual(len(deduped["changes"]), 1)

    def test_public_api_client_200_403_404_and_retry_after(self):
        sleeps = []
        body = json.dumps({"bugs": []}).encode()
        with tempfile.TemporaryDirectory() as temp:
            state = {"requests_made": 0, "completed_endpoints": {}, "endpoint_metadata": {}, "path": str(Path(temp) / "state.json")}
            def good(request, timeout):
                return FakeResponse(body)
            client = p4.PublicBugzillaClient(Path(temp) / "cache", state, 4, 1, 0, good, sleeps.append)
            response = client.get_json(10, "history")
            self.assertEqual(response["status_code"], 200)
            self.assertTrue(Path(response["cache_path"]).is_file())
            with gzip.open(response["cache_path"], "rt", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["body_sha256"], hashlib.sha256(body).hexdigest())

            for status in (403, 404):
                def denied(request, timeout, status=status):
                    raise urllib.error.HTTPError(request.full_url, status, "denied", {}, None)
                denied_client = p4.PublicBugzillaClient(Path(temp) / str(status),
                    {"requests_made": 0, "completed_endpoints": {}, "endpoint_metadata": {}, "path": str(Path(temp) / f"{status}.json")},
                    2, 1, 0, denied, sleeps.append)
                denied_result = denied_client.get_json(10, "history")
                self.assertEqual(denied_result["status_code"], status)
                self.assertEqual(denied_result["error_label"], f"http_{status}")

            calls = []
            def flaky(request, timeout):
                calls.append(1)
                if len(calls) == 1:
                    raise urllib.error.HTTPError(request.full_url, 429, "slow down", {"Retry-After": "0"}, None)
                return FakeResponse(body)
            retry_state = {"requests_made": 0, "completed_endpoints": {}, "endpoint_metadata": {}, "path": str(Path(temp) / "retry.json")}
            retry_client = p4.PublicBugzillaClient(Path(temp) / "retry", retry_state, 2, 1, 0, flaky, sleeps.append)
            retry_result = retry_client.get_json(10, "history")
            self.assertEqual(retry_result["status_code"], 200)
            self.assertEqual(len(calls), 2)
            self.assertEqual(retry_state["requests_made"], 2)
            self.assertIn(0.0, sleeps)

    def test_comment_privacy_conflict_retention_import_and_temporal_cutoff(self):
        comments, qc = p4.parse_comments({"bugs": {"10": {"comments": [
            {"id": 1, "is_private": False, "creation_time": "2024-01-01T00:00:00Z", "text": "Public a@example.test"},
            {"id": 1, "is_private": False, "creation_time": "2024-01-01T00:00:00Z", "text": "Public a@example.test"},
            {"id": 2, "is_private": True, "text": "PRIVATE SECRET"},
            {"id": 3, "text": "unknown SECRET"},
        ]}}}, 10)
        self.assertEqual(qc, {"error": None, "public": 1, "withheld": 2,
                              "invalid_timestamp": 0, "duplicate_rows": 1})
        self.assertNotIn("a@example.test", comments[0]["text"])
        self.assertEqual(len(comments), 1)
        self.assertNotIn("PRIVATE SECRET", json.dumps(comments))
        future, future_qc = p4.parse_comments({"bugs": {"10": {"comments": [
            {"id": 4, "is_private": False, "creation_time": "2027-01-01T00:00:00Z", "text": "future"}
        ]}}}, 10, "2026-01-01T00:00:00Z")
        self.assertEqual(future, [])
        self.assertEqual(future_qc["invalid_timestamp"], 1)

        diffs = p4.consistency_differences({"snapshot_status": "NEW", "snapshot_resolution": None,
            "product": "Firefox", "component": "UI", "opened_at_utc": "2024-01-01T00:00:00Z"},
            {"status": "RESOLVED", "resolution": "FIXED", "product": "Firefox", "component": "UI",
             "creation_time": "2024-01-01T00:00:00Z"})
        self.assertEqual(len(diffs), 2)
        self.assertEqual({x["interpretation"] for x in diffs},
                         {"source_time_difference_requires_review", "timestamp_disagreement"})

        good = {"bug_id": 10, "source_dataset": "bugzilla_rest_history", "source_row_key": "row-1",
                "source_url": "https://bugzilla.mozilla.org/rest/bug/10/history",
                "event_time_utc": "2024-01-02T00:00:00Z", "observed_at_utc": "2024-01-03T00:00:00Z",
                "ingested_at_utc": "2024-01-03T01:00:00Z", "text_available": False,
                "raw_field_mapping": {}, "content_sha256": p4.digest("fixture-change"), "field_name": "resolution"}
        rejected = dict(good, source_row_key="row-2", event_time_utc="2024-01-04T00:00:00Z")
        result = p4.import_field_changes([good, rejected, good])
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 2)
        strict = p4.temporal_eligibility([good], "2024-01-02T12:00:00Z", "strict")
        replay = p4.temporal_eligibility([good], "2024-01-02T12:00:00Z", "retrospective-replay")
        self.assertEqual(strict["eligible_count"], 0)
        self.assertEqual(replay["eligible_count"], 1)
        self.assertIn("RETROSPECTIVE REPLAY", replay["interpretation"])

    def test_api_comments_deduplicate_and_preserve_conflict_versions(self):
        same_hash = hashlib.sha256(b"same public text").hexdigest()
        conflict_hash = hashlib.sha256(b"changed public text").hexdigest()
        base_index = {
            (10, "1"): [{"event_time_utc": "2024-01-01T00:00:00.000000Z",
                          "text_sha256": same_hash, "text_available": True}],
            (10, "2"): [{"event_time_utc": "2024-01-01T00:00:00.000000Z",
                          "text_sha256": same_hash, "text_available": True}],
        }
        public = [
            {"bug_id": 10, "comment_id": 1, "creation_time_utc": "2024-01-01T00:00:00Z",
             "text_sha256": same_hash, "text_available": True, "text": "same public text"},
            {"bug_id": 10, "comment_id": 2, "creation_time_utc": "2024-01-01T00:00:00Z",
             "text_sha256": conflict_hash, "text_available": True, "text": "changed public text"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "cohort-fixture"
            run_dir.mkdir()
            state = {"state": "COMPLETE", "updated_at_utc": "2026-10-22T02:00:00Z",
                     "candidate_results": {"10": {"bug_id": 10, "public_comments": public,
                         "comments_fetch": {"fetched_at_utc": "2026-10-22T01:59:00Z"}}}}
            manifest = {"baseline_run_id": "base", "candidate_manifest_sha256": "fixture",
                        "candidates": [{"bug_id": 10, "explicit_link_count": 0}]}
            summary = p4.build_enrichment_outputs(temp, run_dir, manifest, state,
                                                 {"_base_comment_index": base_index})
            self.assertEqual(summary["duplicate_api_comments_matching_csv_skipped"], 1)
            self.assertEqual(summary["api_comments_retained_as_source_conflicts"], 1)
            output = json.loads((run_dir / "api_comments.json").read_text())
            self.assertEqual(len(output), 1)
            self.assertTrue(output[0]["source_conflict"])

    def test_temporal_qc_covers_events_comments_and_current_refresh_without_text(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            event = {"source_row_key": "event-key", "event_time_utc": "2024-01-01T00:00:00Z",
                     "observed_at_utc": "2026-01-02T00:00:00Z", "ingested_at_utc": "2026-01-02T00:01:00Z",
                     "text": "DO_NOT_PRINT_EVENT_BODY"}
            (run_dir / "field_changes.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            comment = {"source_row_key": "comment-key", "event_time_utc": "2024-01-01T00:00:00Z",
                       "observed_at_utc": "2026-01-02T00:00:00Z", "ingested_at_utc": "2026-01-02T00:01:00Z",
                       "text": "DO_NOT_PRINT_COMMENT_BODY"}
            (run_dir / "api_comments.json").write_text(json.dumps([comment]), encoding="utf-8")
            link = {"source_row_key": "link-key", "event_time_utc": "2027-01-01T00:00:00Z",
                    "observed_at_utc": "2026-01-02T00:00:00Z", "ingested_at_utc": "2026-01-02T00:01:00Z"}
            (run_dir / "api_link_changes.json").write_text(json.dumps([link]), encoding="utf-8")
            refresh = {"bug_id": 10, "observed_at_utc": "2026-01-02T00:00:00Z",
                       "ingested_at_utc": "2026-01-02T00:01:00Z", "status": "RESOLVED"}
            (run_dir / "api_bug_refresh.json").write_text(json.dumps([refresh]), encoding="utf-8")
            args = SimpleNamespace(root=temp, run_dir=temp, cutoff="2026-01-03T00:00:00Z",
                                   mode="strict", dry_run=True)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                p4.command_temporal_qc(args)
            rendered = output.getvalue()
            report = json.loads(rendered)
            self.assertEqual(report["event_evidence_by_source"]["field_changes"]["eligible_count"], 1)
            self.assertEqual(report["event_evidence_by_source"]["api_comments"]["eligible_count"], 1)
            self.assertEqual(report["event_evidence_by_source"]["api_link_changes"]["excluded_counts"],
                             {"event_after_cutoff": 1})
            self.assertEqual(report["current_refresh_availability_counts"],
                             {"available_as_current_refresh_by_cutoff": 1})
            self.assertNotIn("DO_NOT_PRINT", rendered)

    def test_interrupted_run_resumes_and_keeps_snapshot_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / "outputs/normalization/phase03b/base"
            run.mkdir(parents=True)
            db_path = run / "canonical.duckdb"
            db = duckdb.connect(str(db_path))
            db.execute("""CREATE TABLE bugs(bug_id VARCHAR, product VARCHAR, component VARCHAR,
                snapshot_status VARCHAR, snapshot_resolution VARCHAR, opened_at_utc TIMESTAMPTZ)""")
            db.execute("INSERT INTO bugs VALUES (10,'Firefox','UI','NEW',NULL,'2024-01-01T00:00:00Z')")
            db.execute("""CREATE TABLE comments(bug_id VARCHAR,comment_id VARCHAR,event_time_utc TIMESTAMPTZ,
                body VARCHAR)""")
            db.close()
            manifest = {"schema_version": 1, "baseline_run_id": "run-test", "baseline_manifest_identity": "basehash",
                "baseline_duckdb_path": "outputs/normalization/phase03b/base/canonical.duckdb",
                "candidates": [{"bug_id": 10, "rank": 1, "pilot": True, "csv_comment_count": 1}]}
            manifest["candidate_manifest_sha256"] = p4.digest(manifest)
            manifest_path = root / "candidate_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            event_payload = history([{"field_name": "resolution", "removed": "", "added": "FIXED"}],
                                    "2024-01-03T00:00:00Z", "actor@example.test")
            bug_payload = {"bugs": [{"id": 10, "creation_time": "2024-01-01T00:00:00Z",
                "last_change_time": "2024-01-03T00:00:00Z", "product": "Firefox", "component": "UI",
                "status": "RESOLVED", "resolution": "FIXED", "is_open": False}]}
            cache = {}
            class MockClient:
                def __init__(self, cache_dir, checkpoint, max_requests, **kwargs):
                    self.cp, self.cap = checkpoint, max_requests
                def cached_result(self, bug_id, endpoint):
                    return cache.get((bug_id, endpoint))
                def get_json(self, bug_id, endpoint):
                    if self.cp["requests_made"] >= self.cap:
                        raise p4.RequestBudgetExceeded("cap")
                    self.cp["requests_made"] += 1
                    payload = event_payload if endpoint == "history" else bug_payload
                    item = {"bug_id": bug_id, "endpoint": endpoint, "url": "mock", "fetched_at_utc": "2026-10-22T02:00:00Z",
                            "status_code": 200, "response_shape": "mock", "cache_path": "mock.gz",
                            "raw_sha256": "mockhash", "source_visibility": "public_endpoint_response",
                            "error_label": None, "attempt": 1, "payload": payload}
                    safe = {k: v for k, v in item.items() if k != "payload"}
                    key = f"{bug_id}:{endpoint}"
                    self.cp["completed_endpoints"][key] = safe
                    self.cp["endpoint_metadata"][key] = safe
                    cache[(bug_id, endpoint)] = item
                    p4.write_json(self.cp["path"], self.cp)
                    return item

            def args(cap, resume):
                return SimpleNamespace(root=str(root), manifest=str(manifest_path), limit=None, pilot=True,
                    dry_run=False, max_requests=cap, resume=resume, fetch_missing_comments=False,
                    timeout=5, pace_seconds=0, link_field=[])
            with patch.object(p4, "PublicBugzillaClient", MockClient):
                p4.run_enrichment(args(1, False))
                run_dir = p4._run_dir(root, manifest)
                partial = json.loads((run_dir / "summary.json").read_text())
                self.assertEqual(partial["successful_histories"], 1)
                self.assertEqual(partial["successful_current_metadata"], 0)
                p4.run_enrichment(args(2, True))
                final = json.loads((run_dir / "summary.json").read_text())
                self.assertEqual(final["state"], "COMPLETE")
                self.assertEqual(final["requests_made_including_retries"], 2)
                self.assertEqual(final["valid_f2_cases"], 1)
                self.assertGreater(final["source_consistency_differences"], 0)
                self.assertEqual(final["source_snapshot_as_of_utc"], None)
                db = duckdb.connect(str(run_dir / "api_enrichment.duckdb"), read_only=True)
                self.assertEqual(db.execute("SELECT count(*) FROM field_changes").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT count(*) FROM api_bug_refresh").fetchone()[0], 1)
                db.close()
                checkpoint = json.loads((run_dir / "checkpoint.json").read_text())
                self.assertNotIn("payload", json.dumps(checkpoint))
                self.assertNotIn("actor@example.test", json.dumps(checkpoint))


if __name__ == "__main__":
    unittest.main()
