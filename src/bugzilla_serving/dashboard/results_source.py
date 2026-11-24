"""Validated final-result CSVs. Local first; remote artifacts cached for ten minutes."""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from bugzilla_serving.contracts.run_config import ROOT


def cached_data(**options):
    """Initialize Streamlit caching only on use; CLI readers have no runtime."""

    def decorate(function):
        cached = None

        @functools.wraps(function)
        def call(*args, **kwargs):
            nonlocal cached
            if cached is None:
                cached = st.cache_data(**options)(function)
            return cached(*args, **kwargs)

        def clear():
            if cached is not None:
                cached.clear()

        call.clear = clear
        return call

    return decorate


PACK = ROOT / "outputs/analysis/results_pack"
SYSTEMS = [
    "Closed-book",
    "Keyword search",
    "Smart search",
    "Query rewriting",
    "Self-checking search",
    "Full bug dossier",
    "Linked-bugs search",
    "Database tools",
    "Auto-router",
]
IDS = dict(zip(SYSTEMS, [f"S{i}" for i in range(8)] + ["S8v2"]))
TYPES = [
    "Field lookup",
    "Lifecycle & timing",
    "Counting",
    "Bug relationships",
    "Reasons (LLM-graded)",
    "Unanswerable",
    "Find bug by description",
    "Multi-step",
    "Hard unanswerable",
]
DESCRIPTIONS = dict(
    zip(
        SYSTEMS,
        [
            "Answers from model memory, without bug records.",
            "Finds passages using matching words.",
            "Searches several rewrites of the question.",
            "Shares the Smart search pipeline.",
            "Searches again when the first evidence is weak.",
            "Reads a large dossier of the bug’s records.",
            "Adds records from linked bugs.",
            "Uses structured database lookups.",
            "Chooses database lookups, a cited-comment dossier, or Smart search.",
        ],
    )
)
HEADERS = {
    "final_scores.csv": {"System", "Overall %", *TYPES},
    "overall_bootstrap.csv": {"System", "Overall %", "95% CI low %", "95% CI high %"},
    "per_question_scores.csv": {
        "System",
        "Source",
        "Family",
        "qid",
        "Scorer 2 verdict",
        "Origin",
        "Declined",
        "Status",
    },
    "abstention_failures.csv": {
        "System",
        "Declines / all questions",
        "Correct declines / Unanswerable + Hard unanswerable",
        "False declines / answerable",
        "Wrong non-declined answers / answerable",
        "Errors / all questions",
    },
    "original_pilot_cost.csv": {
        "System",
        "Calls / question",
        "Tokens / question",
        "Latency p50 ms",
        "Latency p95 ms",
    },
    "v2_cost_by_origin.csv": {
        "Origin",
        "Questions",
        "Historical source calls (separate)",
        "Fresh calls this resume",
        "Source tokens in",
        "Source tokens out",
        "Source latency p50 ms",
        "Source latency p95 ms",
    },
    "routing_by_family.csv": {
        "Family",
        "Chosen route",
        "Final answer component",
        "Final answer used LLM",
        "Final generation count",
        "Rows",
        "Correct / total",
    },
    "accuracy_by_source.csv": {"Source", "Auto-router v2", *SYSTEMS[:-1]},
    "retrieval_pairs.csv": {
        "Retriever",
        "Corpus",
        "Selection macro Recall@10",
        "Macro Hit@5 (eligible cells)",
        "Macro MRR@10 (eligible cells)",
        "Macro nDCG@10 (eligible cells)",
        "Find bug by description bug Hit@5",
        "Multi-step full evidence@10",
        "Selection questions",
        "Selection latency p50 ms",
        "Selection latency p95 ms",
        "Selected",
    },
    "retrieval_family_comparison.csv": {
        "Retriever",
        "Corpus",
        "Source",
        "Family",
        "n",
        "recall_at_10",
        "hit_at_5",
        "bug_hit_at_5",
        "mh_full_evidence_at_10",
    },
    "retrieval_bootstrap_vs_keyword.csv": {
        "Retriever",
        "Corpus",
        "Baseline",
        "Source",
        "Family",
        "Metric",
        "CI low",
        "CI high",
    },
    "judge_agreement.csv": {"External judge"},
}


def clean_label(value):
    if not isinstance(value, str):
        return value
    for a, b in [
        ("Auto-router v2", "Auto-router"),
        ("Phase 5", "Core benchmark"),
        ("Benchmark v3", "Extended benchmark"),
        ("tools-v2 parser path", "database path, no model call"),
        ("other: preserved native tools v2", "database path, model answer"),
        ("other: failed tools v2", "database path, failed"),
        ("dossier + pinned cited comment", "bug dossier with the cited comment first"),
        ("Smart search R7b", "Smart search"),
        ("gpt-oss-20b with native tools", "model with database tools"),
    ]:
        value = value.replace(a, b)
    return value


