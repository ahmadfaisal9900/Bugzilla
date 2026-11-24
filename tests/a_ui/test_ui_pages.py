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


def test_history_lists_each_question_once_newest_first():
    app = page_app("history").run()
    questions = [e.label for e in app.expander]
    assert len(questions) == 2
    assert "quota check" in questions[0]
    assert "Which component is bug 1000001 filed under?" in questions[1]
    assert all(not e.proto.expanded for e in app.expander)


def test_history_search_matches_answers_and_handles_no_results():
    app = page_app("history").run()
    app.text_input(key="history-search").set_value("demo answer").run()
    assert len(app.expander) == 1
    assert "1000001" in app.expander[0].label
    app.text_input(key="history-search").set_value("no matching question").run()
    assert not app.expander
    assert any("No questions match" in message.value for message in app.info)


def _rows(app):
    return [b.key for b in app.button if b.key and b.key.startswith("bug-row-")]


def test_cited_bugs_search_filters_the_list():
    app = page_app("cited_bugs").run()
    assert len(_rows(app)) == 3
    app.text_input(key="cited-search").set_value("duplicate").run()
    assert _rows(app) == ["bug-row-1000003"]


def test_selecting_a_cited_bug_opens_its_details():
    app = page_app("cited_bugs").run()
    app.button(key="bug-row-1000003").click().run()
    assert not app.exception
    assert any("What the archive says" in m.value for m in app.markdown)
