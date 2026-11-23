"""Typed per-browser-session state. Pages use this instead of raw st.session_state keys."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import uuid4

import streamlit as st

from .chat import CitedBug, Turn, cited_bugs

_KEY = "bug_assistant"


@dataclass
class AppState:
    session_id: str = field(default_factory=lambda: uuid4().hex)
    turns: list[Turn] = field(default_factory=list)
    pending_question: str | None = None
    rate_limited_until: float = 0.0
    notice: str = ""  # last problem, shown above the input until the next question
    invalid_setting: tuple[str, str] | None = None  # (setting name, message)

    @property
    def rate_limit_seconds(self) -> int:
        return max(0, round(self.rate_limited_until - time.time()))

    def new_conversation(self) -> None:
        self.turns.clear()
        self.pending_question = None
        self.notice = ""
        self.invalid_setting = None

    def cited_bugs(self) -> list[CitedBug]:
        """Each cited bug once, newest first, with its evidence and the questions that used it."""
        return cited_bugs(self.turns)


def get_state() -> AppState:
    if _KEY not in st.session_state:
        st.session_state[_KEY] = AppState()
    return st.session_state[_KEY]