def fraction(value):
    match = re.search(r"(\d+)\s*/\s*(\d+)", str(value))
    return tuple(map(int, match.groups())) if match else (0, 0)


def rate(value):
    k, n = fraction(value)
    return k / n if n else float("nan")


def derive_cost(raw):
    original = raw["original_pilot_cost.csv"].set_index("System")
    origins = raw["v2_cost_by_origin.csv"].set_index("Origin")
    routes = raw["routing_by_family.csv"]
    smart_n = int(routes.loc[routes["Chosen route"].eq("Smart search R7b"), "Rows"].sum())
    dossier_n = int(
        routes.loc[
            routes["Family"].eq("Unanswerable") & routes["Chosen route"].eq("other"), "Rows"
        ].sum()
    )
    parsed_n = int(origins.loc["parser-built", "Questions"])
    kept_calls = float(origins.loc["preserved v2", "Historical source calls (separate)"])
    kept_tokens = float(origins.loc["preserved v2", "Source tokens in"]) + float(
        origins.loc["preserved v2", "Source tokens out"]
    )
    failed_calls = float(origins.loc["failed", "Fresh calls this resume"])
    smart, dossier = original.loc["Smart search"], original.loc["Full bug dossier"]
    calls = (
        kept_calls
        + float(smart["Calls / question"]) * smart_n
        + float(dossier["Calls / question"]) * dossier_n
        + failed_calls
    ) / 122
    tokens = (
        kept_tokens
        + float(smart["Tokens / question"]) * smart_n
        + float(dossier["Tokens / question"]) * dossier_n
    ) / 122
    calculation = (
        f"Auto-router calls/question = (0*{parsed_n} + {kept_calls:g} + "
        f"{smart['Calls / question']}*{smart_n} + "
        f"{dossier['Calls / question']}*{dossier_n} + {failed_calls:g})/122 = {calls:.6f}; "
        f"tokens/question = ({kept_tokens:g} + {smart['Tokens / question']}*{smart_n} + "
        f"{dossier['Tokens / question']}*{dossier_n})/122 = {tokens:.6f}. "
        + (
            "Estimated route-weighted cost; failed-call tokens unknown. Route percentiles"
            " are not pooled."
        )
    )
    rows = []
    for system in SYSTEMS:
        parent = "Smart search" if system == "Query rewriting" else system
        if system == "Auto-router":
            rows.append(
                dict(
                    System=system,
                    calls_per_q=calls,
                    tokens_per_q=tokens,
                    latency_p50_s=float("nan"),
                    latency_p95_s=float("nan"),
                    note="Estimated by route; times are shown separately by route.",
                )
            )
        else:
            r = original.loc[parent]
            rows.append(
                dict(
                    System=system,
                    calls_per_q=float(r["Calls / question"]),
                    tokens_per_q=float(r["Tokens / question"]),
                    latency_p50_s=float(r["Latency p50 ms"]) / 1000,
                    latency_p95_s=float(r["Latency p95 ms"]) / 1000,
                    note="shares Smart search's pipeline"
                    if system == "Query rewriting"
                    else "Original pilot; reported token usage may be incomplete.",
                )
            )
    return pd.DataFrame(rows), calculation


def read_pack(folder):
    folder = Path(folder)
    raw = {}
    for file, expected in HEADERS.items():
        frame = pd.read_csv(folder / file, keep_default_na=False)
        missing = expected - set(frame.columns)
        if missing:
            raise ValueError(f"{file}: missing required headers: {sorted(missing)}")
        raw[file] = frame
    cost, calculation = derive_cost(raw)
    tables = {}
    for file, frame in raw.items():
        if "System" in frame:
            frame = frame.loc[frame["System"].ne("Auto-router")].copy()
        if "Auto-router v2" in frame.columns:
            frame = frame.drop(columns=["Auto-router"], errors="ignore").rename(
                columns={"Auto-router v2": "Auto-router"}
            )
        frame = frame.map(clean_label)
        if file == "routing_by_family.csv":
            dossier = frame["Chosen route"].eq("other") & frame[
                "Final answer component"
            ].str.contains("Full bug dossier")
            frame.loc[dossier, "Chosen route"] = "bug dossier"
        tables[file] = frame
    optional = folder / "route_latency.csv"
    if optional.is_file():
        times = pd.read_csv(optional)
        expected = {"Path", "Questions", "latency_p50_s", "latency_p95_s", "Source"}
        if not expected <= set(times):
            raise ValueError("route_latency.csv: missing required headers")
        tables["route_latency.csv"] = times
    tables["system_cost.csv"] = cost
    assert set(tables["final_scores.csv"]["System"]) == set(SYSTEMS)
    assert len(tables["per_question_scores.csv"]) == 9 * 122
    return tables, calculation


