"""Explicit, idempotent final-results publication; model inference is never used."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import time
from pathlib import Path

import pandas as pd
import yaml
from mlflow.entities import Metric, Param, RunTag

from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.dashboard.results_source import (
    DESCRIPTIONS,
    IDS,
    PACK,
    SYSTEMS,
    TYPES,
    fraction,
    rate,
    read_pack,
)
from bugzilla_serving.tracking.client import (
    TrackingClient,
    artifact_tracking_uri,
    assert_no_secrets,
)

EVAL_SET = "dev-pilot-122"
FREEZES = {"core_freeze": "d8ef826fbeb90d13", "extended_freeze": "e2207774a0f2cbad"}
SLUGS = dict(
    zip(
        TYPES,
        [
            "field_lookup",
            "lifecycle",
            "counting",
            "relationships",
            "reasons",
            "unanswerable",
            "description",
            "multi_step",
            "hard_unanswerable",
        ],
    )
)
ORDER = SYSTEMS


def write_route_times(folder):
    """Group saved final-answer source latencies by actual route, never pool routes."""
    ledger = ROOT / "outputs/predictions/v2/dev/run-09675f0b6b4468c9/S8v2.jsonl"
    prior = ROOT / "outputs/predictions/v2/dev/run-cf2c6f2cf859a3c6/S8v2.jsonl"
    if not ledger.is_file() or not prior.is_file():
        return False
    from bugzilla_serving.tracking.backfill import discover_ledgers

    def load(path):
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    old = {(r["dataset"], r["qid"]): r for r in load(prior)}
    parents = {}
    for ds, directory in discover_ledgers(
        ROOT / "outputs/evaluation/phase11/pilot125", ROOT
    ).items():
        for system in ["S2", "S5"]:
            for r in load(Path(directory) / f"{system}.jsonl"):
                parents[system, ds, r["qid"]] = r
    groups = {}
    for p in load(ledger):
        key = p["dataset"], p["qid"]
        if p.get("carried_forward"):
            system = p["route"]
            r = parents[system, *key]
            label = "Smart search" if system == "S2" else "Bug dossier"
            source = "Original downstream system answers"
        elif p.get("preserved_from_v2"):
            r = old[key]
            label = (
                "Bug dossier with cited comment"
                if p["route"] == "S5"
                else "Database path (model answer)"
            )
            source = "Preserved source answers"
        else:
            r = p
            label = "Failed" if p["status"] != "ok" else "Database path (parser)"
            source = "Current local computation or failed request"
        groups.setdefault((label, source), []).append(float(r["latency_ms"]) / 1000)
    rows = [
        dict(
            Path=label,
            Questions=len(values),
            latency_p50_s=float(pd.Series(values).quantile(0.5)),
            latency_p95_s=float(pd.Series(values).quantile(0.95)),
            Source=source,
        )
        for (label, source), values in groups.items()
    ]
    assert sum(r["Questions"] for r in rows) == 122
    pd.DataFrame(rows).to_csv(Path(folder) / "route_latency.csv", index=False)
    return True


def write_cost(folder=PACK):
    folder = Path(folder)
    tables, calculation = read_pack(folder)
    tables["system_cost.csv"].to_csv(folder / "system_cost.csv", index=False)
    write_route_times(folder)
    report = folder / "results_pack.md"
    if (
        report.exists()
        and "outputs/analysis/results_pack/system_cost.csv" not in report.read_text()
    ):
        with report.open("a") as stream:
            stream.write(
                "\nDerived route-weighted cost: `outputs/analysis/results_pack/system_cost.csv`.\n"
            )
    if report.exists() and (folder / "route_latency.csv").exists():
        ref = "outputs/analysis/results_pack/route_latency.csv"
        if ref not in report.read_text():
            with report.open("a") as stream:
                stream.write("\nPer-route saved-source latency: `" + ref + "`.\n")
    return calculation


def configuration(system):
    """Recover historical evaluated settings; do not make a deployability claim."""
    from bugzilla_serving.tracking.backfill import (
        projected_config,
        read,
        sha,
    )

    internal = IDS[system]
    if internal == "S8v2":
        cfg = RunConfig(
            system_id="S8", top_k=10, s7_max_tool_steps=4, s5_dossier_budget=12000
        ).model_dump(mode="json")
        # Preserve the actual identity. Substituting S8 here would silently serve the wrong graph.
        return {
            **cfg,
            "system_id": internal,
            "router_rules_version": "json-tools-v2",
            "tool_route_version": "json-tools-v2",
        }
    source = ROOT / "outputs/evaluation/phase11/pilot125"
    from bugzilla_serving.tracking.backfill import discover_ledgers

    folders = discover_ledgers(source, ROOT)
    if not folders:
        raise ValueError("Historical pilot configurations are missing; refusing to invent configs")
    folder = Path(next(iter(folders.values())))
    manifest = read(folder / "manifest.json")
    for file in ["identity.json", "config_snapshot.json"]:
        expected = manifest.get("sha256", {}).get(file)
        if not expected or sha(folder / file) != expected:
            raise ValueError("Historical configuration checksum mismatch: " + file)
    identity = read(folder / "identity.json")
    snapshot = read(folder / "config_snapshot.json")
    snapshot = {**snapshot, **identity["config"], "effective_llm": identity["llm"]}
    return projected_config(internal, snapshot, ROOT, selected=identity["selected"]).model_dump(
        mode="json"
    )


def plans(folder=PACK, config_loader=configuration):
    folder = Path(folder)
    t, calculation = read_pack(folder)
    final = t["final_scores.csv"].set_index("System")
    ci = t["overall_bootstrap.csv"].set_index("System")
    abst = t["abstention_failures.csv"].set_index("System")
    cost = t["system_cost.csv"].set_index("System")
    source = t["accuracy_by_source.csv"].set_index("Source")
    perq = t["per_question_scores.csv"]
    judge = t["judge_agreement.csv"]["External judge"].iloc[0]
    result = []
    for system in ORDER:
        r, c, a, k = final.loc[system], ci.loc[system], abst.loc[system], cost.loc[system]
        cfg = config_loader(system)
        config_text = yaml.safe_dump(cfg, sort_keys=True)
        metrics = dict(
            overall_pct=float(r["Overall %"]),
            ci_low=float(c["95% CI low %"]),
            ci_high=float(c["95% CI high %"]),
            correct_total=int(
                perq.loc[perq["System"].eq(system), "Scorer 2 verdict"].eq("CORRECT").sum()
            ),
            calls_per_q=float(k["calls_per_q"]),
            tokens_per_q=float(k["tokens_per_q"]),
        )
        for f in TYPES:
            yes, n = fraction(r[f])
            metrics["acc_" + SLUGS[f]], metrics["n_" + SLUGS[f]] = yes / n, n
        for metric, column in [
            ("decline_rate", "Declines / all questions"),
            ("correct_decline_rate", "Correct declines / Unanswerable + Hard unanswerable"),
            ("false_decline_rate", "False declines / answerable"),
            ("wrong_answer_rate", "Wrong non-declined answers / answerable"),
            ("error_rate", "Errors / all questions"),
        ]:
            metrics[metric] = rate(a[column])
        for ds, suffix in [
            ("Natural rewrites", "natural"),
            ("Core benchmark", "core"),
            ("Extended benchmark", "extended"),
        ]:
            metrics["acc_" + suffix] = rate(source.loc[ds, system])
        for field in ["latency_p50_s", "latency_p95_s"]:
            if math.isfinite(float(k[field])):
                metrics[field] = float(k[field])
        params = {
            key: json.dumps(value, sort_keys=True)
            if value is None or isinstance(value, (bool, dict, list))
            else str(value)
            for key, value in cfg.items()
        }
        params["config_hash"] = hashlib.sha256(config_text.encode()).hexdigest()
        tags = dict(
            display_name=system,
            system_id=IDS[system],
            eval_set=EVAL_SET,
            reasons_judge=judge,
            split="dev",
            description=DESCRIPTIONS[system],
            final_key=IDS[system],
            **FREEZES,
        )
        if system == "Auto-router":
            tags.update(
                latency="Route-specific; no valid pooled percentile",
                evaluation="composite_changed_routes",
                provenance="82 parser-built; 10 preserved model; 29 reused downstream; 1 failed",
                cost_basis="Estimated by route; failed-call token usage missing",
            )
        if system == "Auto-router" and "route_latency.csv" in t:
            for _, route in t["route_latency.csv"].iterrows():
                slug = re.sub(r"[^a-z0-9]+", "_", route["Path"].lower()).strip("_")
                for p in ["50", "95"]:
                    metrics[f"latency_{slug}_p{p}_s"] = float(route[f"latency_p{p}_s"])
        artifact_rows = (
            perq.loc[perq["System"].eq(system)]
            .rename(columns={"Scorer 2 verdict": "Verdict"})
            .drop(columns=["Scorer 1 verdict"], errors="ignore")
        )
        artifact_rows = artifact_rows.map(
            lambda x: str(x).replace("preserved v2", "preserved model answer")
            if isinstance(x, str)
            else x
        )
        result.append(
            dict(
                name=system,
                params=params,
                tags=tags,
                metrics=metrics,
                artifacts={
                    "config.yaml": config_text,
                    "per_question.csv": artifact_rows.to_csv(index=False),
                },
            )
        )
    return result, calculation


def find_runs(client, experiment):
    exp = client.get_experiment_by_name(experiment)
    if not exp:
        return []
    out = []
    token = None
    while True:
        page = client.search_runs([exp.experiment_id], max_results=1000, page_token=token)
        out.extend(page)
        token = getattr(page, "token", None)
        if not token:
            return out


def upsert(client, uri, experiment, plan, apply):
    existing = [
        r
        for r in find_runs(client, experiment)
        if r.data.tags.get("final_key") == plan["tags"]["final_key"]
    ]
    if len(existing) > 1:
        raise ValueError(f"Duplicate final result identity: {plan['name']}")
    action = "update" if existing else "create"
    rid = existing[0].info.run_id if existing else None
    if apply:
        if rid is None:
            exp = client.get_experiment_by_name(experiment)
            eid = exp.experiment_id if exp else client.create_experiment(experiment)
            rid = client.create_run(
                eid, tags={"mlflow.runName": plan["name"], **plan["tags"]}
            ).info.run_id
        previous = client.get_run(rid).data.params
        if any(key in previous and previous[key] != value for key, value in plan["params"].items()):
            raise ValueError(
                "An existing final run has different immutable config params; "
                "review before updating"
            )
        client.update_run(rid, status="RUNNING")
        client.log_batch(
            rid,
            metrics=[
                Metric(k, float(v), int(time.time() * 1000), 0) for k, v in plan["metrics"].items()
            ],
            params=[Param(k, str(v)) for k, v in plan["params"].items() if k not in previous],
            tags=[
                RunTag(k, str(v))
                for k, v in {**plan["tags"], "mlflow.runName": plan["name"]}.items()
            ],
        )
        with tempfile.TemporaryDirectory(prefix="bugzilla-final-") as tmp:
            for file, text in plan["artifacts"].items():
                if Path(file).name != file:
                    raise ValueError("Only flat final-results artifact names are allowed")
                assert_no_secrets(text)
                p = Path(tmp) / file
                p.write_text(text)
                with artifact_tracking_uri(uri):
                    client.log_artifact(rid, str(p))
        client.set_terminated(rid)
    return dict(
        name=plan["name"],
        action=action,
        run_id=rid,
        metrics=plan["metrics"],
        params=plan["params"],
        tags=plan["tags"],
        artifacts=sorted(plan["artifacts"]),
    )


def publish(folder=PACK, tracking_uri=None, apply=False, config_loader=configuration):
    plans_, calculation = plans(folder, config_loader)
    # Constructing the explicit client is read-only. No writes in dry-run.
    tracker = TrackingClient(tracking_uri)
    result = []
    for plan in plans_:
        for data in (plan["params"], plan["tags"], plan["metrics"]):
            assert_no_secrets(json.dumps(data))
        result.append(upsert(tracker.client, tracker.uri, "final-results", plan, apply))
    files = {p.name: p.read_text() for p in sorted(Path(folder).glob("*.csv"))}
    tables, _ = read_pack(folder)
    files["system_cost.csv"] = tables["system_cost.csv"].to_csv(index=False)
    pack_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    result.append(
        upsert(
            tracker.client,
            tracker.uri,
            "final-results",
            dict(
                name="results-pack",
                params={},
                tags=dict(
                    final_key="results-pack",
                    results_pack="true",
                    pack_sha256=pack_hash,
                    route_latency=str("route_latency.csv" in files).lower(),
                    eval_set=EVAL_SET,
                    split="dev",
                    reasons_judge=plans_[0]["tags"]["reasons_judge"],
                ),
                metrics={},
                artifacts=files,
            ),
            apply,
        )
    )
    prior = find_runs(tracker.client, "research-retrieval-eval")
    retrieval = []
    for _, r in tables["retrieval_pairs.csv"].iterrows():
        matching = []
        from bugzilla_serving.tracking.backfill import read

        catalog = read(ROOT / "configs/display_catalog.yaml")
        retriever = next(k for k, v in catalog["retrievers"].items() if v["name"] == r["Retriever"])
        corpus = next(k for k, v in catalog["corpora"].items() if v["name"] == r["Corpus"])
        matching = [
            p
            for p in prior
            if p.data.params.get("retriever") == retriever and p.data.params.get("corpus") == corpus
        ]
        selected = str(r["Selected"]).lower() == "true"
        label = r["Retriever"] + " / " + r["Corpus"]
        if matching:
            for p in matching:
                if apply:
                    for key, value in dict(
                        display_name=label,
                        selected=str(selected).lower(),
                        **{"mlflow.runName": label},
                    ).items():
                        tracker.client.set_tag(p.info.run_id, key, value)
            retrieval.append(
                dict(name=label, action="tag existing", run_ids=[p.info.run_id for p in matching])
            )
        else:
            metrics = {
                re.sub(r"[^a-zA-Z0-9_]", "_", k): float(v)
                for k, v in r.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            }
            plan = dict(
                name=label,
                params=dict(retriever=retriever, corpus=corpus),
                tags=dict(
                    final_key=retriever + "-" + corpus,
                    display_name=label,
                    selected=str(selected).lower(),
                    split="dev",
                ),
                metrics=metrics,
                artifacts={"retrieval_pair.csv": pd.DataFrame([r]).to_csv(index=False)},
            )
            retrieval.append(upsert(tracker.client, tracker.uri, "final-retrieval", plan, apply))
    if apply and tracker.uri.startswith(("https://", "http://")):
        exp = tracker.client.get_experiment_by_name("final-results")
        receipt = ROOT / "outputs/analysis/b9/final_results_receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "experiment_id": exp.experiment_id,
                    "tracking_uri_sha256": hashlib.sha256(tracker.uri.encode()).hexdigest(),
                }
            )
        )
    return dict(
        state="APPLIED" if apply else "DRY_RUN",
        runs=result,
        retrieval=retrieval,
        computation=calculation,
        actual_llm_calls=0,
    )
