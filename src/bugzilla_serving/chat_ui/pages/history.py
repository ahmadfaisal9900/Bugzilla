"""History: earlier questions in this browser session (kept in memory only)."""

from __future__ import annotations

import time

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
    query = (
        st.text_input(
            "Search history", placeholder="Find a question or answer…", key="history-search"
        )
        .strip()
        .casefold()
    )
    selected = [
        (number, turn)
        for number, turn in reversed(list(enumerate(turns, start=1)))
        if not query
        or query
        in (turn.question + " " + (turn.record.text if turn.record else turn.error)).casefold()
    ]
    components.section_label(
        f"{len(selected)} of {len(turns)} questions"
        if query
        else f"{len(turns)} question{'s' * (len(turns) != 1)}",
        "Newest first",
    )
    if not selected:
        st.info("No questions match your search.")
    with st.container(key="history"):
        for number, turn in selected:
            with st.expander(turn.question):
                status = (
                    "Not completed"
                    if turn.record is None
                    else "Sources only"
                    if turn.record.sources_only
                    else "No answer"
                    if turn.record.abstain
                    else "Answered"
                )
                st.caption(
                    f"Question {number} · {status} · {turn.mode_label} · {_ago(turn.asked_at)}"
                )
                components.answer_body(turn, details=False)
