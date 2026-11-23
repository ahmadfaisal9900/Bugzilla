"""Interactive controls: answer mode, advanced settings and feedback."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from ..api import ApiClient, ApiError, Catalog, Preset, Setting
from ..chat import Turn, changed_settings, preset_values
from ..state import AppState

MODE_KEY = "mode"


def mode_picker(catalog: Catalog, *, disabled: bool = False) -> Preset:
    slugs = [p.slug for p in catalog.presets]
    if st.session_state.get(MODE_KEY) not in slugs:
        st.session_state[MODE_KEY] = catalog.default_preset.slug
    slug = st.selectbox(
        "Mode",
        slugs,
        key=MODE_KEY,
        format_func=lambda s: catalog.preset(s).display_label,
        disabled=disabled,
        help=" ".join(f"**{p.display_label}:** {p.description}" for p in catalog.presets),
    )
    return catalog.preset(slug)


def _widget_key(preset: Preset, setting: Setting) -> str:
    return f"setting:{preset.slug}:{setting.name}"


def _setting_widget(preset: Preset, setting: Setting, value: Any) -> Any:
    key = _widget_key(preset, setting)
    common = {"key": key, "help": setting.help or None}
    if setting.kind == "choice":
        st.session_state.setdefault(key, value)
        return st.selectbox(setting.label, setting.choices, **common)
    if setting.kind == "integer":
        low, high = int(setting.minimum or 0), int(setting.maximum or 100)
        st.session_state.setdefault(
            key, _clamp(int(value if value is not None else low), low, high)
        )
        return st.slider(setting.label, low, high, **common)
    low, high = float(setting.minimum or 0.0), float(setting.maximum or 1.0)
    st.session_state.setdefault(key, _clamp(float(value if value is not None else low), low, high))
    return st.slider(setting.label, low, high, step=0.05, **common)


def _clamp(value, low, high):
    return min(max(value, low), high)


def advanced_settings(catalog: Catalog, preset: Preset, state: AppState) -> dict[str, Any]:
    """The "Advanced settings" expander. Returns only the values the user changed.

    Widgets come from /v1/options: only settings whose applies_to includes the mode's system_id,
    with each spec's label, help, min/max or choices. A 422 from the API is shown under its field.
    """
    settings = catalog.settings_for(preset)
    baseline = preset_values(preset, settings)

    def reset() -> None:
        for setting in settings:
            st.session_state[_widget_key(preset, setting)] = baseline[setting.name]
        state.invalid_setting = None

    current = {
        s.name: st.session_state.get(_widget_key(preset, s), baseline[s.name]) for s in settings
    }
    overrides = changed_settings(baseline, current)

    with st.expander(
        "Advanced settings", icon=":material/tune:", expanded=state.invalid_setting is not None
    ):
        mode = escape(preset.display_label)
        st.markdown(
            f"<p class='meta'>Search and model options for the {mode} mode. "
            "Most questions don't need them.</p>",
            unsafe_allow_html=True,
        )
        if not settings:
            st.caption("This mode has no adjustable settings.")
        for setting in settings:
            _setting_widget(preset, setting, baseline[setting.name])
            if state.invalid_setting and state.invalid_setting[0] == setting.name:
                st.error(state.invalid_setting[1])
        if overrides:
            st.button("Reset", key="reset-settings", icon=":material/restart_alt:", on_click=reset)
    return overrides


def custom_badge(overrides: dict[str, Any]) -> None:
    """A "Custom settings" badge, shown only while a setting differs from the mode's default."""
    if overrides:
        names = ", ".join(sorted(overrides))
        st.markdown(
            f"<span class='badge' title='{escape(names, quote=True)}'>Custom settings</span>",
            unsafe_allow_html=True,
        )


def feedback(turn: Turn, client: ApiClient, key: str) -> None:
    """Thumbs up or down, saved immediately; an optional comment can follow."""
    if not turn.request_id:
        return
    widget = f"feedback:{key}"

    def send(comment: str | None = None) -> None:
        score = st.session_state.get(widget)
        if score is None:
            return
        try:
            client.feedback(turn.request_id, int(score), comment)
            turn.feedback = int(score)
        except ApiError:
            st.toast("Feedback couldn't be saved. Please try again.")

    left, right = st.columns([1, 3], vertical_alignment="center")
    with left:
        st.feedback("thumbs", key=widget, on_change=send)
    if turn.feedback is not None:
        with right, st.popover("Add a comment"):
            note = st.text_area("What could be better?", max_chars=2000, key=f"note:{key}")
            if st.button("Send", key=f"send:{key}"):
                send(note.strip() or None)
                st.toast("Feedback saved.")
