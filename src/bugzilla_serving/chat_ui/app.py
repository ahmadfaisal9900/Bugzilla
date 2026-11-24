"""Firefox Bug Assistant: Streamlit entry point.

Run from the repo root:  streamlit run src/bugzilla_serving/chat_ui/app.py
Sets up the page, the sidebar, the top bar and navigation. Each page lives in pages/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# `streamlit run` puts only this folder on sys.path. Add src/ so the package imports
# work without `pip install -e .`.
SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bugzilla_serving.chat_ui.config import ConfigError, Settings  # noqa: E402
from bugzilla_serving.chat_ui.pages import about, chat, cited_bugs, history  # noqa: E402
from bugzilla_serving.chat_ui.state import get_state  # noqa: E402
from bugzilla_serving.chat_ui.ui import components, data  # noqa: E402

st.set_page_config(
    page_title="Firefox Bug Assistant", page_icon=":material/bug_report:", layout="wide"
)
components.load_styles()

try:
    Settings.from_env()
except ConfigError as error:
    st.error(f"The frontend isn't configured: {error}. See docs/CHAT_UI.md.")
    st.stop()

ICONS = {
    "Ask": ":material/chat_bubble:",
    "Cited bugs": ":material/bug_report:",
    "History": ":material/history:",
    "About": ":material/info:",
}
CHAT = st.Page(chat.render, title="Ask", icon=ICONS["Ask"], url_path="chat", default=True)
CITED = st.Page(cited_bugs.render, title="Cited bugs", icon=ICONS["Cited bugs"], url_path="cited")
HISTORY = st.Page(history.render, title="History", icon=ICONS["History"], url_path="history")
ABOUT = st.Page(about.render, title="About", icon=ICONS["About"], url_path="about")
PAGES = [CHAT, CITED, HISTORY, ABOUT]
BUGZILLA = "https://bugzilla.mozilla.org"


def sidebar() -> None:
    """Brand, primary action, grouped navigation, then the archive note pinned to the bottom."""
    with st.sidebar:
        components.brand()
        if st.button("New conversation", icon=":material/add:", use_container_width=True):
            get_state().new_conversation()
            st.switch_page(CHAT)
        _link(CHAT)
        components.nav_group("This session")
        _link(CITED)
        _link(HISTORY)
        components.nav_group("Help")
        _link(ABOUT)
        st.page_link(BUGZILLA, label="Mozilla Bugzilla", icon=":material/open_in_new:")
        components.sidebar_footer()


def _link(target: st.Page) -> None:
    st.page_link(target, icon=ICONS[target.title])  # page_link doesn't reuse the page's icon


page = st.navigation(PAGES, position="hidden")
sidebar()
components.mark_current_page("" if page.url_path == CHAT.url_path else page.url_path)
components.top_bar(page.title, data.api_ready())
page.run()
