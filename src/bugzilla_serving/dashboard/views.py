"""Nine monitoring pages; only the explicitly enabled Lab performs experiments."""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from bugzilla_serving.contracts.names import EXPERIMENTS, FAMILIES, RETRIEVAL_METRICS
from bugzilla_serving.contracts.run_config import FIXED_RETRIEVERS, RunConfig, load_spec
from bugzilla_serving.dashboard.data import langsmith_source as ls
from bugzilla_serving.dashboard.data import mlflow_source as mf
from bugzilla_serving.dashboard.data.common import display_frame, family_cell, scrub
from bugzilla_serving.dashboard.theme import PALETTE, style
from bugzilla_serving.tracking.backfill import read


def dataframe(rows, **kwargs):
    st.dataframe(display_frame(rows), **kwargs)


def enabled():
    return os.environ.get("DASHBOARD_LAB_ENABLED") == "true"


def records(experiments=EXPERIMENTS):
    result = []
    for experiment in experiments:
        snapshot = mf.runs(mf.uri(), experiment)
        if snapshot.error:
            st.warning(snapshot.error)
        st.caption(f"{experiment} · last updated {snapshot.updated_at} · reads cached 60 s")
        result.extend(snapshot.value)
    return result


def name(run):
    suffix = " · pilot subset" if run.tags.get("eval_set") == "pilot125" else ""
    if run.tags.get("split") == "test-aggregate":
        suffix += " · test-aggregate (metrics only)"
    if run.tags.get("simulated") == "true" or run.tags.get("source") == "ci":
        suffix += " · SIMULATED"
    return (
        f"{run.params.get('system_id', '?')} / {run.params.get('retriever', '?')} / "
        f"{run.params.get('corpus', '?')} · {run.id[:8]}{suffix}"
    )


def rows_for(run, artifact="per_family.csv"):
    snapshot = mf.artifact(mf.uri(), run.id, artifact)
    return snapshot.value if isinstance(snapshot.value, list) else []


def filtered(values):
    sets = sorted({r.tags.get("eval_set", "unknown") for r in values})
    datasets = sorted({d for r in values for d in r.tags.get("datasets", "").split(",") if d})
    chosen = st.multiselect("Evaluation sets", sets, default=sets)
    dataset = st.selectbox("Dataset tag filter", ["All", *datasets])
    return [
        r
        for r in values
        if r.tags.get("eval_set") in chosen
        and (dataset == "All" or dataset in r.tags.get("datasets", "").split(","))
    ]


def answer_table(values):
    result = []
    for run in values:
        families = rows_for(run)
        row = {
            "Run": name(run),
            "eval_set": run.tags.get("eval_set"),
            "split": run.tags.get("split"),
            "provenance": run.tags.get("provenance", "recorded"),
            "scored families n": sum(f"answer.{f}.score" in run.metrics for f in FAMILIES),
            "macro (scored families only)": missing(run, "answer.macro"),
        }
        for family in FAMILIES:
            row[family] = family_cell(
                run.metrics, family, tags=run.tags, family_rows=families
            ).label
        result.append(row)
    return result


def bars(values, title, y="score"):
    if not values:
        st.info("No scored values available yet.")
        return
    frame = pd.DataFrame(values)
    frame["label"] = frame.apply(lambda r: f"{r[y]:.3g} · n={r['n']}", axis=1)
    figure = px.bar(
        frame,
        x="family",
        y=y,
        color="run",
        barmode="group",
        text="label",
        color_discrete_sequence=PALETTE,
        hover_data=["n"],
        title=title,
    )
    st.plotly_chart(style(figure), use_container_width=True)


def overview():
    st.header("Overview")
    champion = mf.champion(mf.uri())
    st.caption(f"Registry last updated {champion.updated_at}")
    if champion.value:
        st.subheader(f"Champion · version {champion.value['version']}")
        st.json(champion.value["config"])
        source = next(
            (
                r
                for r in records(("research-answer-eval", "playground"))
                if r.id == champion.value["run_id"]
            ),
            None,
        )
        if source:
            dataframe(answer_table([source]), use_container_width=True)
            st.caption(f"Champion p95 ms: {missing(source, 'latency.p95_ms')}")
    else:
        st.info(champion.error or "No champion published yet.")
    values = filtered(records(("research-answer-eval", "playground")))
    st.caption(
        "Leaderboard cells show score and scored n; click column headers to sort. "
        "No pooled overall score is the headline. pilot125 is a pilot subset."
    )
    dataframe(answer_table(mf.latest_per_config(values)), use_container_width=True)
    if not values:
        st.info("No answer evaluation runs yet.")


