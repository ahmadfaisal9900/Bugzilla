"""Tiny offline checks; no real ledgers needed by CI."""

import hashlib
import json
from pathlib import Path

import pytest

from bugzilla_serving.experiments.failure_audit import (
    numeric_candidate,
    primary_cause,
    record_ids,
    table,
)

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_prompts_schemas_and_cache_keys_byte_identical():
    # Pin all existing research modules, not just a projection of their behavior.
    # This covers graph prompts/payloads, tool schemas, provider cache identities,
    # retrieval identities, and every S0-S8 implementation at B7 entry.
    pins = json.loads((ROOT / "tests/fixtures/b7_legacy_bytes.json").read_text())
    for path, expected in pins.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path


def item(kind="integer", expected=12, family="F3"):
    return dict(
        kind=kind,
        expected=expected,
        family=family,
        scope={},
        question="How many bugs?" if kind == "integer" else "How long, in hours?",
    )


@pytest.mark.parametrize(
    "value,expected_cause",
    [([12], "SCORER"), ([13], "SCOPE"), ([12, 13], "SCOPE"), ([True], "SCOPE")],
)
def test_singleton_diagnosis_never_fixes_wrong_count(value, expected_cause):
    pred = dict(answer=dict(answer=value, abstain=False, answer_type="number"), status="ok")
    assert primary_cause(item(), pred, False, False)[0] == expected_cause


def test_units_and_hours_diagnostic_only():
    q = item("calendar_duration", 24, "F2")
    assert numeric_candidate(q, dict(answer="1 day", answer_type="string"))[0] == 24
    assert numeric_candidate(q, dict(answer="24 hours"))[0] == 24
    assert numeric_candidate(q, dict(answer=[24], answer_type="number"))[0] == 24
    assert numeric_candidate(q, dict(answer="24 engineer hours"))[0] is None
    assert numeric_candidate(q, dict(answer=float("nan")))[0] is None


def test_test_population_conflict_preserves_existing_correctness():
    q = item()
    q["scope"] = dict(original_scope=dict(partition="test"))
    pred = dict(answer=dict(answer=[12], abstain=False))
    assert primary_cause(q, pred, False, False)[0] == "GOLD"
    assert primary_cause(q, pred, True, False)[0] == ""


def test_record_identity_not_chunk_or_content_hash():
    assert record_ids(["C1:abc:0", "C1:abc:1", "C1:def:0"]) == {"abc", "def"}
    assert record_ids([]) == set()


def test_tool_direction_and_evidence_priorities():
    q = item(family="MH")
    p = dict(
        answer=dict(answer=None, abstain=True),
        status="ok",
        tools=[dict(name="get_links", arguments=dict(link_type="blocks"), result=dict(targets=[]))],
    )
    assert primary_cause(q, p, False, False)[0] == "SCOPE"
    p["tools"] = [dict(result=dict(known=False))]
    assert primary_cause(q, p, False, False)[0] == "TOOL"
    p["tools"] = []
    assert primary_cause(q, p, False, False)[0] == "RETRIEVAL"
    assert primary_cause(q, p, False, True)[0] == "ABSTAIN"
    p["answer"] = dict(answer=99, abstain=False)
    assert primary_cause(q, p, False, True)[0] == "REASONING"


def test_table_includes_every_cause_family_and_system():
    result = table([dict(cause="SCORER", family="F3", system="S7")])
    assert "| SCORER | F3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |" in result
    assert "| GOLD | F5 |" in result
