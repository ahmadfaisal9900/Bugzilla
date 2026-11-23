"""Tiny offline fixtures for JSON tools, resume and blind external grading."""

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_b7b as support
from jsonschema import ValidationError, validate
from langsmith import tracing_context

from bugzilla_qa.answering.contracts import check_answer
from bugzilla_qa.answering_v2 import json_tools
from bugzilla_qa.evaluation import systems as legacy_scorer
from bugzilla_qa.llm.provider import InvalidJSONResponse
from bugzilla_serving.experiments import f5_packet
from bugzilla_serving.experiments.preflight import usage
from bugzilla_serving.experiments.v2_resume import seed_rows, selection
from bugzilla_serving.tracking.backfill import sha
from bugzilla_serving.tracking.f5_gold import load_verdicts

tools = pytest.fixture(support.tools.__wrapped__)


def test_parser_all_modes_and_strict_schema():
    cases = [
        (
            "How many bugs have component=Firefox View in the dev partition, denominator 592?",
            "count_bugs",
            "count",
        ),
        (
            "Use the dev partition of 882 distinct bugs. How many have resolution FIXED?",
            "count_bugs",
            "count",
        ),
        ("How many calendar hours to first FIXED for bug 100000?", "get_lifecycle", "hours"),
        ("How many transitions into REOPENED for bug 100000?", "get_lifecycle", "reopened"),
        ("Which bugs are blocking bug 100000 within the cohort?", "get_linked_bugs", "id_set"),
        (
            "Bug 100000 depends on which bugs, and which of those are FIXED?",
            "get_linked_bugs",
            "depends_fixed",
        ),
        ("Which see also targets from bug 100000?", "get_linked_bugs", "id_set"),
    ]
    for text, tool, mode in cases:
        p = json_tools.preparse(dict(question=text))
        assert p["complete"] and p["plan"]["tool"] == tool and p["facts"]["mode"] == mode
        validate(p["plan"], json_tools.PLAN_SCHEMA)
    refused = json_tools.preparse(dict(question="How many bugs in the test partition?"))
    assert refused["facts"]["refused_population"] and refused["plan"] is None
    invalid = dict(tool="count_bugs", args=dict(scope="cohort", sql="DELETE"))
    with pytest.raises(ValidationError):
        validate(invalid, json_tools.PLAN_SCHEMA)


@pytest.mark.parametrize(
    "mode,result,kind",
    [
        ("count", {"count": 29}, int),
        ("hours", {"first_fixed_hours": 3.5}, float),
        ("reopened", {"reopened_count": 2}, int),
        ("id_set", {"targets": []}, list),
        (
            "depends_fixed",
            {"targets": [dict(bug_id="3", status="RESOLVED", resolution="FIXED")]},
            str,
        ),
    ],
)
def test_deterministic_shapes_and_citations(mode, result, kind):
    result["evidence_ids"] = ["public-id"]
    p = dict(plan={}, facts=dict(mode=mode))
    answer = json_tools.deterministic(p, result)
    assert type(answer["answer"]) is kind
    assert answer["citations"] == ["public-id"]
    check_answer(answer, ["public-id"])
    if mode == "depends_fixed":
        assert json.loads(answer["answer"]) == dict(depends_on=["3"], resolved_fixed=["3"])
    assert json_tools.deterministic(p, dict(known=False))["abstain"]


def test_parser_needs_no_provider_and_refuses_private_comment(tools):
    class Forbidden:
        calls = 0

        def generate_tools(self, *a, **k):
            raise AssertionError("Native tools forbidden")

        def generate_json(self, *a, **k):
            raise AssertionError("Fully parsed link query must be deterministic")

    with tracing_context(enabled=False):
        result = support.graph(tools, Forbidden()).invoke(support.question(), "S7v2", "fixture")
    assert result["call_count"] == 0 and result["status"] == "ok"
    assert result["tool_log"][0]["plan_source"] == "parser"
    tools.backend.docs[0]["visibility"] = "private"
    with pytest.raises(ValueError, match="private"):
        tools.get_comment(100000, "a" * 64)


@pytest.mark.parametrize("invalid", [0, 1, 2])
def test_llm_repair_and_best_guess_fallback(tools, invalid):
    state = dict(
        support.question(),
        question="What component was recorded as of yesterday for bug 100000?",
        errors=[],
        tool_log=[],
    )
    calls = []

    def call(prompt, schema, purpose):
        assert schema is json_tools.PLAN_SCHEMA
        calls.append(purpose)
        if len(calls) <= invalid:
            raise InvalidJSONResponse("invalid plan")
        return dict(tool="get_bug_fields", args=dict(bug_id=100000, fields=["component"]))

    result, _ = json_tools.answer(state, tools, call, tools.backend, tools.config)
    assert len(calls) == min(invalid + 1, 2)
    assert state["tool_log"][0]["plan_source"] == ["llm", "repair", "fallback"][invalid]
    assert result["abstain"]  # Unknown historical snapshot stays unknown.


