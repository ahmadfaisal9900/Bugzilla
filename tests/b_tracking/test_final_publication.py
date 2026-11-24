"""No network or inference: final runs and registry use a temporary file MLflow store."""

from pathlib import Path

import pytest

from bugzilla_serving.contracts.names import REGISTRY_MODEL_NAME
from bugzilla_serving.contracts.run_config import RunConfig
from bugzilla_serving.dashboard.results_source import IDS
from bugzilla_serving.tracking.client import TrackingClient
from bugzilla_serving.tracking.final_registry import champion_check, register
from bugzilla_serving.tracking.final_results import find_runs, publish

FIXTURE = Path(__file__).parents[1] / "b_dashboard/fixtures/results_pack"


def fixture_config(system):
    internal = IDS[system]
    cfg = RunConfig(system_id="S8" if internal == "S8v2" else internal, provider="mock").model_dump(
        mode="json"
    )
    if internal == "S8v2":
        cfg.update(
            system_id=internal, router_rules_version="json-tools-v2", s5_dossier_budget=12000
        )
    return cfg


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import httpx
    import requests

    def denied(*args, **kwargs):
        raise AssertionError("No network or remote MLflow allowed")

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    for key in ["LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"]:
        monkeypatch.setenv(key, "false")


def test_publish_and_register_idempotent(tmp_path, monkeypatch):
    uri = (tmp_path / "store").as_uri()
    dry = publish(FIXTURE, uri, False, fixture_config)
    assert dry["state"] == "DRY_RUN"
    client = TrackingClient(uri).client
    assert not find_runs(client, "final-results")
    result = publish(FIXTURE, uri, True, fixture_config)
    assert len(result["runs"]) == 10 and len(result["retrieval"]) == 24
    before = {r.info.run_id for r in find_runs(client, "final-results")}
    assert len(before) == 10
    assert len(find_runs(client, "final-retrieval")) == 24
    second = publish(FIXTURE, uri, True, fixture_config)
    assert all(r["action"] == "update" for r in second["runs"])
    assert before == {r.info.run_id for r in find_runs(client, "final-results")}
    assert len(find_runs(client, "final-retrieval")) == 24
    from mlflow.tracking import MlflowClient

    # Updates must replace even lower scores, not keep a higher same-timestamp metric.
    from bugzilla_serving.tracking.final_results import plans, upsert

    original = plans(FIXTURE, fixture_config)[0][0]
    lowered = {**original, "metrics": {**original["metrics"], "overall_pct": 1.0}}
    update = upsert(client, uri, "final-results", lowered, True)
    assert client.get_run(update["run_id"]).data.metrics["overall_pct"] == 1.0
    upsert(client, uri, "final-results", original, True)
    assert (
        client.get_run(update["run_id"]).data.metrics["overall_pct"]
        == original["metrics"]["overall_pct"]
    )
    from bugzilla_serving.dashboard.results_source import load_results, remote_folder

    calls = []
    download = MlflowClient.download_artifacts

    def counted(self, *args, **kwargs):
        calls.append(args)
        return download(self, *args, **kwargs)

    monkeypatch.setattr(MlflowClient, "download_artifacts", counted)
    monkeypatch.setenv("DASHBOARD_RESULTS_DIR", str(tmp_path / "missing-pack"))
    monkeypatch.setenv("DASHBOARD_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    remote_folder.clear()
    loaded = load_results()
    assert len(loaded[0]["final_scores.csv"]) == 9
    first_count = len(calls)
    assert first_count > 0
    load_results()
    assert len(calls) == first_count
    client.create_registered_model(REGISTRY_MODEL_NAME)
    historical = client.create_model_version(
        REGISTRY_MODEL_NAME, tmp_path.as_uri(), tags={"source_run_id": "historical-source"}
    )
    client.set_registered_model_alias(REGISTRY_MODEL_NAME, "champion", str(historical.version))
    preview = register(FIXTURE, uri, config_loader=fixture_config)
    assert not preview["champion_check"]["passed"]
    assert all(r["status"] == "FAIL" for r in preview["champion_check"]["routes"])
    result = register(FIXTURE, uri, apply=True, config_loader=fixture_config)
    versions = list(client.search_model_versions(f"name = '{REGISTRY_MODEL_NAME}'"))
    assert len(versions) == 10
    latest = max(versions, key=lambda v: int(v.version))
    assert latest.tags["display_name"] == "Auto-router"
    assert latest.tags["system_id"] == "S8v2"
    aliases = client.get_registered_model(REGISTRY_MODEL_NAME).aliases
    assert aliases["champion"] == str(historical.version)
    assert aliases["auto-router"] == str(latest.version)
    fast = client.get_model_version(REGISTRY_MODEL_NAME, aliases["fast"])
    assert fast.tags["display_name"] == "Keyword search"
    rerun = register(FIXTURE, uri, apply=True, config_loader=fixture_config)
    assert all(r["action"] == "reuse" for r in rerun["versions"])
    assert len(list(client.search_model_versions(f"name = '{REGISTRY_MODEL_NAME}'"))) == 10
    refused = register(FIXTURE, uri, apply=True, move_champion=True, config_loader=fixture_config)
    assert refused["state"] == "REFUSED"
    assert client.get_registered_model(REGISTRY_MODEL_NAME).aliases["champion"] == str(
        historical.version
    )
    assert len(list(client.search_model_versions(f"name = '{REGISTRY_MODEL_NAME}'"))) == 10
    assert result["versions"][-1]["system"] == "Auto-router"


def test_gate_cannot_substitute_old_router():
    import yaml

    cfg = fixture_config("Auto-router")
    check = champion_check(yaml.safe_dump(cfg))
    assert not check["passed"]
    assert len(check["routes"]) == 3
    assert all("run_config.py" in r["file"] for r in check["routes"])
    cfg = RunConfig(system_id="S8", provider="mock").model_dump(mode="json")
    check = champion_check(yaml.safe_dump(cfg))
    assert not check["passed"]
    assert all(r["stage"] == "graph identity" for r in check["routes"])


def test_explicit_settings_never_expand_or_load_model_keys(tmp_path, monkeypatch, capsys):
    from bugzilla_serving.tracking.environment import load_settings

    monkeypatch.delenv("MLFLOW_TRACKING_PASSWORD", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    path = tmp_path / "settings.env"
    path.write_text(
        'MLFLOW_TRACKING_PASSWORD="literal#value$(noop)" # comment\n'
        "GROQ_API_KEY=fixture-provider-value\n"
    )
    load_settings(path)
    import os

    assert os.environ["MLFLOW_TRACKING_PASSWORD"] == "literal#value$(noop)"
    assert "GROQ_API_KEY" not in os.environ
    assert not capsys.readouterr().out
