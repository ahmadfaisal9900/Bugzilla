"""Tiny fixture and fake-model checks. No model, external service or real dataset."""
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

from bugzilla_qa.methods import generation as gen
from bugzilla_qa.methods.local_model import ModelError, OllamaClient, RequestLimit
from bugzilla_qa.evaluation import phase06, scoring
from bugzilla_qa.benchmark import phase05 as p5
from test_phase05 import fixture


QUESTION = {"qid": "q-1", "question": "What component is recorded for Firefox bug 7?", "scope": {"corpus": "fixture"}}
DOCUMENT = {"doc_id": "d-7", "record_id": "snapshot:7", "bug_id": "7", "url": "https://example.test/7",
            "text": "Firefox bug 7. component Shopping.", "rank": 1, "score": 2.0}


def response(value="Shopping", evidence=(), raw=None):
    content = raw if raw is not None else json.dumps({"answer": str(value), "abstained": False,
                                                      "value": value, "evidence": list(evidence)})
    return {"done": True, "model": "fixture-model", "message": {"content": content},
            "prompt_eval_count": 11, "eval_count": 9, "done_reason": "stop"}


class AdapterTests(unittest.TestCase):
    def test_payload_and_request_budget(self):
        post = Mock(return_value=response())
        client = OllamaClient("fixture-model", max_requests=1, post=post)
        result = client.chat([{"role": "user", "content": "question"}])
        url, payload, timeout = post.call_args.args
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"], {"temperature": 0, "seed": 317, "num_predict": 512})
        self.assertNotIn("tools", payload)
        self.assertEqual((result["prompt_tokens"], result["output_tokens"]), (11, 9))
        with self.assertRaises(RequestLimit):
            client.chat([])
        self.assertEqual(post.call_count, 1)

    def test_external_endpoint_and_missing_model_are_refused(self):
        for endpoint in ("https://api.example.test", "http://127.0.0.1.evil.test", "http://localhost/api",
                         "http://user@localhost", "http://localhost?redirect=evil"):
            with self.assertRaises(ValueError):
                OllamaClient("fixture-model", endpoint)
        for model in (None, "", " "):
            with self.assertRaises(ValueError):
                OllamaClient(model)

    def test_failures_count_as_requests_and_incomplete_replies_fail(self):
        client = OllamaClient("fixture-model", max_requests=1, post=Mock(side_effect=TimeoutError()))
        with self.assertRaises(ModelError):
            client.chat([])
        with self.assertRaises(RequestLimit):
            client.chat([])
        for reply in ({"done": False}, {"done": True}, [], {"done": True, "message": None}):
            with self.assertRaises(ModelError):
                OllamaClient("fixture-model", post=Mock(return_value=reply)).chat([])