def answer_eval():
    st.header("Answer eval")
    values = filtered(records(("research-answer-eval", "playground")))
    cells = []
    for run in values:
        for f in FAMILIES:
            cell = family_cell(run.metrics, f, tags=run.tags, family_rows=rows_for(run))
            if cell.value is not None:
                cells.append(dict(run=name(run), family=f, score=cell.value, n=cell.n))
    bars(cells, "Per-family correctness (inspect scorer and n)")
    dataframe(answer_table(values), use_container_width=True)
    for run in values:
        intervals = mf.artifact(mf.uri(), run.id, "intervals.json").value
        if intervals:
            st.caption(f"{name(run)} · saved intervals, no new intervals estimated")
            dataframe(intervals, use_container_width=True)
            # Saved intervals can describe dataset-specific scores, while the main
            # bars pool a family across datasets. Plot the actual bounds separately.
            if all({"ci_low", "ci_high", "family", "n"} <= r.keys() for r in intervals):
                import plotly.graph_objects as go

                figure = go.Figure()
                for row in intervals:
                    label = f"{row.get('dataset', '')} / {row['family']} · n={row['n']}"
                    figure.add_trace(
                        go.Scatter(
                            x=[row["ci_low"], row["ci_high"]],
                            y=[label, label],
                            mode="lines+markers",
                            name=label,
                            showlegend=False,
                            line=dict(color=PALETTE[0]),
                        )
                    )
                figure.update_layout(xaxis_title="Saved confidence interval (score)")
                st.plotly_chart(style(figure), use_container_width=True)
    st.subheader("Abstention and failures")
    dataframe(
        [
            {
                "run": name(r),
                **{
                    k: missing(r, k)
                    for k in ("abstain.correct_rate", "abstain.false_rate", "fail.rate")
                },
            }
            for r in values
        ],
        use_container_width=True,
    )


def missing(run, key):
    return (
        run.metrics[key]
        if key in run.metrics
        else (
            "not available yet: review-only"
            if run.tags.get("provenance") == "review-only"
            else "not available"
        )
    )


def retrieval_eval():
    st.header("Retrieval eval")
    values = records(("research-retrieval-eval",))
    sets = sorted({r.tags.get("eval_set", "unknown") for r in values})
    if sets:
        selected_set = st.selectbox("Retrieval eval set", sets)
        values = [r for r in values if r.tags.get("eval_set") == selected_set]
    dataset = st.selectbox("Dataset", ["v3", "natural", "phase05"])
    metric = st.selectbox(
        "Metric", [m for m in RETRIEVAL_METRICS if m not in ("n", "r4_r3_jaccard_top10")], index=4
    )
    family = st.selectbox("Family", list(FAMILIES))
    st.caption(
        "KI and MH are key retrieval challenge families. Known-citation qrels are incomplete; "
        "unlabeled passages are not established irrelevant."
    )
    table = []
    for run in mf.latest_per_config(values):
        cell = family_cell(
            run.metrics,
            family,
            dataset=dataset,
            metric=metric,
            na_rows=rows_for(run, "na_cells.csv"),
        )
        table.append(
            dict(
                retriever=run.params.get("retriever"),
                corpus=run.params.get("corpus"),
                value=cell.value,
                n=cell.n,
                cell=cell.label,
                selected=run.tags.get("selected") == "true",
                p95_ms=missing(run, f"retr.{dataset}.{family}.latency_p95_ms"),
            )
        )
    dataframe(table, use_container_width=True)
    known = [r for r in table if r["value"] is not None]
    if known:
        frame = pd.DataFrame(known)
        pivot = frame.pivot_table(
            index="retriever", columns="corpus", values="value", aggfunc="first"
        )
        labels = frame.pivot_table(
            index="retriever", columns="corpus", values="cell", aggfunc="first"
        )
        import plotly.graph_objects as go

        figure = go.Figure(
            go.Heatmap(
                z=pivot.values,
                x=list(pivot.columns),
                y=list(pivot.index),
                text=labels.values,
                texttemplate="%{text}",
                colorscale=[[0, "#EFF6FF"], [1, PALETTE[0]]],
            )
        )
        st.plotly_chart(style(figure), use_container_width=True)
    elif not table:
        st.info("No retrieval evaluation runs yet.")


