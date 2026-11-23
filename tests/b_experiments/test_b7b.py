"""Offline v2 regression tests with tiny synthetic databases and providers."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
from langsmith import tracing_context

from bugzilla_qa.answering.contracts import ANSWER_SCHEMA, answer_payload, encode_payload
from bugzilla_qa.answering.graph import rule_route
from bugzilla_qa.answering.tools import TOOLS as OLD_TOOLS
from bugzilla_qa.answering_v2.graph import AnswerGraphV2, route_v2
from bugzilla_qa.answering_v2.tools import TOOLS, ToolsV2
from bugzilla_qa.llm.provider import InvalidJSONResponse, MockProvider
from bugzilla_serving.experiments.scorer_v2 import excluded, grade, normalize


def item(kind="integer", value=29, question="How many bugs?"):
    return dict(
        qid="q",
        family="F3",
        dataset="v3",
        split="dev",
        cluster_id="a",
        kind=kind,
        expected=value,
        question=question,
        scope={},
        acceptable_bug_ids=[],
    )


def prediction(value, answer_type="number", abstain=False):
    return dict(
        status="ok",
        system_id="S7",
        context_chunk_ids=[],
        answer=dict(
            answer=value,
            answer_type=answer_type,
            abstain=abstain,
            citations=[],
            bug_ids=[],
            rationale="",
        ),
    )


@pytest.mark.parametrize(
    "value,correct",
    [
        ([29], True),
        ([28], False),
        ([29, 30], False),
        (["29"], False),
        ([True], False),
        ("29 bugs", True),
        ("28 bugs", False),
        ("29 days", False),
    ],
)
def test_scalar_numeric_rules(value, correct):
    assert (grade(item(), prediction(value))["verdict"] == "CORRECT") == correct


def test_list_gold_and_abstention_unchanged():
    pred = prediction(["29"])
    assert normalize(item("id_set", ["29"]), pred) == (pred, [])
    assert normalize(item(), prediction(None, abstain=True))[1] == []
    assert grade(item(), prediction(None, abstain=True))["reason"] == "false_abstention"


@pytest.mark.parametrize(
    "value,correct",
    [("9316.65 hours", True), ("9318 hours", False), ("9316.65 days", False), ([9316.65], True)],
)
def test_explicit_hours_tolerance(value, correct):
    q = item("calendar_duration", 9316.653055555556, "How long in hours?")
    assert (grade(q, prediction(value, "hours"))["verdict"] == "CORRECT") == correct
    assert grade(q, prediction(9316.65, "number"))["verdict"] == "CORRECT"


def test_exclusion_policy_all_versions_and_no_false_single_bug_exclusion():
    assert excluded(dict(item(), qid="v3_32a15a37c79becf4fcfa7085"))
    q = dict(item(), scope=dict(original_scope=dict(partition="test")))
    assert excluded(q)
    assert not excluded(dict(q, family="F1"))


@pytest.fixture
def tools(tmp_path):
    config = dict(
        seed=317,
        source_config="source.json",
        history_checkpoint="history.json",
        duckdb_memory="64MB",
        context_tokens=3000,
        dossier_tokens=12000,
        tool_steps=4,
        prompt_version="answer-v1",
    )
    (tmp_path / "source.json").write_text('{"canonical_db":"unused"}')
    db = duckdb.connect()
    db.execute((Path(__file__).parents[1] / "fixtures/serving_bundle/canonical.sql").read_text())
    db.execute("DELETE FROM bug_links")
    db.execute(
        "INSERT INTO bug_links VALUES ('100000','100001','a','depends_on'),"
        "('100000','100002','b','blocks'),('100000','999999','c','depends_on')"
    )
    db.execute(
        "INSERT INTO source_records VALUES ('conflict','CONFLICT_VARIANT','{}','100003','metadata')"
    )
    db.execute("INSERT INTO bug_links VALUES ('100000','100003','d','depends_on')")
    ref = "a" * 64
    doc = dict(
        bug_id="100000",
        record_id=ref,
        chunk_id="C1:" + ref + ":0",
        text="Public reason.",
        visibility="public",
        kind="comment",
        source_char_start=0,
    )
    backend = SimpleNamespace(docs=[doc], selected="R7b")
    t = ToolsV2(config, tmp_path, backend)
    t._db = db
    yield t
    t.close()


def question(family="MH"):
    return dict(
        qid="q",
        dataset="v3",
        split="dev",
        family=family,
        freeze_id="fixture",
        question="Within the downloaded cohort, which bugs are blocking bug 100000?",
        scope={},
    )


def test_direction_cohort_and_conflicts(tools):
    q = question()
    result = tools.execute(
        "get_linked_bugs", dict(bug_id=100000, relation="blocks", direction="incoming"), q
    )
    assert [r["bug_id"] for r in result["targets"]] == ["100001"]
    assert result["targets"][0]["in_cohort"]
    assert set(result["excluded_outside_cohort"]) == {"999999", "100003"}
    assert {"status", "resolution", "component"} <= result["targets"][0].keys()
    outgoing = tools.get_linked_bugs(100000, "blocks", "outgoing", q)
    assert [r["bug_id"] for r in outgoing["targets"]] == ["100002"]
    all_targets = tools.get_linked_bugs(
        100000, "depends_on", "outgoing", dict(q, question="Links for bug 100000?")
    )
    assert any(not r["in_cohort"] for r in all_targets["targets"])


def test_comment_lookup_and_privacy(tools):
    q = question("F5")
    assert (
        tools.execute("get_comment", dict(bug_id=100000, comment_ref="a" * 64), q)["text"]
        == "Public reason."
    )
    with pytest.raises(ValueError):
        tools.get_comment(100001, "a" * 64)
    for visibility in ("private", None):
        tools.backend.docs[0]["visibility"] = visibility
        with pytest.raises(ValueError, match="private/unknown"):
            tools.get_comment(100000, "a" * 64)


def test_count_reuse_and_test_population_refused(tools):
    q = question("F3")
    assert tools.execute("count_bugs", dict(scope="cohort"), q)["count"] == 20
    with pytest.raises(ValueError, match="development"):
        tools.execute("count_bugs", dict(scope="cohort"), dict(q, scope=dict(partition="test")))
    with pytest.raises(ValueError):
        tools.execute("count_bugs", dict(scope="cohort"), dict(q, split="test"))


def test_schemas_and_unchanged_route_cache_payload():
    old = copy.deepcopy(OLD_TOOLS)
    assert TOOLS is not OLD_TOOLS
    assert OLD_TOOLS == old
    for text in (
        "What component is bug 100000?",
        "Find a report about tabs",
        "Why did bug 100000 change?",
    ):
        route, _ = rule_route(text)
        v2, _ = route_v2(text)
        assert v2 == ("S7v2" if route == "S7" else route)
        s = dict(question=text, scope={}, context="same", context_map={}, route=route)
        assert encode_payload(answer_payload(s)) == encode_payload(
            answer_payload(dict(s, route=v2))
        )
    assert route_v2("Which of those are still unresolved?")[0] == "S7v2"


def graph(tools, provider):
    return AnswerGraphV2(
        tools.config, provider, tools.backend, tools, "unchanged prompt", lambda s: None
    )


def test_one_repair_per_tool_call_and_accounting(tools):
    calls = []

    def response(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise InvalidJSONResponse("schema rejected")
        return dict(tool="get_bug_fields", args=dict(bug_id=100000, fields=["component"]))

    provider = MockProvider(response)
    with tracing_context(enabled=False):
        result = graph(tools, provider).invoke(
            dict(question(), question="Tell me details for bug 100000."), "S7v2", "fixture"
        )
    assert provider.calls == 2 and result["call_count"] == 2 and result["status"] == "ok"


def test_repair_exhaustion_and_provider_errors_never_retried(tools):
    for error, expected in ((InvalidJSONResponse("schema"), 3), (RuntimeError("429"), 1)):

        def fail(prompt):
            raise error

        provider = MockProvider(fail)
        tools.backend.retrieve = lambda *a, **k: (tools.backend.docs, False)
        with tracing_context(enabled=False):
            result = graph(tools, provider).invoke(
                dict(question(), question="Tell me details for bug 100000."), "S7v2", "fixture"
            )
        assert provider.calls == expected and result["status"] == "error"


def test_cited_comment_is_first_dossier_block(tools):
    other = dict(
        tools.backend.docs[0], record_id="b" * 64, chunk_id="other", text="Other", kind="metadata"
    )
    tools.backend.docs.insert(0, other)
    tools.backend.dossier = lambda q: tools.backend.docs
    q = dict(
        question("F5"), question="What reason is in cited comment " + "a" * 64 + " for bug 100000?"
    )
    with tracing_context(enabled=False):
        g = graph(tools, MockProvider(prediction("Public reason.", "string")["answer"]))
        retrieved = g.retrieve(
            dict(q, route="S5", tool_log=[], call_count=0, usage=[], cache_hit=False, errors=[])
        )
        packed = g.pack_context(dict(q, route="S5", retrieved=retrieved["retrieved"]))
    assert retrieved["retrieved"][0]["record_id"] == "a" * 64
    assert "Cited comment:" in packed["context"].split("Other")[0]


def test_reuse_existing_count_and_lifecycle():
    from bugzilla_qa.answering.tools import Tools

    assert ToolsV2.count is Tools.count
    assert ToolsV2.lifecycle is Tools.lifecycle


def test_tracking_versions_are_distinct_and_resumable(tmp_path):
    from bugzilla_serving.contracts.run_config import RunConfig
    from bugzilla_serving.tracking.client import TrackingClient, params_for

    client = TrackingClient((tmp_path / "mlflow").as_uri())
    params = params_for(RunConfig(system_id="S2"))
    tags = dict(
        source="backfill",
        eval_set="synthetic",
        datasets="v3",
        split="dev",
        scorer="synthetic",
        git_sha="fixture",
        system_id="S2",
    )

    def log(version):
        return client.log_run(
            "research-answer-eval",
            params,
            dict(tags, scorer_version=version, exclusions="f3_test_scope_v1"),
            {"answer.F3.n": 12, "answer.F3.score": 0, "answer.macro": 0, "answer.macro_excl_F5": 0},
            {},
        )

    old = log("1")
    new = log("2")
    assert old != new
    assert log("2") == new and len(client.runs("research-answer-eval")) == 2
    client.client.set_tag(old, "superseded_by", new)
    assert client.client.get_run(old).data.tags["superseded_by"] == new
    assert client.client.get_run(old).data.metrics["answer.F3.n"] == 12


def test_v2_job_checkpoint_resume_and_backfill_without_network(tools, tmp_path, monkeypatch):
    from bugzilla_serving.experiments import v2_jobs as jobs

    monkeypatch.setattr(jobs, "git_sha", lambda root: "fixture")
    monkeypatch.setattr(jobs, "ToolsV2", lambda *args: tools)
    q = dict(question(), question="How many bugs in the downloaded cohort?")
    i = dict(item(value=20), family="MH", freeze_id="fixture")
    provider = MockProvider(
        dict(
            calls=[dict(name="submit_answer", arguments_json=json.dumps(prediction(29)["answer"]))]
        )
    )
    tools.backend.base = SimpleNamespace()
    llm = dict(max_output_tokens=2048)
    monkeypatch.setattr("bugzilla_serving.engine._bundle", lambda p: {})
    monkeypatch.setattr(
        jobs,
        "context",
        lambda *args: ([i], {("v3", "q"): q}, tools.config, tools.backend, llm, "prompt", {}),
    )
    monkeypatch.setattr(jobs, "load_eval_set", lambda *args, **kwargs: ([i], {}))
    monkeypatch.setattr(
        "bugzilla_serving.experiments.preflight.usage",
        lambda *args: dict(tokens=180000, requests=900),
    )
    monkeypatch.setattr(
        "bugzilla_qa.llm.provider.create_provider", lambda *args, **kwargs: provider
    )
    result = jobs.execute(tmp_path, tmp_path, "S7v2", "synthetic", None, 25)
    assert result["state"] == "COMPLETE" and result["actual_api_calls"] == 0
    resumed = jobs.execute(tmp_path, tmp_path, "S7v2", "synthetic", None, 25)
    assert resumed["completed"] == 1 and provider.calls == 0
    plan = jobs.backfill(tmp_path, Path(result["ledger"]), "S7v2", "synthetic")
    assert plan["state"] == "DRY_RUN" and plan["metrics"]["answer.MH.score"] == 1
    assert plan["tags"]["iteration"] == "v2" and plan["tags"]["diagnosed_on"] == "pilot125"


def test_readonly_provider_reuses_exact_legacy_cache_key(tmp_path):
    import sqlite3

    from bugzilla_qa.answering.runner import cached_generation_key
    from bugzilla_serving.experiments.v2_jobs import CacheMiss, CacheOnlyProvider

    llm = dict(provider="groq", models=dict(generator=dict(id="synthetic")))
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE responses(key TEXT PRIMARY KEY,response TEXT,metadata TEXT)")
    provider = CacheOnlyProvider(db, llm)
    prompt = encode_payload(dict(question="same", declared_scope={}, evidence="", citation_map={}))
    key = cached_generation_key(llm, prompt, "prompt", ANSWER_SCHEMA, "answer-v1")
    expected = prediction(29)["answer"]
    db.execute("INSERT INTO responses VALUES (?,?,?)", [key, json.dumps(expected), "{}"])
    result = provider.generate_json(
        prompt, ANSWER_SCHEMA, system_prompt="prompt", prompt_version="answer-v1"
    )
    assert result["value"] == expected and result["state"] == "CACHE_HIT" and provider.calls == 0
    with pytest.raises(CacheMiss):
        provider.generate_json(
            prompt + " ", ANSWER_SCHEMA, system_prompt="prompt", prompt_version="answer-v1"
        )
    db.close()


def test_quota_pause_preserves_attempt_cost_before_resume(tools, tmp_path, monkeypatch):
    from bugzilla_serving.experiments import v2_jobs as jobs

    q = dict(question(), question="Tell me details for bug 100000.")
    i = dict(item(), family="MH", freeze_id="fixture")
    plan = dict(tool="search_text", args=dict(query="public details", k=1))
    first = MockProvider(plan, max_requests=1)
    second = MockProvider(
        lambda prompt: plan if "explicit_facts" in json.loads(prompt) else prediction(29)["answer"]
    )
    tools.backend.retrieve = lambda *a, **k: (tools.backend.docs, False)
    providers = iter([first, second])
    tools.backend.base = SimpleNamespace()
    monkeypatch.setattr("bugzilla_serving.engine._bundle", lambda p: {})
    monkeypatch.setattr(jobs, "git_sha", lambda root: "fixture")
    monkeypatch.setattr(jobs, "ToolsV2", lambda *args: tools)
    monkeypatch.setattr(
        jobs,
        "context",
        lambda *args: (
            [i],
            {("v3", "q"): q},
            tools.config,
            tools.backend,
            dict(max_output_tokens=2048),
            "prompt",
            {},
        ),
    )
    monkeypatch.setattr(jobs, "load_eval_set", lambda *args, **kwargs: ([i], {}))
    monkeypatch.setattr(
        "bugzilla_serving.experiments.preflight.usage",
        lambda *args: dict(tokens=180000, requests=900),
    )
    monkeypatch.setattr(
        "bugzilla_qa.llm.provider.create_provider", lambda *args, **kwargs: next(providers)
    )
    paused = jobs.execute(tmp_path, tmp_path, "S7v2", "synthetic", None, 1)
    assert paused["state"] == "PAUSED_QUOTA" and paused["completed"] == 0
    assert not Path(paused["ledger"]).exists()
    completed = jobs.execute(tmp_path, tmp_path, "S7v2", "synthetic", None, 25)
    assert completed["state"] == "COMPLETE" and completed["completed"] == 1
    plan = jobs.backfill(tmp_path, Path(completed["ledger"]), "S7v2", "synthetic")
    assert plan["metrics"]["cost.llm_calls"] == 3


def test_unit_must_match_counted_quantity_not_bug_mention():
    q = dict(item(value=1, question="How many REOPENED transitions for bug 100000?"), family="F2")
    pred = prediction("1 bug")
    assert normalize(q, pred) == (pred, [])
    assert grade(q, pred)["verdict"] == "INCORRECT"


@pytest.mark.parametrize("value", [9316.65, [9316.65]])
def test_question_stated_hours(value):
    q = item("calendar_duration", 9316.653055555556, "How many calendar hours elapsed?")
    p = prediction(value, "number")
    marked = grade(q, p)
    assert marked["verdict"] == "CORRECT"
    assert "question_stated_hours" in marked["normalization_rules"]
    assert p["answer"]["answer"] == value


@pytest.mark.parametrize(
    "question,value,unit",
    [
        ("How long elapsed?", 9316.65, "number"),
        ("How long in hours?", 9318, "number"),
        ("How long in hours?", [9318], "number"),
        ("How long in hours?", "9316.65 days", "number"),
        ("How long in hours?", 9316.653055555556 / 24, "days"),
    ],
)
def test_question_stated_hours_negative(question, value, unit):
    assert (
        grade(item("calendar_duration", 9316.653055555556, question), prediction(value, unit))[
            "verdict"
        ]
        != "CORRECT"
    )


def test_measured_usage_never_divides_by_unreported_calls():
    from bugzilla_serving.experiments.token_budget import measured_usage

    result = measured_usage(
        [
            dict(call_count=2, tokens=dict(input=100, output=20, usage_missing=False)),
            dict(call_count=7, tokens=dict(input=20, output=0, usage_missing=True)),
            dict(
                carried_forward=True,
                call_count=2,
                tokens=dict(input=200, output=20, usage_missing=False),
            ),
        ]
    )
    assert result["reported_calls"] == 2 and result["skipped_calls"] == 7
    assert result["mean_tokens"] == 60 and result["tokens_with_margin"] == 90
    assert measured_usage([])["tokens_with_margin"] == 3072


def test_measured_pacing_preserves_request_and_daily_gates():
    from bugzilla_serving.experiments.runner import PacedProvider

    provider = MockProvider({})
    paced = PacedProvider(provider, 8000, 2048, measured_tokens=100, daily_remaining=lambda: 50)
    with pytest.raises(RuntimeError, match="daily token budget"):
        paced.generate_json("small", {})
    assert provider.calls == 0 and paced.daily_exhausted
    paced = PacedProvider(provider, 8000, 2048, measured_tokens=100)
    with pytest.raises(ValueError, match="exceeds TPM"):
        paced.generate_json("x" * 30000, {})
    assert provider.calls == 0
    paced.generate_json("small", {})
    assert paced.reservations[0][1] == 0  # Synthetic calls consume no provider quota.


def test_composite_scope_is_rule_only_and_explicit(tmp_path):
    from bugzilla_serving.experiments.v2_jobs import changed_scope

    items = [
        dict(dataset="v3", qid="a", family="F2", question="How many calendar hours?"),
        dict(dataset="v3", qid="b", family="F1", question="What is the status of bug 12?"),
        dict(dataset="v3", qid="c", family="F4", question="Tell me about it"),
    ]
    full = changed_scope(tmp_path, items)
    priority = changed_scope(tmp_path, items, "priority")
    assert ("v3", "a") in full and ("v3", "a") in priority
    assert ("v3", "c") not in full
    assert ("v3", "b") in full and ("v3", "b") not in priority
    ordinary = dict(dataset="v3", qid="d", family="F4", question="What is the status of bug 12?")
    assert ("v3", "d") in changed_scope(tmp_path, [ordinary], "priority")


def test_composite_carries_source_answer_and_logs_both(tools, tmp_path, monkeypatch):
    from bugzilla_serving.experiments import v2_jobs as jobs

    monkeypatch.setattr(jobs, "git_sha", lambda root: "fixture")
    monkeypatch.setattr(jobs, "ToolsV2", lambda *args: tools)
    first = dict(item(value=20), freeze_id="fixture")
    carried_item = dict(first, qid="carry", family="F1", question="What is the status of bug 12?")
    old = dict(
        prediction(17),
        dataset="v3",
        qid="carry",
        split="dev",
        family="F1",
        system_id="S8",
        config_hash="old-config",
        source_run_id="run-old-S8",
        call_count=2,
        tokens=dict(input=100, output=20, usage_missing=False),
        context_chunk_ids=[],
        latency_ms=12,
    )
    tools.backend.base = SimpleNamespace()
    tools.backend.saved = {("v3", "carry"): old}
    provider = MockProvider(
        dict(
            calls=[dict(name="submit_answer", arguments_json=json.dumps(prediction(29)["answer"]))]
        )
    )
    monkeypatch.setattr("bugzilla_serving.engine._bundle", lambda p: {})
    monkeypatch.setattr(
        jobs,
        "context",
        lambda *args: (
            [first, carried_item],
            {("v3", "q"): dict(question(), question="How many bugs in the downloaded cohort?")},
            tools.config,
            tools.backend,
            dict(max_output_tokens=2048),
            "prompt",
            {},
        ),
    )
    monkeypatch.setattr(jobs, "load_eval_set", lambda *a, **k: ([first, carried_item], {}))
    monkeypatch.setattr(
        "bugzilla_serving.experiments.preflight.usage", lambda *a: dict(tokens=180000, requests=900)
    )
    monkeypatch.setattr("bugzilla_qa.llm.provider.create_provider", lambda *a, **k: provider)
    result = jobs.execute(tmp_path, tmp_path, "S8v2", "pilot122-v2", None, 25, "priority")
    rows = [json.loads(line) for line in Path(result["ledger"]).read_text().splitlines()]
    carry = next(r for r in rows if r["qid"] == "carry")
    assert result["completed"] == 2 and result["actual_api_calls"] == 0
    assert carry["carried_forward"] and carry["source_run_id"] == "run-old-S8"
    assert carry["answer"] == old["answer"] and carry["call_count"] == 0
    assert old["system_id"] == "S8" and old["call_count"] == 2
    plan = jobs.backfill(tmp_path, Path(result["ledger"]), "S8v2", "pilot122-v2")
    assert plan["tags"]["evaluation"] == "composite_changed_routes"
    assert plan["tags"]["carried_forward"] == "1" and plan["metrics"]["cost.llm_calls"] == 0


def test_preflight_uses_total_history_with_margin_without_changing_gate(tmp_path, monkeypatch):
    from bugzilla_serving.contracts.run_config import RunConfig
    from bugzilla_serving.experiments.preflight import estimate

    cfg = RunConfig(system_id="S7")
    history = [
        dict(
            params=dict(system_id="S7", model=cfg.model),
            metrics={
                "cost.usage_missing_n": 0,
                "cost.llm_calls": 10,
                "cost.tokens_in": 7000,
                "cost.tokens_out": 1000,
            },
        )
    ]
    monkeypatch.setattr(
        "bugzilla_serving.experiments.preflight.usage",
        lambda *a: dict(tokens=180000, requests=900, limits=dict(tpm=8000)),
    )
    # Config/prompts come from the repository; quota and history are synthetic.
    result = estimate(cfg, [item()], history=history)
    assert result["tokens_per_call"] == 1200
    assert result["request_gate_tokens"] > result["tokens_per_call"]
    assert result["token_estimate_source"] == "reported ledger mean +50%"