def test_retrieval_fallback_is_bounded_and_plain(tools):
    state = dict(support.question(), question="Explain this archive", errors=[], tool_log=[])
    methods, calls = [], []
    tools.backend.retrieve = lambda *a, **k: (methods.append(a[1]) or tools.backend.docs, False)

    def call(prompt, schema, purpose):
        calls.append(purpose)
        if schema is json_tools.PLAN_SCHEMA:
            raise InvalidJSONResponse("bad")
        return support.prediction("Public reason.", "string")["answer"]

    result, _ = json_tools.answer(state, tools, call, tools.backend, tools.config)
    assert len(calls) == 3 and methods == ["R1"]
    assert state["tool_log"][0]["name"] == "text_retrieval_fallback"
    assert result["answer"] == "Public reason."

    # An LLM can supply a relation not recognized by the parser; the link answer
    # is still built in code, with no second model request for the ID list.
    state = dict(
        support.question(), question="Which bugs does bug 100000 block?", errors=[], tool_log=[]
    )
    plans = []

    def linked_plan(prompt, schema, purpose):
        plans.append(purpose)
        assert schema is json_tools.PLAN_SCHEMA
        return dict(
            tool="get_linked_bugs",
            args=dict(bug_id=100000, relation="blocks", direction="outgoing"),
        )

    result, _ = json_tools.answer(state, tools, linked_plan, tools.backend, tools.config)
    assert len(plans) == 1 and result["answer"] == ["100002"]


def test_budget_error_usage_and_measured_unknown(tmp_path, monkeypatch):
    from bugzilla_serving.contracts.run_config import RunConfig

    monkeypatch.setattr(
        "bugzilla_serving.experiments.token_budget.measured_parents",
        lambda r: {"S7": dict(reported_calls=2, tokens_with_margin=1500)},
    )
    now = dt.datetime(2026, 11, 23, 5, tzinfo=dt.timezone.utc)
    base = dict(
        provider="groq", model=RunConfig().model, purpose="structured-tools-v2", ts=now.isoformat()
    )
    rows = []
    for n, status, tokens in [
        (1, "ERROR", (100, 10)),
        (2, "ERROR", (None, None)),
        (3, "SUCCESS", (900, 90)),
    ]:
        rows.extend(
            [
                dict(base, prompt_hash=str(n), status="REQUEST_STARTED"),
                dict(
                    base,
                    prompt_hash=str(n),
                    status=status,
                    input_tokens=tokens[0],
                    output_tokens=tokens[1],
                ),
            ]
        )
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    actual = usage(RunConfig(), dict(ledger="ledger.jsonl"), tmp_path, now)
    assert actual["reported_tokens"] == 1100
    assert actual["unknown_token_reserve"] == 825
    assert actual["used_tokens"] == 1925 and actual["tokens"] == 178075


def test_resume_marks_errors_and_preserves_f5_fingerprint(tmp_path):
    source = tmp_path / "old/S8v2.jsonl"
    source.parent.mkdir()
    rows = [
        dict(
            support.prediction("reason", "string"),
            dataset="v3",
            qid="f5",
            family="F5",
            split="dev",
            system_id="S8v2",
            config_hash="old",
            errors=[],
            carried_forward=False,
        ),
        dict(
            support.prediction(1),
            dataset="v3",
            qid="bad",
            family="F2",
            split="dev",
            system_id="S8v2",
            config_hash="old",
            errors=["repair"],
            carried_forward=False,
        ),
    ]
    source.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (source.parent / "manifest.json").write_text(
        json.dumps(dict(system="S8v2", sha256={source.name: sha(source)}))
    )
    old_hash = sha(source)
    items = [
        dict(dataset="v3", qid=q, family=f) for q, f in [("bad", "F2"), ("f5", "F5"), ("mh", "MH")]
    ]
    ordered, keys, keep, info = selection(items, {("v3", "bad"), ("v3", "mh")}, source)
    assert ordered[0]["family"] == "MH" and keep.keys() == {("v3", "f5")}
    assert info["superseded"][0]["status"] == "superseded" and ("v3", "bad") in keys
    path = tmp_path / "new.jsonl"
    seed_rows(path, items, keep, "new", "S8v2", source)
    row = json.loads(path.read_text())
    assert row["answer_source_config_hash"] == "old" and row["call_count"] == 0
    assert sha(source) == old_hash
    from bugzilla_serving.experiments.v2_jobs import grading_rows
    from bugzilla_serving.tracking.f5_gold import fingerprint

    q = dict(support.item(), qid="f5", family="F5", expected="Frozen claim")
    assert fingerprint(grading_rows([q], [rows[0]])[0]) == fingerprint(grading_rows([q], [row])[0])


