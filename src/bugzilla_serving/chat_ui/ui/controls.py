"""Interactive controls: answer mode, advanced settings and feedback."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from ..api import ApiClient, ApiError, Catalog, Preset, Setting
from ..chat import Turn, changed_settings, preset_values
from ..state import AppState
from . import labels

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


def _stored_key(preset: Preset, setting: Setting) -> str:
    """Where a changed value is kept while the settings panel is closed.

    Streamlit drops a widget's state when the widget isn't drawn, so the panel copies each change
    here and the next question still uses it.
    """
    return f"value:{preset.slug}:{setting.name}"


def _value(preset: Preset, setting: Setting, baseline: Any) -> Any:
    return st.session_state.get(_stored_key(preset, setting), baseline)


def _setting_widget(preset: Preset, setting: Setting, value: Any) -> Any:
    key = _widget_key(preset, setting)
    stored = _stored_key(preset, setting)

    def keep() -> None:
        st.session_state[stored] = st.session_state[key]

    name = labels.label(setting.name, setting.label)
    common = {
        "key": key,
        "help": labels.help_text(setting.name, setting.help or None),
        "on_change": keep,
    }
    if setting.kind == "choice":
        st.session_state.setdefault(key, value)
        return st.selectbox(
            name,
            setting.choices,
            format_func=lambda v: labels.choice(setting.name, v),
            **common,
        )
    if setting.kind == "integer":
        low, high = int(setting.minimum or 0), int(setting.maximum or 100)
        st.session_state.setdefault(
            key, _clamp(int(value if value is not None else low), low, high)
        )
        step = 100 if high - low >= 2000 else 1
        return st.number_input(name, min_value=low, max_value=high, step=step, **common)
    low, high = float(setting.minimum or 0.0), float(setting.maximum or 1.0)
    st.session_state.setdefault(key, _clamp(float(value if value is not None else low), low, high))
    if high - low <= 2:
        return st.slider(name, low, high, step=0.05, **common)
    return st.number_input(name, min_value=low, max_value=high, step=0.5, format="%.2f", **common)


def _clamp(value, low, high):
    return min(max(value, low), high)


def custom_settings(catalog: Catalog, preset: Preset) -> dict[str, Any]:
    """The settings the user changed for this mode, whether or not the panel is open."""
    settings = catalog.settings_for(preset)
    baseline = preset_values(preset, settings)
    current = {s.name: _value(preset, s, baseline[s.name]) for s in settings}
    return changed_settings(baseline, current)


def settings_panel(catalog: Catalog, preset: Preset, state: AppState) -> dict[str, Any]:
    """The side panel of search and model settings, in sections. Returns the changed values.

    Widgets come from /v1/options: only settings whose applies_to includes the mode's system_id,
    with each spec's min/max or choices. A 422 from the API is shown under its field.
    """
    settings = catalog.settings_for(preset)
    baseline = preset_values(preset, settings)
    by_name = {s.name: s for s in settings}

    def reset() -> None:
        for setting in settings:
            st.session_state[_widget_key(preset, setting)] = baseline[setting.name]
            st.session_state.pop(_stored_key(preset, setting), None)
        state.invalid_setting = None

    with st.container(key="settings-panel"):
        title, close = st.columns([1, 1], vertical_alignment="center")
        with title:
            mode = escape(preset.display_label)
            _html(f"<p class='panel-title'>Settings</p><p class='panel-mode'>{mode} mode</p>")
        with close:
            st.button("Close", key="settings-close", icon=":material/close:", on_click=_close_panel)
        if not settings:
            st.caption("This mode has no adjustable settings.")
        for section, names in labels.grouped(list(by_name)):
            _html(f"<p class='panel-section'>{escape(section)}</p>")
            for name in names:
                setting = by_name[name]
                if _widget_key(preset, setting) not in st.session_state:
                    st.session_state[_widget_key(preset, setting)] = _value(
                        preset, setting, baseline[name]
                    )
                _setting_widget(preset, setting, baseline[name])
                if state.invalid_setting and state.invalid_setting[0] == name:
                    st.error(state.invalid_setting[1])
        overrides = custom_settings(catalog, preset)
        if overrides:
            st.button(
                "Reset to mode defaults",
                key="reset-settings",
                icon=":material/restart_alt:",
                on_click=reset,
                use_container_width=True,
            )
    return overrides


PANEL_KEY = "settings-open"


def panel_open(state: AppState) -> bool:
    return bool(st.session_state.get(PANEL_KEY)) or state.invalid_setting is not None


def _toggle_panel() -> None:
    st.session_state[PANEL_KEY] = not st.session_state.get(PANEL_KEY)


def _close_panel() -> None:
    st.session_state[PANEL_KEY] = False


def settings_button(open_: bool) -> None:
    """Opens or closes the settings panel on the right."""
    with st.container(key="settings-toggle"):
        st.button(
            "Hide settings" if open_ else "Settings",
            key="settings-button",
            icon=":material/tune:",
            on_click=_toggle_panel,
        )


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def custom_badge(overrides: dict[str, Any]) -> None:
    """A "Custom settings" badge, shown only while a setting differs from the mode's default."""
    if overrides:
        names = ", ".join(labels.label(n, n) for n in sorted(overrides))
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
