"""Read-only cloud fallback and sharing command; no external requests."""

import csv
import os
import subprocess

from streamlit.testing.v1 import AppTest

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard import cloud
from bugzilla_serving.dashboard.results_source import HEADERS


def test_cloud_snapshot_headers_and_render(monkeypatch):
    for key in cloud.SECRETS:
        monkeypatch.delenv(key, raising=False)
    for path in cloud.SNAPSHOT.glob("*.csv"):
        with path.open() as stream:
            assert set(csv.DictReader(stream).fieldnames) == HEADERS[path.name]
    app = AppTest.from_file(str(ROOT / "dashboard/streamlit_app.py"), default_timeout=15).run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Results", "Compare", "How it works & links"]
    assert os.environ["DASHBOARD_LAB_ENABLED"] == "false"
    assert os.environ["DASHBOARD_ADVANCED"] == "false"


def test_cloud_remote_preferred_and_unavailable(monkeypatch):
    import streamlit as st

    from bugzilla_serving.dashboard import results_source as source

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "https://example.invalid/mlflow")
    calls = []
    monkeypatch.setattr(
        source, "remote_folder", lambda uri: calls.append(uri) or str(cloud.SNAPSHOT)
    )
    _, label = cloud.load_cloud_results()
    assert calls and label == "MLflow results-pack"

    def unavailable(uri):
        raise RuntimeError("never show private transport messages")

    monkeypatch.setattr(source, "remote_folder", unavailable)
    monkeypatch.setattr(st, "caption", lambda text: calls.append(text))
    _, label = cloud.load_cloud_results()
    assert label == "Saved development snapshot"
    assert "private" not in calls[-1]


def test_cloud_secrets(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(st, "secrets", {"DASHBOARD_PASSWORD": "synthetic-cloud-password"})
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    cloud.settings()
    assert os.environ["DASHBOARD_PASSWORD"] == "synthetic-cloud-password"
    monkeypatch.delenv("DASHBOARD_PASSWORD")


def test_share_chat_only(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands"
    for name in ("curl", "cloudflared"):
        path = bin_dir / name
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SHARE_LOG"\n')
        path.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/app/share_demo.sh")],
        env={**os.environ, "PATH": str(bin_dir) + ":" + os.environ["PATH"], "SHARE_LOG": str(log)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == 3
    assert "8000/v1/health" in calls[0] and "8501/_stcore/health" in calls[1]
    assert calls[2] == "tunnel --url http://localhost:8501"
