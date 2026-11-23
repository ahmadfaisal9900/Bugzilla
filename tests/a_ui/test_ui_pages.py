"""Secondary pages rendered on their own, with a session that already holds answers."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"

SCRIPT = """
import sys
sys.path[:0] = [{src!r}, {here!r}]
from bugzilla_serving.chat_ui.api import AnswerRecord
from bugzilla_serving.chat_ui.chat import Turn
from bugzilla_serving.chat_ui.pages import {page}
from bugzilla_serving.chat_ui.state import get_state
from ui_mock_api import answer_record

state = get_state()
if not state.turns:
    for question in ("Which component is bug 1000001 filed under?", "quota check"):
        record = AnswerRecord.from_json(answer_record(question))
        state.turns.append(Turn(question, "Recommended", "GPT OSS 20B", record))
{page}.render()
"""


def page_app(page: str) -> AppTest:
    return AppTest.from_string(
        SCRIPT.format(src=str(SRC), here=str(HERE), page=page), default_timeout=10
    )


@pytest.mark.parametrize("page", ["history", "cited_bugs", "about"])
def test_page_renders_with_answers(page):
    app = page_app(page).run()
    assert not app.exception
    assert len([m for m in app.markdown if "page-title" in m.value]) == 1  # one heading per page


def test_history_lists_each_question_once():
    app = page_app("history").run()
    assert [e.label for e in app.expander] == [
        "quota check",
        "Which component is bug 1000001 filed under?",
    ]


def test_cited_bugs_search_filters_the_table():
    app = page_app("cited_bugs").run()
    assert len(app.dataframe[0].value) == 3
    app.text_input(key="cited-search").set_value("duplicate").run()
    assert list(app.dataframe[0].value["Bug"]) == [
        "https://bugzilla.mozilla.org/show_bug.cgi?id=1000003"
    ]
