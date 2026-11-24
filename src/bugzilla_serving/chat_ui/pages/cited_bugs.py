"""Cited bugs: every bug report referenced in this session, as a searchable table with details."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import streamlit as st

from ..chat import CitedBug
from ..state import get_state
from ..ui import components

SORTS: dict[str, Callable[[list[CitedBug]], list[CitedBug]]] = {
    "Newest first": lambda bugs: bugs,  # already newest first
    "Most cited": lambda bugs: sorted(bugs, key=lambda b: (-b.times_cited, -b.last_turn)),
    "Bug number": lambda bugs: sorted(
        bugs, key=lambda b: int(b.bug_id) if b.bug_id.isdecimal() else 0
    ),
}


def render() -> None:
    components.page_width(880)
    components.page_header(
        "Cited bugs", "Bug reports used by answers in this session. Select one to see what it said."
    )
    bugs = get_state().cited_bugs()
    if not bugs:
        st.info(
            "No cited bugs yet. Ask a question, and the reports its answer uses are listed here."
        )
        return

    search, sort = st.columns([3, 1.2], vertical_alignment="bottom")
    query = search.text_input(
        "Search cited bugs",
        placeholder="Search by bug number, evidence or question",
        icon=":material/search:",
        label_visibility="collapsed",
        key="cited-search",
    )
    order = sort.selectbox("Sort", list(SORTS), label_visibility="collapsed", key="cited-sort")
    shown = SORTS[order](matching(bugs, query))

    components.section_label(f"{len(shown)} of {len(bugs)} cited bug{'s' * (len(bugs) != 1)}")
    if not shown:
        st.caption("No cited bugs match that search.")
        return
    with st.container(key="bug-list"):
        for bug in shown:
            if st.button(_row_label(bug), key=f"bug-row-{bug.bug_id}", use_container_width=True):
                _detail_dialog(bug)


def matching(bugs: list[CitedBug], query: str) -> list[CitedBug]:
    """Case-insensitive match on the bug number, its evidence or the questions that cited it."""
    needle = query.strip().lower()
    if not needle:
        return bugs
    return [b for b in bugs if needle in " ".join([b.bug_id, *b.snippets, *b.questions]).lower()]


def _row_label(bug: CitedBug) -> str:
    """Bold bug number and citation count on top, the first line of evidence under it."""
    cited = f"cited {bug.times_cited}×"
    evidence = bug.snippets[0] if bug.snippets else "No evidence text."
    evidence = evidence if len(evidence) <= 150 else evidence[:149].rstrip() + "…"
    # Button labels are markdown: escape characters that would format the evidence.
    for char in "\\*_`[]#<>":
        evidence = evidence.replace(char, "\\" + char)
    return f"**Bug {bug.bug_id} · {cited}** {evidence}"


def _detail_dialog(bug: CitedBug) -> None:
    """A popup titled with the bug number; Escape or the cross closes it."""
    st.dialog(f"Bug {bug.bug_id}", width="large")(_detail)(bug)


def _detail(bug: CitedBug) -> None:
    """The selected bug: what the archive said about it and where it came up."""
    evidence = (
        "".join(f"<li>{escape(s[:600])}</li>" for s in bug.snippets) or "<li>No evidence text.</li>"
    )
    questions = "".join(f"<li>{escape(q)}</li>" for q in bug.questions)
    answers = f"{bug.times_cited} answer{'s' * (bug.times_cited != 1)}"
    with st.container(key="bug-detail"):
        st.markdown(
            "<dl class='stats'>"
            f"<div><dt>Cited by</dt><dd>{answers}</dd></div>"
            f"<div><dt>Best match score</dt><dd>{bug.best_score:.2f}</dd></div>"
            f"<div><dt>Last cited</dt><dd>Question {bug.last_turn + 1}</dd></div>"
            "</dl>"
            "<h3 class='detail-label'>What the archive says</h3>"
            f"<ul class='detail-list'>{evidence}</ul>"
            "<h3 class='detail-label'>Questions that cited it</h3>"
            f"<ul class='detail-list'>{questions}</ul>",
            unsafe_allow_html=True,
        )
        if bug.url:
            st.link_button("Open on Bugzilla", bug.url, icon=":material/open_in_new:")
