"""Exercise the actual V2 graph through API and Lab; no network or model weights."""

import hashlib
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from bugzilla_qa.llm.provider import MockProvider
from bugzilla_serving.api import app as api
from bugzilla_serving.api.presets import PresetStore
from bugzilla_serving.contracts.run_config import ROOT, RunConfig, config_hash
from bugzilla_serving.experiments import runner as lab
from bugzilla_serving.experiments.fixtures import build_fixture_runner

REF = "a" * 64
CASES = [
    ("What component is recorded for bug 100000?", "S7v2", False),
    (f"What reason is in cited comment {REF} for bug 100000?", "S5", False),
    ("Which report describes an imaginary keyboard widget?", "S2", False),
    ("How many engineering work hours for bug 100000?", "S7v2", True),
]


class CitedMock(MockProvider):
    def __init__(self):
        super().__init__(None)

    def generate_json(self, prompt, schema, **kwargs):
        if "queries" in schema.get("properties", {}):
            self.value = {"queries": ["imaginary keyboard widget"] * 3}
        else:
            payload = json.loads(prompt)
            mapping = payload.get("citation_map", {})
            ids = list(mapping.values())
            self.value = dict(
                abstain=False,
                answer="Synthetic explanation",
                answer_type="string",
                bug_ids=[100000],
                citations=([i for i in ids if i.startswith("comment-")] or ids)[:1],
                rationale="The public fixture supports this.",
            )
        return super().generate_json(prompt, schema, **kwargs)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import httpx
    import requests

    from bugzilla_serving.experiments.fixtures import build_synthetic_bundle

    def denied(*a, **kw):
        raise AssertionError("Network forbidden in parity proof")

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(key, "false")
    bundle = build_synthetic_bundle(tmp_path)
    # A legal synthetic comment record hash; preserve chunk IDs used by tool citations.
    for corpus in ("C0", "C1", "C2"):
        path = bundle / "indexes" / corpus / "corpus.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            if row["chunk_id"] == "comment-100000:0":
                row["record_id"] = REF
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        manifest = path.parent / "manifest.json"
        value = json.loads(manifest.read_text())
        value["sha256"]["corpus.jsonl"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(value))
    path = bundle / "indexes/manifest.json"
    value = json.loads(path.read_text())
    for corpus in ("C0", "C1", "C2"):
        value["sha256"][corpus + "/manifest.json"] = hashlib.sha256(
            (bundle / "indexes" / corpus / "manifest.json").read_bytes()
        ).hexdigest()
    path.write_text(json.dumps(value))
    path = bundle / "manifest.json"
    value = json.loads(path.read_text())
    for name in value["files"]:
        file = bundle / name
        value["files"][name] = dict(
            bytes=file.stat().st_size, sha256=hashlib.sha256(file.read_bytes()).hexdigest()
        )
    path.write_text(json.dumps(value))
    monkeypatch.setenv("BUNDLE_DIR", str(bundle))
    monkeypatch.setenv("SERVING_API_KEY", "parity-test-key")
    monkeypatch.setenv("SERVING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TRACE_SAMPLE", "0")
    monkeypatch.setattr(PresetStore, "_registry", Mock(side_effect=RuntimeError("offline")))
    cfg = RunConfig(
        system_id="S8v2",
        provider="mock",
        top_k=10,
        s5_dossier_budget=4096,
        serving_bug_scope=True,
        router_rules_version="json-tools-v2",
        tool_route_version="json-tools-v2",
    )
    cfg.validate_against(mode="execute")
    monkeypatch.setattr(api, "build_runner", lambda c: build_fixture_runner(c, CitedMock()))
    return cfg


def test_four_routes_api_lab_parity(setup, tmp_path, monkeypatch):
    cfg = setup
    records = []
    with TestClient(api.create_app()) as client:
        for question, route, abstain in CASES:
            response = client.post(
                "/v1/ask",
                headers={"X-API-Key": "parity-test-key"},
                json={
                    "session_id": "parity",
                    "message": question,
                    "preset_slug": "recommended",
                    "overrides": cfg.model_dump(),
                },
            )
            assert response.status_code == 200, response.text
            record = response.json()["record"]
            assert record["route"] == route and record["answer"]["abstain"] == abstain
            assert not record["errors"]
            if route == "S5":
                assert "comment-100000:0" in record["answer"]["citations"]
            records.append(record)
    items = [
        dict(
            question=q,
            qid=str(i),
            dataset="synthetic",
            split="dev",
            family="F6",
            freeze_id="synthetic",
            cluster_id=str(i),
            kind="unanswerable",
            expected=None,
            evidence=[],
            dataset_notes={},
            tolerance_hours=0,
        )
        for i, (q, _, _) in enumerate(CASES)
    ]
    monkeypatch.setattr(lab, "load_eval_set", lambda *a, **kw: (items, {"synthetic": "fixed"}))
    result = lab.run_experiment(
        cfg,
        "parity",
        4,
        provider=CitedMock(),
        build=build_fixture_runner,
        jobs_dir=tmp_path / "jobs",
        tracking_uri=(tmp_path / "mlruns").as_uri(),
    )
    assert result["state"] == "COMPLETED", result
    rows = [
        json.loads(line)
        for line in (tmp_path / "jobs" / result["id"] / "predictions.jsonl")
        .read_text()
        .splitlines()
    ]
    for api_record, lab_record in zip(records, rows):
        assert api_record["answer"] == lab_record["answer"]
        assert api_record["route"] == lab_record["route"]
        assert api_record["config_hash"] == lab_record["config_hash"] == config_hash(cfg)


