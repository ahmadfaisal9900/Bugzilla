"""Nine monitoring pages; only the explicitly enabled Lab performs experiments."""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import streamlit as st

from bugzilla_serving.contracts.names import EXPERIMENTS, FAMILIES, RETRIEVAL_METRICS
from bugzilla_serving.contracts.run_config import FIXED_RETRIEVERS, RunConfig, load_spec
from bugzilla_serving.dashboard import labels as L
from bugzilla_serving.dashboard.data import langsmith_source as ls
from bugzilla_serving.dashboard.data import mlflow_source as mf
from bugzilla_serving.dashboard.data.common import display_frame, family_cell, scrub
from bugzilla_serving.dashboard.profiling import page
from bugzilla_serving.dashboard.theme import PALETTE, style
from bugzilla_serving.tracking.backfill import read


def dataframe(rows, **kwargs):
    frame = display_frame(rows)
    config = {}
    glossary = {entry["name"]: entry["short"] for entry in L.catalog()["metrics"].values()}
    for col in frame.columns:
        key = str(col)
        help_text = glossary.get(
            key, f"{key}: recorded evaluation value; unavailable values are not zero."
        )
        if key == "Calls without usage data":
            counts = frame[col].astype(str).str.extract(r"^(\d+)", expand=False).dropna()
            n = int(counts.astype(int).max()) if len(counts) else 0
            help_text = (
                f"The provider didn't report usage for {n} calls, so this is a lower bound."
                if n
                else glossary[key]
            )
        if key.endswith("(s)") and pd.api.types.is_numeric_dtype(frame[col]):
            config[col] = st.column_config.NumberColumn(format="%.1f", help=help_text)
        elif key == "Questions" and pd.api.types.is_numeric_dtype(frame[col]):
            config[col] = st.column_config.NumberColumn(format="localized", help=help_text)
        else:
            config[col] = st.column_config.Column(help=help_text)
    kwargs.setdefault("column_config", config)
    st.dataframe(frame, hide_index=True, **kwargs)


def enabled():
    return os.environ.get("DASHBOARD_LAB_ENABLED") == "true"


def records(experiments=EXPERIMENTS):
    result = []
    for experiment in experiments:
        snapshot = mf.runs(mf.uri(), experiment)
        if snapshot.error:
            st.warning(snapshot.error)
        result.extend(snapshot.value)
    st.session_state["_run_labels"] = L.run_labels(result)
    return result


def name(run):
    label = st.session_state.get("_run_labels", {}).get(
        run.id, L.name("systems", run.params.get("system_id", "?"))
    )
    if st.session_state.get("technical_ids", False):
        label += " · " + " / ".join(
            run.params.get(k, "?") for k in ("system_id", "retriever", "corpus")
        )
    if run.tags.get("simulated") == "true":
        label += " · Simulated"
    return label


def rows_for(run, artifact="per_family.csv"):
    snapshot = mf.artifact(mf.uri(), run.id, artifact)
    return snapshot.value if isinstance(snapshot.value, list) else []


def filtered(values):
    sets = sorted({r.tags.get("eval_set", "unknown") for r in values})
    datasets = sorted({d for r in values for d in r.tags.get("datasets", "").split(",") if d})
    chosen = st.multiselect(
        "Question set",
        sets,
        default=sets,
        format_func=lambda v: L.name("eval_sets", v),
        help="Choose the dev questions used for evaluation; pilot results cover a subset.",
    )
    dataset = st.selectbox(
        "Question source",
        ["All", *datasets],
        format_func=lambda v: v if v == "All" else L.name("dataset_tags", v),
        help=(
            "Filter runs containing this source. Scores retain their recorded scope; "
            "mixed-source runs are not rescored."
        ),
    )
    return [
        r
        for r in values
        if r.tags.get("eval_set") in chosen
        and (dataset == "All" or dataset in r.tags.get("datasets", "").split(","))
    ]


