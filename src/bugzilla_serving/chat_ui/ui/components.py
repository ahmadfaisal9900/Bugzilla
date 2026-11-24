"""Presentational building blocks. They render data; they never call the API."""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from ..api import Evidence
from ..chat import Turn
from .labels import choice

ASSETS = Path(__file__).resolve().parents[1] / "assets"
DEGRADED = "Sources only"
ARCHIVE_NOTE = "Answers come from the Firefox Bugzilla archive (3,000-bug sample)."
HEADER_NOTE = (
    "Ask about a bug's component, duplicates, dependencies or how often an issue comes up. "
    + ARCHIVE_NOTE
)


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def load_styles() -> None:
    _html(f"<style>{(ASSETS / 'styles.css').read_text(encoding='utf-8')}</style>")


# ---- App frame ------------------------------------------------------------------------------


APP_NAME = "Bug Assistant"


def brand() -> None:
    """Plain wordmark: no logo block, so the sidebar starts quietly."""
    _html(f"<div class='brand'>{APP_NAME}</div>")


def mark_current_page(href: str) -> None:
    """Streamlit doesn't expose the current page link to CSS, so mark it by its href."""
    target = escape(href, quote=True)
    link = f'[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][href="{target}"]'
    raised = (
        "background: var(--raised); box-shadow: 0 1px 2px rgb(0 0 0 / .06), 0 0 0 1px var(--line);"
    )
    ink = "color: var(--ink) !important;"
    _html(f"<style>/* current page */ {link} {{ {raised} }} {link} p {{ {ink} }}</style>")


def nav_group(label: str) -> None:
    _html(f"<p class='nav-group'>{escape(label)}</p>")


def sidebar_footer() -> None:
    _html("<div class='sidebar-footer'>Bugzilla snapshot<br>About 3,000 reports, not live</div>")


def top_bar(title: str, api_ready: bool) -> None:
    """The thin bar across the top of the pane: page name on the left, API status on the right."""
    state, label = ("ok", "API connected") if api_ready else ("down", "API unavailable")
    with st.container(key="app-header"):
        _html(
            f"<div class='top-bar'><span class='crumb'>{escape(title)}</span>"
            f"<span class='status'><i class='dot {state}'></i>{label}</span></div>"
        )


def page_width(pixels: int) -> None:
    """Pages choose their own reading width; the chat reads best narrow, tables need room."""
    _html(f"<style>:root {{ --content: {int(pixels)}px; }}</style>")


def page_header(title: str, description: str) -> None:
    """The page's single heading and one line of context."""
    _html(
        f"<h1 class='page-title'>{escape(title)}</h1>"
        f"<p class='page-description'>{escape(description)}</p>"
    )


def section_label(text: str, aside: str = "", *, rule: bool = True) -> None:
    """A quiet label above a group (kapa's 'Explore use cases'); `rule` adds a hairline under it."""
    right = f"<span>{escape(aside)}</span>" if aside else ""
    css = "section-label" + ("" if rule else " plain")
    _html(f"<div class='{css}'><span>{escape(text)}</span>{right}</div>")


# ---- Sources ----------------------------------------------------------------------------------


def _bug_link(source: Evidence, tooltip: str = "", css: str = "") -> str:
    label = f"Bug {escape(source.bug_id)}"
    title = f" title='{escape(tooltip, quote=True)}'" if tooltip else ""
    cls = f" class='{css}'" if css else ""
    if not source.url:
        return f"<span{cls}{title}>{label}</span>"
    href = escape(source.url, quote=True)
    return f"<a{cls} href='{href}' target='_blank' rel='noopener noreferrer'{title}>{label}</a>"


def source_list(sources: list[Evidence], citations: tuple[str, ...] = ()) -> None:
    """Reports with their evidence snippet, for answers that show sources without text."""
    items = []
    for source in sources:
        snippet = escape(source.snippet[:240] + ("…" if len(source.snippet) > 240 else ""))
        label = "Cited in answer" if source.chunk_id in citations else "Retrieved report"
        items.append(
            f"<li><div class='source-heading'>{_bug_link(source)}"
            f"<span>{label}</span></div><p>{snippet or 'No excerpt available.'}</p></li>"
        )
    _html(f"<ul class='source-list'>{''.join(items)}</ul>")


