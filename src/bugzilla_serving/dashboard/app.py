"""Run: streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502."""

import hashlib
import hmac
import os

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
    st.set_page_config(page_title="Bugzilla · Development results", layout="wide")
    if not authenticated():
        st.stop()
    from bugzilla_serving.dashboard.results_app import render
    from bugzilla_serving.dashboard.results_source import load_results

    def show():
        if st.sidebar.button("Refresh saved results"):
            from bugzilla_serving.dashboard.results_source import (
                _cached_pack,
                final_experiment_id,
                remote_folder,
            )

            _cached_pack.clear()
            remote_folder.clear()
            final_experiment_id.clear()
        data = load_results()
        if data is None:
            st.title("Bugzilla development results")
            st.info(
                "No saved results yet. Generate the local results pack with "
                "PYTHONPATH=src:. python scripts/mlops/build_results_pack.py, or set "
                "MLFLOW_TRACKING_URI to read a logged final-results pack."
            )
            return
        render(data[0])

    # Declaring one hidden navigation page disables automatic discovery of old pages/.
    st.navigation([st.Page(show, title="Development results")], position="hidden").run()
    if os.environ.get("DASHBOARD_ADVANCED", "false").lower() == "true":
        with st.sidebar.expander("Advanced"):
            view = st.selectbox("Additional tools", ["None", "Experiment Lab", "Production"])
        if view == "Experiment Lab":
            st.session_state["final_dashboard"] = True
            st.info("Auto-router uses the V2 serving adapter with a 4,096-byte dossier cap.")
            from bugzilla_serving.dashboard.views import experiment_lab

            experiment_lab()
        elif view == "Production":
            from bugzilla_serving.dashboard.views import production

            production()


if __name__ == "__main__":
    main()