def cost_latency():
    st.header("Cost & latency")
    values = filtered(records(("research-answer-eval", "playground")))
    keys = [
        "cost.llm_calls",
        "cost.tokens_in",
        "cost.tokens_out",
        "latency.p50_ms",
        "latency.p95_ms",
    ]
    table = []
    for run in values:
        families = rows_for(run)
        n = sum(int(r.get("source_n") or r.get("n") or 0) for r in families)
        # A scored n is only an attempted n when every attempted family is scored.
        # With no accounting artifact, leave the per-question denominator unknown.
        row = {
            "run": name(run),
            "model": run.params.get("model"),
            "attempted n": n if n else "unknown",
        }
        row.update({k: missing(run, k) for k in keys})
        if n and all(k in run.metrics for k in ("cost.tokens_in", "cost.tokens_out")):
            tokens = (run.metrics["cost.tokens_in"] + run.metrics["cost.tokens_out"]) / n
            row["reported tokens / question"] = tokens
            limits = next(
                (
                    m
                    for m in load_spec()["models"].values()
                    if m["model_id"] == run.params.get("model")
                ),
                {},
            )
            row["daily token quota % / question"] = (
                100 * tokens / limits["tpd"] if limits.get("tpd") else "not available"
            )
        else:
            row["reported tokens / question"] = "not available"
            row["daily token quota % / question"] = "not available"
        table.append(row)
    dataframe(table, use_container_width=True)
    st.caption(
        "Token usage is not a dollar cost. Per-question usage requires source-row accounting; "
        "unknown denominators and review-only costs stay unavailable. Quota % uses configured "
        "per-model daily limits, not the provider's current remaining allowance."
    )
    if not table:
        st.info("No cost or latency records yet.")


def error_analysis():
    st.header("Error analysis")
    values = [
        r for r in records(("research-answer-eval", "playground")) if r.tags.get("split") == "dev"
    ]
    if not values:
        st.info("No dev prediction artifacts yet.")
        return
    run = st.selectbox("Dev run", values, format_func=name)
    snapshot = mf.artifact(mf.uri(), run.id, "predictions.jsonl")
    if not snapshot.value:
        st.info(
            snapshot.error
            or (
                "not available yet: review-only"
                if run.tags.get("provenance") == "review-only"
                else "No dev prediction artifact available."
            )
        )
        return
    from collections import Counter

    counts = Counter(error.split(":")[0] for r in snapshot.value for error in r.get("errors", []))
    dataframe([{"category": k, "n": v} for k, v in counts.items()], use_container_width=True)
    st.caption(
        "Dev predictions only; no test questions or gold. Citation IDs reference the run evidence."
    )
    dataframe(snapshot.value, use_container_width=True)


def widgets(start):
    spec = load_spec()
    fields = spec["hyperparameters"]
    system = st.selectbox(
        "System",
        fields["system_id"]["choices"],
        index=fields["system_id"]["choices"].index(start.get("system_id", "S2")),
        help=fields["system_id"]["help"],
    )
    model_ids = [m["model_id"] for m in spec["models"].values()]
    model = st.selectbox(
        "Model",
        model_ids,
        index=model_ids.index(start.get("model", model_ids[0])),
        help=fields["model"]["help"],
    )
    values = {"system_id": system, "model": model}
    for key, knob in fields.items():
        if key in values or system not in knob["applies_to"]:
            continue
        default = start.get(key, knob["default"])
        choices = knob.get("choices")
        if key == "retriever":
            if system in FIXED_RETRIEVERS:
                choices = [FIXED_RETRIEVERS[system]]
            elif system == "R0":
                choices = [v for v in choices if not v.startswith("R7")]
            elif system == "S3":
                choices = ["R7a", "R7b"]
        if key == "rrf_k" and values.get("retriever") in ("R1", "R2"):
            continue
        if key == "query_transform":
            values[key] = values["retriever"]
            st.caption(f"{knob['label']}: {values[key]} (matches S3 retriever)")
            continue
        if choices:
            default = default if default in choices else knob["default"]
            if default not in choices:
                default = choices[0]
            values[key] = st.selectbox(
                knob["label"],
                choices,
                index=choices.index(default),
                help=knob["help"],
                key=f"knob-{system}-{key}",
            )
        else:
            if default is None:
                if not st.checkbox(
                    f"Override {knob['label']}", help=knob["help"], key=f"override-{system}-{key}"
                ):
                    continue
                default = knob["default"] if knob["default"] is not None else knob["min"]
            cast = int if knob["type"] == "integer" else float
            values[key] = st.number_input(
                knob["label"],
                min_value=cast(knob["min"]),
                max_value=cast(knob["max"]),
                value=cast(default),
                help=knob["help"],
                key=f"knob-{system}-{key}",
            )
    return RunConfig(**values).validate_against()


