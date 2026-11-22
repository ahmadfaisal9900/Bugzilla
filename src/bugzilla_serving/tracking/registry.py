"""Configuration model versions, published presets, and the champion alias."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import mlflow.pyfunc
import yaml
from mlflow.exceptions import MlflowException

from bugzilla_serving.contracts.names import CHAMPION_ALIAS, REGISTRY_MODEL_NAME
from bugzilla_serving.contracts.run_config import RunConfig, config_hash
from bugzilla_serving.tracking.client import (
    TrackingClient,
    artifact_tracking_uri,
    assert_no_secrets,
    config_artifact,
)


class ConfigWrapper(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        self.config = yaml.safe_load(Path(context.artifacts["config"]).read_text())

    def predict(self, context, model_input: list[str], params: dict | None = None) -> list[str]:
        return [json.dumps(self.config, sort_keys=True) for _ in range(len(model_input))]


def executable(config):
    if not isinstance(config, RunConfig):
        config = RunConfig.model_validate(config)
    try:
        return config.validate_against(mode="execute")
    except ValueError as exc:
        raise ValueError(
            f"Historical config is not deployable; execute validation failed: {exc}"
        ) from None


class Registry:
    def __init__(self, tracking_uri=None):
        self.tracking = TrackingClient(tracking_uri)
        self.client = self.tracking.client

    def versions(self):
        return list(self.client.search_model_versions(f"name = '{REGISTRY_MODEL_NAME}'"))

    def register_config_version(self, config, tags):
        config = executable(config)
        assert_no_secrets(json.dumps(tags))
        h = config_hash(config)
        existing = [v for v in self.versions() if v.tags.get("config_hash") == h]
        if existing:
            return existing[0].version
        with tempfile.TemporaryDirectory(prefix="bugzilla-model-") as tmp:
            folder = Path(tmp)
            artifact = folder / "config.yaml"
            artifact.write_text(config_artifact(config))
            model = folder / "model"
            previous, registry = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
            mlflow.set_tracking_uri(self.tracking.uri)
            mlflow.set_registry_uri(self.tracking.uri)
            try:
                mlflow.pyfunc.save_model(
                    str(model),
                    python_model=ConfigWrapper(),
                    artifacts={"config": str(artifact)},
                    pip_requirements=["mlflow==2.22.1", "PyYAML==6.0.2"],
                )
            finally:
                mlflow.set_tracking_uri(previous)
                mlflow.set_registry_uri(registry)
            source_run_id = tags.get("source_run_id")
            run_id = None
            if source_run_id:
                source_run = self.client.get_run(source_run_id)
                if source_run.data.params.get("config_hash") != h:
                    raise ValueError("Source run config_hash differs from published config")
                # Attach model to the evaluated source run; no params-only carrier run.
                try:
                    with artifact_tracking_uri(self.tracking.uri):
                        self.client.log_artifacts(source_run_id, str(model), artifact_path="model")
                    run_id = source_run_id
                except MlflowException as exc:
                    # Some archived runs are immutable. Transport/auth failures
                    # must still surface rather than creating misleading carriers.
                    if exc.error_code != "PERMISSION_DENIED":
                        raise
            if run_id is None:
                exp = self.client.get_experiment_by_name("registry")
                exp_id = exp.experiment_id if exp else self.client.create_experiment("registry")
                run_id = self.client.create_run(
                    exp_id,
                    tags={
                        "source": "registry",
                        "source_run_id": source_run_id or "standalone",
                        "config_hash": h,
                    },
                ).info.run_id
                # Registry metadata is deliberately outside evaluation contracts.
                with artifact_tracking_uri(self.tracking.uri):
                    self.client.log_artifact(run_id, str(artifact))
                    self.client.log_artifacts(run_id, str(model), artifact_path="model")
                self.client.set_terminated(run_id)

        try:
            self.client.get_registered_model(REGISTRY_MODEL_NAME)
        except MlflowException as exc:
            if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
                raise
            self.client.create_registered_model(REGISTRY_MODEL_NAME)
        run = self.client.get_run(run_id)
        version = self.client.create_model_version(
            REGISTRY_MODEL_NAME,
            run.info.artifact_uri.rstrip("/") + "/model",
            run_id=run_id,
            tags={**tags, "config_hash": h},
        )
        return version.version

    def get_config(self, version):
        value = self.client.get_model_version(REGISTRY_MODEL_NAME, str(version))
        # All versions, including Phase 0, carry the pyfunc's config artifact.
        with artifact_tracking_uri(self.tracking.uri):
            path = self.client.download_artifacts(value.run_id, "config.yaml")
        return executable(yaml.safe_load(Path(path).read_text()))

    def set_champion(self, version):
        self.get_config(version)
        self.client.set_registered_model_alias(REGISTRY_MODEL_NAME, CHAMPION_ALIAS, str(version))

    def publish_preset(self, version, slug, label, description):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug):
            raise ValueError("slug: lowercase letters, digits and hyphens only")
        if not label.strip() or not description.strip():
            raise ValueError("Preset label and description are required")
        self.get_config(version)
        assert_no_secrets(json.dumps([slug, label, description]))
        self.unpublish(slug)
        for key, value in dict(
            preset_slug=slug, preset_label=label, preset_description=description, published="true"
        ).items():
            self.client.set_model_version_tag(REGISTRY_MODEL_NAME, str(version), key, value)

    def unpublish(self, slug):
        for v in self.versions():
            if v.tags.get("preset_slug") == slug and v.tags.get("published") == "true":
                self.client.set_model_version_tag(
                    REGISTRY_MODEL_NAME, v.version, "published", "false"
                )

    def get_champion(self):
        try:
            return self.client.get_model_version_by_alias(REGISTRY_MODEL_NAME, CHAMPION_ALIAS)
        except MlflowException as exc:
            if exc.error_code in ("RESOURCE_DOES_NOT_EXIST", "INVALID_PARAMETER_VALUE"):
                return None
            raise

    def list_presets(self):
        champion = self.get_champion()
        return [
            dict(
                slug=v.tags["preset_slug"],
                label=v.tags["preset_label"],
                description=v.tags["preset_description"],
                version=v.version,
                config=self.get_config(v.version).model_dump(mode="json"),
                is_champion=bool(champion and v.version == champion.version),
            )
            for v in self.versions()
            if v.tags.get("published") == "true"
        ]
