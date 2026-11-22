"""Bounded offline checks for deployment boundaries and CI configuration."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_readonly_pages_do_not_import_torch_engine_or_experiments(tmp_path):
    script = """
import sys
import requests
import httpx
from streamlit.testing.v1 import AppTest

def denied(*args, **kwargs):
    raise AssertionError("No external services in readonly test")
requests.sessions.Session.request = denied
httpx.HTTPTransport.handle_request = denied
app = AppTest.from_file("src/bugzilla_serving/dashboard/app.py").run()
for page in ("overview", "answer_eval", "retrieval_eval", "cost_latency",
             "error_analysis", "experiment_lab", "compare_runs", "production"):
    if page != "overview":
        app.switch_page(f"pages/{page}.py").run()
    assert not app.exception, app.exception
assert "torch" not in sys.modules
assert "bugzilla_serving.engine" not in sys.modules
assert not any(m.startswith("bugzilla_serving.experiments") for m in sys.modules)
"""
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(word in k for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "MLFLOW"))
    }
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        DASHBOARD_LAB_ENABLED="false",
        LANGSMITH_SOURCE="fixture",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        MLFLOW_TRACKING_URI=(tmp_path / "empty").as_uri(),
        HF_HUB_OFFLINE="1",
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr


def test_dockerignore_excludes_sensitive_build_inputs():
    # Docker uses last-match-wins semantics. All exclusions here are literal
    # directories or these two globs; reject negations to prevent re-inclusion.
    lines = [s.strip() for s in (ROOT / ".dockerignore").read_text().splitlines()]
    rules = [s for s in lines if s and not s.startswith("#")]
    assert not any(s.startswith("!") for s in rules), "Review re-inclusion before building"
    for rule in (
        "outputs/",
        "Dataset/",
        "logs/",
        "serving_bundle/",
        ".dvc/",
        ".env*",
        "mlruns/",
        "**/__pycache__/",
    ):
        assert rule in rules, f"{rule} would enter the build context"


def test_ci_boundaries_and_action_pins():
    import re

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert {"lint", "contracts", "test", "secrets", "docker"} <= jobs.keys()
    for job in jobs.values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[a-f0-9]{40}", step["uses"])
    assert jobs["docker"]["needs"] == "lint"
    assert "DASHBOARD_LAB_ENABLED" in workflow["env"]
