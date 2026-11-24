"""Chat use case: one question in, one finished Turn out."""

from __future__ import annotations

import pytest

from bugzilla_serving.chat_ui.api import ApiError
from bugzilla_serving.chat_ui.chat import (
    ask,
    changed_settings,
    cited_bugs,
    preset_values,
    progress_label,
)


def _ask(client, question, overrides=None):
    catalog = client.catalog()
    progress = []
    turn = ask(
        client,
        session_id="s1",
        question=question,
        preset=catalog.default_preset,
        overrides=overrides or {},
        model_label="GPT OSS 20B",
        on_progress=progress.append,
    )
    return turn, progress


def test_answer_turn_has_text_sources_and_request_id(client, backend):
    turn, progress = _ask(client, "What component is bug 1000001 filed under?")
    assert "Found 3 sources…" in progress
    assert turn.record.text.startswith("This is a demo answer")
    assert [s.bug_id for s in turn.record.sources()][:2] == ["1000001", "1000003"]  # cited first
    assert turn.request_id in backend.feedback
    assert backend.requests[-1]["overrides"] is None  # no overrides -> preset sent as is


def test_sources_only_and_abstain_states(client):
    degraded, _ = _ask(client, "quota test")
    unsure, _ = _ask(client, "unknown thing")
    assert degraded.record.sources_only and not unsure.record.sources_only
    assert unsure.record.abstain and unsure.record.text == ""


def test_error_event_raises(client):
    with pytest.raises(ApiError) as error:
        _ask(client, "broken please")
    assert error.value.code == "internal"


def test_feedback_round_trip(client, backend):
    turn, _ = _ask(client, "any question")
    client.feedback(turn.request_id, 1, "great")
    assert backend.feedback[turn.request_id] == {
        "request_id": turn.request_id,
        "score": 1,
        "comment": "great",
    }


def test_only_changed_settings_are_sent(client):
    catalog = client.catalog()
    preset = catalog.preset("fast")
    baseline = preset_values(preset, catalog.settings_for(preset))
    assert changed_settings(baseline, {**baseline, "top_k": 8}) == {"top_k": 8}
    assert changed_settings(baseline, dict(baseline)) == {}


def test_unset_preset_values_fall_back_to_the_spec_default(client):
    catalog = client.catalog()
    preset = catalog.preset("recommended")  # S8: s7_max_tool_steps and rrf_k are null
    baseline = preset_values(preset, catalog.settings_for(preset))
    assert baseline["s7_max_tool_steps"] == 4
    assert baseline["rrf_k"] == 60
    assert None not in baseline.values()


def test_progress_labels_are_friendly():
    assert progress_label("retrieving", "Searching public evidence") == "Searching…"
    assert progress_label("retrieved", "Found 5 sources") == "Found 5 sources…"
    assert progress_label("generating", "Preparing answer") == "Writing answer…"


def test_cited_bugs_merge_turns_newest_first(client):
    first, _ = _ask(client, "What component is bug 1000001 filed under?")
    second, _ = _ask(client, "Which bugs does bug 1000002 depend on?")
    bugs = cited_bugs([first, second])
    assert {b.bug_id for b in bugs} == {"1000001", "1000002", "1000003"}
    top = next(b for b in bugs if b.bug_id == "1000001")
    assert top.times_cited == 2 and top.last_turn == 1 and len(top.snippets) == 1
    assert top.url == "https://bugzilla.mozilla.org/show_bug.cgi?id=1000001"
