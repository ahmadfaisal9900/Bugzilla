"""MLflow reads only; each cache entry includes its actual fetch time."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from bugzilla_serving.contracts.names import EXPERIMENTS
from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.data.common import Snapshot, now, scrub
from bugzilla_serving.dashboard.data.snapshot import directory, invalidate, load_snapshot
from bugzilla_serving.dashboard.profiling import TimedClient, measured
from bugzilla_serving.tracking.client import TrackingClient

_USED = set()


@dataclass
class Run:
    id: str
    experiment: str
    params: dict
    tags: dict
    metrics: dict
    started: int
    experiment_id: str = ""


def uri():
    return os.environ.get("MLFLOW_TRACKING_URI") or (ROOT / "outputs/mlflow/b1-local").as_uri()


@measured("mlflow.runs")
def _fetch_runs(tracking_uri: str, experiment: str) -> Snapshot[list[Run]]:
    try:
        if experiment not in EXPERIMENTS:
            raise ValueError("Unknown experiment")
        tracker = TrackingClient(tracking_uri)
        tracker.client = TimedClient(tracker.client, "mlflow")
        records = tracker.runs(experiment)
        values = [
            Run(
                r.info.run_id,
                experiment,
                scrub(r.data.params),
                scrub(r.data.tags),
                dict(r.data.metrics),
                r.info.start_time or 0,
                r.info.experiment_id,
            )
            for r in records
        ]
        return Snapshot(sorted(values, key=lambda r: r.started, reverse=True), now())
    except Exception as exc:
        return Snapshot([], now(), f"MLflow unavailable ({type(exc).__name__})")


def latest_per_config(values):
    # Preserve distinct eval sets/splits: mock and live must never replace one another.
    result = {}
    for r in sorted(values, key=lambda r: r.started, reverse=True):
        key = (
            r.experiment,
            r.params.get("config_hash"),
            r.tags.get("eval_set"),
            r.tags.get("split"),
        )
        result.setdefault(key, r)
    return list(result.values())


@measured("mlflow.champion")
def _fetch_champion(tracking_uri: str) -> Snapshot[dict | None]:
    from bugzilla_serving.tracking.registry import Registry

    try:
        registry = Registry(tracking_uri)
        registry.client = TimedClient(registry.client, "registry")
        version = registry.get_champion()
        if not version:
            return Snapshot(None, now())
        return Snapshot(
            dict(
                version=version.version,
                run_id=version.tags.get("source_run_id", version.run_id),
                config=registry.get_config(version.version).model_dump(),
                tags=scrub(version.tags),
            ),
            now(),
        )
    except Exception as exc:
        return Snapshot(None, now(), f"Registry unavailable ({type(exc).__name__})")


@measured("mlflow.presets")
def _fetch_presets(tracking_uri: str) -> Snapshot[list[dict]]:
    from bugzilla_serving.tracking.registry import Registry

    try:
        registry = Registry(tracking_uri)
        registry.client = TimedClient(registry.client, "registry")
        return Snapshot(scrub(registry.list_presets()), now())
    except Exception as exc:
        return Snapshot([], now(), f"Presets unavailable ({type(exc).__name__})")


@measured("mlflow.artifact")
def _fetch_artifact(tracking_uri: str, run_id: str, name: str) -> Snapshot[object]:
    allowed = {
        "config.yaml",
        "per_family.csv",
        "na_cells.csv",
        "intervals.json",
        "manifest.json",
        "predictions.jsonl",
        "scores.jsonl",
    }
    try:
        if name not in allowed:
            raise ValueError("Artifact not allowlisted")
        client = TimedClient(TrackingClient(tracking_uri).client, "artifact")
        run = client.get_run(run_id)
        if run.data.tags.get("split") != "dev":
            return Snapshot(
                None, now(), "Artifacts withheld: dev split only; test-aggregate metrics only"
            )
        # Missing artifacts are normal for review-only backfills.
        listing = {a.path: a for a in client.list_artifacts(run_id)}
        if name not in listing:
            return Snapshot(None, now())
        if listing[name].file_size and listing[name].file_size > 10_000_000:
            return Snapshot(None, now(), "Artifact exceeds the 10 MB interactive limit")
        with tempfile.TemporaryDirectory(prefix="dashboard-artifact-") as tmp:
            path = Path(client.download_artifacts(run_id, name, tmp))
            text = path.read_text(encoding="utf-8-sig")
        if name.endswith(".csv"):
            value = list(csv.DictReader(io.StringIO(text)))
        elif name.endswith(".jsonl"):
            value = [json.loads(line) for line in text.splitlines() if line.strip()]
            if any(
                r.get("split", "dev" if name == "scores.jsonl" else None) != "dev" for r in value
            ):
                return Snapshot(None, now(), "Non-dev prediction artifact refused")
            # Never expose gold, raw prompts, or snippets copied from unknown artifacts.
            allowed_fields = {
                "qid",
                "dataset",
                "family",
                "split",
                "system_id",
                "status",
                "answer",
                "errors",
                "route",
                "route_rule",
                "latency_ms",
                "context_chunk_ids",
                "verdict",
                "reason",
                "score",
                "scorer",
                "simulated",
            }
            value = [{k: v for k, v in r.items() if k in allowed_fields} for r in value]
        elif name.endswith(".yaml"):
            import yaml

            value = yaml.safe_load(text)
        else:
            value = json.loads(text)
        return Snapshot(scrub(value), now())
    except Exception as exc:
        return Snapshot(None, now(), f"Artifact unavailable ({type(exc).__name__})")


def _snapshot(tracking_uri):
    _USED.add(tracking_uri)
    return load_snapshot(tracking_uri)


def runs(tracking_uri, experiment):
    data = _snapshot(tracking_uri)
    return Snapshot(
        [
            Run(**r)
            for r in data["runs"].get(experiment, [])
            if r["tags"].get("split") in ("dev", "test-aggregate")
            and r["tags"].get("source") in ("backfill", "lab")
            and r["tags"].get("eval_set") != "config-registry"
        ],
        data["meta"]["built_at"],
        "; ".join(data["errors"]) or None,
    )


def champion(tracking_uri):
    return Snapshot(**_snapshot(tracking_uri)["champion"])


def presets(tracking_uri):
    return Snapshot(**_snapshot(tracking_uri)["presets"])


def checkpoint_artifact(tracking_uri, run_id, name):
    # Resume immutable artifact reads across CLI/container restarts. Filenames are
    # digests so callers cannot escape the credential-free per-source directory.
    import hashlib
    import uuid
    from dataclasses import asdict

    key = hashlib.sha256((run_id + "/" + name).encode()).hexdigest()
    folder = directory(tracking_uri) / "artifacts"
    path = folder / (key + ".json")
    if path.exists():
        try:
            return Snapshot(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError):
            pass
    result = _fetch_artifact(tracking_uri, run_id, name)
    if not result.error:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / (key + "-" + uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(asdict(result)))
        temporary.replace(path)
    return result


@st.cache_data(show_spinner=False)
def _lazy_artifact(tracking_uri, run_id, name):
    from bugzilla_serving.tracking.client import artifact_tracking_uri

    with artifact_tracking_uri(tracking_uri):
        return checkpoint_artifact(tracking_uri, run_id, name)


def artifact(tracking_uri, run_id, name):
    data = _snapshot(tracking_uri)
    cached = data["artifacts"].get(run_id + "/" + name)
    return Snapshot(**cached) if cached is not None else _lazy_artifact(tracking_uri, run_id, name)


def clear():
    for tracking_uri in list(_USED):
        invalidate(tracking_uri)
    _USED.clear()
    _lazy_artifact.clear()
    load_snapshot.clear()
