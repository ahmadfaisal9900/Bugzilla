"""Phase 6 tests on the synthetic Phase 5 fixture; no model, network or corpus job."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_phase05 import fixture

import duckdb

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data import phase04 as p4
from bugzilla_qa.evaluation import phase06, scoring
from bugzilla_qa.methods import contract, m3_sql
from bugzilla_qa.retrieval import bm25


def answer(value=None, abstained=False, status=contract.OK):
    return contract.make_answer("q", "M", "text", abstained, value, status=status)


def item(gold, family="F1"):
    return {"qid": "q", "family": family, "gold": gold}


class ContractTests(unittest.TestCase):
    def test_only_a_complete_reply_parses(self):
        good = {"answer": "x", "abstained": False, "value": 3, "evidence": [{"bug_id": "1", "record_id": "r", "url": None}]}
        self.assertEqual(contract.parse_model_output("q", "M", json.dumps(good))["status"], contract.OK)
        for raw in ("not json", None, "[]", json.dumps({**good, "extra": 1}), json.dumps({**good, "abstained": "no"}),
                    json.dumps({**good, "value": True}), json.dumps({**good, "evidence": ["bug 1"]}),
                    json.dumps({**good, "abstained": "no", "value": None}), json.dumps({**good, "answer": 5}),
                    json.dumps({**good, "abstained": True}), '{"answer":"x","abstained":false,"value":NaN,"evidence":[]}'):
            parsed = contract.parse_model_output("q", "M", raw)
            self.assertEqual(parsed["status"], contract.PARSE_ERROR, raw)
            self.assertFalse(parsed["abstained"], raw)
            self.assertEqual(parsed["raw"], raw)


class ScoringTests(unittest.TestCase):
    def verdict(self, gold, ans, family="F1"):
        return scoring.score(item(gold, family), ans)

    def test_failed_answers_earn_nothing_even_on_unanswerable_gold(self):
        for gold in ({"type": "unanswerable", "value": "x"}, {"type": "unknown", "value": "x"}, {"type": "string", "value": "x"}):
            for status in (contract.NO_INTENT, contract.PARSE_ERROR):
                self.assertEqual(self.verdict(gold, answer(status=status))["verdict"], scoring.INCORRECT)
                # Even a failed answer that claims to abstain, or carries the right value, earns nothing.
                failed = self.verdict(gold, answer(abstained=True, status=status))
                self.assertEqual((failed["verdict"], failed["reason"]), (scoring.INCORRECT, status))
                self.assertEqual(self.verdict(gold, answer("x", status=status))["verdict"], scoring.INCORRECT)

    def test_abstention_is_right_only_when_evidence_is_missing(self):
        gold = {"type": "unanswerable", "value": "x"}
        self.assertEqual(self.verdict(gold, answer(abstained=True))["verdict"], scoring.CORRECT)
        self.assertEqual(self.verdict(gold, answer(5))["reason"], "answered_unanswerable")
        self.assertEqual(self.verdict(gold, answer("5", abstained=True))["verdict"], scoring.INCORRECT)
        for answerable in ({"type": "integer", "value": 5}, {"type": "supported_explanation", "claims": []}):
            result = self.verdict(answerable, answer(abstained=True))
            self.assertEqual((result["verdict"], result["reason"]), (scoring.INCORRECT, "false_abstention"))

    def test_explanations_are_never_auto_graded(self):
        gold = {"type": "supported_explanation", "claims": [{"text": "because x"}]}
        self.assertEqual(self.verdict(gold, answer("because x"), "F5")["verdict"], scoring.NEEDS_HUMAN)

    def test_exact_types(self):
        string = {"type": "string", "value": "Tabbed  Browser"}
        self.assertEqual(self.verdict(string, answer("tabbed browser "))["verdict"], scoring.CORRECT)
        self.assertEqual(self.verdict(string, answer("Tabbed"))["verdict"], scoring.INCORRECT)
        self.assertEqual(self.verdict(string, answer(None))["verdict"], scoring.INCORRECT)
        integer = {"type": "integer", "value": 2}
        self.assertEqual(self.verdict(integer, answer(2))["verdict"], scoring.CORRECT)
        self.assertEqual(self.verdict(integer, answer(2.5))["verdict"], scoring.INCORRECT)
        self.assertEqual(self.verdict({"type": "integer", "value": 1}, answer(True))["verdict"], scoring.INCORRECT)

    def test_duration_tolerance_and_exact_flag(self):
        gold = {"type": "calendar_duration", "hours": 100.0, "tolerance_seconds": 1}
        exact = self.verdict(gold, answer(100.0001))
        self.assertEqual((exact["verdict"], exact["exact"]), (scoring.CORRECT, True))
        rounded = self.verdict(gold, answer(100.5))
        self.assertEqual((rounded["verdict"], rounded["exact"]), (scoring.CORRECT, False))
        self.assertEqual(self.verdict(gold, answer(101.5))["verdict"], scoring.INCORRECT)
        self.assertEqual(self.verdict(gold, answer("soon"))["reason"], "no_duration")

    def test_id_set_needs_the_complete_set(self):
        gold = {"type": "id_set", "value": ["1", "2"]}
        self.assertEqual(self.verdict(gold, answer(["2", "1"]))["verdict"], scoring.CORRECT)
        partial = self.verdict(gold, answer(["1"]))
        self.assertEqual((partial["verdict"], partial["recall"], partial["precision"]), (scoring.INCORRECT, 0.5, 1.0))
        self.assertEqual(self.verdict(gold, answer(["1", "2", "3"]))["verdict"], scoring.INCORRECT)
        self.assertEqual(self.verdict(gold, answer([]))["f1"], 0.0)
        self.assertEqual(self.verdict(gold, answer("1"))["reason"], "no_id_set")

    def test_statistics(self):
        low, high = scoring.wilson(8, 10)
        self.assertAlmostEqual(low, 0.4902, places=3)
        self.assertAlmostEqual(high, 0.9433, places=3)
        self.assertIsNone(scoring.wilson(0, 0))
        rows = [{"method": "M", "family": "F1", "verdict": v, "reason": r, "qid": str(i)}
                for i, (v, r) in enumerate([(scoring.CORRECT, "exact_integer"), (scoring.INCORRECT, contract.NO_INTENT), (scoring.NEEDS_HUMAN, "human_graded_rubric")])]
        cell = scoring.summarize(rows)[0]
        self.assertEqual((cell["auto_scored"], cell["correct"], cell["needs_human"], cell["failed_to_answer"]), (2, 1, 1, 1))

    def test_paired_bootstrap_is_seeded_and_paired(self):
        a = [{"qid": str(i), "verdict": scoring.CORRECT} for i in range(20)]
        b = [{"qid": str(i), "verdict": scoring.CORRECT if i < 10 else scoring.INCORRECT} for i in range(20)]
        first = scoring.paired_bootstrap(a, b)
        self.assertEqual(first, scoring.paired_bootstrap(a, b))
        self.assertEqual(first["difference"], 0.5)
        self.assertLessEqual(first["bootstrap_95"][0], 0.5)
        self.assertGreaterEqual(first["bootstrap_95"][1], 0.5)
        self.assertIsNone(scoring.paired_bootstrap(a, []))


class IntentTests(unittest.TestCase):
    def test_allowlist_rejects_anything_else(self):
        good = {"template": "field_lookup", "bug_id": "12", "field": "status"}
        self.assertTrue(m3_sql.validate_intent(good))
        for bad in (None, "field_lookup", {}, {"template": "drop"}, {**good, "extra": 1}, {"template": ["x"]},
                    {**good, "bug_id": "1 OR 1=1"}, {**good, "bug_id": 12}, {**good, "field": "summary"}, {**good, "field": ["status"]},
                    {"template": "relation_targets", "bug_id": "1", "relation": "blocks; DROP TABLE bugs"}):
            self.assertFalse(m3_sql.validate_intent(bad), bad)


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.pins = fixture(cls.root)
        cls.items, _ = p5.complete_candidates(cls.root, cls.pins, per_family=5, f5_target=5)
        cls.base, cls.overlay = p5.paths(cls.root, cls.pins)
        cls.store = m3_sql.SqlStore(cls.base / "canonical.duckdb", cls.overlay / "api_enrichment.duckdb")

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.temp.cleanup()

    def inference(self, q, wording="dev"):
        return {"qid": q["qid"], "question": p5.render(q, wording), "scope": q["scope"]}

    def test_m3_matches_independently_built_gold_for_every_family(self):
        """Gold comes from the Phase 5 generator's own queries; synthetic items may use dev wording."""
        families = set()
        for q in self.items:
            result = scoring.score(q, m3_sql.answer_question(self.store, self.inference(q)))
            families.add(q["family"])
            if q["family"] == "F5":
                self.assertEqual(result["reason"], "false_abstention")
            else:
                self.assertEqual(result["verdict"], scoring.CORRECT, (q["family"], q["gold"], result))
        self.assertEqual(families, set(p5.FAMILIES))

    def test_duration_and_counts_are_real_values(self):
        fixed = next(q for q in self.items if q["gold"]["type"] == "calendar_duration")
        got = m3_sql.answer_question(self.store, self.inference(fixed))
        self.assertEqual(got["value"], 48)
        self.assertIn("not engineer work hours", got["answer"])
        self.assertEqual(got["evidence"][0]["record_id"], "history:" + fixed["bug_ids"][0])

    def test_held_out_wording_is_not_parsed(self):
        for q in self.items:
            for wording in ("test", "challenge"):
                got = m3_sql.answer_question(self.store, self.inference(q, wording))
                self.assertEqual(got["status"], contract.NO_INTENT, wording)
                self.assertFalse(got["abstained"])

    def test_fixed_reopened_fixed_uses_the_first_fix_and_counts_real_reopens(self):
        store = m3_sql.SqlStore(self.base / "canonical.duckdb", self.overlay / "api_enrichment.duckdb")
        try:
            store.overlay.close()
            store.overlay = duckdb.connect(":memory:")
            store.overlay.execute("""CREATE TABLE field_changes (bug_id BIGINT, field_name VARCHAR, old_value VARCHAR,
                new_value VARCHAR, event_time_utc VARCHAR, history_state VARCHAR)""")
            # Bug 1 is filed 2024-01-01T00:00Z. Rows are out of order on purpose.
            c = p4.canonical
            for row in [("resolution", c(""), c("FIXED"), "2024-01-10T00:00:00Z"),  # the later fix
                        ("resolution", c("FIXED"), c(""), "2024-01-05T00:00:00Z"),
                        ("status", c("RESOLVED"), c("REOPENED"), "2024-01-05T00:00:00Z"),
                        ("status", c("REOPENED"), c("REOPENED"), "2024-01-06T00:00:00Z"),  # no-op, not a reopening
                        ("resolution", c(""), c("FIXED"), "2024-01-03T00:00:00Z"),
                        ("resolution", c(""), c("FIXED"), "2023-12-01T00:00:00Z"),  # before filing, never qualifies
                        ("resolution", c("FIXED"), c("FIXED"), "2024-01-02T00:00:00Z"),  # no-op, not a transition
                        ("resolution", c("INVALID"), c("WONTFIX"), "2024-01-02T00:00:00Z"),
                        ("status", c("NEW"), c("REOPENED"), "2024-01-04T00:00:00Z")]:
                field, old, new, when = row
                store.overlay.execute("INSERT INTO field_changes VALUES (1,?,?,?,?,'PARSED')", [field, old, new, when])
            # An unparsed history row must not count, for either measure.
            store.overlay.execute("INSERT INTO field_changes VALUES (1,'resolution',?,?,'2024-01-02T00:00:00Z','FAILED')", [c(""), c("FIXED")])
            hours = store.execute({"template": "first_fixed_hours", "bug_id": "1"}, {})
            self.assertEqual((hours[1], hours[2]), (False, 48.0))
            reopened = store.execute({"template": "reopen_count", "bug_id": "1"}, {})
            self.assertEqual((reopened[1], reopened[2]), (False, 2))
            # DUPLICATE or INVALID is not a fix, and no history is UNKNOWN, not zero.
            store.overlay.execute("DELETE FROM field_changes WHERE new_value=?", [c("FIXED")])
            self.assertTrue(store.execute({"template": "first_fixed_hours", "bug_id": "1"}, {})[1])
            self.assertEqual(store.execute({"template": "reopen_count", "bug_id": "3"}, {})[1], True)
        finally:
            store.close()

    def test_scope_guards_refuse_instead_of_guessing(self):
        count = next(q for q in self.items if q["family"] == "F3")
        wrong = {**self.inference(count), "scope": {**count["scope"], "population_manifest_sha256": "other"}}
        self.assertTrue(m3_sql.answer_question(self.store, wrong)["abstained"])
        wrong = {**self.inference(count), "scope": {**count["scope"], "partition": "other"}}
        self.assertTrue(m3_sql.answer_question(self.store, wrong)["abstained"])
        self.assertTrue(self.store.execute({"template": "field_lookup", "field": "status", "bug_id": "999"}, {})[1])
        self.assertTrue(self.store.execute({"template": "first_fixed_hours", "bug_id": "20"}, {})[1])

    def test_count_stays_inside_its_partition(self):
        bugs = dict(self.store.base.execute("SELECT bug_id, snapshot_status FROM bugs").fetchall())
        sizes = []
        for partition in ("dev", "test"):
            scope = {"partition": partition, "population_manifest_sha256": self.store.population_sha256}
            intent = {"template": "count_in_partition", "field": "status", "value": "RESOLVED", "partition": partition}
            want = sum(bugs[b] == "RESOLVED" for b in self.store.partitions[partition])
            self.assertEqual(self.store.execute(intent, scope)[2], want)
            sizes.append(want)
        self.assertTrue(all(sizes), "The fixture must have matches in both partitions for this to mean anything")

    def test_private_comment_is_excluded_even_if_marked_available(self):
        db = duckdb.connect(":memory:")
        db.execute("""CREATE TABLE comments (bug_id VARCHAR, comment_key VARCHAR, source_url VARCHAR, body VARCHAR,
            private_flag BOOLEAN, text_availability VARCHAR)""")
        db.execute("INSERT INTO comments VALUES ('1','public','u','open text',false,'AVAILABLE'), ('1','hidden','u','secret text',true,'AVAILABLE'), ('1','gone','u','gone text',false,'WITHHELD')")
        self.assertEqual([d["record_id"] for d in bm25.comment_documents(db, {"1"})], ["public"])
        db.close()

    def test_store_cannot_write(self):
        with self.assertRaises(duckdb.Error):
            self.store.base.execute("DELETE FROM bugs")
        with self.assertRaises(duckdb.Error):
            self.store.overlay.execute("DELETE FROM field_changes")

    def test_bm25_finds_each_record_and_never_a_withheld_one(self):
        db = duckdb.connect(str(self.base / "canonical.duckdb"), read_only=True)
        api = duckdb.connect(str(self.overlay / "api_enrichment.duckdb"), read_only=True)
        try:
            db.execute("SET TimeZone='UTC'")
            documents = list(bm25.build_corpus(db, api))
            private = {k for k, in db.execute("SELECT comment_key FROM comments WHERE private_flag=true").fetchall()}
        finally:
            db.close()
            api.close()
        self.assertTrue(private)
        self.assertFalse(private & {d["record_id"] for d in documents})
        self.assertFalse(any("fixture@example.test" in d["text"] for d in documents))
        self.assertFalse(any(d["bug_id"] == "20" for d in documents))  # conflicted metadata parent
        self.assertEqual({d["kind"] for d in documents}, {"bug_snapshot", "comment", "history"})
        index = bm25.BM25Index(documents)
        checked = 0
        for q in self.items:
            relevant = bm25.relevant_records(q)
            if relevant:
                hits = index.search(p5.render(q, "dev"), 10)
                self.assertEqual(bm25.recall_at(hits, relevant, 10), 1.0, q["family"])
                self.assertEqual(hits, index.search(p5.render(q, "dev"), 10))
                checked += 1
        self.assertGreater(checked, 0)

    def test_runner_scores_after_predicting_resumes_and_blocks(self):
        run = self.root / "bench"
        run.mkdir(exist_ok=True)
        # Dev wording is what the generator produced for dev rows, so this is the real file shape.
        p5.write_json(run / "candidates.json", self.items)
        sources = self.root / "sources.json"
        p5.write_json(sources, self.pins)
        common = ["--root", str(self.root), "--sources", "sources.json", "--run", "bench"]
        dev = [q for q in self.items if q["split"] == "dev"]
        self.assertEqual(phase06.main(["m3", *common, "--unfrozen-dev-smoke", "--dry-run"]), 0)
        self.assertEqual(phase06.main(["m3", *common, "--run", "absent", "--unfrozen-dev-smoke"]), 1)
        self.assertEqual(phase06.main(["m3", *common]), 1)  # not frozen, and no smoke flag
        self.assertEqual(phase06.main(["m3", *common, "--unfrozen-dev-smoke", "--limit", "2"]), 0)
        out = next((self.root / "outputs/phase06").glob("m3-dev-smoke-*"))
        self.assertEqual(p5.read(out / "summary.json")["state"], "PARTIAL")
        self.assertEqual(p5.read(out / "summary.json")["benchmark_state"], phase06.SMOKE)
        with self.assertRaises(SystemExit):  # never silently reuse a run
            phase06.main(["m3", *common, "--unfrozen-dev-smoke"])
        predictions = out / "predictions.jsonl"
        predictions.write_text(predictions.read_text(encoding="utf-8") + '{"torn', encoding="utf-8")
        self.assertEqual(phase06.main(["m3", *common, "--unfrozen-dev-smoke", "--resume"]), 0)
        summary = p5.read(out / "summary.json")
        self.assertEqual((summary["state"], summary["answered"]), ("COMPLETE", len(dev)))
        self.assertEqual(sorted(json.loads(x)["qid"] for x in predictions.read_text(encoding="utf-8").splitlines()), sorted(q["qid"] for q in dev))
        lines = [json.loads(x) for x in predictions.read_text(encoding="utf-8").splitlines()]
        self.assertFalse(any("gold" in json.dumps(x) for x in lines))
        for cell in summary["table"]:
            if cell["family"] != "F5":
                self.assertEqual(cell["correct"], cell["questions"], cell)
        self.assertEqual(phase06.main(["bm25", *common, "--unfrozen-dev-smoke"]), 0)
        recall = p5.read(next((self.root / "outputs/phase06").glob("bm25-dev-smoke-*")) / "summary.json")
        self.assertTrue(recall["table"])
        self.assertTrue(all(cell["recall_at_10"] == 1.0 for cell in recall["table"]), recall["table"])

    def test_runner_has_no_way_to_select_the_locked_test(self):
        with self.assertRaises(SystemExit):
            phase06.main(["m3", "--split", "test"])
        self.assertEqual(phase06.SPLIT, "dev")

    def test_relevant_record_is_the_question_parent_not_a_link_target(self):
        linked = [q for q in self.items if q["family"] == "F4"]
        self.assertTrue(any(q["bug_ids"][0] != q["evidence"][0]["bug_id"] for q in linked))
        for q in linked:
            self.assertEqual(bm25.relevant_records(q), {"snapshot:" + q["evidence"][0]["bug_id"]})

    def test_frozen_files_are_checked_and_inference_excludes_gold(self):
        run = self.root / "frozen-run"
        dest = run / "frozen-x"
        dest.mkdir(parents=True)
        dev = [q for q in self.items if q["split"] == "dev"]
        p5.jsonl(dest / "dev.questions.jsonl", [{k: q[k] for k in ("qid", "question", "scope")} for q in dev])
        p5.jsonl(dest / "dev.gold.jsonl", dev)
        hashes = {n: phase06.file_hash(dest / n) for n in ("dev.questions.jsonl", "dev.gold.jsonl")}
        p5.write_json(dest / "manifest.json", {"state": "FROZEN_HUMAN_SIGNED", "sha256": hashes})
        (run / "FROZEN").write_text("frozen-x\n")
        state, questions, gold = phase06.load_benchmark(run, False)
        self.assertEqual(state, phase06.FROZEN)
        self.assertEqual({q["qid"] for q in questions}, {q["qid"] for q in gold()})
        self.assertFalse(any("gold" in q for q in questions))
        original = (dest / "dev.gold.jsonl").read_bytes()
        (dest / "dev.gold.jsonl").write_bytes(original + b"\n")
        with self.assertRaises(AssertionError):
            phase06.load_benchmark(run, False)
        (dest / "dev.gold.jsonl").write_bytes(original)
        p5.jsonl(dest / "dev.questions.jsonl", [dev[0]])
        p5.write_json(dest / "manifest.json", {"state": "FROZEN_HUMAN_SIGNED", "sha256": {**hashes, "dev.questions.jsonl": phase06.file_hash(dest / "dev.questions.jsonl")}})
        with self.assertRaises(AssertionError):  # gold fields in the inference file
            phase06.load_benchmark(run, False)


if __name__ == "__main__":
    unittest.main()
