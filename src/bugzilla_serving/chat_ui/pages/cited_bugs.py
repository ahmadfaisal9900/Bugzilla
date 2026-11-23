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
    components.page_width(1120)
    components.page_header(
        "Cited bugs", "Bug reports used by answers in this session, and what each said."
    )
    bugs = get_state().cited_bugs()
    if not bugs:
        st.info(
            "No cited bugs yet. Ask a question, and the reports its answer uses are listed here."
        )
        return

    search, sort, _ = st.columns([3, 1.3, 2.7], vertical_alignment="bottom")
    query = search.text_input(
        "Search cited bugs",
        placeholder="Search by bug number, evidence or question",
        icon=":material/search:",
        label_visibility="collapsed",
        key="cited-search",
    )
    order = sort.selectbox("Sort", list(SORTS), label_visibility="collapsed", key="cited-sort")
    shown = SORTS[order](matching(bugs, query))

    table, detail = st.columns([3, 2], gap="large")
    with table:
        selected = _table(shown)
        count = f"{len(shown)} of {len(bugs)} cited bug{'s' * (len(bugs) != 1)}"
        components.section_label(count, "Select a row to see its details")
    with detail:
        if selected:
            _detail(selected)
        else:
            st.caption("No cited bugs match that search.")


def matching(bugs: list[CitedBug], query: str) -> list[CitedBug]:
    """Case-insensitive match on the bug number, its evidence or the questions that cited it."""
    needle = query.strip().lower()
    if not needle:
        return bugs
    return [b for b in bugs if needle in " ".join([b.bug_id, *b.snippets, *b.questions]).lower()]


def _table(bugs: list[CitedBug]) -> CitedBug | None:
    if not bugs:
        return None
    rows = [
        {
            "Bug": bug.url or bug.bug_id,
            "Evidence": bug.snippets[0] if bug.snippets else "",
            "Cited": bug.times_cited,
        }
        for bug in bugs
    ]
    event = st.dataframe(
        rows,
        key="cited-table",
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Bug": st.column_config.LinkColumn("Bug", display_text=r"id=(\d+)$", width="small"),
            "Evidence": st.column_config.TextColumn(width="large"),
            "Cited": st.column_config.NumberColumn(
                width="small", help="Answers that cited it", format="%d×"
            ),
        },
    )
    picked = event.selection.rows if event and event.selection else []
    index = picked[0] if picked and picked[0] < len(bugs) else 0
    return bugs[index]


def _detail(bug: CitedBug) -> None:
    """The selected bug: what the archive said about it and where it came up."""
    title = escape(f"Bug {bug.bug_id}")
    if bug.url:
        href = escape(bug.url, quote=True)
        title = f"<a href='{href}' target='_blank' rel='noopener noreferrer'>{title}</a>"
    evidence = (
        "".join(f"<li>{escape(s[:400])}</li>" for s in bug.snippets) or "<li>No evidence text.</li>"
    )
    questions = "".join(f"<li>{escape(q)}</li>" for q in bug.questions)
    answers = f"{bug.times_cited} answer{'s' * (bug.times_cited != 1)}"
    with st.container(key="bug-detail"):
        st.markdown(
            f"<h2 class='detail-title'>{title}</h2>"
            "<dl class='stats'>"
            f"<div><dt>Cited</dt><dd>{answers}</dd></div>"
            f"<div><dt>Best match</dt><dd>{bug.best_score:.2f}</dd></div>"
            f"<div><dt>Last cited</dt><dd>Question {bug.last_turn + 1}</dd></div>"
            "</dl>"
            f"<h3 class='detail-label'>Evidence</h3><ul class='detail-list'>{evidence}</ul>"
            "<h3 class='detail-label'>Asked in this session</h3>"
            f"<ul class='detail-list'>{questions}</ul>",
            unsafe_allow_html=True,
        )
        if bug.url:
            st.link_button("Open on Bugzilla", bug.url, icon=":material/open_in_new:")
