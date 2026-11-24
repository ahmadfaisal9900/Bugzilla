"""Load published MLflow configurations with a five-minute cache and local fallback."""

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import yaml

from bugzilla_serving.contracts.api_models import Preset
from bugzilla_serving.contracts.names import CHAMPION_ALIAS, REGISTRY_MODEL_NAME
from bugzilla_serving.contracts.run_config import ROOT, RunConfig, config_hash


class PresetStore:
    def __init__(self):
        self._items = []
        self._expires = 0
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if time.monotonic() >= self._expires:
                try:
                    self._items = self._registry()
                except Exception:
                    fallback = yaml.safe_load((ROOT / "configs/presets.yaml").read_text())
                    self._items = [Preset.model_validate(p) for p in fallback["presets"]]
                if not self._items:
                    raise RuntimeError("No valid presets available")
                for item in self._items:
                    item.config.validate_against()
                self._expires = time.monotonic() + 300
            return list(self._items)

    def _registry(self):
        from mlflow.tracking import MlflowClient

        uri = os.environ.get("MLFLOW_TRACKING_URI")
        if not uri:
            raise RuntimeError("MLflow tracking URI is not configured")
        if uri.startswith("file:"):
            parsed = urlsplit(uri)
            if parsed.netloc not in ("", "localhost"):
                raise ValueError("Remote file stores are not supported")
            uri = Path(url2pathname(parsed.path)).resolve().as_uri()
        client = MlflowClient(tracking_uri=uri, registry_uri=uri)
        versions = client.search_model_versions(f"name='{REGISTRY_MODEL_NAME}'")
        try:
            champion = client.get_model_version_by_alias(
                REGISTRY_MODEL_NAME, CHAMPION_ALIAS
            ).version
        except Exception:
            champion = None
        items = {}
        for version in sorted(
            versions, key=lambda v: (v.version == champion, int(v.version)), reverse=True
        ):
            tags = version.tags
            is_champion = str(version.version) == str(champion)
            slug = "recommended" if is_champion else tags.get("preset_slug")
            if (not is_champion and tags.get("published") != "true") or slug in items:
                continue
            try:
                params = client.get_run(version.run_id).data.params
                if set(RunConfig.model_fields) <= params.keys():
                    values = {}
                    for field in RunConfig.model_fields:
                        raw = params[field]
                        try:
                            values[field] = json.loads(raw)
                        except ValueError:
                            values[field] = raw
                    config = RunConfig(**values).validate_against(mode="execute")
                else:
                    # Standalone registry versions carry config.yaml rather than run params.
                    from bugzilla_serving.tracking.client import artifact_tracking_uri
                    from bugzilla_serving.tracking.registry import executable

                    with artifact_tracking_uri(uri):
                        path = client.download_artifacts(version.run_id, "config.yaml")
                    config = executable(yaml.safe_load(Path(path).read_text()))
                expected = params.get("config_hash") or tags.get("config_hash")
                if expected != config_hash(config):
                    continue
                preset = Preset(
                    slug=slug,
                    label="Recommended" if is_champion else tags["preset_label"],
                    description=tags.get("preset_description", "Registry champion"),
                    config=config,
                    is_champion=is_champion,
                )
            except (ValueError, KeyError, TypeError):
                continue
            items[preset.slug] = preset
        if not items:
            raise RuntimeError("No published valid configurations")
        return list(items.values())
