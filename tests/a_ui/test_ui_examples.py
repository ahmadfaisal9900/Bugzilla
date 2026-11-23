"""Benchmark-style examples from the API become plain questions with a kind and bug number."""

from __future__ import annotations

import pytest

from bugzilla_serving.chat_ui.examples import starters, task_questions, tidy

# Shapes seen in the serving bundle's dev questions, with made-up bug numbers.
FIELD_A = (
    "Using the specified frozen evidence, what component is recorded for Firefox bug 1111111? "
    "The source snapshot date is UNKNOWN."
)
FIELD_B = (
    "In the broad metadata archive for Firefox bug 2222222 (snapshot date unknown), "
    "what is its recorded status?"
)
RELATION = (
    "Which target bug IDs are explicitly recorded for relation duplicate_of from Firefox bug "
    "3333333 in the archive? Historical validity is unknown."
)
COUNT = (
    "Using the specified frozen evidence, how many distinct Firefox bug IDs have "
    "component=Search in the dev partition? Corpus: eligible broad-metadata frozen sample."
)
HOURS = (
    "How many engineer work hours did Firefox bug 4444444 require, using only its recorded "
    "product, component, status, resolution and filing time?"
)


@pytest.mark.parametrize(
    ("text", "question", "tag"),
    [
        (FIELD_A, "What component is bug 1111111 filed under?", "Lookup · Bug 1111111"),
        (FIELD_B, "What is the status of bug 2222222?", "Lookup · Bug 2222222"),
        (RELATION, "Which bug is bug 3333333 a duplicate of?", "Relationships · Bug 3333333"),
        (COUNT, "How many bugs in the sample are filed under Search?", "Count"),
        (
            "Which bugs does bug 5 depend on?",
            "Which bugs does bug 5 depend on?",
            "Relationships · Bug 5",
        ),
    ],
)
def test_tidy_rewrites_known_shapes(text, question, tag):
    example = tidy(text)
    assert example.question == question
    assert example.tag == tag


def test_shapes_without_a_plain_phrasing_are_dropped():
    assert tidy(HOURS) is None


def test_starters_pick_one_of_each_kind_first():
    shown = starters([FIELD_A, FIELD_B, HOURS, RELATION, COUNT])
    assert [e.kind for e in shown] == ["Lookup", "Relationships", "Count"]


def test_task_questions_use_the_next_example_of_each_kind():
    questions = task_questions([FIELD_A, FIELD_B, RELATION])
    assert questions["Lookup"] == "What is the status of bug 2222222?"
    assert questions["Relationships"] == "Which bug is bug 3333333 a duplicate of?"
    assert "Count" not in questions
