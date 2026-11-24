"""Serving-only grouped counts and the ranking-question rule."""

import duckdb
import pytest

from bugzilla_qa.answering.tools import TOOLS
from bugzilla_serving.serving_tools import (
    SERVING_TOOLS,
    ServingTools,
    is_ranking_question,
)


@pytest.fixture
def tools():
    db = duckdb.connect()
    db.execute(
        "CREATE TABLE bugs(bug_id VARCHAR, product VARCHAR, component VARCHAR, "
        "snapshot_status VARCHAR, snapshot_resolution VARCHAR)"
    )
    rows = [("1", "Firefox", "Address Bar", "RESOLVED", "FIXED")] * 1
    rows += [(str(i), "Firefox", "Address Bar", "NEW", "") for i in range(2, 5)]
    rows += [(str(i), "Firefox", "Tabbed Browser", "RESOLVED", "FIXED") for i in range(5, 7)]
    rows += [("7", "Firefox", "Downloads", "NEW", "")]
    db.executemany("INSERT INTO bugs VALUES (?,?,?,?,?)", rows)
    serving = ServingTools.__new__(ServingTools)
    serving._db = db
    return serving


def test_count_by_ranks_groups(tools):
    result = tools.execute("count_bugs_by", {"field": "component"}, {"scope": {}})
    assert [g["value"] for g in result["groups"]] == ["Address Bar", "Tabbed Browser", "Downloads"]
    assert [g["count"] for g in result["groups"]] == [4, 2, 1]
    assert (result["groups_total"], result["bugs_counted"]) == (3, 7)
    assert result["summary"] == "Address Bar has the most bugs: 4 of 7, out of 3 component values."


def test_count_by_fewest_with_filter_keeps_runners_up(tools):
    args = {"field": "component", "order": "fewest", "status": "NEW", "limit": 1}
    result = tools.execute("count_bugs_by", args, {"scope": {}})
    assert result["groups"] == [
        {"rank": 1, "value": "Downloads", "count": 1},
        {"rank": 2, "value": "Address Bar", "count": 3},
    ]
    assert result["summary"].startswith("Downloads has the fewest bugs")


def test_count_by_rejects_unknown_field(tools):
    with pytest.raises(Exception):
        tools.execute("count_bugs_by", {"field": "summary"}, {"scope": {}})


def test_tool_list_extends_research_list():
    assert [t["name"] for t in SERVING_TOOLS[:-2]] == [t["name"] for t in TOOLS[:-1]]
    assert SERVING_TOOLS[-1]["name"] == "submit_answer"


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Which component has the most bugs in the sample", True),
        ("Top 5 components by bug count", True),
        ("Which status has the fewest bugs?", True),
        ("Show a breakdown of bugs per resolution", True),
        ("Why do address bar suggestions flicker?", False),
        ("What is the most common crash?", False),
    ],
)
def test_ranking_questions(question, expected):
    assert is_ranking_question(question) is expected
