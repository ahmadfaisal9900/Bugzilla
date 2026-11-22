"""Run: streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502."""

import hashlib
import hmac
import os
from pathlib import Path

import streamlit as st


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


def main():
    st.set_page_config(page_title="Bugzilla · Dev dashboard", layout="wide")
    if not authenticated():
        st.stop()
    from bugzilla_serving.dashboard.views import enabled

    st.title("Bugzilla · Dev dashboard")
    st.caption(
        "Dev evidence only. v3 coverage gaps: no F2, no F5, no test F3. "
        "pilot125 is a pilot subset; missing review-only metrics are unknown, never zero."
    )
    pages = [
        ("Overview", "overview"),
        ("Answer eval", "answer_eval"),
        ("Retrieval eval", "retrieval_eval"),
        ("Cost & latency", "cost_latency"),
        ("Error analysis", "error_analysis"),
        ("Experiment Lab", "experiment_lab"),
        ("Compare runs", "compare_runs"),
        ("Presets", "presets_page"),
        ("Production", "production"),
    ]
    navigation = [
        st.Page(
            str(Path(__file__).parent / "pages" / f"{module}.py"),
            title=title,
            default=module == "overview",
        )
        for title, module in pages
        if module != "presets_page" or enabled()
    ]
    st.navigation(navigation).run()


if __name__ == "__main__":
    main()
