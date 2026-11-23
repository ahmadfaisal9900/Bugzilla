"""Production aggregates only. Never retain/display trace inputs or answer text."""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import streamlit as st

from bugzilla_serving.contracts.names import (
    FEEDBACK_KEY,
    LANGSMITH_PROJECTS,
    validate_trace_metadata,
)
from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.data.common import Snapshot, now, scrub
from bugzilla_serving.dashboard.profiling import TimedClient, measured

FIXTURE = ROOT / "tests/fixtures/sample_langsmith_runs.json"


def stamp(value):
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@measured("langsmith.roots")
def _fetch_roots(source: str, start: str, end: str) -> Snapshot[list[dict]]:
    try:
        lower, upper = stamp(start), stamp(end)
        if source == "fixture":
            raw = json.loads(FIXTURE.read_text())
        else:
            from langsmith import Client

            client = TimedClient(Client(), "langsmith")
            values = list(
                client.list_runs(
                    project_name=LANGSMITH_PROJECTS[0],
                    is_root=True,
                    start_time=lower,
                    select=["id", "start_time", "end_time", "extra", "outputs", "parent_run_id"],
                    limit=1000,
                )
            )
            # Fetch only the contract feedback key; cap the interactive read.
            feedback = defaultdict(list)
            ids = [r.id for r in values]
            if ids:
                for f in client.list_feedback(run_ids=ids, feedback_key=[FEEDBACK_KEY], limit=2000):
                    feedback[str(f.run_id)].append(
                        dict(
                            key=f.key,
                            score=f.score,
                            comment=f.comment,
                            created_at=str(f.created_at),
                        )
                    )
            raw = []
            for r in values:
                if r.parent_run_id:
                    continue
                outputs = r.outputs or {}
                record = outputs.get("record", outputs)
                answer = record.get("answer", {}) if isinstance(record, dict) else {}
                raw.append(
                    dict(
                        id=str(r.id),
                        project=LANGSMITH_PROJECTS[0],
                        start_time=r.start_time.isoformat(),
                        metadata=(r.extra or {}).get("metadata", {}),
                        abstain=answer.get("abstain") if isinstance(answer, dict) else None,
                        latency_ms=(r.end_time - r.start_time).total_seconds() * 1000
                        if r.end_time
                        else None,
                        feedback=feedback[str(r.id)],
                    )
                )
        result = []
        invalid = 0
        for r in raw:
            if r.get("project") != LANGSMITH_PROJECTS[0] or r.get("parent_run_id"):
                continue
            if not lower <= stamp(r["start_time"]) < upper:
                continue
            try:
                validate_trace_metadata(r["metadata"])
            except ValueError:
                invalid += 1
                continue
            ratings = [
                f
                for f in r.get("feedback", [])
                if f.get("key") == FEEDBACK_KEY and f.get("score") in (0, 1)
            ]
            latest = sorted(ratings, key=lambda f: f.get("created_at", ""))[-1] if ratings else {}
            result.append(
                dict(
                    id=r["id"],
                    started_at=r["start_time"],
                    day=stamp(r["start_time"]).date().isoformat(),
                    preset_slug=r["metadata"]["preset_slug"],
                    model=r["metadata"]["model"],
                    degraded=r["metadata"]["degraded"],
                    abstain=r.get("abstain"),
                    latency_ms=r.get("latency_ms"),
                    rating=latest.get("score"),
                    comment=scrub(str(latest.get("comment") or ""))[:1000],
                )
            )
        return Snapshot(
            result, now(), f"{invalid} runs excluded for invalid metadata" if invalid else None
        )
    except Exception as exc:
        return Snapshot([], now(), f"Production source unavailable ({type(exc).__name__})")


def grouped(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["preset_slug"], row["model"], row["degraded"]].append(row)
    result = []
    for (preset, model, degraded), values in sorted(groups.items()):
        latency = sorted(
            r["latency_ms"] for r in values if isinstance(r.get("latency_ms"), (int, float))
        )
        rated = [r for r in values if r.get("rating") in (0, 1)]
        known = [r for r in values if type(r.get("abstain")) is bool]
        result.append(
            dict(
                preset=preset,
                model=model,
                degraded=degraded,
                n=len(values),
                thumbs_up=sum(r["rating"] == 1 for r in rated) / len(rated) if rated else None,
                feedback_n=len(rated),
                abstain_rate=sum(r["abstain"] for r in known) / len(known) if known else None,
                abstain_n=len(known),
                latency_n=len(latency),
                p50_ms=latency[len(latency) // 2] if latency else None,
                p95_ms=latency[min(len(latency) - 1, int(0.95 * len(latency)))]
                if latency
                else None,
            )
        )
    return result


@st.cache_resource(show_spinner=False)
def _production(source):
    import os

    from bugzilla_serving.dashboard.data.snapshot import directory, publish

    folder = directory(
        os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        + "/"
        + LANGSMITH_PROJECTS[0]
    )
    path = folder / "production_meta.json"
    if path.exists():
        meta = json.loads(path.read_text())
        payload = json.loads((folder / meta["file"]).read_text())
        return Snapshot(**payload["snapshot"])
    # Fetch a fixed retention window once; date widgets filter locally.
    end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    snap = _fetch_roots(source, (end - dt.timedelta(days=31)).isoformat(), end.isoformat())
    from dataclasses import asdict

    publish(folder, {"snapshot": asdict(snap)}, {"built_at": snap.updated_at}, prefix="production")
    return snap


def roots(source, start, end):
    if source == "fixture":
        return _fixture(source, start, end)
    snap = _production(source)
    return Snapshot(
        [r for r in snap.value if stamp(start) <= stamp(r["started_at"]) < stamp(end)],
        snap.updated_at,
        snap.error,
    )


@st.cache_data(show_spinner=False)
def _fixture(source, start, end):
    return _fetch_roots(source, start, end)


def clear():
    _fixture.clear()
    _production.clear()


roots.clear = clear


def refresh():
    import os

    from bugzilla_serving.dashboard.data.snapshot import directory

    folder = directory(
        os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        + "/"
        + LANGSMITH_PROJECTS[0]
    )
    (folder / "production_meta.json").unlink(missing_ok=True)
    clear()
