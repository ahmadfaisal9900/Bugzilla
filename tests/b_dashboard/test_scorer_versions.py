"""Version selector reads saved runs only and defaults to scorer v2."""

from streamlit.testing.v1 import AppTest

from bugzilla_serving.dashboard.data.common import Snapshot
from bugzilla_serving.dashboard.data.mlflow_source import Run


def test_scorer_selector_defaults_v2_and_preserves_v1(monkeypatch):
    from bugzilla_serving.dashboard.data import mlflow_source as mf

    runs = [
        Run(
            str(v),
            "research-answer-eval",
            {"system_id": "S2", "config_hash": "fixture"},
            {"scorer_version": str(v), "eval_set": "synthetic", "split": "dev"},
            {},
            v,
        )
        for v in (1, 2)
    ]
    monkeypatch.setattr(mf, "runs", lambda *args: Snapshot(runs, "fixture"))
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from bugzilla_serving.dashboard.views import records\n"
        'values = records(["research-answer-eval"])\n'
        'st.write("selected=" + ",".join(r.id for r in values))\n'
    ).run()
    assert not app.exception
    control = app.sidebar.selectbox[0]
    assert control.label == "Scorer version" and control.value == "2"
    assert app.markdown[0].value == "selected=2"
    control.set_value("1").run()
    assert not app.exception and app.markdown[0].value == "selected=1"


def test_external_judge_batches_are_never_mixed(monkeypatch):
    from bugzilla_serving.dashboard.data import mlflow_source as mf

    runs = [
        Run(
            identifier,
            "research-answer-eval",
            {"system_id": "S2"},
            dict(scorer_version="2", f5_judge=judge, f5_packet_sha256=packet),
            {},
            started,
        )
        for identifier, judge, packet, started in [
            ("old", "judge-a", "packet-old", 1),
            ("current", "judge-a", "packet-new", 2),
            ("other", "judge-b", "packet-b", 3),
            ("unbound", "judge-a", "", 4),
        ]
    ]
    monkeypatch.setattr(mf, "runs", lambda *args: Snapshot(runs, "fixture"))
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from bugzilla_serving.dashboard.views import records\n"
        'values = records(["research-answer-eval"])\n'
        'st.write("selected=" + ",".join(r.id for r in values))\n'
    ).run()
    assert not app.exception and app.markdown[0].value == "selected=current"
    app.sidebar.selectbox[1].set_value("judge-b").run()
    assert not app.exception and app.markdown[0].value == "selected=other"
