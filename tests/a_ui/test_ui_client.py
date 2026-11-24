"""API client: parsing, errors and the SSE stream, against the in-memory mock."""

from __future__ import annotations

import pytest

from bugzilla_serving.chat_ui.api import ApiError, parse_sse
from bugzilla_serving.chat_ui.api.models import bug_url


def test_catalog_has_presets_settings_and_examples(client):
    catalog = client.catalog()
    assert catalog.default_preset.slug == "recommended"
    assert catalog.model_labels["openai/gpt-oss-20b"] == "GPT OSS 20B"
    names = {s.name for s in catalog.settings_for(catalog.preset("fast"))}
    assert "top_k" in names and "system_id" not in names and "s7_max_tool_steps" not in names
    assert len(catalog.examples) == 4


def test_spec_endpoints_presets_examples_and_ask(client, backend):
    presets = client.presets()
    assert [p.display_label for p in presets][0] == "Recommended"  # champion shown as Recommended
    assert "hyperparameters" in client.options()
    assert len(client.examples()) == 4
    request_id, record = client.ask(
        client.chat_body("s1", "Which component is bug 1000001 filed under?", None, None)
    )
    assert request_id in backend.feedback and record.text.startswith("This is a demo answer")


def test_wrong_key_is_an_api_error(make_client):
    bad = make_client(api_key="nope")
    with pytest.raises(ApiError) as error:
        bad.catalog()
    assert error.value.status == 401
    assert bad.is_ready() is False


def test_rate_limit_carries_retry_after(client):
    with pytest.raises(ApiError) as error:
        list(client.stream(client.chat_body("s1", "please slow down", "recommended", None)))
    assert (error.value.code, error.value.retry_after) == ("rate_limited", 30)


def test_invalid_setting_names_the_field(client):
    with pytest.raises(ApiError) as error:
        list(client.stream(client.chat_body("s1", "hi", "recommended", {"top_k": 40})))
    assert error.value.field == "top_k"


def test_parse_sse_handles_comments_and_multiline_data():
    lines = [
        ": keepalive",
        "event: status",
        'data: {"stage":',
        'data: "retrieving"}',
        "",
        "event: done",
        'data: {"request_id": "r1"}',
    ]
    events = list(parse_sse(lines))
    assert [(e.name, e.data) for e in events] == [
        ("status", {"stage": "retrieving"}),
        ("done", {"request_id": "r1"}),
    ]


@pytest.mark.parametrize(
    "bug_id, supplied, expected",
    [
        ("123", "", "https://bugzilla.mozilla.org/show_bug.cgi?id=123"),
        (
            "123",
            "https://bugzilla.mozilla.org/show_bug.cgi?id=123",
            "https://bugzilla.mozilla.org/show_bug.cgi?id=123",
        ),
        ("123", "javascript:alert(1)", "https://bugzilla.mozilla.org/show_bug.cgi?id=123"),
        ("abc", "https://evil.example/show_bug.cgi?id=1", None),
    ],
)
def test_only_bugzilla_links_are_rendered(bug_id, supplied, expected):
    assert bug_url(bug_id, supplied) == expected
