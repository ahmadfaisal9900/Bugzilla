"""Ask: the main chat screen."""

from __future__ import annotations

import time

import streamlit as st

from .. import chat
from ..api import ApiError, Catalog
from ..examples import COUNT, LOOKUP, RELATIONS, starters, task_questions
from ..state import AppState, get_state
from ..ui import components, controls, data

PLACEHOLDER = "Ask a question about the Firefox bug sample…"

# Starting points for the three kinds of question the archive answers well. The question is a
# fallback: when the API's examples include one of the same kind, the tile asks that instead.
TASKS = [
    (
        LOOKUP,
        ":material/search:",
        "Look up a bug",
        "What a report says, where it's filed.",
        "What is bug 1000001 about?",
    ),
    (
        COUNT,
        ":material/bar_chart:",
        "Count and compare",
        "How many reports match a component.",
        "Which component has the most bugs in the sample?",
    ),
    (
        RELATIONS,
        ":material/account_tree:",
        "Trace relationships",
        "Duplicates, dependencies, related reports.",
        "Which bugs are duplicates of bug 1000001?",
    ),
]


def render() -> None:
    state = get_state()
    ready = data.api_ready()
    catalog = _load_catalog() if ready else None

    components.page_width(880)
    components.page_header("Ask about Firefox bugs", components.HEADER_NOTE)
    if catalog is None:
        st.error(
            "The bug archive service isn't reachable right now, so new questions are paused. "
            "Earlier answers in this session are still shown below."
        )
        _history(state)
        st.chat_input(PLACEHOLDER, disabled=True)
        return

    preset, overrides = _chat_controls(state, catalog)
    _banners(state)
    if state.turns:
        _history(state)
    else:
        _welcome(state, catalog)

    limited = state.rate_limit_seconds > 0
    typed = st.chat_input(PLACEHOLDER, disabled=limited, max_chars=6000)
    question = typed or state.pending_question
    state.pending_question = None
    if question and not limited:
        _answer(state, catalog, preset, overrides, question.strip())


def _chat_controls(state: AppState, catalog: Catalog):
    """Mode picker with the "Custom settings" badge beside it, then Advanced settings."""
    with st.container(key="chat-controls"):
        mode, badge, _ = st.columns([2.2, 1.6, 4.2], vertical_alignment="bottom")
        with mode:
            preset = controls.mode_picker(catalog)
        overrides = controls.advanced_settings(catalog, preset, state)
        with badge:
            controls.custom_badge(overrides)
    return preset, overrides


def _load_catalog() -> Catalog | None:
    try:
        return data.get_catalog()
    except ApiError:
        return None


def _banners(state: AppState) -> None:
    quota = data.get_quota()
    if quota and quota.degraded_now:
        st.info(
            "The free model quota is nearly used up. New questions return the most relevant "
            "bug reports without a written answer until it resets.",
        )
    if state.rate_limit_seconds > 0:
        _rate_limit_countdown()
    if state.notice:
        st.warning(state.notice)


@st.fragment(run_every=1)
def _rate_limit_countdown() -> None:
    seconds = get_state().rate_limit_seconds
    if seconds:
        st.warning(
            f"You've asked a lot of questions in the last minute. You can ask again in {seconds} s."
        )
    else:
        st.rerun()


def _welcome(state: AppState, catalog: Catalog) -> None:
    """Empty state, laid out like kapa's onboarding: numbered examples, a fact panel, task tiles."""
    examples, facts = st.columns([3, 2], gap="large")
    with examples:
        shown = starters(catalog.examples)
        if shown:
            components.section_label("Try an example")
            with st.container(key="examples"):
                for index, example in enumerate(shown):
                    label = f"**{example.tag}** {example.question}"
                    if st.button(label, key=f"example:{index}", use_container_width=True):
                        _ask_later(state, example.question)
    with facts, st.container(key="archive"):
        st.markdown("**About the archive**")
        st.markdown(
            ":material/database: About 3,000 Firefox bug reports  \n"
            ":material/link: Saved from Mozilla Bugzilla, not live  \n"
            ":material/fact_check: Every answer lists the reports it used  \n"
            ":material/tune: Mode changes how hard it searches"
        )

    components.section_label("Research tasks", rule=False)
    questions = task_questions(catalog.examples)
    with st.container(key="tasks"):
        for column, (kind, icon, title, blurb, fallback) in zip(st.columns(3), TASKS, strict=True):
            question = questions.get(kind, fallback)
            with column:
                label = f"**{title}** {blurb}"
                tip = f"Asks: {question}"
                if st.button(
                    label, key=f"task:{title}", icon=icon, help=tip, use_container_width=True
                ):
                    _ask_later(state, question)


def _ask_later(state: AppState, question: str) -> None:
    state.pending_question = question
    st.rerun()


def _history(state: AppState) -> None:
    client = data.get_client()
    for index, turn in enumerate(state.turns):
        components.user_message(turn.question)
        with st.container(key=f"answer-{index}"):
            components.answer_body(turn)
            controls.feedback(turn, client, key=str(index))


def _answer(state: AppState, catalog: Catalog, preset, overrides, question: str) -> None:
    state.notice = ""
    state.invalid_setting = None
    components.user_message(question)
    with st.container(key="answer-pending"):
        with st.status("Searching…") as status:
            try:
                turn = chat.ask(
                    data.get_client(),
                    session_id=state.session_id,
                    question=question,
                    preset=preset,
                    overrides=overrides,
                    model_label=catalog.model_labels.get(
                        str(preset.config.get("model")), "Not reported"
                    ),
                    on_progress=lambda label: status.update(label=label),
                )
            except ApiError as error:
                status.update(label="Couldn't answer this one", state="error")
                _remember_error(state, error)
            else:
                status.update(label="Answer ready", state="complete")
                state.turns.append(turn)
    st.rerun()


def _remember_error(state: AppState, error: ApiError) -> None:
    if error.code == "rate_limited":
        state.rate_limited_until = time.time() + (error.retry_after or 60)
    elif error.code == "invalid_config":
        if error.field:
            state.invalid_setting = (error.field, error.message)
        state.notice = (
            f"One of the advanced settings isn't valid ({error.message}). "
            "Open Advanced settings to fix it."
        )
    elif error.status == 401:
        state.notice = "The frontend's API key was rejected. Check SERVING_API_KEY."
    else:
        state.notice = "Something went wrong while answering. Please try again in a moment."
