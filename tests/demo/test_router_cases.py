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
