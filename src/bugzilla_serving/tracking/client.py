"""Validated tracking writes; importing this module never connects to a service."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

import yaml

from bugzilla_serving.contracts.names import EXPERIMENTS, validate_mlflow_run
from bugzilla_serving.contracts.run_config import RunConfig, config_hash

_ARTIFACT_URI_LOCK = RLock()


@contextmanager
def artifact_tracking_uri(uri):
    """MLflow 2.x resolves mlflow-artifacts:/ via global URI, even on explicit clients."""
    import mlflow

    with _ARTIFACT_URI_LOCK:
        previous = mlflow.get_tracking_uri()
        previous_env = os.environ.get("MLFLOW_TRACKING_URI")
        try:
            mlflow.set_tracking_uri(uri)
            yield
        finally:
            mlflow.set_tracking_uri(previous)
            if previous_env is None:
                os.environ.pop("MLFLOW_TRACKING_URI", None)
            else:
                os.environ["MLFLOW_TRACKING_URI"] = previous_env


def params_for(config: RunConfig) -> dict:
    return {
        **{
            k: v if isinstance(v, str) else json.dumps(v)
            for k, v in config.model_dump(mode="json").items()
        },
        "config_hash": config_hash(config),
    }


def assert_no_secrets(value: str | bytes) -> None:
    data = value.encode() if isinstance(value, str) else value
    for name, secret in os.environ.items():
        if any(word in name for word in ("KEY", "PASSWORD", "TOKEN", "SECRET")):
            if secret and len(secret) >= 8 and secret.encode() in data:
                raise ValueError("Secret value refused before tracking write")


class TrackingClient:
    def __init__(self, tracking_uri: str | None = None):
        from mlflow.tracking import MlflowClient

        uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
        if not uri:
            raise ValueError("Set MLFLOW_TRACKING_URI or --tracking-uri")
        if urlsplit(uri).username or urlsplit(uri).password:
            raise ValueError("Use MLflow credential environment variables, not a credential URI")
        self.uri = uri
        self.client = MlflowClient(tracking_uri=uri, registry_uri=uri)

    def runs(self, experiment: str) -> list:
        exp = self.client.get_experiment_by_name(experiment)
        if not exp:
            return []
        result, token = [], None
        while True:
            page = self.client.search_runs([exp.experiment_id], max_results=1000, page_token=token)
            result.extend(page)
            token = getattr(page, "token", None)
            if not token:
                return result

    def log_run(self, experiment, params, tags, metrics, artifacts):
        """Upsert (source, config_hash, eval_set); never downgrade ledger provenance.

        Config changes are different runs. A review-only -> ledger upgrade requires
        the same canonical config; a conflicting historical config is refused.
        Artifacts are aggregate-only strings or prepared model directories.
        """
        validate_mlflow_run(params, tags, metrics)
        if experiment not in EXPERIMENTS:
            raise ValueError("Unknown experiment")
        tags = {**tags, "config_hash": params["config_hash"]}
        for value in (params, tags, metrics):
            assert_no_secrets(json.dumps(value))
        for name, value in artifacts.items():
            assert_no_secrets(name)
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Unsafe artifact name")
            if isinstance(value, Path):
                for file in value.rglob("*") if value.is_dir() else [value]:
                    if file.is_file():
                        assert_no_secrets(file.read_bytes())
            else:
                assert_no_secrets(value)
        # Hash content, not temporary artifact paths. Checkpoints live on the remote
        # run, so resume also works from another machine without a local state file.
        artifact_hashes = {}
        for name, value in artifacts.items():
            h = hashlib.sha256()
            if isinstance(value, Path):
                files = sorted(value.rglob("*")) if value.is_dir() else [value]
                for file in files:
                    if file.is_file():
                        relative = file.relative_to(value) if value.is_dir() else Path(file.name)
                        h.update(str(relative).encode())
                        h.update(file.read_bytes())
            else:
                h.update(value.encode("utf-8"))
            artifact_hashes[name] = h.hexdigest()
        upload_hash = hashlib.sha256(
            json.dumps([params, tags, metrics, artifact_hashes], sort_keys=True).encode()
        ).hexdigest()
        runs = self.runs(experiment)
        matches = [
            r
            for r in runs
            if all(r.data.tags.get(k) == tags[k] for k in ("source", "config_hash", "eval_set"))
        ]
        # Do not silently create a second system run when historical reconstruction differed.
        if experiment == "research-answer-eval" and not matches:
            conflict = [
                r
                for r in runs
                if r.data.tags.get("source") == tags["source"]
                and r.data.tags.get("eval_set") == tags["eval_set"]
                and r.data.params.get("system_id") == params["system_id"]
            ]
            if conflict:
                raise ValueError(
                    "Historical config conflict: reconcile config before ledger upgrade"
                )
        if len(matches) > 1:
            raise ValueError("Duplicate tracking identity exists; inspect without overwriting")
        if matches:
            old = matches[0]
            if old.data.params != params:
                raise ValueError("Immutable MLflow params differ; refusing overwrite")
            if (
                old.data.tags.get("provenance") == "ledgers"
                and tags.get("provenance") == "review-only"
            ):
                self.last_action = "skipped_ledger_downgrade"
                return old.info.run_id
            run_id = old.info.run_id
            if old.data.tags.get("tracking.upload_sha256") == upload_hash:
                if old.info.status != "FINISHED":
                    self.client.set_terminated(run_id)
                self.last_action = "skipped_complete"
                return run_id
        else:
            exp = self.client.get_experiment_by_name(experiment)
            exp_id = exp.experiment_id if exp else self.client.create_experiment(experiment)
            run_id = self.client.create_run(exp_id, tags=tags).info.run_id
        from mlflow.entities import Metric, Param, RunTag

        old_params = matches[0].data.params if matches else {}
        old_metrics = matches[0].data.metrics if matches else {}
        old_tags = matches[0].data.tags if matches else {}
        timestamp = int(time.time() * 1000)
        pending_metrics = [
            Metric(key, float(value), timestamp, 0)
            for key, value in metrics.items()
            if old_metrics.get(key) != float(value)
        ]
        pending_params = [
            Param(key, str(value)) for key, value in params.items() if key not in old_params
        ]
        pending_tags = [
            RunTag(key, str(value))
            for key, value in tags.items()
            if old_tags.get(key) != str(value)
        ]
        # MLflow accepts <=100 params/tags and <=1000 entities per batch.
        # Keep batches at 100 metrics for conservative compatibility with DagsHub.
        for offset in range(0, max(len(pending_metrics), 1), 100):
            self.client.log_batch(
                run_id,
                metrics=pending_metrics[offset : offset + 100],
                params=pending_params if offset == 0 else [],
                tags=pending_tags if offset == 0 else [],
            )
        with (
            artifact_tracking_uri(self.uri),
            tempfile.TemporaryDirectory(prefix="bugzilla-tracking-") as tmp,
        ):
            for name, value in artifacts.items():
                checkpoint = "tracking.artifact." + hashlib.sha256(name.encode()).hexdigest()[:16]
                if old_tags.get(checkpoint) == artifact_hashes[name]:
                    continue
                if isinstance(value, Path):
                    if value.is_dir():
                        self.client.log_artifacts(run_id, str(value), artifact_path=name)
                    else:
                        self.client.log_artifact(
                            run_id, str(value), artifact_path=str(Path(name).parent)
                        )
                else:
                    file = Path(tmp) / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(value, encoding="utf-8")
                    parent = str(Path(name).parent)
                    self.client.log_artifact(run_id, str(file), None if parent == "." else parent)
                self.client.set_tag(run_id, checkpoint, artifact_hashes[name])
        # Written only after every artifact succeeds. A crash retries only unfinished work.
        self.client.set_tag(run_id, "tracking.upload_sha256", upload_hash)
        self.client.set_terminated(run_id)
        self.last_action = "uploaded"
        return run_id


def config_artifact(config: RunConfig) -> str:
    return yaml.safe_dump(config.model_dump(mode="json"), sort_keys=True)
