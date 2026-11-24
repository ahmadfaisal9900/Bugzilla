"""Chat wording routes, independent of providers and research gold."""

import pytest
import yaml

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.routing import explicit_ids, route_serving

CASES = yaml.safe_load((ROOT / "tests/demo/demo_cases.yaml").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_routes(case):
    if "1000000" in explicit_ids(case["question"]):
        actual = "outside_archive"  # Membership guard precedes every answering mode.
    elif case["mode"] == "recommended":
        actual = route_serving(case["question"])[0]
    else:
        actual = {"fast": "S1", "deep": "S5"}[case["mode"]]
    assert actual == case["expected_route"]


def test_blocking_direction_is_explicit():
    from bugzilla_qa.answering_v2.json_tools import preparse
    from bugzilla_serving.routing import tool_question

    for question, direction in [
        ("What blocks bug 1771951?", "incoming"),
        ("Which bugs block bug 1771951?", "incoming"),
        ("Which bugs does bug 1771951 block?", "outgoing"),
    ]:
        plan = preparse({"question": tool_question(question)})["plan"]
        assert plan["tool"] == "get_linked_bugs" and plan["args"]["direction"] == direction
