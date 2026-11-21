"""All contract checks use synthetic files and deny HTTP."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Contract tests must never make network requests")

    import httpx
    import requests

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    # FastAPI TestClient uses ASGI transport; only actual HTTP transport is blocked.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(key, "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")


@pytest.fixture
def fixture_bundle(tmp_path, monkeypatch):
    builder = module(ROOT / "scripts/build_fixture_bundle.py", "p0_builder")
    bundle = builder.build(tmp_path / "serving_bundle")
    builder.samples(tmp_path)
    monkeypatch.setenv("BUNDLE_DIR", str(bundle))
    from bugzilla_qa.answering.backend import Backend
    from bugzilla_qa.retrieval_v3.registry import Engine
    from bugzilla_qa.retrieval_v3.transforms import QueryTransforms

    fake = module(ROOT / "tests/fixtures/serving_models.py", "p0_fake_models")

    def no_download_engine(backend):
        if backend.engine is None:
            backend.engine = Engine(
                backend.docs, backend.directory / "lexical.sqlite", fake.Dense(backend.docs),
                fake.Cross(), json.loads((bundle / "graph.json").read_text()),
                backend.rc, QueryTransforms(backend.provider),
            )
        return backend.engine

    monkeypatch.setattr(Backend, "_engine", no_download_engine)
    return bundle
