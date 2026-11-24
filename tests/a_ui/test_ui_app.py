"""Whole-app checks with Streamlit's AppTest, with the HTTP client swapped for the mock."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bugzilla_serving.chat_ui.ui import data

APP = Path(__file__).resolve().parents[2] / "src" / "bugzilla_serving" / "chat_ui" / "app.py"


@pytest.fixture
def app(monkeypatch, client, backend):
    monkeypatch.setenv("API_URL", "http://mock")
    monkeypatch.setenv("SERVING_API_KEY", "dev-key")
    monkeypatch.setattr(data, "get_client", lambda: client)
    for cached in (data.get_catalog, data.api_ready, data.get_quota):
        cached.clear()
    return AppTest.from_file(str(APP), default_timeout=10)


def test_welcome_shows_modes_and_examples(app):
    app.run()
    assert not app.exception
    assert app.selectbox(key="mode").value == "recommended"
    first = app.button(key="example:0").label
    assert first == "**Lookup · Bug 1000001** Which component is bug 1000001 filed under?"
    assert len([b for b in app.button if b.key and b.key.startswith("example:")]) == 3
    labels = " ".join(b.label for b in app.button)
    assert "frozen evidence" not in labels and "UNKNOWN" not in labels
    # The lookup tile asks about a bug the API's examples name, not a made-up one.
    assert (
        app.button(key="task:Look up a bug").help == "Asks: What is the resolution of bug 1000003?"
    )
    assert not [b for b in app.sidebar.button if "?" in b.label]  # examples are not duplicated


def test_asking_shows_answer_and_feedback(app):
    app.run()
    app.chat_input[0].set_value("What component is bug 1000001 filed under?").run()
    assert not app.exception
    text = " ".join(m.value for m in app.markdown)
    assert "This is a demo answer" in text and "Bug 1000001" in text


def _ask(app, question):
    if not app.chat_input:
        app.run()
    app.chat_input[0].set_value(question).run()
    assert not app.exception
    return " ".join(m.value for m in app.markdown)


def test_abstention_shows_closest_sources(app):
    text = _ask(app, "something unknown")
    assert "Not enough evidence in the archive." in text and "Closest reports" in text


def test_degraded_shows_sources_without_answer(app):
    text = _ask(app, "quota check")
    assert any("quota is used up" in w.value for w in app.warning)
    assert "source-list" in text and "This is a demo answer" not in text


def test_settings_panel_opens_and_closes(app):
    app.run()
    assert not app.number_input  # closed by default: no settings drawn
    app.button(key="settings-button").click().run()
    assert app.number_input(key="setting:recommended:top_k").value == 5
    assert app.number_input(key="setting:recommended:top_k").label == "Top-k passages"
    app.button(key="settings-close").click().run()
    assert not app.number_input


def test_changed_setting_is_kept_after_closing_the_panel(app, backend):
    app.run()
    app.button(key="settings-button").click().run()
    app.number_input(key="setting:recommended:top_k").set_value(7).run()
    app.button(key="settings-close").click().run()
    assert any("Custom settings" in m.value for m in app.markdown)
    _ask(app, "Which component is bug 1000001 filed under?")
    assert backend.requests[-1]["overrides"] == {"top_k": 7}


def test_bad_advanced_setting_is_shown_next_to_the_field(app):
    app.run()
    app.button(key="settings-button").click().run()
    app.number_input(key="setting:recommended:top_k").set_value(40).run()
    assert any("Custom settings" in m.value for m in app.markdown)
    assert app.button(key="reset-settings")
    app.button(key="settings-close").click().run()
    _ask(app, "Which component is bug 1000001 filed under?")
    # The panel reopens by itself and shows the API's message under the field.
    assert app.number_input(key="setting:recommended:top_k")
    assert any("top_k" in e.value for e in app.error)


def test_rate_limit_disables_input(app):
    app.run()
    app.chat_input[0].set_value("slow down").run()
    assert app.chat_input[0].disabled


def test_api_down_pauses_questions(app, backend):
    backend.ready = False
    app.run()
    assert app.error and app.chat_input[0].disabled
