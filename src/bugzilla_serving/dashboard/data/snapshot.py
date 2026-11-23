"""Atomic disk snapshots. Ordinary page reads never refresh a network source."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import streamlit as st

from bugzilla_serving.contracts.names import EXPERIMENTS
from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.data.common import now, scrub
from bugzilla_serving.dashboard.profiling import measured


def safe_uri(uri):
    p = urlsplit(uri)
    return urlunsplit((p.scheme, p.netloc.rsplit("@", 1)[-1], p.path, "", ""))


def directory(uri):
    clean = safe_uri(uri)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean).strip("-")[-80:]
    key = hashlib.sha256(clean.encode()).hexdigest()[:12]
    return (
        Path(os.environ.get("DASHBOARD_CACHE_DIR", ROOT / "outputs/dashboard_cache"))
        / f"{slug}-{key}"
    )


def publish(folder, payload, meta, prefix="snapshot"):
    folder.mkdir(parents=True, exist_ok=True)
    generation = prefix + "-" + uuid.uuid4().hex + ".json"
    (folder / generation).write_text(json.dumps(payload, default=str))
    meta = {**meta, "file": generation}
    temporary = folder / (prefix + "-meta-" + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(meta, indent=2))
    temporary.replace(folder / (prefix + "_meta.json"))
    return {**payload, "meta": meta}


@measured("snapshot.build")
def _build_snapshot(tracking_uri, progress=None):
    from bugzilla_serving.dashboard.data import mlflow_source as mf
    from bugzilla_serving.dashboard.profiling import TimedClient
    from bugzilla_serving.tracking.registry import Registry

    start = time.perf_counter()
    runs, errors = {}, []
    for i, experiment in enumerate(EXPERIMENTS):
        snap = mf._fetch_runs(tracking_uri, experiment)
        if snap.error:
            errors.append(snap.error)
        runs[experiment] = [asdict(r) for r in snap.value]
        if progress:
            progress((i + 1) / 5)
    champion, presets = mf._fetch_champion(tracking_uri), mf._fetch_presets(tracking_uri)
    errors.extend(s.error for s in (champion, presets) if s.error)
    versions, aliases = [], {}
    try:
        registry = Registry(tracking_uri)
        registry.client = TimedClient(registry.client, "registry")
        from bugzilla_serving.contracts.names import REGISTRY_MODEL_NAME

        model_versions = registry.versions()
        if model_versions:
            aliases = dict(registry.client.get_registered_model(REGISTRY_MODEL_NAME).aliases)
        versions = [
            dict(
                version=v.version,
                run_id=v.run_id,
                tags=scrub(v.tags),
                aliases=getattr(v, "aliases", []),
            )
            for v in model_versions
        ]
    except Exception as exc:
        errors.append(f"Registry versions unavailable ({type(exc).__name__})")
    # Keep only small aggregate artifacts; predictions stay lazy and dev-gated.
    jobs = [
        (r["id"], name)
        for values in runs.values()
        for r in values
        if r["tags"].get("split") == "dev"
        and r["tags"].get("source") in ("backfill", "lab")
        and r["tags"].get("eval_set") != "config-registry"
        for name in ("per_family.csv", "na_cells.csv", "intervals.json", "scores.jsonl")
    ]

    def fetch(job):
        rid, name = job
        value = mf.checkpoint_artifact(tracking_uri, rid, name)
        return rid + "/" + name, asdict(value)

    from bugzilla_serving.tracking.client import artifact_tracking_uri

    # MLflow 2.x resolves mlflow-artifacts:/ against process-global tracking URI.
    # Hold the URI lock in the parent while its eight workers download in parallel.
    with artifact_tracking_uri(tracking_uri), ThreadPoolExecutor(max_workers=8) as pool:
        artifacts = dict(pool.map(fetch, jobs))
    if progress:
        progress(1.0)
    errors.extend(v["error"] for v in artifacts.values() if v.get("error"))
    payload = dict(
        runs=runs,
        champion=asdict(champion),
        presets=asdict(presets),
        versions=versions,
        aliases=aliases,
        artifacts=artifacts,
        errors=errors,
    )
    meta = dict(
        built_at=now(),
        tracking_uri=safe_uri(tracking_uri),
        run_counts={k: len(v) for k, v in runs.items()},
        duration_seconds=round(time.perf_counter() - start, 4),
    )
    if errors and (directory(tracking_uri) / "snapshot_meta.json").exists():
        return {**payload, "meta": meta}  # prior good generation remains the active one
    return publish(directory(tracking_uri), payload, meta)


@st.cache_resource(show_spinner=False)
@measured("snapshot.load")
def load_snapshot(tracking_uri):
    folder = directory(tracking_uri)
    path = folder / "snapshot_meta.json"
    if not path.exists():
        progress = st.progress(0.0, text="Preparing dashboard data…")
        try:
            return build_snapshot(tracking_uri, progress.progress, force=False)
        finally:
            progress.empty()
    meta = json.loads(path.read_text())
    payload = json.loads((folder / meta["file"]).read_text())
    return {**payload, "meta": meta}


def stale(meta, minutes=30):
    stamp = dt.datetime.fromisoformat(meta["built_at"].replace("Z", "+00:00"))
    return (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() > minutes * 60


def invalidate(tracking_uri):
    (directory(tracking_uri) / "snapshot_meta.json").unlink(missing_ok=True)
    load_snapshot.clear()


def build_snapshot(tracking_uri, progress=None, *, force=True):
    import fcntl

    folder = directory(tracking_uri)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "build.lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if not force and (folder / "snapshot_meta.json").exists():
            meta = json.loads((folder / "snapshot_meta.json").read_text())
            return {**json.loads((folder / meta["file"]).read_text()), "meta": meta}
        return _build_snapshot(tracking_uri, progress)
