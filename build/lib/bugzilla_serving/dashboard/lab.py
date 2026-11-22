"""Background jobs communicate through files, never through Streamlit session state."""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.data.common import scrub

LAB_ROOT = ROOT
SETS_PATH = ROOT / "configs/eval_sets.yaml"


def inputs(eval_set, limit):
    from bugzilla_serving.experiments.data import load_eval_set

    return load_eval_set(eval_set, limit, root=LAB_ROOT, sets_path=SETS_PATH)


def preflight(cfg, eval_set, limit):
    from bugzilla_serving.experiments.preflight import estimate

    items, _ = inputs(eval_set, limit)
    return estimate(cfg, items, root=LAB_ROOT)


def real_bundle():
    path = Path(os.environ.get("BUNDLE_DIR", "serving_bundle")) / "manifest.json"
    try:
        return path.is_file() and not json.loads(path.read_text()).get("synthetic")
    except (ValueError, OSError):
        return False


class Jobs:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dashboard-lab")
        self.lock = threading.Lock()
        self.futures = {}

    def path(self, token):
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid launch ID")
        return LAB_ROOT / "outputs/mlops/jobs/dashboard" / f"{token}.json"

    def save(self, token, state):
        path = self.path(token)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(scrub(state), default=str))
        temporary.replace(path)

    def status(self, token):
        return json.loads(self.path(token).read_text())

    def submit(self, cfg, eval_set, limit, *, live, max_requests, tracking_uri, fixture, grid=None):
        if os.environ.get("DASHBOARD_LAB_ENABLED") != "true":
            raise ValueError("Lab is disabled")
        if live and (fixture or not real_bundle()):
            raise ValueError("Live execution requires the real serving bundle")
        if urlsplit(tracking_uri).username or urlsplit(tracking_uri).password:
            raise ValueError("Use credential environment variables, not a credential URI")
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A dashboard experiment is already active")
        token = uuid.uuid4().hex
        self.save(token, dict(state="QUEUED", done=0, total=limit, tracking_uri=tracking_uri))

        def progress(state):
            self.save(token, {**state, "tracking_uri": tracking_uri})

        def worker():
            previous = os.environ.get("BUNDLE_DIR")
            try:
                from bugzilla_serving.experiments.runner import run_experiment

                kwargs = dict(
                    root=LAB_ROOT,
                    sets_path=SETS_PATH,
                    enable_llm=live,
                    max_requests=max_requests,
                    tracking_uri=tracking_uri,
                    label="dashboard",
                    on_progress=progress,
                )
                if fixture:
                    from bugzilla_serving.experiments.fixtures import build_fixture_runner

                    os.environ["BUNDLE_DIR"] = str(ROOT / "tests/fixtures/serving_bundle")
                    kwargs["build"] = build_fixture_runner
                if grid:
                    from bugzilla_serving.experiments.sweep import run_sweep

                    result = run_sweep(cfg, grid, eval_set, limit, **kwargs)
                    progress(
                        dict(
                            state="COMPLETED"
                            if all(j["state"] == "COMPLETED" for j in result["jobs"])
                            else "STOPPED",
                            sweep=result,
                            done=len(result["jobs"]),
                            total=result["plan"]["points"],
                        ),
                    )
                else:
                    progress(run_experiment(cfg, eval_set, limit, **kwargs))
            except Exception as exc:
                progress(dict(state="FAILED", error=f"{type(exc).__name__}: {scrub(str(exc))}"))
            finally:
                if previous is None:
                    os.environ.pop("BUNDLE_DIR", None)
                else:
                    os.environ["BUNDLE_DIR"] = previous
                self.lock.release()

        self.futures[token] = self.pool.submit(worker)
        return token

    def cancel(self, token):
        from bugzilla_serving.experiments.runner import cancel

        state = self.status(token)
        if state.get("id"):
            return cancel(state["id"], LAB_ROOT / "outputs/mlops/jobs")
        raise ValueError("Job is queued; wait until it starts before cancelling")


@st.cache_resource
def jobs():
    return Jobs()


def publication(*args, **kwargs):
    # Reuse the existing CLI's policy and execute-mode gate without changing B1.
    path = ROOT / "scripts/publish_preset.py"
    spec = importlib.util.spec_from_file_location("dashboard_publish", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.publish(*args, **kwargs)


@st.cache_data(ttl=60, show_spinner=False)
def publication_preview(tracking_uri, run_id, slug, label, description, champion):
    from bugzilla_serving.tracking.registry import Registry

    return scrub(
        publication(
            Registry(tracking_uri), run_id, slug, label, description, champion=champion, apply=False
        )
    )
