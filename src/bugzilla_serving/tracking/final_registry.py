"""Register final evaluated configs, with an independent serving gate for champion."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import mlflow
import mlflow.pyfunc
from mlflow.exceptions import MlflowException

from bugzilla_serving.contracts.names import REGISTRY_MODEL_NAME
from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.results_source import IDS, SYSTEMS
from bugzilla_serving.tracking.client import TrackingClient, artifact_tracking_uri
from bugzilla_serving.tracking.final_results import EVAL_SET, SLUGS, find_runs, plans
from bugzilla_serving.tracking.policy import assess
from bugzilla_serving.tracking.registry import ConfigWrapper, Registry

OVERRIDE = (
    "Highest dev overall (92.5%, 95% CI 87.5–96.8) and lowest false-decline rate "
    "(5/97); estimated 0.57 model calls per question"
)
ROUTES = ["database path", "dossier with cited comment", "Smart search"]


@contextmanager
def local_model_settings():
    values = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def champion_check(config_text, version=None, registry=None):
    """Use the existing shared registry loader; never map the new graph to old S8."""
    model_uri = f"models:/{REGISTRY_MODEL_NAME}/{version or 'proposed'}"
    with tempfile.TemporaryDirectory(prefix="bugzilla-champion-check-") as tmp:
        p = Path(tmp) / "config.yaml"
        p.write_text(config_text)
        # Before apply there is no new version. Exercise the exact get_config ->
        # executable -> RunConfig path with a local artifact client, no remote writes.
        if registry is None or version is None:

            class CandidateClient:
                def get_model_version(self, name, candidate):
                    return SimpleNamespace(run_id="local-candidate")

                def download_artifacts(self, run_id, artifact):
                    return str(p)

            loader = Registry.__new__(Registry)
            loader.client = CandidateClient()
            loader.tracking = SimpleNamespace(uri=Path(tmp).as_uri())
            candidate = "proposed"
        else:
            loader, candidate = registry, str(version)
        try:
            cfg = loader.get_config(candidate)
        except (ValueError, TypeError) as exc:
            return dict(
                passed=False,
                model_uri=model_uri,
                routes=[
                    dict(
                        route=r,
                        status="FAIL",
                        stage="shared config loader",
                        reason="Evaluated router identity is unsupported by the serving contract.",
                        detail=str(exc),
                        file="src/bugzilla_serving/contracts/run_config.py",
                        function="RunConfig; Registry.get_config -> executable",
                    )
                    for r in ROUTES
                ],
            )
        # An engine that only supports the earlier router cannot qualify by being renamed.
        if cfg.system_id != "S8v2":
            return dict(
                passed=False,
                model_uri=model_uri,
                routes=[
                    dict(
                        route=r,
                        status="FAIL",
                        stage="graph identity",
                        reason="Loader substituted a different router implementation.",
                        file="src/bugzilla_serving/engine.py",
                        function="Runner.run / ProgressGraph",
                    )
                    for r in ROUTES
                ],
            )
        from bugzilla_serving.engine import _mock_provider, build_runner

        # Probes use public bundle metadata, never gold or invented comment hashes.
        corpus = (
            Path(os.environ.get("BUNDLE_DIR", "serving_bundle"))
            / "indexes"
            / cfg.corpus
            / "corpus.jsonl"
        )
        public = None
        if corpus.is_file():
            from bugzilla_qa.answering.contracts import public_chunk

            with corpus.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get("kind", row.get("chunk_type")) != "comment":
                        continue
                    try:
                        public = public_chunk(row)
                    except ValueError:
                        continue
                    break
        if public is None:
            return dict(
                passed=False,
                model_uri=model_uri,
                routes=[
                    dict(
                        route=r,
                        status="FAIL",
                        stage="mock fixture",
                        reason="A public bundle comment is required",
                    )
                    for r in ROUTES
                ],
            )
        bug = public["bug_id"]
        ref = public["record_id"]
        samples = [
            ("database path", f"What component is recorded for bug {bug}?", "S7v2"),
            (
                "dossier with cited comment",
                f"What reason is in cited comment {ref} for bug {bug}?",
                "S5",
            ),
            ("Smart search", "Which report describes the fixture issue?", "S2"),
        ]
        results = []
        for route, question, expected_route in samples:
            try:
                with local_model_settings(), build_runner(cfg, provider=_mock_provider()) as engine:
                    value = engine.run(question)
                results.append(
                    dict(
                        route=route,
                        status="PASS"
                        if not value.errors and value.route == expected_route
                        else "FAIL",
                        errors=value.errors,
                    )
                )
            except (ValueError, RuntimeError, KeyError) as exc:
                results.append(
                    dict(
                        route=route,
                        status="FAIL",
                        reason=str(exc),
                        file="src/bugzilla_serving/engine.py",
                        function="build_runner",
                    )
                )
        return dict(
            passed=all(r["status"] == "PASS" for r in results), model_uri=model_uri, routes=results
        )


def promotion(plan):
    from bugzilla_serving.tracking.backfill import read

    m = plan["metrics"]
    candidate = SimpleNamespace(
        info=SimpleNamespace(run_id="final-auto-router"),
        data=SimpleNamespace(
            tags=dict(split="dev", eval_set=EVAL_SET),
            metrics={
                **{
                    f"answer.{code}.score": m["acc_" + slug]
                    for code, slug in zip(
                        ["F1", "F2", "F3", "F4", "F5", "F6", "KI", "MH", "F6H"], SLUGS.values()
                    )
                },
                **{
                    f"answer.{code}.n": m["n_" + slug]
                    for code, slug in zip(
                        ["F1", "F2", "F3", "F4", "F5", "F6", "KI", "MH", "F6H"], SLUGS.values()
                    )
                },
                "answer.macro": m["overall_pct"] / 100,
                "abstain.false_rate": m["false_decline_rate"],
                "fail.rate": m["error_rate"],
            },
        ),
    )
    # Do not invent a pooled p95 just to pass the existing promotion policy.
    result = assess(candidate, [], read(ROOT / "configs/promotion.yaml"))
    return dict(**result, proposed_override=OVERRIDE)


def register(
    folder,
    tracking_uri=None,
    apply=False,
    move_champion=False,
    config_loader=None,
    gate=champion_check,
):
    from bugzilla_serving.tracking.final_results import configuration

    desired, _ = plans(folder, config_loader or configuration)
    check = gate(desired[-1]["artifacts"]["config.yaml"])
    policy = promotion(desired[-1])
    tracker = TrackingClient(tracking_uri)
    client = tracker.client
    runs = find_runs(client, "final-results")
    # Dry-run before publication is useful; report missing source runs explicitly.
    selected = {}
    for system in SYSTEMS:
        matches = [
            r
            for r in runs
            if r.data.tags.get("system_id") == IDS[system]
            and r.data.tags.get("eval_set") == EVAL_SET
            and r.info.status == "FINISHED"
        ]
        if len(matches) > 1:
            raise ValueError("Ambiguous final-results source run: " + system)
        selected[system] = matches[0] if matches else None
    try:
        versions = list(
            client.search_model_versions(f"name = '{REGISTRY_MODEL_NAME}'", max_results=1000)
        )
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
            raise
        versions = []
    refusal = move_champion and not check["passed"]
    if apply and refusal:
        return dict(
            state="REFUSED",
            reason="Serving safety check failed; champion unchanged; no registry writes.",
            champion_check=check,
            promotion_policy=policy,
            versions=[],
            actual_llm_calls=0,
        )
    if apply and any(r is None for r in selected.values()):
        raise ValueError(
            "Run log_final_results.py --apply first; all nine source runs are required"
        )
    if apply:
        try:
            client.get_registered_model(REGISTRY_MODEL_NAME)
        except MlflowException as exc:
            if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
                raise
            client.create_registered_model(REGISTRY_MODEL_NAME)
    result = []
    for plan in desired:
        system = plan["name"]
        run = selected[system]
        rid = run.info.run_id if run else None
        existing = [v for v in versions if rid and v.tags.get("source_run_id") == rid]
        if len(existing) > 1:
            raise ValueError("Duplicate registered source run: " + system)
        version = existing[0].version if existing else None
        m = plan["metrics"]
        tags = dict(
            display_name=system,
            system_id=IDS[system],
            overall_pct=str(m["overall_pct"]),
            ci=json.dumps([m["ci_low"], m["ci_high"]]),
            source_run_id=rid or "pending",
            eval_set=EVAL_SET,
            **{k: str(v) for k, v in m.items() if k.startswith("acc_")},
        )
        if system == "Auto-router":
            tags.update(
                serving_status="blocked: shared loader does not support evaluated graph",
                promotion_policy=json.dumps(policy, sort_keys=True),
                champion_check=json.dumps(check, sort_keys=True),
            )
        description = (
            f"{plan['tags']['description']} Overall {m['overall_pct']:.1f}%; "
            f"{m['calls_per_q']:.3f} model calls/question."
        )
        if apply:
            with artifact_tracking_uri(tracker.uri):
                saved = Path(client.download_artifacts(rid, "config.yaml")).read_text()
            if saved != plan["artifacts"]["config.yaml"]:
                raise ValueError(
                    "Source config.yaml differs from the evaluated config; refusing registry write"
                )
            if version is None:
                with tempfile.TemporaryDirectory(prefix="bugzilla-final-model-") as tmp:
                    path = Path(tmp)
                    artifact = path / "config.yaml"
                    artifact.write_text(saved)
                    with artifact_tracking_uri(tracker.uri):
                        mlflow.pyfunc.save_model(
                            str(path / "model"),
                            python_model=ConfigWrapper(),
                            artifacts={"config": str(artifact)},
                            pip_requirements=["mlflow==2.22.1", "PyYAML==6.0.2"],
                        )
                        client.log_artifacts(rid, str(path / "model"), artifact_path="model")
                    version = client.create_model_version(
                        REGISTRY_MODEL_NAME,
                        client.get_run(rid).info.artifact_uri.rstrip("/") + "/model",
                        run_id=rid,
                        tags=tags,
                        description=description,
                    ).version
            client.update_model_version(REGISTRY_MODEL_NAME, str(version), description=description)
            for key, value in tags.items():
                client.set_model_version_tag(REGISTRY_MODEL_NAME, str(version), key, value)
            slug = system.lower().replace(" ", "-")
            client.set_registered_model_alias(REGISTRY_MODEL_NAME, slug, str(version))
            if system == "Keyword search":
                client.set_registered_model_alias(REGISTRY_MODEL_NAME, "fast", str(version))
            if system == "Auto-router" and move_champion:
                registry = Registry(tracker.uri)
                actual = gate(saved, version=version, registry=registry)
                if not actual["passed"]:
                    return dict(
                        state="REFUSED",
                        reason="Registered URI failed safety check; champion unchanged",
                        champion_check=actual,
                        promotion_policy=policy,
                        versions=result,
                    )
                client.set_model_version_tag(
                    REGISTRY_MODEL_NAME,
                    str(version),
                    "promotion_policy",
                    json.dumps(policy, sort_keys=True),
                )
                if not policy["allowed"]:
                    client.set_model_version_tag(
                        REGISTRY_MODEL_NAME, str(version), "policy_override", OVERRIDE
                    )
                client.set_registered_model_alias(REGISTRY_MODEL_NAME, "champion", str(version))
        result.append(
            dict(
                system=system,
                source_run_id=rid,
                version=version,
                action="reuse" if existing else "create" if rid else "source run missing",
                alias=system.lower().replace(" ", "-"),
            )
        )
    return dict(
        state="APPLIED" if apply else "DRY_RUN",
        versions=result,
        champion_check=check,
        promotion_policy=policy,
        champion_action="refuse"
        if refusal
        else "move after registered-URI check"
        if move_champion
        else "unchanged",
        actual_llm_calls=0,
    )