def experiment_lab():
    from bugzilla_serving.dashboard import lab

    st.header("Experiment Lab")
    if not enabled():
        st.info(
            "Experiment Lab is disabled. "
            "Set DASHBOARD_LAB_ENABLED=true locally to enable controls. "
            "The deployed read-only dashboard cannot spend LLM quota."
        )
        return
    st.warning("Experiments use dev questions only. Mock scores are simulated plumbing checks.")
    bundles = lab.real_bundle()
    if not bundles:
        st.info("No real BUNDLE_DIR: only fixture-bundle / MockProvider execution is available.")
    available = mf.presets(mf.uri()).value
    source_runs = [
        r for r in records(("research-answer-eval", "playground")) if r.tags.get("split") == "dev"
    ]
    origins = [
        "Defaults",
        *[f"Preset: {p['slug']}" for p in available],
        *[f"Run: {r.id}" for r in source_runs],
    ]
    origin = st.selectbox("Start from", origins)
    start = load_spec()["default_config"]
    if origin.startswith("Preset: "):
        start = next(p["config"] for p in available if p["slug"] == origin[8:])
    elif origin.startswith("Run: "):
        r = next(r for r in source_runs if r.id == origin[5:])
        import yaml

        start = {k: yaml.safe_load(v) for k, v in r.params.items() if k in RunConfig.model_fields}
    try:
        cfg = widgets(start)
    except (ValueError, TypeError) as exc:
        st.error(scrub(str(exc)))
        return
    spec = read(lab.SETS_PATH)
    eval_set = st.selectbox(
        "Eval set",
        list(spec["sets"]),
        index=list(spec["sets"]).index("smoke-5") if "smoke-5" in spec["sets"] else 0,
    )
    limit = st.number_input("Question limit", min_value=1, max_value=20, value=1)
    live = st.toggle(
        "Use live LLM",
        value=False,
        disabled=not bundles or cfg.provider == "mock",
        help="Explicitly spends Groq quota; off means MockProvider.",
    )
    fixture = not live and st.checkbox(
        "Use synthetic fixture bundle", value=not bundles, disabled=not bundles
    )
    max_requests = st.number_input("Maximum requests", min_value=1, max_value=900, value=20)
    sweep_knobs = st.multiselect(
        "Sweep knobs (up to 2)",
        [k for k in cfg.model_dump() if k not in ("system_id", "provider", "model")],
        max_selections=2,
    )
    grid = {}
    import yaml

    for knob in sweep_knobs:
        raw = st.text_input(f"{knob} values (comma separated)", value=str(getattr(cfg, knob)))
        grid[knob] = [yaml.safe_load(v) for v in raw.split(",")]
    try:
        if grid:
            from bugzilla_serving.experiments.sweep import plan_sweep

            _, plan = plan_sweep(
                cfg, grid, eval_set, limit, root=lab.LAB_ROOT, sets_path=lab.SETS_PATH
            )
            estimated = sum(t["calls"] for t in plan["totals"].values())
        else:
            plan = lab.preflight(cfg, eval_set, limit)
            estimated = plan["est_calls"]
        st.subheader("Preflight")
        st.json(plan)
    except (ValueError, OSError, KeyError) as exc:
        st.error(f"Preflight unavailable: {scrub(str(exc))}")
        return
    if not plan["fits"]:
        st.warning(plan["reason"])
    if st.button(
        "Run experiment", disabled=not plan["fits"] or (live and estimated > max_requests)
    ):
        try:
            # Never send mock writes to a remote tracking server.
            tracking = (
                mf.uri()
                if live or mf.uri().startswith("file:")
                else (lab.LAB_ROOT / "outputs/mlops/mlflow").as_uri()
            )
            st.session_state["launch"] = lab.jobs().submit(
                cfg,
                eval_set,
                limit,
                live=live,
                max_requests=max_requests,
                tracking_uri=tracking,
                fixture=fixture,
                grid=grid or None,
            )
        except Exception as exc:
            st.error(f"Job did not start: {scrub(str(exc))}")
    if st.session_state.get("launch"):
        show_progress(st.session_state["launch"])


