"""M3 intent tests with synthetic DuckDB data and fake model replies."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.evaluation import phase06, scoring
from bugzilla_qa.methods import generation as gen, m3_intent, m3_sql
from bugzilla_qa.methods.local_model import OllamaClient, RequestLimit
from test_phase05 import fixture

QUESTION = {"qid": "q-1", "question": "what status is recorded for Firefox bug 7?", "scope": {"partition": "dev"}}


def chat_reply(content):
    return {"done": True, "model": "fixture-model", "message": {"content": content}}


def truthful_parser(url, payload, timeout):
    """Return the expected intent from the development question parser."""
    return chat_reply(json.dumps(m3_sql.parse_dev_wording(payload["messages"][1]["content"])))


class IntentTests(unittest.TestCase):
    def answer(self, content):
        store = Mock(); store.execute.return_value = ("text", False, "NEW", [])
        client = OllamaClient("m", post=Mock(return_value=chat_reply(content)))
        return m3_intent.answer_question(store, QUESTION, client), store

    def test_valid_intent_runs_and_the_model_writes_no_answer(self):
        answer, store = self.answer('{"template":"field_lookup","bug_id":"7","field":"status"}')
        store.execute.assert_called_once_with({"template": "field_lookup", "bug_id": "7", "field": "status"}, QUESTION["scope"])
        self.assertEqual((answer["status"], answer["value"], answer["answer"]), ("OK", "NEW", "text"))

    def test_bare_numbers_become_strings_but_booleans_do_not(self):
        answer, store = self.answer('{"template":"field_lookup","bug_id":7,"field":"status"}')
        self.assertEqual(store.execute.call_args.args[0]["bug_id"], "7")
        answer, store = self.answer('{"template":"field_lookup","bug_id":true,"field":"status"}')
        store.execute.assert_not_called()
        self.assertEqual(answer["status"], "NO_INTENT")

    def test_anything_off_the_allowlist_never_reaches_the_database(self):
        for content in ("broken JSON", "[]", "null", '{"template":"raw_sql","sql":"DROP TABLE bugs"}',
                        '{"template":"field_lookup","bug_id":"7","field":"status; DROP TABLE bugs"}',
                        '{"template":"field_lookup","bug_id":"7 OR 1=1","field":"status"}',
                        '{"template":"field_lookup","bug_id":"7","field":"status","sql":"x"}',
                        '{"template":"abstain","reason":"because"}',
                        '{"template":"count_in_partition","field":"component","value":true,"partition":"dev"}'):
            answer, store = self.answer(content)
            store.execute.assert_not_called()
            self.assertEqual((answer["status"], answer["abstained"], answer["raw"]), ("NO_INTENT", False, content))

    def test_bad_parse_and_timeout_are_wrong_even_on_unanswerable_gold(self):
        gold = {"qid": "q-1", "family": "F6", "gold": {"type": "unanswerable"}}
        answer, _ = self.answer("broken JSON")
        self.assertEqual(scoring.score(gold, answer)["verdict"], scoring.INCORRECT)
        client = OllamaClient("m", post=Mock(side_effect=TimeoutError()))
        answer = m3_intent.answer_question(Mock(), QUESTION, client)
        self.assertEqual(answer["status"], gen.MODEL_ERROR)
        self.assertEqual(scoring.score(gold, answer)["verdict"], scoring.INCORRECT)

    def test_model_sees_only_the_question_and_gold_is_refused(self):
        post = Mock(return_value=chat_reply("{}"))
        m3_intent.answer_question(Mock(), QUESTION, OllamaClient("m", post=post))
        messages = post.call_args.args[1]["messages"]
        self.assertEqual(messages[1]["content"], QUESTION["question"])
        self.assertNotIn("Firefox bug 7", messages[0]["content"])
        with self.assertRaises(ValueError):
            m3_intent.answer_question(Mock(), {**QUESTION, "gold": {"value": "SECRET"}}, OllamaClient("m", post=post))

    def test_request_limit_stops_the_run(self):
        client = OllamaClient("m", max_requests=1, post=Mock(return_value=chat_reply("{}")))
        client.calls = 1
        with self.assertRaises(RequestLimit):
            m3_intent.answer_question(Mock(), QUESTION, client)

    def test_prompt_lists_every_allowed_template(self):
        for template in m3_sql.INTENTS:
            self.assertIn(template + ":", m3_intent.SYSTEM)
        for name in (*m3_sql.LOOKUP_COLUMNS, *m3_sql.FILTER_COLUMNS, *m3_sql.RELATIONS, *m3_sql.ABSTAIN_REASONS):
            self.assertIn(name, m3_intent.SYSTEM)


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        pins = fixture(cls.root)
        items, _ = p5.complete_candidates(cls.root, pins, per_family=5, f5_target=5)
        (cls.root / "bench").mkdir()
        p5.write_json(cls.root / "bench/candidates.json", items)
        p5.write_json(cls.root / "sources.json", pins)
        cls.items = [q for q in items if q["split"] == "dev"]
        cls.common = ["--root", str(cls.root), "--sources", "sources.json", "--run", "bench", "--unfrozen-dev-smoke"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_main(self, *args, post=truthful_parser):
        output = io.StringIO()
        with patch("bugzilla_qa.methods.local_model._post", side_effect=post) as mock, contextlib.redirect_stdout(output):
            code = phase06.main([*args, *self.common])
        return code, json.loads(output.getvalue()), mock

    def test_m3_llm_with_a_perfect_parser_matches_gold_on_computed_families(self):
        code, report, _ = self.run_main("m3-llm", "--output", "outputs/m3-llm", "--model", "fixture-model",
                                        "--max-requests", "100", post=truthful_parser)
        self.assertEqual((code, report["state"], report["model_calls"]), (0, "COMPLETE", len(self.items)))
        scores = [json.loads(x) for x in (Path(report["output"]) / "scores.jsonl").read_text().splitlines()]
        families = {q["qid"]: q["family"] for q in self.items}
        computed = [s for s in scores if families[s["qid"]] != "F5"]
        self.assertTrue(computed)
        self.assertEqual({s["verdict"] for s in computed}, {scoring.CORRECT})
        # Abstaining on an answerable F5 question counts as incorrect.
        self.assertEqual({s["verdict"] for s in scores if families[s["qid"]] == "F5"}, {scoring.INCORRECT})

    def test_m3_llm_with_a_useless_parser_scores_nothing(self):
        code, report, _ = self.run_main("m3-llm", "--output", "outputs/m3-bad", "--model", "fixture-model", "--max-requests", "100",
                                        post=lambda *a: chat_reply("not json"))
        scores = [json.loads(x) for x in (Path(report["output"]) / "scores.jsonl").read_text().splitlines()]
        self.assertNotIn(scoring.CORRECT, {s["verdict"] for s in scores})

    def test_request_cap_resume_and_dry_run(self):
        opts = ("m3-llm", "--model", "fixture-model", "--max-requests", "1")
        code, report, mock = self.run_main(*opts, "--dry-run")
        self.assertEqual((code, report["state"]), (0, "DRY_RUN"))
        mock.assert_not_called()
        code, report, mock = self.run_main(*opts)
        self.assertEqual((code, report["state"], report["answered"]), (0, "PARTIAL", 1))
        mock.assert_called_once()
        code, report, mock = self.run_main(*opts, "--resume")
        self.assertEqual((code, report["state"], report["answered"]), (0, "PARTIAL", 2))
        mock.assert_called_once()
