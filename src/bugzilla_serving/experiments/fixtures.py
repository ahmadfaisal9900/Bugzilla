"""Explicit local mock demo using the existing Phase 0 synthetic model fixtures."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT


def build_synthetic_bundle(directory):
    """Materialize the tiny fixture, including indexes absent from a Git checkout."""
    path = ROOT / "scripts/build_fixture_bundle.py"
    spec = importlib.util.spec_from_file_location("lab_fixture_builder", path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder.build(Path(directory) / "serving_bundle")


def build_fixture_runner(cfg, provider):
    from bugzilla_qa.llm.provider import MockProvider
    from bugzilla_qa.retrieval_v3.registry import Engine
    from bugzilla_qa.retrieval_v3.transforms import QueryTransforms
    from bugzilla_serving.engine import build_runner

    if not isinstance(provider, MockProvider):
        raise ValueError("Synthetic retrieval requires MockProvider")
    bundle = Path(os.environ.get("BUNDLE_DIR", "serving_bundle"))
    if not json.loads((bundle / "manifest.json").read_text()).get("synthetic"):
        raise ValueError("Fixture option requires a synthetic bundle")
    engine = build_runner(cfg, provider)
    try:
        if not engine.manifest.get("synthetic"):
            raise ValueError("Fixture option requires a synthetic bundle")
        path = ROOT / "tests/fixtures/serving_models.py"
        spec = importlib.util.spec_from_file_location("b2_fixture_models", path)
        fake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fake)
        backend = engine.backend
        backend.engine = Engine(
            backend.docs,
            backend.directory / "lexical.sqlite",
            fake.Dense(backend.docs),
            fake.Cross(),
            json.loads((backend.root / "graph.json").read_text()),
            backend.rc,
            QueryTransforms(provider),
        )
        return engine
    except Exception:
        engine.close()
        raise