@pytest.fixture
def packet_fixture(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr("bugzilla_serving.engine._bundle", lambda *a: {})
    (root / "source.json").write_text("{}")
    (root / "configs").mkdir()
    (root / "configs/retrieval_v3.yaml").write_text("{}")
    (root / "configs/display_catalog.yaml").write_text(
        'families:\n  F5: {name: "Reasons", short: "Old judge"}\n'
    )
    items, docs, new = [], [], []
    for n in range(6):
        ref = "a" * 63 + str(n)
        q = f"What reason is in cited comment {ref} for bug {100000 + n}?"
        items.append(
            dict(
                dataset="phase05",
                qid=f"q{n}",
                family="F5",
                split="dev",
                question=q,
                expected="Frozen claim",
            )
        )
        docs.append(
            dict(
                bug_id=str(100000 + n),
                record_id=ref,
                chunk_id=f"C1:{ref}:0",
                text="Public comment",
                visibility="public",
                kind="comment",
            )
        )
        new.append(
            dict(
                support.prediction("Candidate", "string"),
                qid=f"q{n}",
                dataset="phase05",
                family="F5",
                split="dev",
                config_hash="new",
                system_id="S8v2",
                carried_forward=False,
            )
        )
    reviews, old = [], {}
    for system in [f"S{i}" for i in range(9)]:
        old[system] = {}
        for i in items:
            old[system][i["qid"]] = dict(
                support.prediction(
                    None if system == "S0" else "Candidate", "string", system == "S0"
                ),
                system_id=system,
                config_hash="old",
            )
            reviews.append(
                dict(
                    i,
                    system_id=system,
                    review_id=legacy_scorer.digest(
                        [
                            legacy_scorer.VERSION,
                            i,
                            system,
                            "old",
                            old[system][i["qid"]]["answer"],
                            [],
                        ]
                    )[:24],
                    reference_answer="Frozen claim",
                    model_answer="Candidate",
                    answer_verdict="",
                )
            )
    ledger = root / "run/S8v2.jsonl"
    ledger.parent.mkdir()
    ledger.write_text("".join(json.dumps(r) + "\n" for r in new))
    (ledger.parent / "manifest.json").write_text(
        json.dumps(dict(system="S8v2", sha256={ledger.name: sha(ledger)}))
    )
    monkeypatch.setattr(f5_packet, "load_eval_set", lambda *a, **k: (items, {}))
    monkeypatch.setattr(
        f5_packet,
        "context",
        lambda *a: (
            items,
            {},
            dict(source_config="source.json"),
            SimpleNamespace(docs=docs),
            {},
            "",
            {},
        ),
    )
    monkeypatch.setattr(f5_packet, "review_rows", lambda *a, **k: reviews)
    monkeypatch.setattr(f5_packet, "discover_ledgers", lambda *a: {"phase05": "unused"})
    monkeypatch.setattr(f5_packet, "load_dev_items", lambda *a: (items, {}))
    monkeypatch.setattr(f5_packet, "select_predictions", lambda *a: (old, {}, {}))
    folder = root / "packet"
    return root, ledger, folder, reviews, items, new, docs


def test_packet_is_blind_stable_public_and_imports_one_judge(packet_fixture):
    root, ledger, folder, reviews, items, new, _ = packet_fixture
    f5_packet.export(root, root, ledger, folder)
    first = (folder / "packet.jsonl").read_bytes()
    f5_packet.export(root, root, ledger, folder)
    assert (folder / "packet.jsonl").read_bytes() == first
    packet = [json.loads(x) for x in first.splitlines()]
    assert len(packet) == 60 and all(
        set(p) == {"item_id", "question", "reference", "cited_comment", "candidate_answer"}
        for p in packet
    )
    assert sum(p["candidate_answer"] == "[declined]" for p in packet) == 6
    assert (folder / "packet.md").read_text().startswith(f5_packet.RUBRIC)
    assert (folder / "packet_key.jsonl").stat().st_mode & 0o777 == 0o600
    judgments = root / "judgments.jsonl"
    judgments.write_text(
        "".join(
            json.dumps(
                dict(item_id=p["item_id"], verdict="correct", reason="Matches the reference.")
            )
            + "\n"
            for p in packet
        )
    )
    result = f5_packet.import_verdicts(judgments, "fixture-judge", folder, root=root)
    assert (
        result["count"] == 60
        and "fixture-judge" in (root / "configs/display_catalog.yaml").read_text()
    )
    assert len(load_verdicts(reviews, Path(result["output"]))) == 54
    assert len(load_verdicts(f5_packet.grading_rows(items, new), Path(result["output"]))) == 6
    records = [json.loads(x) for x in Path(result["output"]).read_text().splitlines()]
    records[0]["judge_model"] = "another-judge"
    with pytest.raises(ValueError, match="Mixed judge"):
        f5_packet.validate_external(records)
    judgments.write_text("\n".join(judgments.read_text().splitlines()[:-1]))
    with pytest.raises(ValueError, match="60 items"):
        f5_packet.import_verdicts(judgments, "fixture-judge", folder, root=root)


def test_packet_private_comment_and_tampered_key_refused(packet_fixture):
    root, ledger, folder, _, _, _, docs = packet_fixture
    docs[0]["visibility"] = "unknown"
    with pytest.raises(ValueError, match="private/unknown"):
        f5_packet.export(root, root, ledger, folder)
    docs[0]["visibility"] = "public"
    f5_packet.export(root, root, ledger, folder)
    with (folder / "packet_key.jsonl").open("a") as f:
        f.write("{}\n")
    with pytest.raises(ValueError, match="checksum"):
        f5_packet.verify_packet(folder)
