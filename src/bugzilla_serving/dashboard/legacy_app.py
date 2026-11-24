"""Run: streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502."""

import hashlib
import hmac
import os
from pathlib import Path

import streamlit as st

from bugzilla_serving.dashboard.profiling import page


def authenticated():
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password:
        return True
    expected = hashlib.sha256(password.encode()).hexdigest()
    if st.session_state.get("auth_digest") == expected:
        return True
    st.title("Bugzilla dev dashboard")

    def login():
        supplied = st.session_state.pop("login_password", "")
        st.session_state["login_failed"] = not hmac.compare_digest(supplied, password)
        if not st.session_state["login_failed"]:
            st.session_state["auth_digest"] = expected

    st.text_input("Dashboard password", type="password", key="login_password")
    st.button("Sign in", on_click=login)
    if st.session_state.get("login_failed"):
        st.error("Incorrect password.")
    return False


@page
def main():
    st.set_page_config(page_title="Bugzilla · Dev dashboard", layout="wide")
    if not authenticated():
        st.stop()
    import datetime as dt
    from zoneinfo import ZoneInfo

    from bugzilla_serving.dashboard.data import langsmith_source as ls
    from bugzilla_serving.dashboard.data import mlflow_source as mf
    from bugzilla_serving.dashboard.data.common import tracking_location
    from bugzilla_serving.dashboard.data.mlflow_source import uri
    from bugzilla_serving.dashboard.data.snapshot import build_snapshot, load_snapshot, stale
    from bugzilla_serving.dashboard.views import enabled

    st.title("Bugzilla · Dev dashboard")
    st.sidebar.toggle("Show technical IDs", value=False, key="technical_ids")
    if st.sidebar.button("Refresh data"):
        with st.spinner("Refreshing dashboard data…"):
            build_snapshot(uri())
            load_snapshot.clear()
            mf._lazy_artifact.clear()
            ls.refresh()
            from bugzilla_serving.dashboard import lab

            lab.publication_preview.clear()
    data = load_snapshot(uri())
    stamp = dt.datetime.fromisoformat(data["meta"]["built_at"].replace("Z", "+00:00")).astimezone(
        ZoneInfo(os.environ.get("TZ", "America/Winnipeg"))
    )
    text = stamp.strftime("%d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    st.sidebar.caption("Data as of " + text)
    if stale(data["meta"], float(os.environ.get("DASHBOARD_SNAPSHOT_MAX_AGE_MIN", "30"))):
        st.sidebar.caption("Data from " + text + " · Refresh data")
    pages = [
        ("Overview", "overview"),
        ("Answer evaluation", "answer_eval"),
        ("Retrieval evaluation", "retrieval_eval"),
        ("Cost & latency", "cost_latency"),
        ("Error analysis", "error_analysis"),
        ("Experiment Lab", "experiment_lab"),
        ("Compare runs", "compare_runs"),
        ("Presets", "presets_page"),
        ("Production", "production"),
    ]
    navigation = [
        st.Page(
            Path(__file__).resolve().parent / "pages" / f"{module}.py",
            title=title,
            default=module == "overview",
        )
        for title, module in pages
        if module != "presets_page" or enabled()
    ]
    st.navigation(navigation).run()
    st.sidebar.caption(f"MLflow: {tracking_location(uri())}")
    source = "fixture" if os.environ.get("LANGSMITH_SOURCE") == "fixture" else "live"
    st.sidebar.caption(f"LangSmith source: {source}")


if __name__ == "__main__":
    main()