def answer_sources(turn: Turn, *, expandable: bool = True) -> None:
    record = turn.record
    if record is None:
        return
    sources = record.sources(limit=len(record.evidence))
    if not sources:
        return
    title = "Related reports" if record.abstain else "Sources"
    count = len(sources)
    _html(
        f"<div class='source-section-title'>{title}"
        f"<span>{count} bug report{'s' * (count != 1)}</span></div>"
    )
    source_list(sources[:3], () if record.abstain else record.citations)
    if len(sources) > 3:
        if expandable:
            with st.expander(f"Show {len(sources) - 3} more reports"):
                source_list(sources[3:], () if record.abstain else record.citations)
        else:
            source_list(sources[3:], () if record.abstain else record.citations)


# ---- Answers ----------------------------------------------------------------------------------


def user_message(text: str) -> None:
    """The question, right-aligned in a grey pill."""
    _html(f"<div class='user-msg'><p>{escape(text)}</p></div>")


ROUTES = {
    "abstain_low_evidence": "S4 · Stopped (evidence below threshold)",
    "routing_error": "Router couldn't choose",
    "unknown_bug": "Archive check (bug not in the sample)",
}


def answered_by(route: str) -> str:
    """Which answering system produced the answer, e.g. "S7 · Database tools"."""
    if not route:
        return "Not reported"
    return ROUTES.get(route) or choice("system_id", route)


def sources_checked(turn: Turn) -> str:
    """What the answer was based on: "3 sources", or a database query that cites no reports."""
    record = turn.record
    count = len(record.evidence) if record else 0
    if record and not count and record.route == "S7" and not record.abstain:
        return "Database query"
    return f"{count} passage{'s' * (count != 1)} checked"


def answer_summary(turn: Turn) -> str:
    """One line on how an answer was made, e.g. "1.8 s · 3 sources"."""
    record = turn.record
    seconds = record.latency_ms / 1000 if record else 0.0
    return f"{seconds:.1f} s · {sources_checked(turn)}"


def answer_facts(turn: Turn) -> None:
    """Label-over-value pairs: mode, the system that answered, model, sources, time."""
    record = turn.record
    seconds = record.latency_ms / 1000 if record else 0.0
    checked = sources_checked(turn)
    facts = [
        ("Mode", turn.mode_label),
        ("Answered by", answered_by(record.route if record else "")),
        ("Model", turn.model_label),
        ("Evidence checked", checked),
        ("Time", f"{seconds:.1f} s"),
    ]
    if record and record.sources_only:
        facts.append(("Written answer", DEGRADED))
    cells = "".join(f"<div><dt>{escape(k)}</dt><dd>{escape(v)}</dd></div>" for k, v in facts)
    _html(f"<dl class='facts'>{cells}</dl>")


def answer_body(turn: Turn, *, details: bool = True) -> None:
    """The answer, readable source excerpts, then collapsed technical details.

    Pass details=False inside another expander: Streamlit doesn't allow nested expanders.
    """
    record = turn.record
    if record is None:
        if turn.error:
            st.warning(turn.error)
        return
    if record.sources_only:
        st.warning(
            "Answer generation is temporarily limited. Here are related bug reports from the "
            "archive.",
        )
    elif record.abstain and record.route == "unknown_bug":
        st.markdown(record.rationale)
    elif record.abstain:
        st.markdown("I couldn't find enough evidence in the archive to answer that.")
    else:
        st.markdown(record.text)
        if record.rationale and record.rationale.strip() != record.text.strip():
            _html(f"<p class='rationale'>{escape(record.rationale)}</p>")
    answer_sources(turn, expandable=details)
    if details:
        with st.expander(f"Answer details · {answer_summary(turn)}"):
            answer_facts(turn)
