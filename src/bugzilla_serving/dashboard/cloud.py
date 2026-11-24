"""Read-only saved results, remote pack first and a sanitized dev snapshot last."""

import os
from pathlib import Path

import streamlit as st

SECRETS = (
    "MLFLOW_TRACKING_URI",
    "MLFLOW_TRACKING_USERNAME",
    "MLFLOW_TRACKING_PASSWORD",
    "DASHBOARD_PASSWORD",
    "DAGSHUB_REPO_URL",
    "LANGSMITH_PROJECT_URL",
)
SNAPSHOT = Path(__file__).parent / "snapshot"


def settings():
    for key in SECRETS:
        try:
            value = st.secrets.get(key)
        except (FileNotFoundError, KeyError):
            value = None
        if value is not None:
            os.environ[key] = str(value)
    os.environ["DASHBOARD_LAB_ENABLED"] = "false"
    os.environ["DASHBOARD_ADVANCED"] = "false"
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "3")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")


def load_cloud_results():
    from bugzilla_serving.dashboard.results_source import _cached_pack, remote_folder

    uri = os.environ.get("MLFLOW_TRACKING_URI")
    folder = None
    if uri:
        try:
            folder = remote_folder(uri)
        except Exception:
            # Connection/auth errors must not leak SDK errors or credential-bearing URLs.
            st.caption("Remote results unavailable; showing the saved development snapshot.")
    source = "MLflow results-pack" if folder else "Saved development snapshot"
    folder = Path(folder) if folder else SNAPSHOT
    stamps = tuple((p.name, p.stat().st_mtime_ns) for p in sorted(folder.glob("*.csv")))
    return _cached_pack(str(folder), stamps), source


def main():
    settings()
    st.set_page_config(page_title="Bugzilla · Development results", layout="wide")
    from bugzilla_serving.dashboard.app import authenticated

    if not authenticated():
        st.stop()
    from bugzilla_serving.dashboard.results_app import render

    data, source = load_cloud_results()
    st.caption(source + " · read-only · development results")
    render(data[0])