def test_v2_cap_and_legacy_hash():
    with pytest.raises(ValueError, match="4096"):
        RunConfig(system_id="S8v2", s5_dossier_budget=12000).validate_against()
    assert (
        config_hash(RunConfig(system_id="S2", provider="mock"))
        == json.loads((ROOT / "tests/fixtures/config_hashes.json").read_text())["S2"]
    )


@pytest.mark.parametrize("system", ["S8v2", "S2", "S1", "S5", "R0"])
def test_outside_archive_all_modes(setup, system):
    from bugzilla_serving.engine import build_runner

    cfg = RunConfig(system_id=system, provider="mock")
    provider = CitedMock()
    with build_runner(cfg, provider) as runner:
        value = runner.run("Tell me about bug 1000000")
    assert value.route == "outside_archive" and value.llm_calls == provider.calls == 0
    assert value.answer.abstain and "Bug 1000000 isn't in the 3,000-bug" in value.answer.rationale
    assert "https://bugzilla.mozilla.org/show_bug.cgi?id=1000000" in value.answer.rationale


def test_demo_check_mock_against_api(setup, tmp_path):
    import argparse
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "demo_check", ROOT / "scripts/testing/demo_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = argparse.Namespace(
        mock=True,
        live=False,
        case=None,
        limit=None,
        max_requests=None,
        dry_run=False,
        output=tmp_path / "check.json",
        resume=None,
    )
    with TestClient(api.create_app()) as client:

        def send(path, body=None):
            response = client.request(
                "POST" if body else "GET", path, headers={"X-API-Key": "parity-test-key"}, json=body
            )
            assert response.status_code == 200, response.text
            return response.json()

        result = module.run(args, send)
    assert result["state"] == "PASS"
    assert len(result["rows"]) == 4
    args.mock, args.live, args.case, args.cases = (
        False,
        True,
        "field,cited-why,find-description-1,outside",
        ROOT / "tests/demo/demo_cases.yaml",
    )
    args.max_requests = 4
    sender = Mock()
    with pytest.raises(ValueError, match="at least 5"):
        module.run(args, sender)
    sender.assert_not_called()


def test_v2_quota_degrades_to_r0(setup):
    from types import SimpleNamespace

    from bugzilla_serving.quota import degraded_config

    degraded = degraded_config(setup)
    assert degraded.system_id == "R0" and degraded.serving_bug_scope
    assert degraded.router_rules_version is degraded.tool_route_version is None
    with TestClient(api.create_app()) as client:
        client.app.state.quota_check = lambda c: SimpleNamespace(
            action="degrade", reason="Demo quota"
        )
        response = client.post(
            "/v1/ask",
            headers={"X-API-Key": "parity-test-key"},
            json={
                "session_id": "quota-v2",
                "message": "Comments on bug 100000",
                "preset_slug": "recommended",
                "overrides": setup.model_dump(),
            },
        )
        assert response.status_code == 200, response.text
        record = response.json()["record"]
        assert record["degraded"] and record["route"] == "R0" and record["llm_calls"] == 0
        assert {e["bug_id"] for e in record["evidence"]} == {"100000"}


def test_existing_bug_outside_tool_coverage_uses_dossier(setup):
    with build_fixture_runner(setup, CitedMock()) as runner:
        result = runner.run("How many comments are there on bug 100000?")
    assert result.route == "S5" and result.route_rule == "database_coverage_dossier_serving"
    assert not result.errors and result.llm_calls == 1
    assert "comment-100000:0" in result.answer.citations


def test_refused_population_does_not_fall_back_to_dossier(setup):
    with build_fixture_runner(setup, CitedMock()) as runner:
        result = runner.run("How many bugs in the test partition for bug 100000?")
    assert result.route == "S7v2" and result.answer.abstain
    assert result.llm_calls == 0 and not result.errors
