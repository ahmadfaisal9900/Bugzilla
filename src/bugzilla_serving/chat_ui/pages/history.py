"""History: earlier questions in this browser session (kept in memory only)."""

from __future__ import annotations

import time
from html import escape

import streamlit as st

from ..state import get_state
from ..ui import components


def _ago(timestamp: float) -> str:
    minutes = int((time.time() - timestamp) // 60)
    if minutes < 1:
        return "just now"
    return f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h ago"


def render() -> None:
    components.page_width(880)
    components.page_header(
        "History", "Questions from this session. Starting a new conversation clears them."
    )
    turns = get_state().turns
    if not turns:
        st.info("No questions yet.")
        return
    components.section_label(f"{len(turns)} question{'s' * (len(turns) != 1)}", "Newest first")
    with st.container(key="history"):
        for number, turn in reversed(list(enumerate(turns, start=1))):
            with st.expander(turn.question, expanded=number == len(turns)):
                meta = (
                    f"{turn.mode_label} · {components.answer_summary(turn)} · {_ago(turn.asked_at)}"
                )
                st.markdown(f"<p class='meta'>{escape(meta)}</p>", unsafe_allow_html=True)
                components.answer_body(turn, details=False)
