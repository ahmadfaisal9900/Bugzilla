"""Final dashboard exercises rendered tabs, safe naming, links, and missing data."""

import math
import shutil
import time
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.results_source import (
    SYSTEMS,
    links,
    paired,
    read_pack,
)

FIXTURE = Path(__file__).parent / "fixtures/results_pack"
APP = ROOT / "src/bugzilla_serving/dashboard/app.py"


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    import httpx
    import requests

    def denied(*args, **kwargs):
        raise AssertionError("No network in final dashboard tests")

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setenv("DASHBOARD_RESULTS_DIR", str(FIXTURE))
    monkeypatch.setenv("DASHBOARD_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LANGSMITH_SOURCE", "fixture")
    for k in [
        "DASHBOARD_PASSWORD",
        "DASHBOARD_ADVANCED",
        "MLFLOW_TRACKING_URI",
        "DAGSHUB_REPO_URL",
        "LANGSMITH_PROJECT_URL",
    ]:
        monkeypatch.delenv(k, raising=False)
    st.cache_data.clear()


def test_tabs_names_and_cache():
    app = AppTest.from_file(str(APP), default_timeout=10).run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Results", "Compare", "How it works & links"]
    text = " ".join(str(node.proto) for node in app if hasattr(node, "proto"))
    assert "Auto-router v2" not in text and "scorer v2" not in text
    # dataframes also contain no retired versions in labels or cells.
    for table in app.dataframe:
        assert "v2" not in table.value.to_csv(index=False).lower()
        assert "v1" not in table.value.to_csv(index=False).lower()
    assert len(app.get("plotly_chart")) >= 7
    assert not app.get("link_button")
    start = time.monotonic()
    app.run()
    assert time.monotonic() - start < 3
    app.radio[0].set_value("Search methods").run()
    assert not app.exception
    assert any("not measured" in i.value for i in app.info)


def test_empty_and_password(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_RESULTS_DIR", str(tmp_path / "absent"))
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception and "scripts/build_results_pack.py" in app.info[0].value
    monkeypatch.setenv("DASHBOARD_PASSWORD", "fixture-login")
    app = AppTest.from_file(str(APP)).run()
    assert app.text_input[0].label == "Dashboard password"
    assert not app.info


def test_headers_and_names(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "pack")
    tables, _ = read_pack(tmp_path / "pack")
    assert set(tables["final_scores.csv"].System) == set(SYSTEMS)
    p = tmp_path / "pack/final_scores.csv"
    df = pd.read_csv(p).drop(columns=["Overall %"])
    df.to_csv(p, index=False)
    with pytest.raises(ValueError, match="missing required headers"):
        read_pack(tmp_path / "pack")


def test_cost_and_mcnemar_known_values():
    tables, calc = read_pack(FIXTURE)
    cost = tables["system_cost.csv"].set_index("System")
    assert math.isclose(cost.loc["Auto-router", "calls_per_q"], 0.5732459016393443)
    assert math.isclose(cost.loc["Auto-router", "tokens_per_q"], 914.0849180327868)
    assert math.isnan(cost.loc["Auto-router", "latency_p95_s"])
    assert cost.loc["Query rewriting", "tokens_per_q"] == cost.loc["Smart search", "tokens_per_q"]
    assert "0*82" in calc
    route = tables["route_latency.csv"].set_index("Path")
    assert int(route["Questions"].sum()) == 122
    assert route.loc["Database path (model answer)", "Questions"] == 4
    assert route.loc["Bug dossier with cited comment", "Questions"] == 6
    assert route.loc["Database path (parser)", "latency_p50_s"] == 0.035

    result, _ = paired(tables["per_question_scores.csv"], "Auto-router", "Smart search")
    assert result["a_only"] == 36 and result["b_only"] == 3
    from scipy.stats import binomtest

    assert math.isclose(result["p"], binomtest(36, 39).pvalue)


def test_links_hide_missing_and_credentials(monkeypatch):
    assert links() == {}
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "https://example.test/team/repo.mlflow/api/path")
    value = links()
    assert value["Experiments"] == "https://example.test/team/repo.mlflow"
    assert value["Model registry"].endswith("/#/models/bugzilla-qa-config")
    monkeypatch.setenv("DAGSHUB_REPO_URL", "https://user:fixture-password@example.test/repo")
    assert "DagsHub repository" not in links()


def test_advanced_is_opt_in_and_keeps_lab_gate(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADVANCED", "true")
    monkeypatch.setenv("DASHBOARD_LAB_ENABLED", "false")
    app = AppTest.from_file(str(APP), default_timeout=10).run()
    assert app.sidebar.selectbox[0].label == "Additional tools"
    app.sidebar.selectbox[0].set_value("Experiment Lab").run()
    assert not app.exception
    assert any("Experiment Lab is disabled" in i.value for i in app.info)


def test_supported_lab_choices_exclude_retired_router():
    code = """
import streamlit as st
from bugzilla_serving.dashboard.views import widgets
st.session_state['final_dashboard'] = True
widgets({'system_id': 'S8'})
"""
    app = AppTest.from_string(code, default_timeout=10).run()
    assert not app.exception
    control = next(w for w in app.selectbox if w.label == "System")
    assert "Auto-router" not in control.options


def test_normal_tabs_never_import_research_or_torch(monkeypatch):
    import builtins

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith(("bugzilla_qa", "torch")):
            raise AssertionError("Ordinary dashboard tabs must not load model code")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    app = AppTest.from_file(str(APP), default_timeout=10).run()
    assert not app.exception
