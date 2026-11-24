"""Presentational building blocks. They render data; they never call the API."""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from ..api import Evidence
from ..chat import Turn
from .labels import choice

ASSETS = Path(__file__).resolve().parents[1] / "assets"
DEGRADED = "None, sources only (free quota used up)"
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


def source_chips(sources: list[Evidence], label: str = "Sources") -> None:
    """A row of small neutral chips. Hover shows the evidence; click opens Bugzilla."""
    chips = "".join(_bug_link(source, source.snippet[:220], "chip") for source in sources)
    _html(f"<div class='sources'><span class='sources-label'>{escape(label)}</span>{chips}</div>")


def source_list(sources: list[Evidence]) -> None:
    """Reports with their evidence snippet, for answers that show sources without text."""
    items = []
    for source in sources:
        snippet = escape(source.snippet[:300] + ("…" if len(source.snippet) > 300 else ""))
        items.append(f"<li>{_bug_link(source)}<p>{snippet}</p></li>")
    _html(f"<ul class='source-list'>{''.join(items)}</ul>")


# ---- Answers ----------------------------------------------------------------------------------


def user_message(text: str) -> None:
    """The question, right-aligned in a grey pill."""
    _html(f"<div class='user-msg'><p>{escape(text)}</p></div>")


ROUTES = {
    "abstain_low_evidence": "S4 · Stopped (evidence below threshold)",
    "routing_error": "Router couldn't choose",
}


def answered_by(route: str) -> str:
    """Which answering system produced the answer, e.g. "S7 · Database tools"."""
    if not route:
        return "Not reported"
    return ROUTES.get(route) or choice("system_id", route)


def answer_summary(turn: Turn) -> str:
    """One line on how an answer was made, e.g. "1.8 s · 3 sources"."""
    record = turn.record
    count = len(record.evidence) if record else 0
    seconds = record.latency_ms / 1000 if record else 0.0
    return f"{seconds:.1f} s · {count} source{'s' * (count != 1)}"


def answer_facts(turn: Turn) -> None:
    """Label-over-value pairs: mode, the system that answered, model, sources, time."""
    record = turn.record
    count = len(record.evidence) if record else 0
    seconds = record.latency_ms / 1000 if record else 0.0
    facts = [
        ("Mode", turn.mode_label),
        ("Answered by", answered_by(record.route if record else "")),
        ("Model", turn.model_label),
        ("Sources checked", str(count)),
        ("Time", f"{seconds:.1f} s"),
    ]
    if record and record.sources_only:
        facts.append(("Written answer", DEGRADED))
    cells = "".join(f"<div><dt>{escape(k)}</dt><dd>{escape(v)}</dd></div>" for k, v in facts)
    _html(f"<dl class='facts'>{cells}</dl>")


def answer_body(turn: Turn, *, details: bool = True) -> None:
    """How it was answered (collapsed), the answer, then its sources.

    Pass details=False inside another expander: Streamlit doesn't allow nested expanders.
    """
    record = turn.record
    if record is None:
        return
    sources = record.sources()
    if details:
        with st.expander(f"How this was answered · {answer_summary(turn)}"):
            answer_facts(turn)

    if record.sources_only:
        st.warning(
            "The free model quota is used up for now, so here are the most relevant bug reports "
            "instead of a written answer.",
        )
        source_list(sources[:5])
    elif record.abstain:
        st.markdown("I couldn't find enough evidence in the archive to answer that.")
        if sources:
            source_chips(sources[:5], "Closest reports")
    else:
        st.markdown(record.text)
        if record.rationale and record.rationale.strip() != record.text.strip():
            _html(f"<p class='rationale'>{escape(record.rationale)}</p>")
        if sources:
            source_chips(sources)
