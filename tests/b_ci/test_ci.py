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


def test_inherited_provider_environment_does_not_change_fixture_tests():
    env = os.environ.copy()
    env.update(
        GROQ_API_KEY="synthetic-ambient-groq-key",
        LLM_API_KEY="synthetic-ambient-gemini-key",
        GEMINI_MODEL="gemini-2.0-flash",
    )
    targets = [
        "tests/test_groq_provider.py::GroqTests::test_secret_prompt_refused_without_calls",
        "tests/test_llm_provider.py::ProviderTests::test_daily_cap_uses_pacific_date_and_stops_before_call",
        "tests/test_llm_provider.py::ProviderTests::test_http_status_reports_sanitized_provider_message",
        "tests/test_v3_generation.py::GenerationTests::test_generation_resume_validation_privacy_and_freeze",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_external_http_is_refused_before_transport():
    import httpx
    import pytest
    import requests

    with pytest.raises(AssertionError, match="Offline tests refuse"):
        requests.get("https://example.invalid")
    with pytest.raises(AssertionError, match="Offline tests refuse"):
        httpx.get("https://example.invalid", trust_env=False)


def test_fixture_jobs_work_without_local_outputs_or_ignored_indexes(tmp_path):
    import shutil

    clean = tmp_path / "clean source"
    clean.mkdir()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for name in filter(None, tracked):
        path = Path(name)
        if path.parts[0] not in {"src", "tests", "scripts", "configs", "prompts"} and name not in {
            "pyproject.toml",
            "conftest.py",
        }:
            continue
        source = ROOT / path
        if source.is_file():
            target = clean / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    assert not (clean / "outputs").exists()
    assert not (clean / "tests/fixtures/serving_bundle/indexes").exists()
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(clean / "src"),
        # Share read-only commit provenance, not ignored workspace contents.
        GIT_DIR=subprocess.check_output(
            ["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT, text=True
        ).strip(),
        GIT_WORK_TREE=str(clean),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase05_assisted_review.py",
            "tests/b_dashboard/test_dashboard.py::test_lab_mock_completion_and_secret_scan",
        ],
        cwd=clean,
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
