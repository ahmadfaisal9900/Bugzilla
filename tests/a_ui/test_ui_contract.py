"""Keeps the mock and the client honest against the real API contract.

Skipped when pydantic isn't installed (the [ui] extra alone doesn't include it).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pydantic")
contracts = pytest.importorskip("bugzilla_serving.contracts.api_models")
records = pytest.importorskip("bugzilla_serving.contracts.records")
from pydantic import TypeAdapter  # noqa: E402
from ui_mock_api import API_KEY, MockBackend  # noqa: E402

HEADERS = {"x-api-key": API_KEY}


def _get(backend, path):
    return backend.handle("GET", path, HEADERS, b"").body


def test_catalog_endpoints_match_contract():
    backend = MockBackend()
    TypeAdapter(list[contracts.Preset]).validate_python(_get(backend, "/v1/presets"))
    contracts.OptionsResponse.model_validate(_get(backend, "/v1/options"))
    contracts.QuotaResponse.model_validate(_get(backend, "/v1/quota"))
    TypeAdapter(list[str]).validate_python(_get(backend, "/v1/examples"))


def test_mock_presets_send_every_run_config_field_like_the_api():
    """The API dumps the whole RunConfig, nulls included; the UI must cope with those nulls."""
    fields = set(contracts.RunConfig.model_fields)
    for preset in _get(MockBackend(), "/v1/presets"):
        assert set(preset["config"]) == fields


@pytest.mark.parametrize("question", ["normal", "quota", "unknown", "broken"])
def test_stream_events_match_contract(question):
    body = json.dumps({"session_id": "s", "message": question}).encode()
    contracts.ChatRequest.model_validate_json(body)
    response = MockBackend().handle("POST", "/v1/chat/stream", HEADERS, body)
    adapter = TypeAdapter(records.SSEEvent)
    for chunk in response.body:
        name, data = (line.split(": ", 1)[1] for line in chunk.strip().split("\n"))
        adapter.validate_python({"event": name, "data": json.loads(data)})


def test_ask_response_matches_contract():
    body = json.dumps({"session_id": "s", "message": "normal"}).encode()
    response = MockBackend().handle("POST", "/v1/ask", HEADERS, body)
    contracts.AskResponse.model_validate(response.body)


def test_error_body_matches_contract():
    body = json.dumps({"session_id": "s", "message": "slow down"}).encode()
    response = MockBackend().handle("POST", "/v1/chat/stream", HEADERS, body)
    contracts.ErrorResponse.model_validate(response.body)
