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
            if tags.get("published") != "true" or tags.get("preset_slug") in items:
                continue
            try:
                params = client.get_run(version.run_id).data.params
                values = {}
                for field in RunConfig.model_fields:
                    raw = params[field]
                    try:
                        values[field] = json.loads(raw)
                    except ValueError:
                        values[field] = raw
                config = RunConfig(**values).validate_against()
                if params.get("config_hash") != config_hash(config):
                    continue
                preset = Preset(
                    slug=tags["preset_slug"],
                    label=tags["preset_label"],
                    description=tags["preset_description"],
                    config=config,
                    is_champion=version.version == champion,
                )
            except (ValueError, KeyError, TypeError):
                continue
            items[preset.slug] = preset
        if not items:
            raise RuntimeError("No published valid configurations")
        return list(items.values())
