import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from bugzilla_qa.benchmark import assisted_review as ar
from bugzilla_qa.data import phase04 as p4
from bugzilla_qa.data.normalize import digest


class AssistedReviewFixtureTests(unittest.TestCase):
    def test_review_decision_schema_and_statuses(self):
        self.assertEqual(ar.QUEUE_COLUMNS[-11:], (
            "decision", "reviewer", "reviewed_at_utc", "source_checked", "rationale_present",
            "corrected_gold_json", "corrected_question", "note", "issue_type_observed",
            "second_reviewer", "second_decision"))
        self.assertEqual(ar.status([True, True]), "PASS")
        self.assertEqual(ar.status([True, None]), "UNKNOWN")
        self.assertEqual(ar.status([True, False]), "FAIL")
        self.assertEqual(ar.status([]), "UNKNOWN")

    def test_comment_scrubbing_and_advisory_flags(self):
        raw = "Hi Alice Smith, see https://example.invalid/x. Because it is clearer. Thanks, Alice\nalice@example.com @alice"
        safe = ar.safe_comment_text(raw)
        for marker in ("Alice", "Smith", "alice@example.com", "@alice"):
            self.assertNotIn(marker.casefold(), safe.casefold())
        q = {"gold": {"claims": [{"text": "Because it is clearer."}]}}
        flags = {x["code"] for x in ar.f5_flags(q, raw, "not-a-url")}
        self.assertIn("short_fragment", flags)
        self.assertIn("trivial_because", flags)
        self.assertIn("malformed_source_url", flags)
        self.assertIn("heuristics_are_advisory", {"heuristics_are_advisory"})

    def test_context_is_bounded_and_keeps_candidate(self):
        body = "A" * 500 + "This was delayed because component tests needed an update." + "B" * 500
        excerpt, bounds = ar.context_excerpt(body, "delayed because component tests needed an update", max_chars=140, radius=60)
        self.assertLessEqual(len(excerpt), 140)
        self.assertIn("delayed because component tests needed an update", excerpt)
        self.assertEqual(bounds["mode"], "candidate_with_bounded_context")

    def test_history_cache_requires_explicit_saved_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            absent, check = ar._history_envelope(root, {"history_fetch": {"cache_path": "missing.gz"}}, "31")
            self.assertIsNone(absent)
            self.assertFalse(check["cache_exists"])
            body = json.dumps({"bugs": [{"id": 31, "history": []}]}).encode()
            raw_hash = hashlib.sha256(body).hexdigest()
            cache = root / "31-history.json.gz"
            envelope = {"body_utf8": body.decode(), "body_sha256": raw_hash, "status_code": 200,
                        "requested_bug_id": 31, "endpoint": "history", "url": "https://bugzilla.mozilla.org/rest/bug/31/history",
                        "source_visibility": "public_endpoint_response"}
            with gzip.open(cache, "wt", encoding="utf-8") as handle:
                json.dump(envelope, handle)
            payload, check = ar._history_envelope(root, {"history_fetch": {"cache_path": str(cache),
                "raw_sha256": raw_hash, "status_code": 200, "url": envelope["url"]}}, "31")
            self.assertEqual(payload["bugs"][0]["history"], [])
            self.assertTrue(all(v for k, v in check.items() if isinstance(v, bool)))

    def _base_db(self):
        db = duckdb.connect(":memory:")
        db.execute("SET TimeZone='UTC'")
        db.execute("""CREATE TABLE bugs (
            bug_id VARCHAR, product VARCHAR, component VARCHAR, summary VARCHAR, description VARCHAR,
            opened_at_utc TIMESTAMPTZ, snapshot_status VARCHAR, snapshot_resolution VARCHAR,
            snapshot_assignee VARCHAR, snapshot_as_of_utc TIMESTAMPTZ, last_change_at_utc TIMESTAMPTZ,
            history_state VARCHAR, source_record_id VARCHAR, source_dataset VARCHAR, source_row_key VARCHAR,
            source_url VARCHAR, event_time_utc TIMESTAMPTZ, observed_at_utc TIMESTAMPTZ,
            ingested_at_utc TIMESTAMPTZ, text_availability VARCHAR, raw_field_mapping JSON, content_hash VARCHAR)""")
        db.execute("""CREATE TABLE source_records (
            source_record_id VARCHAR, source_dataset VARCHAR, source_row_key VARCHAR, source_url VARCHAR,
            content_hash VARCHAR, entity_type VARCHAR, disposition VARCHAR, normalized_fields JSON,
            entity_content_hash VARCHAR)""")
        db.execute("""INSERT INTO bugs VALUES
            ('31','Firefox','UI','summary','',TIMESTAMPTZ '2022-01-01 00:00:00+00','RESOLVED','FIXED',
             NULL,NULL,NULL,'UNKNOWN','src-31','metadata','row-31','https://bugzilla.mozilla.org/show_bug.cgi?id=31',
             TIMESTAMPTZ '2022-01-01 00:00:00+00',TIMESTAMPTZ '2026-01-02 00:00:00+00',
             TIMESTAMPTZ '2026-01-02 00:01:00+00','AVAILABLE','{}','entity-31')""")
        fields = {"product": "Firefox", "component": "UI", "snapshot_status": "RESOLVED",
                  "snapshot_resolution": "FIXED", "opened_at_utc": "2022-01-01T00:00:00Z"}
        entity_hash = digest(fields)
        db.execute("UPDATE bugs SET content_hash=? WHERE bug_id='31'", [entity_hash])
        db.execute("INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?)", ["src-31", "metadata", "row-31",
            "https://bugzilla.mozilla.org/show_bug.cgi?id=31", "raw-31", "bugs", "NORMALIZED",
            json.dumps(fields), entity_hash])
        return db

    def test_f1_compares_canonical_and_retained_source_field(self):
        db = self._base_db()
        q = {"question": "What component is recorded? Snapshot date is UNKNOWN.",
             "evidence": [{"id": "src-31", "bug_id": "31", "content_hash": db.execute("SELECT content_hash FROM bugs WHERE bug_id='31'").fetchone()[0],
              "source_row_key": "row-31", "source_url": "https://bugzilla.mozilla.org/show_bug.cgi?id=31",
              "fields": {"component": "UI"}}], "gold": {"type": "string", "value": "UI"},
             "scope": {"snapshot_as_of_utc": None}}
        result = ar.validate_f1(q, db, Path("."))
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(all(result["checks"].values()))
        db.close()

    def test_f2_replays_saved_history_and_utc_duration_not_base_changes(self):
        db = self._base_db()
        api = duckdb.connect(":memory:")
        api.execute("""CREATE TABLE field_changes (
            bug_id BIGINT,event_index BIGINT,change_index BIGINT,content_sha256 VARCHAR,
            source_row_key VARCHAR,field_name VARCHAR,old_value VARCHAR,new_value VARCHAR,
            event_time_utc VARCHAR,observed_at_utc VARCHAR,ingested_at_utc VARCHAR)""")
        payload = {"bugs": [{"id": 31, "history": [
            {"when": "2022-01-02T00:00:00Z", "who": "user-a", "changes": [
                {"field_name": "resolution", "removed": "", "added": "DUPLICATE"}]},
            {"when": "2022-01-03T12:00:00Z", "who": "user-b", "changes": [
                {"field_name": "resolution", "removed": "DUPLICATE", "added": "FIXED"}]},
            {"when": "2022-01-04T00:00:00Z", "who": "user-c", "changes": [
                {"field_name": "status", "removed": "RESOLVED", "added": "REOPENED"}]},
        ]}]}
        observed = "2026-01-02T00:00:00Z"
        parsed = p4.parse_api_history(payload, 31, "2022-01-01T00:00:00Z", observed)
        changes = parsed["changes"]
        ingested = "2026-01-02T00:01:00Z"
        for i, change in enumerate(changes):
            api.execute("INSERT INTO field_changes VALUES (?,?,?,?,?,?,?,?,?,?,?)", [31, change["event_index"],
                change["change_index"], p4.digest(change), "event-key-%d" % i, change["field_name"],
                change["old_value"], change["new_value"], change["event_time_utc"], observed, ingested])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = json.dumps(payload).encode()
            raw_hash = hashlib.sha256(body).hexdigest()
            cache = root / "history.json.gz"
            url = "https://bugzilla.mozilla.org/rest/bug/31/history"
            envelope = {"body_utf8": body.decode(), "body_sha256": raw_hash, "status_code": 200,
                "requested_bug_id": 31, "endpoint": "history", "url": url,
                "source_visibility": "public_endpoint_response", "fetched_at_utc": observed}
            with gzip.open(cache, "wt", encoding="utf-8") as handle:
                json.dump(envelope, handle)
            checkpoint_dir = root / "outputs/phase04/enrichment/cohort-8bb3150d29a598d8"
            checkpoint_dir.mkdir(parents=True)
            (checkpoint_dir / "checkpoint.json").write_text("{}")
            (checkpoint_dir / "api_enrichment.duckdb").write_bytes(b"fixture")
            metric = (datetime(2022, 1, 3, 12, tzinfo=timezone.utc) - datetime(2022, 1, 1, tzinfo=timezone.utc)).total_seconds() / 86400
            result = {"changes": changes, "history": parsed,
                "history_fetch": {"cache_path": str(cache), "raw_sha256": raw_hash, "status_code": 200,
                    "url": url, "fetched_at_utc": observed},
                "fix_metric": {"state": "VALID_EVENT_TIME", "elapsed_calendar_days": metric},
                "source_consistency_differences": []}
            checkpoint = {"candidate_results": {"31": result}}
            fixed = next(x for x in changes if x["field_name"] == "resolution" and x["new_value"] == p4.canonical("FIXED"))
            receipt = {"id": "history:31", "source_dataset": "bugzilla_rest_history", "content_hash": raw_hash,
                "source_row_key": "response:" + raw_hash, "observed_at_utc": observed,
                "ingested_at_utc": ingested, "fields": {"history_state": "PARSED"}}
            creation = {"id": "src-31", "bug_id": "31", "source_dataset": "metadata",
                "content_hash": db.execute("SELECT content_hash FROM bugs WHERE bug_id='31'").fetchone()[0],
                "source_row_key": "row-31", "source_url": "https://bugzilla.mozilla.org/show_bug.cgi?id=31",
                "fields": {"opened_at_utc": "2022-01-01T00:00:00.000000Z"}}
            event_evidence = {"id": "event-key-1", "source_dataset": "bugzilla_rest_history", "content_hash": p4.digest(fixed),
                "fields": {"field_name": fixed["field_name"], "old_value": fixed["old_value"], "new_value": fixed["new_value"]}}
            seconds = (datetime.fromisoformat(fixed["event_time_utc"].replace("Z", "+00:00")) - datetime(2022, 1, 1, tzinfo=timezone.utc)).total_seconds()
            q = {"bug_ids": ["31"], "gold": {"type": "calendar_duration", "seconds": seconds,
                    "hours": seconds / 3600, "days": seconds / 86400,
                    "first_fixed_at_utc": fixed["event_time_utc"], "tolerance_seconds": 1},
                 "evidence": [creation, event_evidence, receipt]}
            value = ar.validate_f2(q, db, api, checkpoint, root, 0)
            self.assertEqual(value["status"], "PASS")
            self.assertTrue(value["checks"]["phase03b_field_changes_empty_is_not_used_as_history"])
            self.assertEqual(value["independent_recomputation"]["explicit_reopened_entries"], 1)
            self.assertGreater(value["independent_recomputation"]["elapsed_calendar_hours"], 0)
        api.close()
        db.close()

    def test_f3_sql_matches_independent_fixture_id_set(self):
        seed = 317
        members = {"dev": [], "test": []}
        for i in range(1, 100):
            bug = str(i)
            members[ar.phase05.partition(seed, bug)].append(bug)
        members = {k: v[:(2 if k == "dev" else 3)] for k, v in members.items()}
        universe = members["dev"]
        matching = {universe[0]}
        db = duckdb.connect(":memory:")
        db.execute("CREATE TABLE bugs (bug_id VARCHAR,component VARCHAR,snapshot_status VARCHAR,opened_at_utc TIMESTAMPTZ)")
        db.execute("CREATE TABLE sample_membership (bug_id VARCHAR)")
        pop_rows = {}
        for bug in members["dev"] + members["test"]:
            component = "Messaging System" if bug in matching else "Other"
            db.execute("INSERT INTO bugs VALUES (?,?,?,?)", [bug, component, "NEW", "2022-01-01T00:00:00Z"])
            db.execute("INSERT INTO sample_membership VALUES (?)", [bug])
            pop_rows[bug] = {"bug_id": bug, "product": "Firefox", "component": component,
                "snapshot_status": "NEW", "opened_at_utc": "2022-01-01T00:00:00Z", "conflict_free": True}
        q = {"question": f"Within the dev partition ({len(universe)} distinct eligible bugs), count this component.",
             "scope": {"partition": "dev", "denominator": len(universe), "filter": {"component": "Messaging System"},
                "sample_seed": 317, "included_bug_ids_sha256": digest(sorted(members["dev"] + members["test"]))},
             "source_coverage": {"matching_bug_ids_sha256": digest(sorted(matching))},
             "sql": {"query": "SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND component = ?",
                "parameters": [universe, "Messaging System"]}, "bug_ids": sorted(matching), "gold": {"type": "integer", "value": 1}}
        result = ar.validate_f3(q, db, Path("."), {"members": members}, pop_rows, True,
                                expected_partition_counts={"dev": 2, "test": 3})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["independent_recomputation"]["python_count"], 1)
        self.assertEqual(result["independent_recomputation"]["sql_count"], 1)
        db.close()

    def test_f4_requires_complete_explicit_target_set(self):
        db = self._base_db()
        db.execute("""CREATE TABLE bug_links (link_key VARCHAR,bug_id VARCHAR,target_bug_id VARCHAR,relation VARCHAR,
            source_record_id VARCHAR,source_row_key VARCHAR,source_url VARCHAR,content_hash VARCHAR)""")
        target = next(str(i) for i in range(32, 100) if ar.phase05.partition(317, str(i)) == ar.phase05.partition(317, "31"))
        link = {"link_key": "link-31", "bug_id": "31", "target_bug_id": target, "relation": "depends_on"}
        db.execute("INSERT INTO bug_links VALUES (?,?,?,?,?,?,?,?)", ["link-31", "31", target, "depends_on", "src-31", "link-row", "https://bugzilla.mozilla.org/show_bug.cgi?id=31", "edge-hash"])
        payload = {"product": "Firefox", "component": "UI", "snapshot_status": "RESOLVED", "snapshot_resolution": "FIXED",
                   "opened_at_utc": "2022-01-01T00:00:00Z", "recorded_links": [link]}
        entity_hash = digest(payload)
        db.execute("UPDATE source_records SET normalized_fields=?,entity_content_hash=? WHERE source_record_id='src-31'",
                   [json.dumps(payload), entity_hash])
        db.execute("UPDATE bugs SET content_hash=? WHERE bug_id='31'", [entity_hash])
        evidence = {"id": "link-31", "bug_id": "31", "source_row_key": "link-row",
            "source_url": "https://bugzilla.mozilla.org/show_bug.cgi?id=31", "content_hash": "edge-hash",
            "fields": {"relation": "depends_on", "target_bug_id": target}}
        q = {"question": "Return the complete numeric set. Snapshot date and historical validity are UNKNOWN.",
             "evidence": [evidence], "gold": {"type": "id_set", "value": [target]},
             "bug_ids": ["31", target], "split": ar.phase05.partition(317, "31")}
        result = ar.validate_f4(q, db, Path("."))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["independent_recomputation"]["target_count"], 1)
        q["gold"]["value"] = []
        self.assertEqual(ar.validate_f4(q, db, Path("."))["status"], "FAIL")
        db.close()

    def test_f6_is_bounded_and_possible_effort_mentions_stay_unknown(self):
        db = self._base_db()
        api = duckdb.connect(":memory:")
        db.execute("CREATE TABLE comments (bug_id VARCHAR,body VARCHAR)")
        api.execute("CREATE TABLE api_comments (row_json JSON)")
        q = {"bug_ids": ["31"], "template_id": "phase05-v1.1:engineer_hours",
             "gold": {"type": "unanswerable", "value": "cannot be established from the specified evidence"},
             "scope": {"corpus": "frozen archive and selective API evidence", "snapshot_as_of_utc": None},
             "evidence": [{"fields": {"available_fields": ["product", "component", "snapshot_status", "snapshot_resolution"],
                                        "engineer_hours_field": "ABSENT", "snapshot_as_of_utc": None}}]}
        self.assertEqual(ar.validate_f6(q, db, api, Path("."))["status"], "PASS")
        db.execute("UPDATE bugs SET summary='Developer spent 4 hours investigating' WHERE bug_id='31'")
        self.assertEqual(ar.validate_f6(q, db, api, Path("."))["status"], "UNKNOWN")
        db.execute("UPDATE bugs SET summary='summary' WHERE bug_id='31'")
        db.execute("INSERT INTO comments VALUES ('31','The developer spent 4 hours testing')")
        self.assertEqual(ar.validate_f6(q, db, api, Path("."))["status"], "UNKNOWN")
        api.close()
        db.close()

    def test_f5_packet_reads_full_public_comment_and_redacts_identity_patterns(self):
        db = duckdb.connect(":memory:")
        db.execute("SET TimeZone='UTC'")
        db.execute("""CREATE TABLE comments (
            comment_key VARCHAR,bug_id VARCHAR,comment_id VARCHAR,body VARCHAR,private_flag BOOLEAN,
            source_record_id VARCHAR,source_dataset VARCHAR,source_row_key VARCHAR,source_url VARCHAR,
            event_time_utc TIMESTAMPTZ,observed_at_utc TIMESTAMPTZ,ingested_at_utc TIMESTAMPTZ,
            text_availability VARCHAR,raw_field_mapping JSON,content_hash VARCHAR)""")
        db.execute("""CREATE TABLE source_records (
            source_record_id VARCHAR,source_dataset VARCHAR,source_row_key VARCHAR,source_url VARCHAR,
            content_hash VARCHAR,entity_content_hash VARCHAR,normalized_fields JSON,disposition VARCHAR)""")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "outputs/normalization/phase03b/run-20261022T023542Z-1182018/manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}")
            body = ("The delay was because the test fixture did not include the new event. "
                    "Please retry after updating it. Thanks, Alice Smith\nalice@example.com @alice")
            comment_key = "comment-key-31"
            url = "https://bugzilla.mozilla.org/show_bug.cgi?id=31#c17"
            row_hash = digest({"comment_key": comment_key, "bug_id": "31", "comment_id": "17",
                               "body": body, "private_flag": False})
            source_fields = {"body_hash": digest(body), "bug_id": "31", "comment_id": "17",
                             "event_time_utc": "2022-01-02T00:00:00+00:00"}
            db.execute("INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [comment_key, "31", "17", body,
                False, "src-comment", "comments_part_1", "comment-row", url,
                "2022-01-02T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-02T00:01:00Z",
                "AVAILABLE", "{}", row_hash])
            db.execute("INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?)", ["src-comment", "comments_part_1",
                "comment-row", url, "raw-row-hash", row_hash, json.dumps(source_fields), "NORMALIZED"])
            claim = "because the test fixture did not include the new event."
            q = {"qid": "q_fixture_f5", "split": "test", "question": "What constraint is stated in comment 17?",
                 "gold": {"type": "supported_explanation", "claims": [{"text": claim, "evidence_id": comment_key}]},
                 "evidence": [{"id": comment_key, "source_dataset": "comments_part_1", "source_row_key": "comment-row",
                    "source_url": url, "content_hash": row_hash, "event_time_utc": "2022-01-02T00:00:00.000000Z",
                    "fields": {"body_sha256": hashlib.sha256(body.encode()).hexdigest(), "excerpt": claim, "private_flag": False}}]}
            result = ar._comment_packet(q, db, root)
            self.assertEqual(result["status"], "PASS")
            packet_json = json.dumps(result["packet"])
            self.assertIn("Please retry after updating it.", packet_json)
            for identity in ("Alice", "Smith", "alice@example.com", "@alice"):
                self.assertNotIn(identity.casefold(), packet_json.casefold())
            self.assertFalse(result["packet"]["evidence"]["privacy_provenance"]["raw_comment_body_written"])
        db.close()


if __name__ == "__main__":
    unittest.main()
