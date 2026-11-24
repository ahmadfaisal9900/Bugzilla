#!/usr/bin/env python3
"""Seed local synthetic tracking runs and config presets. Never contacts DagsHub."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from bugzilla_serving.contracts.names import (
    CHAMPION_ALIAS,
    EXPERIMENTS,
    REGISTRY_MODEL_NAME,
    validate_mlflow_run,
)
from bugzilla_serving.contracts.run_config import RunConfig, config_hash


def local_tracking_uri(tracking_uri: str) -> str:
    parts = urlsplit(tracking_uri)
    if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
        raise ValueError("tracking-uri: Phase 0 seed accepts only a local file: store")
    if not parts.path or parts.query or parts.fragment:
        raise ValueError("tracking-uri: expected a local file path without query or fragment")
    return Path(url2pathname(parts.path)).resolve().as_uri()


def seed(tracking_uri: str) -> dict:
    uri = local_tracking_uri(tracking_uri)
    import mlflow
    import mlflow.pyfunc
    import yaml
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    previous, registry = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    created = 0
    versions = []

    class ConfigWrapper(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            with open(context.artifacts["config"], encoding="utf-8") as f:
                self.config = yaml.safe_load(f)

        def predict(self, context, model_input: list[str], params: dict | None = None) -> list[str]:
            return [json.dumps(self.config, sort_keys=True) for _ in range(len(model_input))]

    try:
        try:
            client.get_registered_model(REGISTRY_MODEL_NAME)
        except mlflow.exceptions.MlflowException as exc:
            if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
                raise
            client.create_registered_model(REGISTRY_MODEL_NAME)
        for experiment in EXPERIMENTS:
            exp = client.get_experiment_by_name(experiment)
            exp_id = exp.experiment_id if exp else client.create_experiment(experiment)
            for i, system in enumerate(("S2", "S1", "S5")):
                cfg = RunConfig(system_id=system, provider="mock", top_k=3 + i).validate_against()
                params = {
                    k: json.dumps(v) if not isinstance(v, str) else v
                    for k, v in cfg.model_dump(mode="json").items()
                }
                params["config_hash"] = config_hash(cfg)
                tags = dict(
                    source="ci",
                    eval_set="synthetic-dev-10",
                    datasets="synthetic",
                    split="dev",
                    scorer="synthetic-fixture",
                    git_sha="synthetic",
                    phase0_seed="v1",
                    seed_index=str(i),
                )
                metrics = {
                    "answer.F1.score": 0.5 + i / 10,
                    "answer.F1.n": 10,
                    "answer.macro": 0.5 + i / 10,
                    "abstain.correct_rate": 1.0,
                    "abstain.false_rate": 0.0,
                    "fail.rate": 0.0,
                    "cost.llm_calls": 0,
                    "cost.tokens_in": 0,
                    "cost.tokens_out": 0,
                    "latency.p50_ms": 10.0,
                    "latency.p95_ms": 20.0,
                }
                if experiment == "research-retrieval-eval":
                    metrics = {"retr.v3.F1.recall_at_10": 0.5, "retr.v3.F1.n": 10}
                validate_mlflow_run(params, tags, metrics)
                existing = client.search_runs(
                    [exp_id],
                    filter_string=(
                        f"params.config_hash = '{params['config_hash']}' "
                        f"and tags.source = 'ci' and tags.phase0_seed = 'v1' "
                        f"and tags.seed_index = '{i}'"
                    ),
                )
                run_id = existing[0].info.run_id if existing else None
                if run_id and existing[0].info.status != "FINISHED":
                    raise RuntimeError(
                        "Incomplete seed run exists; preserve it and inspect before retry"
                    )
                if not run_id:
                    with tempfile.TemporaryDirectory(prefix="bugzilla-mlflow-seed-") as tmp:
                        folder = Path(tmp)
                        (folder / "config.yaml").write_text(
                            yaml.safe_dump(cfg.model_dump(mode="json"))
                        )
                        (folder / "per_family.csv").write_text("family,score,n\nF1,0.5,10\n")
                        (folder / "predictions.jsonl").write_text(
                            json.dumps(
                                {
                                    "qid": "synthetic-00",
                                    "split": "dev",
                                    "synthetic": True,
                                    "answer": None,
                                    "abstain": True,
                                }
                            )
                            + "\n"
                        )
                        with mlflow.start_run(experiment_id=exp_id, tags=tags) as run:
                            run_id = run.info.run_id
                            mlflow.log_params(params)
                            mlflow.log_metrics(metrics)
                            for name in ("config.yaml", "per_family.csv", "predictions.jsonl"):
                                mlflow.log_artifact(str(folder / name))
                            if experiment == "playground":
                                mlflow.pyfunc.log_model(
                                    artifact_path="config_model",
                                    python_model=ConfigWrapper(),
                                    artifacts={"config": str(folder / "config.yaml")},
                                    pip_requirements=["mlflow==2.22.1", "PyYAML==6.0.2"],
                                )
                    created += 1
                if experiment == "playground":
                    matches = [
                        v
                        for v in client.search_model_versions(f"name = '{REGISTRY_MODEL_NAME}'")
                        if v.run_id == run_id
                    ]
                    version = (
                        matches[0]
                        if matches
                        else client.create_model_version(
                            REGISTRY_MODEL_NAME,
                            client.get_run(run_id).info.artifact_uri + "/config_model",
                            run_id=run_id,
                        )
                    )
                    versions.append(version.version)
                    if i < 2:
                        for key, value in dict(
                            preset_slug=("recommended", "fast")[i],
                            preset_label=("Recommended", "Fast")[i],
                            preset_description="Synthetic fixture preset; no performance claim.",
                            published="true",
                        ).items():
                            client.set_model_version_tag(
                                REGISTRY_MODEL_NAME, version.version, key, value
                            )
                    if i == 0:
                        client.set_registered_model_alias(
                            REGISTRY_MODEL_NAME,
                            CHAMPION_ALIAS,
                            version.version,
                        )
        return dict(
            state="COMPLETE",
            synthetic=True,
            created_runs=created,
            expected_runs=9,
            versions=versions,
            presets=2,
            tracking_uri=uri,
        )
    finally:
        mlflow.set_tracking_uri(previous)
        mlflow.set_registry_uri(registry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.tracking_uri.startswith("file:"):
        parser.error("Phase 0 fixtures require a local file: URI")
    if args.dry_run:
        print(json.dumps({"state": "DRY_RUN", "experiments": list(EXPERIMENTS), "runs": 9}))
    else:
        print(json.dumps(seed(args.tracking_uri), sort_keys=True))


if __name__ == "__main__":
    main()