class GenerationTests(unittest.TestCase):
    def test_m0_cannot_receive_sources_or_gold(self):
        post = Mock(return_value=response())
        answer = gen.answer_question(QUESTION, OllamaClient("fixture-model", post=post))
        prompt = post.call_args.args[1]["messages"]
        user = json.loads(prompt[1]["content"])
        self.assertEqual(set(user), {"question", "scope"})
        self.assertEqual(answer["trace"]["supplied_doc_ids"], [])
        with self.assertRaises(ValueError):
            gen.answer_question({**QUESTION, "gold": {"value": "SECRET"}}, None)
        with self.assertRaises(ValueError):
            gen.answer_question(QUESTION, None, index=Mock())

    def test_m1_supplies_retrieved_text_and_checks_citation_provenance(self):
        cited = {k: DOCUMENT[k] for k in ("bug_id", "record_id", "url")}
        post = Mock(return_value=response(evidence=[cited]))
        index = Mock(); index.search.return_value = [DOCUMENT]
        answer = gen.answer_question(QUESTION, OllamaClient("fixture-model", post=post), "M1", index)
        user = json.loads(post.call_args.args[1]["messages"][1]["content"])
        self.assertEqual(user["source_documents"][0]["text"], DOCUMENT["text"])
        index.search.assert_called_once_with(QUESTION["question"], 5)
        self.assertEqual(answer["trace"]["citations_not_in_supplied_evidence"], [])
        self.assertGreaterEqual(answer["trace"]["latency_seconds"], answer["trace"]["generation_seconds"])
        self.assertGreaterEqual(answer["trace"]["latency_seconds"], answer["trace"]["retrieval_seconds"])
        post.return_value = response(evidence=[{**cited, "record_id": "invented"}])
        answer = gen.answer_question(QUESTION, OllamaClient("fixture-model", post=post), "M1", index)
        self.assertEqual(answer["trace"]["citations_not_in_supplied_evidence"][0]["record_id"], "invented")

    def test_evidence_budget_includes_escaped_text_and_metadata(self):
        hits = [{**DOCUMENT, "text": '\\"\n' * 1000}, {**DOCUMENT, "doc_id": "second"}]
        selected = gen.bounded_evidence(hits, 300)
        self.assertTrue(selected)
        self.assertLessEqual(len(gen._json(selected)), 300)
        self.assertEqual(gen.bounded_evidence(hits, 2), [])

    def test_missing_retrieval_is_not_filled_from_gold(self):
        index = Mock(); index.search.return_value = []
        post = Mock(return_value=response(raw='{"answer":"Missing evidence","abstained":true,"value":null,"evidence":[]}'))
        answer = gen.answer_question(QUESTION, OllamaClient("fixture-model", post=post), "M1", index)
        self.assertTrue(answer["abstained"])
        self.assertEqual(json.loads(post.call_args.args[1]["messages"][1]["content"])["source_documents"], [])

    def test_timeout_and_broken_json_are_failures_not_correct_abstentions(self):
        gold = {"qid": QUESTION["qid"], "family": "F6", "gold": {"type": "unanswerable"}}
        for post, status in ((Mock(side_effect=TimeoutError()), "MODEL_ERROR"),
                             (Mock(return_value=response(raw="broken JSON")), "PARSE_ERROR")):
            answer = gen.answer_question(QUESTION, OllamaClient("fixture-model", post=post))
            self.assertEqual(answer["status"], status)
            self.assertFalse(answer["abstained"])
            self.assertEqual(scoring.score(gold, answer)["verdict"], scoring.INCORRECT)


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
        cls.common = ["--root", str(cls.root), "--sources", "sources.json", "--run", "bench",
                      "--unfrozen-dev-smoke", "--model", "fixture-model"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_dry_run_never_calls_model(self):
        with patch("bugzilla_qa.methods.local_model._post") as post, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(phase06.main(["m0", *self.common, "--dry-run"]), 0)
            post.assert_not_called()

    def test_request_cap_resume_and_provisional_label(self):
        output = "outputs/generation-test"
        args = ["m0", *self.common, "--output", output, "--limit", "2", "--max-requests", "1"]
        with patch("bugzilla_qa.methods.local_model._post", return_value=response()) as post, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(phase06.main(args), 0)
            self.assertEqual(post.call_count, 1)
            out = next((self.root / output).glob("m0-dev-smoke-*"))
            first = p5.read(out / "summary.json")
            self.assertEqual((first["state"], first["answered"]), ("PARTIAL", 1))
            self.assertTrue(first["provisional_answers"])
            self.assertEqual(first["benchmark_state"], phase06.SMOKE)
            self.assertEqual(phase06.main([*args, "--resume"]), 0)
            self.assertEqual(post.call_count, 2)
            self.assertEqual(p5.read(out / "summary.json")["answered"], 2)
            self.assertEqual(phase06.main([*args, "--resume"]), 0)
            self.assertEqual(post.call_count, 2)
            # Model settings change the checkpoint identity; old predictions cannot be reused.
            self.assertEqual(phase06.main([*args, "--model", "different-model"]), 0)
            self.assertEqual(len(list((self.root / output).glob("m0-dev-smoke-*"))), 2)

    def test_m1_builds_source_index_and_saves_retrieval_trace(self):
        with patch("bugzilla_qa.methods.local_model._post", return_value=response()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(phase06.main(["m1", *self.common, "--output", "outputs/m1-test", "--limit", "1"]), 0)
        out = next((self.root / "outputs/m1-test").glob("m1-dev-smoke-*"))
        answer = json.loads((out / "predictions.jsonl").read_text())
        self.assertEqual(answer["method"], "M1")
        self.assertTrue(answer["trace"]["retrieved"])
        self.assertLessEqual(answer["trace"]["evidence_chars"], 12000)


if __name__ == "__main__":
    unittest.main()