@st.fragment(run_every=2)
def show_progress(token):
    from bugzilla_serving.dashboard import lab

    try:
        state = lab.jobs().status(token)
    except (OSError, ValueError):
        st.info("Waiting for job status…")
        return
    st.subheader("Job status")
    st.json(state)
    total = state.get("total") or 1
    st.progress(min(1.0, state.get("done", 0) / total))
    if state.get("state") in ("RUNNING", "PREFLIGHT", "SCORING", "QUEUED"):
        if st.button("Cancel job", key=f"cancel-{token}"):
            try:
                lab.jobs().cancel(token)
                st.info("Cancellation requested; current question may finish.")
            except ValueError as exc:
                st.warning(str(exc))
    elif state.get("mlflow_run_id") or state.get("sweep"):
        st.success(
            "Job completed and logged. "
            "Inspect pending/unscored families before interpreting scores."
        )
        if not st.session_state.get("refreshed-" + token):
            mf.clear()
            lab.publication_preview.clear()
            st.session_state["refreshed-" + token] = True
        jobs = state.get("sweep", {}).get("jobs", [state])
        for job in jobs:
            if not job.get("mlflow_run_id"):
                continue
            tracking = state.get("tracking_uri", mf.uri())
            run = next(
                (r for r in mf.runs(tracking, "playground").value if r.id == job["mlflow_run_id"]),
                None,
            )
            if run:
                if not tracking.startswith("file:"):
                    st.link_button(
                        "Open MLflow run",
                        tracking.rstrip("/") + f"/#/experiments/{run.experiment_id}/runs/{run.id}",
                    )
                else:
                    st.caption(f"Local MLflow run: {run.id} · {tracking} (view with mlflow ui)")
                # The mock store may differ from the dashboard's remote read store.
                families = mf.artifact(tracking, run.id, "per_family.csv").value or []
                dataframe(
                    [
                        {
                            "family": f,
                            "cell": family_cell(
                                run.metrics, f, tags=run.tags, family_rows=families
                            ).label,
                        }
                        for f in FAMILIES
                    ],
                    use_container_width=True,
                )


def compare_runs():
    st.header("Compare runs")
    values = records(("research-answer-eval", "playground"))
    by_label = {f"{name(r)} · {r.id}": r for r in values}
    labels = st.multiselect("Choose 2–3 runs", list(by_label), max_selections=3)
    chosen = [by_label[key] for key in labels]
    if len(chosen) < 2:
        st.info("Choose two or three runs with comparable eval sets and scored coverage.")
        return
    rows = []
    different = []
    for key in sorted(set().union(*(r.params for r in chosen))):
        row = {"parameter": key, **{r.id[:8]: r.params.get(key, "not available") for r in chosen}}
        rows.append(row)
        if len({str(row[r.id[:8]]) for r in chosen}) > 1:
            different.append(key)
    frame = pd.DataFrame(rows).set_index("parameter")
    dataframe(
        frame.style.apply(
            lambda s: ["background-color: #FEF3C7" if s.name in different else "" for _ in s],
            axis=1,
        ),
        use_container_width=True,
    )
    baseline = chosen[0]
    cells = []
    for run in chosen[1:]:
        for family in FAMILIES:
            a = family_cell(baseline.metrics, family)
            b = family_cell(run.metrics, family)
            if a.value is not None and b.value is not None:
                cells.append(
                    dict(
                        run=f"{name(run)} − {baseline.id[:8]}",
                        family=family,
                        score=b.value - a.value,
                        n=f"{b.n} vs {a.n}",
                    )
                )
    bars(cells, "Per-family score delta; n = candidate vs baseline")
    if len({r.tags.get("eval_set") for r in chosen}) > 1:
        st.warning("These eval sets differ. Deltas are descriptive, not a controlled comparison.")


