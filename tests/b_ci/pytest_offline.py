"""Suite-wide offline boundaries, including legacy unittest fixtures.

Loaded before collection by pyproject's explicit pytest plugin. Production
credentials/model overrides must never replace temporary synthetic .env values.
"""

import os

import pytest

MODEL_PREFIXES = ("GROQ_", "GEMINI_", "LANGSMITH_", "LANGCHAIN_", "MLFLOW_")
CREDENTIAL_WORDS = ("KEY", "TOKEN", "PASSWORD", "SECRET")


def clear_external_environment():
    for name in list(os.environ):
        # Preserve the explicitly selected local tracking store/fixture mode.
        if name in {"MLFLOW_TRACKING_URI", "LANGSMITH_SOURCE"}:
            continue
        if name.startswith(MODEL_PREFIXES) or (
            name.startswith("LLM_") and any(word in name for word in CREDENTIAL_WORDS)
        ):
            os.environ.pop(name, None)


def pytest_configure(config):
    # Process-local only: the invoking shell and its credentials are unchanged.
    clear_external_environment()
    os.environ.update(
        LANGSMITH_SOURCE="fixture",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    uri = os.environ.get("MLFLOW_TRACKING_URI", "")
    if uri and not uri.startswith("file:"):
        os.environ.pop("MLFLOW_TRACKING_URI", None)


@pytest.fixture(autouse=True)
def deny_external_http(monkeypatch):
    import httpx
    import requests

    def denied(*args, **kwargs):
        raise AssertionError("Offline tests refuse external HTTP; use a fixture client")

    async def async_denied(*args, **kwargs):
        denied()

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_denied)