def answer_table(values):
    result = []
    presets = mf.presets(mf.uri()).value
    starred = {p["config"]["system_id"] for p in presets if p["slug"] in ("recommended", "fast")}
    for run in values:
        if run.params.get("system_id") == "ORACLE":
            continue
        families = rows_for(run)
        row = {
            "System": ("★ " if run.params.get("system_id") in starred else "") + name(run),
            "Description": L.short("systems", run.params.get("system_id", "?")),
            "Overall score": run.metrics.get("answer.macro"),
        }
        for family in FAMILIES:
            cell = family_cell(run.metrics, family, tags=run.tags, family_rows=families)
            row[L.name("families", family)] = cell.value if cell.value is not None else None
        result.append(row)
    return sorted(
        result,
        key=lambda r: r["Overall score"] if r["Overall score"] is not None else -1,
        reverse=True,
    )


def bars(values, title, y="score"):
    if not values:
        st.info("No scored values available yet.")
        return
    import plotly.express as px

    frame = pd.DataFrame(values)
    frame["label"] = frame[y].map(lambda v: f"{v:.0%}") + " · n=" + frame["n"].astype(str)
    frame["family"] = frame["family"].map(lambda f: L.name("families", f) if f in FAMILIES else f)
    figure = px.bar(
        frame,
        y="family",
        x=y,
        color="run",
        orientation="h",
        barmode="group",
        text="label",
        color_discrete_sequence=PALETTE,
        hover_data=["n"],
        title=title,
    )
    figure.update_layout(xaxis_title="Share correct", yaxis_title="Question family")
    figure.update_xaxes(tickformat=".0%")
    st.plotly_chart(style(figure), use_container_width=True)


