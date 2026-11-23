"""Chat UI fixtures: an in-memory mock API wired into the real client (no network).

Every test in this folder gets the `ui` marker."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for ui_mock_api

from ui_mock_api import API_KEY, MockBackend  # noqa: E402

from bugzilla_serving.chat_ui.api import ApiClient  # noqa: E402
from bugzilla_serving.chat_ui.config import Settings  # noqa: E402


def transport_for(backend: MockBackend) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {k.lower(): v for k, v in request.headers.items()}
        result = backend.handle(request.method, request.url.path, headers, request.content)
        if result.stream:
            return httpx.Response(
                result.status, headers=result.headers, content="".join(result.body).encode()
            )
        return httpx.Response(result.status, headers=result.headers, json=result.body)

    return httpx.MockTransport(handler)


@pytest.fixture
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def make_client(backend: MockBackend):
    def make(api_key: str = API_KEY) -> ApiClient:
        return ApiClient(
            Settings(api_url="http://mock", api_key=api_key), transport=transport_for(backend)
        )

    return make


@pytest.fixture
def client(make_client) -> ApiClient:
    return make_client()


def pytest_collection_modifyitems(items):
    here = Path(__file__).resolve().parent
    for item in items:
        if Path(str(item.fspath)).resolve().parent == here:
            item.add_marker(pytest.mark.ui)
