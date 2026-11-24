"""Suite-wide offline boundaries, including legacy unittest fixtures.

Loaded before collection by pyproject's explicit pytest plugin. Production
credentials/model overrides must never replace temporary synthetic .env values.
"""

import os
import sys
from pathlib import Path

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


def fixture_env_reader(reader, root):
    """Ignore the owner's checkout .env while preserving temporary fixture files."""

    def read(path):
        if Path(path).resolve() == (root / ".env").resolve():
            return {}
        return reader(path)

    return read


@pytest.fixture(autouse=True)
def deny_external_http(monkeypatch):
    import httpx
    import requests

    from bugzilla_qa.llm import provider

    previous = os.environ.copy()
    original = provider.env_values
    safe = fixture_env_reader(original, Path(__file__).resolve().parents[2])
    # Patch already imported aliases as well as imports performed during a test.
    for name, module in list(sys.modules.items()):
        if name.startswith(("bugzilla_qa", "bugzilla_serving")) and (
            getattr(module, "env_values", None) is original
        ):
            monkeypatch.setattr(module, "env_values", safe)

    def denied(*args, **kwargs):
        raise AssertionError("Offline tests refuse external HTTP; use a fixture client")

    async def async_denied(*args, **kwargs):
        denied()

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_denied)
    yield
    # App startup sets environment defaults without pytest's monkeypatch helper.
    # Restore those too, so subsequent provider tests keep their own fixture keys.
    os.environ.clear()
    os.environ.update(previous)