@page
def overview():
    page_intro("Overview", "Research results and published modes at a glance.")
    champion = mf.champion(mf.uri())
    presets = mf.presets(mf.uri()).value
    values = filtered(records(("research-answer-eval", "playground")))
    latest = mf.latest_per_config(values)
    columns = st.columns(5)
    for column, slug, title in zip(
        columns[:2], ("recommended", "fast"), ("Recommended mode", "Fast mode")
    ):
        preset = next((p for p in presets if p["slug"] == slug), None)
        system = preset["config"]["system_id"] if preset else None
        source = next((r for r in latest if r.params.get("system_id") == system), None)
        column.metric(
            title,
            L.name("systems", system) if system else "Not published",
            L.fmt_score(source.metrics.get("answer.macro")) if source else None,
        )
    scored = [
        r for r in latest if "answer.macro" in r.metrics and r.params.get("system_id") != "ORACLE"
    ]
    best = max(scored, key=lambda r: r.metrics["answer.macro"], default=None)
    columns[2].metric(
        "Best overall in research",
        name(best) if best else "Not available",
        L.fmt_score(best.metrics["answer.macro"]) if best else None,
    )
    override = (champion.value or {}).get("tags", {}).get("policy_override")
    if best and (override or best.tags.get("policy_override")):
        columns[2].caption("not deployable: exceeds the 4,096-token serving limit")
    columns[3].metric(
        "Systems evaluated",
        len({r.params.get("system_id") for r in latest if r.params.get("system_id") != "ORACLE"}),
    )
    pilot = [r for r in latest if r.tags.get("eval_set") == "pilot125"]
    counts = [sum(int(f.get("source_n") or f.get("n") or 0) for f in rows_for(r)) for r in pilot]
    columns[4].metric(
        "Questions in the pilot", L.fmt_int(max(counts)) if counts else "Not available"
    )
    if not champion.value:
        st.info(champion.error or "No champion published yet.")
    rows = answer_table(latest)
    if rows:
        frame = pd.DataFrame(rows)
        config = {
            "System": st.column_config.TextColumn(
                help="★ marks a published Recommended or Fast system."
            ),
            "Description": st.column_config.TextColumn(help="How the answering system works."),
            "Overall score": st.column_config.ProgressColumn(
                min_value=0, max_value=1, format="percent", help=L.short("metrics", "macro")
            ),
        }
        for f in FAMILIES:
            config[L.name("families", f)] = st.column_config.NumberColumn(
                format="percent",
                help=L.short("families", f)
                + " Missing means unscored or unavailable. "
                + "Inspect Answer evaluation for denominators.",
            )
        st.dataframe(
            frame.style.map(
                lambda v: f"background-color: rgba(37,99,235,{0.08 + 0.5 * v:.2f})"
                if pd.notna(v)
                else "",
                subset=[L.name("families", f) for f in FAMILIES],
            ),
            column_config=config,
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No answer evaluation runs yet.")
    st.subheader("Key findings")
    with st.container(border=True):
        for finding in read(L.ROOT / "configs/findings.yaml"):
            st.markdown("- " + finding)
    for run in latest:
        technical(run)


@page
def answer_eval():
    page_intro(
        "Answer evaluation",
        "Correctness by question family, with recorded sample sizes and uncertainty.",
    )
    values = filtered(records(("research-answer-eval", "playground")))
    cells = []
    for run in values:
        families = rows_for(run)
        for f in FAMILIES:
            cell = family_cell(run.metrics, f, tags=run.tags, family_rows=families)
            if cell.value is not None:
                cells.append(dict(run=name(run), family=f, score=cell.value, n=cell.n))
    bars(cells, "Correct answers by family")
    dataframe(
        [
            {
                "System": r["run"],
                "Family": L.name("families", r["family"]),
                "Score": L.fmt_score(r["score"]),
                "Questions": r["n"],
            }
            for r in cells
        ],
        use_container_width=True,
    )
    st.subheader("Declined answers and errors")
    dataframe(
        [
            {
                "System": name(r),
                "Correctly declined": L.fmt_score(r.metrics.get("abstain.correct_rate")),
                "Incorrectly declined": L.fmt_score(r.metrics.get("abstain.false_rate")),
                "Errors": L.fmt_score(r.metrics.get("fail.rate")),
            }
            for r in values
        ],
        use_container_width=True,
    )
    with st.expander("Saved confidence intervals"):
        for run in values:
            intervals = mf.artifact(mf.uri(), run.id, "intervals.json").value
            if intervals:
                st.caption(name(run))
                dataframe(
                    [
                        {
                            k.replace("_", " ").capitalize(): L.name("families", v)
                            if k == "family"
                            else v
                            for k, v in row.items()
                            if k not in ("run_id", "config_hash", "git_sha")
                        }
                        for row in intervals
                    ],
                    use_container_width=True,
                )
    for run in values:
        technical(run)


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


@page
def retrieval_eval():
    page_intro(
        "Retrieval evaluation", "How well each search method finds the known supporting passages."
    )
    values = records(("research-retrieval-eval",))
    sets = sorted({r.tags.get("eval_set", "unknown") for r in values})
    if sets:
        selected = st.selectbox("Question set", sets, format_func=lambda v: L.name("eval_sets", v))
        values = [r for r in values if r.tags.get("eval_set") == selected]
    dataset = st.selectbox(
        "Question source",
        ["v3", "natural", "phase05"],
        format_func=lambda v: L.name("dataset_tags", v),
        help=(
            "Known supporting citations can be incomplete; "
            "unlabelled passages are not necessarily irrelevant."
        ),
    )
    metric = st.selectbox(
        "Search measure",
        [m for m in RETRIEVAL_METRICS if m not in ("n", "r4_r3_jaccard_top10")],
        index=4,
        format_func=lambda v: v.replace("_", " ").title(),
    )
    family = st.selectbox(
        "Question family", list(FAMILIES), format_func=lambda f: L.name("families", f)
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
        latency = run.metrics.get(f"retr.{dataset}.{family}.latency_p95_ms")
        table.append(
            {
                "Search method": L.name("retrievers", run.params.get("retriever", "?")),
                "Archive format": L.name("corpora", run.params.get("corpus", "?")),
                "Score": L.fmt_score(cell.value) if cell.value is not None else cell.state,
                "Questions": cell.n,
                "Selected": run.tags.get("selected") == "true",
                "Slow-case time (s)": L.fmt_seconds(latency / 1000)
                if latency is not None
                else "Not available",
            }
        )
    dataframe(table, use_container_width=True)
    known = [r for r in table if r["Score"].endswith("%")]
    if known:
        import plotly.express as px

        frame = pd.DataFrame(known)
        frame["Score"] = frame["Score"].str.rstrip("%").astype(float) / 100
        figure = px.density_heatmap(
            frame,
            x="Archive format",
            y="Search method",
            z="Score",
            histfunc="avg",
            range_color=(0, 1),
            color_continuous_scale="Blues",
        )
        st.plotly_chart(style(figure), use_container_width=True)
    for run in values:
        technical(run)


@page
def cost_latency():
    page_intro("Cost & latency", "Reported model usage and batch time for each evaluated system.")
    values = filtered(records(("research-answer-eval", "playground")))
    usage, times = [], []
    for run in values:
        m = run.metrics
        missing_n = m.get("cost.usage_missing_n", 0)
        partial = " ⚠ partial" if missing_n > 0 else ""
        tokens = [m.get("cost.tokens_in"), m.get("cost.tokens_out")]
        limits = next(
            (m for m in load_spec()["models"].values() if m["model_id"] == run.params.get("model")),
            {},
        )
        quota = (
            sum(tokens) / limits["tpd"]
            if all(v is not None for v in tokens) and limits.get("tpd")
            else None
        )
        usage.append(
            {
                "System": name(run),
                "Model calls / question": m.get("cost.llm_calls_per_question"),
                "Tokens in": L.fmt_int(tokens[0]) + partial,
                "Tokens out": L.fmt_int(tokens[1]) + partial,
                "Daily quota used": L.fmt_score(quota) + partial,
                "Calls without usage data": L.fmt_int(missing_n) + partial,
            }
        )
        reused = run.tags.get("reused_from") or run.params.get("system_id") == "S3"
        row = {"System": name(run)}
        for key, label in [
            ("latency.p50_ms", "Typical time (s)"),
            ("latency.p95_ms", "Slow-case time (s)"),
        ]:
            row[label] = (
                "Same as Smart search (reused)" if reused else m[key] / 1000 if key in m else None
            )
        times.append(row)
    st.subheader("Model usage")
    st.caption(
        "Calls per question compare model effort; token totals and quota "
        "describe the recorded batch."
    )
    dataframe(usage, use_container_width=True)
    import plotly.express as px

    known = [r for r in usage if r["Model calls / question"] is not None]
    if known:
        st.plotly_chart(
            style(
                px.bar(pd.DataFrame(known), x="Model calls / question", y="System", orientation="h")
            ),
            use_container_width=True,
        )
    token_rows = [
        {
            "System": name(r),
            "Tokens in": r.metrics.get("cost.tokens_in"),
            "Tokens out": r.metrics.get("cost.tokens_out"),
            "Missing usage calls": r.metrics.get("cost.usage_missing_n", 0),
        }
        for r in values
        if "cost.tokens_in" in r.metrics or "cost.tokens_out" in r.metrics
    ]
    if token_rows:
        st.plotly_chart(
            style(
                px.bar(
                    pd.DataFrame(token_rows),
                    y="System",
                    x=["Tokens in", "Tokens out"],
                    barmode="group",
                    orientation="h",
                    hover_data=["Missing usage calls"],
                    title="Reported fresh tokens (partial where usage is missing)",
                )
            ),
            use_container_width=True,
        )
    st.subheader("Time per question")
    st.caption(
        "Typical is the median; slow-case is the 95th percentile, including batch rate-limit waits."
    )
    dataframe(times, use_container_width=True)
    known = [r for r in times if isinstance(r["Typical time (s)"], (float, int))]
    if known:
        st.plotly_chart(
            style(
                px.bar(
                    pd.DataFrame(known),
                    y="System",
                    x=["Typical time (s)", "Slow-case time (s)"],
                    barmode="group",
                    orientation="h",
                )
            ),
            use_container_width=True,
        )
    with st.expander("Notes"):
        for text in COST_NOTES:
            st.markdown("- " + text)
    for run in values:
        technical(run)


@page
def error_analysis():
    page_intro("Error analysis", "Inspect dev answer failures and their recorded reasons.")
    values = [
        r for r in records(("research-answer-eval", "playground")) if r.tags.get("split") == "dev"
    ]
    if not values:
        st.info("No dev prediction artifacts yet.")
        return
    run = st.selectbox("Dev run", values, format_func=run_formatter(values))
    technical(run)
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
    rows = []
    for row in snapshot.value:
        answer = row.get("answer", "")
        if isinstance(answer, dict):
            answer = answer.get("answer", "")
        rows.append(
            {
                "Family": L.name("families", row["family"])
                if row.get("family")
                else "Not recorded",
                "Answer": str(answer),
                "Status": row.get("status", "Not recorded"),
                "Errors": "; ".join(map(str, row.get("errors", []))),
                "Route": L.name("systems", row["route"]) if row.get("route") else "Not recorded",
            }
        )
    dataframe(rows, use_container_width=True)


def widgets(start):
    spec = load_spec()
    fields = spec["hyperparameters"]
    system = st.selectbox(
        "System",
        fields["system_id"]["choices"],
        index=fields["system_id"]["choices"].index(start.get("system_id", "S2")),
        help=fields["system_id"]["help"],
        format_func=lambda v: L.name("systems", v),
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
        if key == "corpus" and st.session_state.get("_bundle_report", {}).get("available_corpora"):
            available = st.session_state["_bundle_report"]["available_corpora"]
            for missing in [c for c in choices if c not in available]:
                st.checkbox(
                    L.name("corpora", missing) + " — isn't in this bundle",
                    value=False,
                    disabled=True,
                    key="unavailable-" + missing,
                )
            choices = [c for c in choices if c in available]
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
                format_func=(
                    lambda v,
                    kind={"corpus": "corpora", "retriever": "retrievers"}.get(key): L.name(kind, v)
                )
                if key in ("corpus", "retriever")
                else str,
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


@page
def experiment_lab():
    page_intro(
        "Experiment Lab",
        "Plan a bounded dev experiment and inspect bundle readiness before running.",
    )
    if not enabled():
        st.info(
            "Experiment Lab is disabled. "
            "Set DASHBOARD_LAB_ENABLED=true locally to enable controls. "
            "The deployed read-only dashboard cannot spend LLM quota."
        )
        return
    from bugzilla_serving.dashboard import lab

    st.warning("Experiments use dev questions only. Mock scores are simulated plumbing checks.")
    from pathlib import Path

    from bugzilla_serving.experiments.bundle_verify import verify_bundle

    bundle_path = Path(os.environ.get("BUNDLE_DIR", str(L.ROOT / "serving_bundle")))
    report = verify_bundle(bundle_path)
    st.session_state["_bundle_report"] = report
    st.subheader("Serving bundle")
    with st.container(border=True):
        st.write("Verified ✓" if report["ok"] else "Verified ✗")
        readable(
            {
                "split": report.get("split", "Unavailable"),
                "corpora": ", ".join(report["available_corpora"]),
                "embedder": report.get("embedding_model", "Unavailable"),
                "reranker": report.get("reranker_model", "Unavailable"),
                "size": f"{report.get('size_bytes', 0) / 1_000_000:.1f} MB",
                "built date": report.get("built_at", "Not recorded"),
            }
        )
        if report["errors"]:
            st.caption("Bundle checks failed; open Technical details for the reasons.")
    with st.expander("Technical details · Serving bundle"):
        st.json(report)
    bundles = report["ok"]
    if not bundles:
        st.info("No real BUNDLE_DIR: only fixture-bundle / MockProvider execution is available.")
    available = mf.presets(mf.uri()).value
    source_runs = [
        r for r in records(("research-answer-eval", "playground")) if r.tags.get("split") == "dev"
    ]
    origins = [
        "Defaults",
        *[f"Preset: {p['slug']}" for p in available],
        *[f"Run: {name(r)}" for r in source_runs],
    ]
    origin = st.selectbox("Start from", origins)
    start = load_spec()["default_config"]
    if origin.startswith("Preset: "):
        start = next(p["config"] for p in available if p["slug"] == origin[8:])
    elif origin.startswith("Run: "):
        r = next(r for r in source_runs if name(r) == origin[5:])
        import yaml

        start = {k: yaml.safe_load(v) for k, v in r.params.items() if k in RunConfig.model_fields}
    try:
        cfg = widgets(start)
        if bundles:
            from bugzilla_serving.experiments.preflight import bundle_preflight

            bundle_preflight(cfg, bundle_path)
    except (ValueError, TypeError) as exc:
        st.error(scrub(str(exc)))
        return
    spec = read(lab.SETS_PATH)
    eval_set = st.selectbox(
        "Question set",
        list(spec["sets"]),
        format_func=lambda v: L.name("eval_sets", v),
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
        readable(plan)
        with st.expander("Raw config (for debugging)"):
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
    readable(state)
    with st.expander("Technical details"):
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
                    technical(run)
                # The mock store may differ from the dashboard's remote read store.
                families = mf.artifact(tracking, run.id, "per_family.csv").value or []
                dataframe(
                    [
                        {
                            "Family": L.name("families", f),
                            "Score": family_cell(
                                run.metrics, f, tags=run.tags, family_rows=families
                            ).label,
                        }
                        for f in FAMILIES
                    ],
                    use_container_width=True,
                )


@page
def compare_runs():
    from bugzilla_serving.dashboard.comparison import (
        delta_to_questions,
        noise_marker,
        paired_counts,
        summary,
    )

    values = records(("research-answer-eval", "playground"))
    if len(values) < 2:
        page_intro("Compare runs", "Compare correct answers for two systems on the same questions.")
        st.info("Choose two runs once comparable evaluations are available.")
        return
    presets = mf.presets(mf.uri()).value
    recommended = next(
        (p["config"]["system_id"] for p in presets if p["slug"] == "recommended"), "S2"
    )
    index = next((i for i, r in enumerate(values) if r.params.get("system_id") == recommended), 0)
    baseline = st.selectbox("Baseline", values, index=index, format_func=run_formatter(values))
    others = [r for r in values if r.id != baseline.id]
    matched = [
        r
        for r in others
        if r.tags.get("eval_set") == baseline.tags.get("eval_set")
        and r.tags.get("datasets") == baseline.tags.get("datasets")
    ]
    others = matched or others
    candidate = st.selectbox("Candidate", others, format_func=run_formatter(values))
    page_intro(
        f"Where does {name(candidate)} do better or worse than {name(baseline)}?",
        "Paired family scores reveal where a strategy gains or loses correct answers.",
    )
    if baseline.tags.get("eval_set") != candidate.tags.get("eval_set") or baseline.tags.get(
        "datasets"
    ) != candidate.tags.get("datasets"):
        st.warning(
            "Question sets or sources differ. Select matching runs for a controlled comparison."
        )
        technical(baseline)
        technical(candidate)
        return
    snap = mf._snapshot(mf.uri())
    score_a = snap["artifacts"].get(baseline.id + "/scores.jsonl", {}).get("value", [])
    score_b = snap["artifacts"].get(candidate.id + "/scores.jsonl", {}).get("value", [])
    cells = []
    for family in FAMILIES:
        a, b = family_cell(baseline.metrics, family), family_cell(candidate.metrics, family)
        if a.value is None or b.value is None:
            continue
        if not a.n or a.n != b.n:
            st.warning(f"{L.name('families', family)}: question counts differ; omitted.")
            continue
        delta = b.value - a.value
        noise = noise_marker(delta, a.n, paired_counts(score_a, score_b, family, a.n))
        count = delta_to_questions(delta, a.n)
        label = (
            "both 0%"
            if a.value == b.value == 0
            else (
                f"{L.fmt_delta(delta)} ({abs(count)} "
                f"{'more' if count > 0 else 'fewer' if count < 0 else 'changed'} right)"
            )
        )
        if noise["noise"]:
            label += " ≈ within noise"
        cells.append(
            dict(family=family, n=a.n, a=a.value, b=b.value, delta=delta, label=label, **noise)
        )
    st.write(
        summary(
            name(candidate),
            name(baseline),
            cells,
            baseline.metrics.get("answer.macro"),
            candidate.metrics.get("answer.macro"),
        )
    )
    grouped = [
        dict(
            run=name(r),
            family=f"{L.name('families', row['family'])} ({row['n']} Qs)",
            score=row[k],
            n=row["n"],
        )
        for row in cells
        for r, k in [(baseline, "a"), (candidate, "b")]
    ]
    bars(grouped, "Correct answers in each family")
    if cells:
        import plotly.graph_objects as go

        colors = [
            "rgba(13,148,136,0.35)" if r["noise"] else "#0D9488" if r["delta"] > 0 else "#DC2626"
            for r in cells
        ]
        colors = [
            (
                "#94A3B8"
                if r["delta"] == 0
                else ("rgba(220,38,38,0.35)" if r["noise"] and r["delta"] < 0 else c)
            )
            for r, c in zip(cells, colors)
        ]
        fig = go.Figure(
            go.Bar(
                x=[r["delta"] * 100 for r in cells],
                y=[L.name("families", r["family"]) for r in cells],
                orientation="h",
                text=[r["label"] for r in cells],
                marker_color=colors,
                customdata=[r["p"] for r in cells],
                hovertemplate="%{text}<br>Exact paired p: %{customdata}<extra></extra>",
            )
        )
        fig.update_layout(
            xaxis_title="Candidate minus baseline (percentage points)",
            yaxis_title="Question family",
        )
        st.plotly_chart(style(fig), use_container_width=True)
        dataframe(
            [
                {
                    "Family": L.name("families", r["family"]),
                    "Questions": r["n"],
                    "Difference": r["label"],
                }
                for r in cells
            ],
            use_container_width=True,
        )
    with st.expander("Families and scoring glossary"):
        for family, entry in L.catalog()["families"].items():
            st.markdown(f"**{entry['name']}**: {entry['short']}. Example: {entry['example']}")
        st.write(L.short("metrics", "score") + " " + L.short("metrics", "macro"))
    technical(baseline)
    technical(candidate)


@st.dialog("Confirm registry change")
def registry_dialog(payload):
    if not enabled():
        st.error("Lab is disabled; registry changes refused.")
        return
    readable(payload)
    with st.expander("Technical details"):
        st.json(payload)
    confirmed = st.checkbox("I confirm this registry change")
    if st.button("Apply change", disabled=not confirmed):
        try:
            from bugzilla_serving.dashboard import lab

            lab.apply_registry_change(mf.uri(), payload)
            mf.clear()
            st.success("Registry updated.")
            lab.publication_preview.clear()
        except Exception as exc:
            st.error(f"Change refused: {scrub(str(exc))}")


@page
def presets_page():
    page_intro("Presets", "Review published modes and prepare an explicit registry change.")
    if not enabled():
        st.info("Registry controls are hidden in read-only mode.")
        return
    existing = mf.presets(mf.uri())
    st.caption(f"Presets last updated {existing.updated_at}")
    dataframe(
        [
            {
                "Mode": p["label"],
                "System": L.name("systems", p["config"]["system_id"]),
                "Description": p["description"],
                "Recommended": p["is_champion"],
            }
            for p in existing.value
        ],
        use_container_width=True,
    )
    if existing.error:
        st.warning(existing.error)
    values = [
        r for r in records(("research-answer-eval", "playground")) if r.tags.get("split") == "dev"
    ]
    if values:
        run = st.selectbox("Candidate run", values, format_func=run_formatter(values))
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
            readable(preview["policy"])
            dataframe(
                [
                    {
                        "Family": L.name("families", r["family"]),
                        "Candidate score": L.fmt_score(r["candidate_score"]),
                        "Candidate questions": r["candidate_n"],
                        "Champion score": L.fmt_score(r["champion_score"]),
                        "Champion questions": r["champion_n"],
                    }
                    for r in preview["comparison"]
                ],
                use_container_width=True,
            )
            technical(run)
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


@page
def production():
    page_intro("Production", "Recent chat volume, feedback and time grouped by mode.")
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
    from zoneinfo import ZoneInfo

    from bugzilla_serving.dashboard.data.snapshot import stale

    source_time = dt.datetime.fromisoformat(snapshot.updated_at).astimezone(
        ZoneInfo(os.environ.get("TZ", "America/Winnipeg"))
    )
    st.sidebar.caption(
        "Production data as of "
        + source_time.strftime("%d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    )
    if stale(
        {"built_at": snapshot.updated_at},
        float(os.environ.get("DASHBOARD_LANGSMITH_MAX_AGE_MIN", "5")),
    ):
        st.sidebar.caption("Production data is older than the configured age · Refresh data")
    if snapshot.error:
        st.warning(snapshot.error)
    if not snapshot.value:
        st.info("No production data yet.")
        return
    groups = ls.grouped(snapshot.value)
    dataframe(
        [
            {
                "Mode": L.name("presets", r["preset"]),
                "Model": r["model"],
                "Degraded": r["degraded"],
                "Questions": r["n"],
                "Thumbs up": L.fmt_score(r["thumbs_up"]),
                "Feedback count": r["feedback_n"],
                "Declined": L.fmt_score(r["abstain_rate"]),
                "Typical time (s)": L.fmt_seconds(r["p50_ms"] / 1000)
                if r["p50_ms"] is not None
                else "Not available",
                "Slow-case time (s)": L.fmt_seconds(r["p95_ms"] / 1000)
                if r["p95_ms"] is not None
                else "Not available",
            }
            for r in groups
        ],
        use_container_width=True,
    )
    from collections import Counter

    days = Counter(r["day"] for r in snapshot.value)
    values = [dict(family=d, score=n, n=n, run="questions/day") for d, n in sorted(days.items())]
    import plotly.express as px

    st.plotly_chart(
        style(
            px.bar(
                pd.DataFrame(values),
                x="family",
                y="n",
                labels={"family": "Day (UTC)", "n": "Questions"},
            )
        ),
        use_container_width=True,
    )
    st.caption(
        f"Degraded requests: {sum(r['degraded'] for r in snapshot.value)} / n={len(snapshot.value)}"
    )
    st.subheader("Recent thumbs-down feedback (sanitized)")
    dataframe(
        [
            {"day": r["day"], "Mode": L.name("presets", r["preset_slug"]), "comment": r["comment"]}
            for r in sorted(snapshot.value, key=lambda r: r["started_at"], reverse=True)
            if r["rating"] == 0 and r["comment"]
        ][:20],
        use_container_width=True,
    )


COST_NOTES = [
    "Tokens measure model usage, not money; the free tier costs nothing.",
    (
        '"Daily quota used" compares against our configured free-tier limits, '
        "not Groq's live remaining allowance."
    ),
    "Answers served from cache don't count as fresh tokens.",
    (
        '"⚠ partial" means the provider didn\'t report usage for some calls, '
        "so the total is a lower bound."
    ),
    (
        "Times include waiting for free-tier rate limits during batch runs; "
        "a single chat answer is much faster."
    ),
]


def page_intro(title, description):
    st.header(title)
    st.caption(description)
    with st.expander("How to read this"):
        st.markdown(
            "- Higher correctness is better; lower usage and time are better.\n-"
            " Check the number of scored questions before comparing.\n- Missing "
            "values are unavailable, never zero.\n- Pilot scores describe a dev "
            "subset; simulated runs check plumbing only."
        )
    if title != "Cost & latency":
        with st.expander("Notes"):
            st.markdown(
                "- Dev results do not establish test performance.\n- Family coverage"
                " and pending human reviews affect averages.\n- Search citations are"
                " incomplete labels, not a full relevance judgement."
            )


def technical(run):
    with st.expander("Technical details · " + name(run)):
        st.write("Run ID: " + run.id)
        st.write("Config hash: " + str(run.params.get("config_hash", "Not recorded")))
        st.write("Git SHA: " + run.tags.get("git_sha", "Not recorded"))
        st.write("Source run: " + run.tags.get("source_run_id", "Not recorded"))
        st.caption(" / ".join(run.params.get(k, "?") for k in ("system_id", "retriever", "corpus")))
        fields = load_spec()["hyperparameters"]
        dataframe(
            [
                {
                    "Setting": fields.get(k, {}).get("label", k.replace("_", " ").title()),
                    "Value": str(v),
                }
                for k, v in run.params.items()
                if k != "config_hash"
            ],
            use_container_width=True,
        )
        with st.popover("Raw config (for debugging)"):
            st.json(run.params)


def readable(values):
    # Top-level status/plan data gets a human-readable scalar table.
    rows = []
    for key, value in values.items():
        if key in ("id", "job_id", "mlflow_run_id", "config_hash", "git_sha", "source_run_id"):
            continue
        if isinstance(value, (dict, list)):
            continue
        rows.append({"Setting": key.replace("_", " ").capitalize(), "Value": str(value)})
    dataframe(rows, use_container_width=True)


def run_formatter(values):
    # Freeze the labels used by a widget; another page can change the visible
    # group before Streamlit serializes this widget's previous state.
    labels = {r.id: name(r) for r in values}
    return lambda run: labels[run.id]