@cached_data(ttl=600, show_spinner=False)
def remote_folder(uri):
    from bugzilla_serving.tracking.client import TrackingClient, artifact_tracking_uri

    tracker = TrackingClient(uri)
    exp = tracker.client.get_experiment_by_name("final-results")
    if not exp:
        return None
    runs = tracker.client.search_runs(
        [exp.experiment_id],
        filter_string="tags.results_pack = 'true' and attributes.status = 'FINISHED'",
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    if not runs:
        return None
    # Explicit destination survives Streamlit reruns and download occurs once per run/hash.
    cache = Path(os.environ.get("DASHBOARD_CACHE_DIR", ROOT / "outputs/dashboard_cache"))
    generation = runs[0].data.tags.get("pack_sha256", "initial")[:16]
    folder = cache / "final-results" / (runs[0].info.run_id + "-" + generation)
    required = set(HEADERS) | {"system_cost.csv"}
    if runs[0].data.tags.get("route_latency") == "true":
        required.add("route_latency.csv")
    if not all((folder / f).is_file() for f in required):
        folder.mkdir(parents=True, exist_ok=True)
        with artifact_tracking_uri(uri):
            for file in sorted(required):
                tracker.client.download_artifacts(runs[0].info.run_id, file, str(folder))
    return str(folder)


@cached_data(ttl=600, show_spinner=False)
def _cached_pack(folder, stamp):
    return read_pack(folder)


def load_results():
    folder = Path(os.environ.get("DASHBOARD_RESULTS_DIR", PACK))
    if not (folder / "final_scores.csv").is_file():
        uri = os.environ.get("MLFLOW_TRACKING_URI")
        fallback = remote_folder(uri) if uri else None
        if not fallback:
            return None
        folder = Path(fallback)
    stamps = tuple(
        (f, (folder / f).stat().st_mtime_ns)
        for f in [*HEADERS, "route_latency.csv"]
        if (folder / f).exists()
    )
    return _cached_pack(str(folder), stamps)


def paired(frame, a, b):
    selected = frame.loc[frame["System"].isin([a, b])]
    pivot = selected.pivot(
        index=["Source", "qid", "Family"], columns="System", values="Scorer 2 verdict"
    )
    if a not in pivot or b not in pivot or pivot[[a, b]].isna().any().any():
        raise ValueError("Paired comparison requires the same question identities")
    aa, bb = pivot[a].eq("CORRECT"), pivot[b].eq("CORRECT")
    counts = dict(
        both=int((aa & bb).sum()),
        a_only=int((aa & ~bb).sum()),
        b_only=int((~aa & bb).sum()),
        neither=int((~aa & ~bb).sum()),
    )
    x, y = counts["a_only"], counts["b_only"]
    n = x + y
    counts["p"] = (
        min(1.0, 2 * sum(math.comb(n, j) for j in range(min(x, y) + 1)) / 2**n) if n else 1.0
    )
    return counts, pivot.loc[aa.ne(bb)].reset_index()


def mlflow_root(uri):
    from urllib.parse import urlsplit, urlunsplit

    p = urlsplit(uri)
    if p.scheme not in ("http", "https") or p.username or p.password:
        return None
    marker = p.path.find(".mlflow")
    return urlunsplit((p.scheme, p.netloc, p.path[: marker + 7], "", "")) if marker >= 0 else None


def links():
    from urllib.parse import urlsplit

    result = {}
    for label, key in [
        ("DagsHub repository", "DAGSHUB_REPO_URL"),
        ("LangSmith project", "LANGSMITH_PROJECT_URL"),
    ]:
        value = os.environ.get(key)
        if value:
            p = urlsplit(value)
            if p.scheme in ("https", "http") and not p.username and not p.password and not p.query:
                result[label] = value
    uri = os.environ.get("MLFLOW_TRACKING_URI", "")
    base = mlflow_root(uri)
    if base:
        result.update(
            {"Experiments": base, "Model registry": base + "/#/models/bugzilla-qa-config"}
        )
        eid = final_experiment_id(uri)
        if eid:
            result["Final results"] = base + "/#/experiments/" + eid
    return result


@cached_data(ttl=600, show_spinner=False)
def final_experiment_id(uri):
    receipt = ROOT / "outputs/analysis/b9/final_results_receipt.json"
    if receipt.exists():
        value = json.loads(receipt.read_text())
        if value.get("tracking_uri_sha256") == hashlib.sha256(uri.encode()).hexdigest():
            return value["experiment_id"]
    if os.environ.get("DASHBOARD_REMOTE_ENABLED", "false").lower() != "true":
        return None
    from bugzilla_serving.tracking.client import TrackingClient

    exp = TrackingClient(uri).client.get_experiment_by_name("final-results")
    return exp.experiment_id if exp else None