@st.dialog("Confirm registry change")
def registry_dialog(payload):
    if not enabled():
        st.error("Lab is disabled; registry changes refused.")
        return
    st.json(payload)
    confirmed = st.checkbox("I confirm this registry change")
    if st.button("Apply change", disabled=not confirmed):
        try:
            from bugzilla_serving.dashboard import lab
            from bugzilla_serving.tracking.registry import Registry

            registry = Registry(mf.uri())
            if payload["action"] == "unpublish":
                registry.unpublish(payload["slug"])
            else:
                lab.publication(
                    registry,
                    payload["run_id"],
                    payload["slug"],
                    payload["label"],
                    payload["description"],
                    champion=payload["champion"],
                    apply=True,
                )
            mf.clear()
            st.success("Registry updated.")
            lab.publication_preview.clear()
        except Exception as exc:
            st.error(f"Change refused: {scrub(str(exc))}")


def presets_page():
    st.header("Presets")
    if not enabled():
        st.info("Registry controls are hidden in read-only mode.")
        return
    existing = mf.presets(mf.uri())
    st.caption(f"Presets last updated {existing.updated_at}")
    dataframe(existing.value, use_container_width=True)
    if existing.error:
        st.warning(existing.error)
    values = [
        r for r in records(("research-answer-eval", "playground")) if r.tags.get("split") == "dev"
    ]
    if values:
        run = st.selectbox("Candidate run", values, format_func=name)
        slug = st.text_input("Preset slug", value="candidate")
        label = st.text_input("Preset label", value="Candidate")
        description = st.text_input(
            "Description", value="Explicitly selected development configuration"
        )
        champion = st.checkbox("Promote to champion")
        try:
            from bugzilla_serving.dashboard import lab

            preview = lab.publication_preview(mf.uri(), run.id, slug, label, description, champion)
            st.subheader("Policy check and champion comparison")
            st.json(preview)
            if st.button(
                "Review publication", disabled=champion and not preview["policy"]["allowed"]
            ):
                registry_dialog(
                    dict(
                        action="publish",
                        run_id=run.id,
                        slug=slug,
                        label=label,
                        description=description,
                        champion=champion,
                    )
                )
        except Exception as exc:
            st.warning(f"Configuration is not publishable: {scrub(str(exc))}")
    else:
        st.info("No dev candidate runs yet.")
    if existing.value:
        slug = st.selectbox("Unpublish preset", [p["slug"] for p in existing.value])
        if st.button("Review unpublish"):
            registry_dialog(dict(action="unpublish", slug=slug))


def production():
    st.header("Production")
    source = os.environ.get("LANGSMITH_SOURCE", "live")
    default = (
        dt.date(2020, 1, 1) if source == "fixture" else dt.date.today() - dt.timedelta(days=30)
    )
    start = st.date_input("From (UTC)", value=default)
    end = st.date_input(
        "Through (UTC)", value=dt.date(2020, 1, 2) if source == "fixture" else dt.date.today()
    )
    if end < start:
        st.warning("End date must be on or after start date.")
        return
    snapshot = ls.roots(
        source, f"{start}T00:00:00+00:00", f"{end + dt.timedelta(days=1)}T00:00:00+00:00"
    )
    st.caption(
        f"ensf621-serving · {source} · last updated {snapshot.updated_at} · "
        "cached 60 s; reads capped at 1,000 root runs / 2,000 feedback records"
    )
    if snapshot.error:
        st.warning(snapshot.error)
    if not snapshot.value:
        st.info("No production data yet.")
        return
    dataframe(ls.grouped(snapshot.value), use_container_width=True)
    from collections import Counter

    days = Counter(r["day"] for r in snapshot.value)
    values = [dict(family=d, score=n, n=n, run="questions/day") for d, n in sorted(days.items())]
    bars(values, "Questions per day")
    st.caption(
        f"Degraded requests: {sum(r['degraded'] for r in snapshot.value)} / n={len(snapshot.value)}"
    )
    st.subheader("Recent thumbs-down feedback (sanitized)")
    dataframe(
        [
            {"day": r["day"], "preset": r["preset_slug"], "comment": r["comment"]}
            for r in sorted(snapshot.value, key=lambda r: r["started_at"], reverse=True)
            if r["rating"] == 0 and r["comment"]
        ][:20],
        use_container_width=True,
    )
