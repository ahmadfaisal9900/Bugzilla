"""Three plain-language tabs over the final saved development results."""

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from bugzilla_serving.dashboard.results_source import (
    DESCRIPTIONS,
    SYSTEMS,
    TYPES,
    fraction,
    links,
    paired,
    rate,
)
from bugzilla_serving.dashboard.theme import HEATMAP_SCALE, cell_color, style


def chart(fig, caption, key):
    st.plotly_chart(style(fig), use_container_width=True, key=key)
    st.caption(caption)


def score_frame(t):
    final = t["final_scores.csv"].copy()
    ci = t["overall_bootstrap.csv"][["System", "95% CI low %", "95% CI high %"]]
    final = final.merge(ci, on="System").merge(t["system_cost.csv"], on="System")
    counts = (
        t["per_question_scores.csv"]
        .groupby("System")["Scorer 2 verdict"]
        .apply(lambda s: int(s.eq("CORRECT").sum()))
    )
    final["Correct / 122"] = final["System"].map(counts).astype(str) + "/122"
    final["Description"] = final["System"].map(DESCRIPTIONS)
    return final.sort_values("Overall %", ascending=False)


def route_times(t):
    if "route_latency.csv" in t:
        return t["route_latency.csv"].rename(
            columns={"latency_p50_s": "Typical time (s)", "latency_p95_s": "Slow-case time (s)"}
        )
    rows = t["v2_cost_by_origin.csv"]
    rows = rows.loc[rows["Origin"].eq("parser-built")].copy()
    rows["Path"] = rows["Origin"].map(
        {"parser-built": "Local database answers", "preserved v2": "Preserved model answers"}
    )
    rows["Typical time (s)"] = pd.to_numeric(rows["Source latency p50 ms"]) / 1000
    rows["Slow-case time (s)"] = pd.to_numeric(rows["Source latency p95 ms"]) / 1000
    base = t["original_pilot_cost.csv"].set_index("System")
    more = []
    for system in ["Smart search", "Full bug dossier"]:
        r = base.loc[system]
        more.append(
            {
                "Path": system,
                "Questions": 23 if system == "Smart search" else 6,
                "Typical time (s)": float(r["Latency p50 ms"]) / 1000,
                "Slow-case time (s)": float(r["Latency p95 ms"]) / 1000,
            }
        )
    return pd.concat(
        [rows[["Path", "Questions", "Typical time (s)", "Slow-case time (s)"]], pd.DataFrame(more)],
        ignore_index=True,
    )


def results(t):
    data = score_frame(t)
    best = data.iloc[0]
    pq = t["per_question_scores.csv"]
    no_model = int(((pq["System"] == best["System"]) & pq["Origin"].eq("parser-built")).sum())
    cards = st.columns(4)
    cards[0].metric("Development questions", 122)
    cards[1].metric("Answering systems", 9)
    cards[2].metric("Most accurate: " + best["System"], f"{best['Overall %']:.1f}%")
    cards[2].caption(f"95% interval {best['95% CI low %']:.1f}–{best['95% CI high %']:.1f}%")
    cards[3].metric("Its answers needing no model call", f"{no_model / 122:.1%}")
    cards[3].caption(f"{no_model}/122 built locally; reused model answers still need a model.")
    st.caption("A development pilot used to diagnose the router. It is not a held-out test.")
    st.caption(
        "Auto-router combines 82 local answers, 10 preserved model answers, "
        "29 reused downstream answers and one failed request."
    )

    display = data[["System", "Description", *TYPES, "Correct / 122"]].copy()
    for f in TYPES:
        display[f] = display[f].map(lambda v: "/".join(map(str, fraction(v))))
    display["Overall (95% interval)"] = data.apply(
        lambda r: f"{r['Overall %']:.1f}% ({r['95% CI low %']:.1f}–{r['95% CI high %']:.1f})",
        axis=1,
    )
    display["Model calls / question"] = data["calls_per_q"].round(3)
    display["Tokens / question"] = data["tokens_per_q"].round(0)
    display["Typical time (s)"] = data["latency_p50_s"].map(
        lambda x: "see route times" if pd.isna(x) else f"{x:.2f}"
    )

    def shade(v):
        n = rate(v)
        return cell_color(n) if math.isfinite(n) else ""

    st.dataframe(display.style.map(shade, subset=TYPES), hide_index=True, use_container_width=True)
    st.caption(
        "Each question type counts equally in Overall. Cells show correct answers/questions."
    )
    chart(
        px.bar(
            data,
            x="System",
            y="Overall %",
            error_y=data["95% CI high %"] - data["Overall %"],
            error_y_minus=data["Overall %"] - data["95% CI low %"],
            text=["n=122"] * len(data),
        ),
        "Overall averages nine type accuracies. Whiskers show the 95% bootstrap interval.",
        "overall",
    )
    z = [[100 * rate(r[f]) for f in TYPES] for _, r in data.iterrows()]
    labels = [["/".join(map(str, fraction(r[f]))) for f in TYPES] for _, r in data.iterrows()]
    chart(
        go.Figure(
            go.Heatmap(
                z=z,
                x=TYPES,
                y=data["System"],
                text=labels,
                texttemplate="%{text}",
                colorscale=HEATMAP_SCALE,
                zmin=0,
                zmax=100,
            )
        ),
        "Darker cells mean more correct answers; labels retain the question count.",
        "heatmap",
    )
    scatter = data.assign(Questions=122)
    chart(
        px.scatter(
            scatter,
            x="tokens_per_q",
            y="Overall %",
            color="System",
            text="Questions",
            hover_data=["calls_per_q"],
        ),
        (
            "Higher and further left means more accurate with fewer estimated tokens per "
            "question; labels are n."
        ),
        "cost",
    )
    declines = t["abstention_failures.csv"].copy()
    declines["Correct decline %"] = 100 * declines[
        "Correct declines / Unanswerable + Hard unanswerable"
    ].map(rate)
    declines["False decline %"] = 100 * declines["False declines / answerable"].map(rate)
    declines["n"] = declines["False declines / answerable"].map(
        lambda v: "n=" + str(fraction(v)[1])
    )
    chart(
        px.scatter(
            declines,
            x="False decline %",
            y="Correct decline %",
            color="System",
            text="n",
            hover_data=["Correct declines / Unanswerable + Hard unanswerable"],
        ),
        (
            "Closed-book declines everything, so it scores full marks only where "
            "declining is the answer."
        ),
        "declines",
    )
    st.subheader("Time by Auto-router path")
    st.dataframe(route_times(t), hide_index=True, use_container_width=True)
    st.caption(
        "Route times are kept separate. Averages of route percentiles are not pooled percentiles."
    )
    st.subheader("How well search finds evidence")
    retr = t["retrieval_pairs.csv"].copy()
    retr["Selected"] = retr["Selected"].astype(str).str.lower().eq("true")
    retr["Method"] = retr["Retriever"] + retr["Selected"].map({True: " ★", False: ""})
    retr["n"] = retr["Selection questions"]
    retrieval_display = retr.drop(columns=["Retriever"]).copy()
    details = t["retrieval_family_comparison.csv"].drop_duplicates(["Source", "Family"])
    diagnostics = {
        "Find bug by description bug Hit@5": ("Find bug by description", "bug_hit_at_5"),
        "Multi-step full evidence@10": ("Multi-step", "mh_full_evidence_at_10"),
    }
    for field in [
        "Selection macro Recall@10",
        "Macro Hit@5 (eligible cells)",
        "Macro MRR@10 (eligible cells)",
        "Macro nDCG@10 (eligible cells)",
    ]:
        retrieval_display[field] = [
            f"{float(v):.3f} (n={int(n)})" for v, n in zip(retr[field], retr["n"])
        ]
    import re

    for field, (kind, metric) in diagnostics.items():
        denominator = sum(
            int(m[1])
            for value in details.loc[details["Family"].eq(kind), metric]
            if (m := re.search(r"n=(\d+)", str(value)))
        )
        retrieval_display[field] = [
            f"{float(v):.3f} (n={denominator})"
            if str(v) != "N/A" and denominator
            else "not measured"
            for v in retr[field]
        ]
    st.dataframe(retrieval_display, hide_index=True, use_container_width=True)
    st.caption(
        (
            "★ is the selected search method and passage version. Metrics use saved "
            "development results; n is the selection question count."
        )
    )
    pivot = retr.pivot(index="Retriever", columns="Corpus", values="Selection macro Recall@10")
    n = int(retr["n"].iloc[0])
    text = [[f"{v:.1%}<br>n={n}" for v in row] for row in pivot.values]
    chart(
        go.Figure(
            go.Heatmap(
                z=pivot.values,
                x=pivot.columns,
                y=pivot.index,
                text=text,
                texttemplate="%{text}",
                colorscale=HEATMAP_SCALE,
            )
        ),
        "Recall measures how much required evidence appears in the first ten passages.",
        "retr_heat",
    )
    retr["Median search time (ms)"] = pd.to_numeric(retr["Selection latency p50 ms"])
    chart(
        px.scatter(
            retr,
            x="Median search time (ms)",
            y="Selection macro Recall@10",
            color="Retriever",
            symbol="Corpus",
            text="n",
            log_x=True,
        ),
        (
            "Higher and further left means better evidence coverage with faster search; "
            "time uses a log scale."
        ),
        "retr_cost",
    )
    with st.expander("How scoring works"):
        st.write(
            "Answers use JSON: answer, answer_type, abstain, bug_ids and citations. "
            "Fields match recorded values; counts match numbers; bug sets ignore order. "
            "Durations use hours and a one-hour tolerance. "
            "Unknown questions require declining. Multi-step answers need every set. "
            "Descriptions match the target bug. Reasons are judged against frozen "
            "human-reviewed claims by "
            + str(t["judge_agreement.csv"]["External judge"].iloc[0])
            + ". Overall is the mean of nine type accuracies. The 95% interval "
            "resamples questions within each type 10,000 times. "
            "Three development-labelled counts with test-population scope are excluded."
        )


def compare(t):
    mode = st.radio("Compare", ["Answering systems", "Search methods"], horizontal=True)
    if mode == "Answering systems":
        a = st.selectbox("System A", SYSTEMS, index=8)
        b = st.selectbox(
            "System B", [s for s in SYSTEMS if s != a], index=2 if a != "Smart search" else 0
        )
        data = score_frame(t).set_index("System")
        for col, s in zip(st.columns(2), [a, b]):
            r = data.loc[s]
            col.metric(s, f"{r['Overall %']:.1f}%")
            col.caption(
                f"95% interval {r['95% CI low %']:.1f}–{r['95% CI high %']:.1f}%; "
                f"{r['Correct / 122']}; {r['calls_per_q']:.3f} calls/question; "
                f"{r['tokens_per_q']:.0f} tokens/question; "
                + (
                    "time varies by route"
                    if pd.isna(r["latency_p50_s"])
                    else f"{r['latency_p50_s']:.2f} s typical"
                )
            )
        rows, delta = [], []
        for f in TYPES:
            for s in [a, b]:
                k, n = fraction(data.loc[s, f])
                rows.append(
                    {"System": s, "Type": f, "Accuracy %": 100 * k / n, "Answers": f"{k}/{n}"}
                )
            delta.append(
                {
                    "Type": f,
                    a: data.loc[a, f],
                    b: data.loc[b, f],
                    "Difference (percentage points)": 100
                    * (rate(data.loc[a, f]) - rate(data.loc[b, f])),
                }
            )
        chart(
            px.bar(
                pd.DataFrame(rows),
                x="Type",
                y="Accuracy %",
                color="System",
                barmode="group",
                text="Answers",
            ),
            "The same questions are compared for both systems; bars show correct/total.",
            "compare_answers",
        )
        st.dataframe(pd.DataFrame(delta), hide_index=True)
        counts, disagreements = paired(t["per_question_scores.csv"], a, b)
        st.write(
            f"Both right: {counts['both']}; only {a}: {counts['a_only']}; "
            f"only {b}: {counts['b_only']}; neither: {counts['neither']}."
        )
        if counts["p"] < 0.001:
            text = (
                "A difference this large would happen by chance less than 1 in 1,000 times "
                "under equal paired correctness."
            )
        elif counts["p"] < 0.05:
            text = "The paired difference is statistically detectable at the 5% level."
        else:
            text = "This difference could be chance."
        st.write(text + f" Exact paired McNemar p = {counts['p']:.6g}.")
        st.caption("This pair’s p-value is unadjusted; the pilot was used to develop the router.")
        with st.expander("Questions where the systems disagree"):
            st.dataframe(
                disagreements.rename(columns={"Source": "Question source", "Family": "Type"}),
                hide_index=True,
            )
    else:
        retr = t["retrieval_pairs.csv"].copy()
        retr["Pair"] = retr["Retriever"] + " / " + retr["Corpus"]
        options = list(retr["Pair"])
        a = st.selectbox(
            "Search A", options, index=options.index("Multi-query / Full-text passages")
        )
        b = st.selectbox(
            "Search B",
            [o for o in options if o != a],
            index=[o for o in options if o != a].index("Keyword (BM25) / Full-text passages")
            if a != "Keyword (BM25) / Full-text passages"
            else 0,
        )
        st.dataframe(
            retr.loc[retr["Pair"].isin([a, b])].drop(columns=["Selected"]), hide_index=True
        )
        for label in [a, b]:
            r = retr.loc[retr["Pair"].eq(label)].iloc[0]
            detail = t["retrieval_family_comparison.csv"]
            detail = detail.loc[
                detail["Retriever"].eq(r["Retriever"]) & detail["Corpus"].eq(r["Corpus"])
            ]
            if detail.empty:
                st.info(label + ": per-group results not measured in this export.")
                continue
            bars = []
            for _, d in detail.iterrows():
                for m, title in [("recall_at_10", "Recall@10"), ("hit_at_5", "Hit@5")]:
                    match = __import__("re").match(r"([0-9.]+) \(n=(\d+)\)", str(d[m]))
                    if match:
                        bars.append(
                            {
                                "Group": d["Source"] + " · " + d["Family"],
                                "Metric": title,
                                "Value": float(match[1]),
                                "n": "n=" + match[2],
                            }
                        )
            if bars:
                chart(
                    px.bar(
                        pd.DataFrame(bars),
                        x="Group",
                        y="Value",
                        color="Metric",
                        barmode="group",
                        text="n",
                    ),
                    label
                    + (
                        ": each bar shows its own evidence denominator; "
                        "absent groups are not measured."
                    ),
                    "search_detail_" + label,
                )
        if "Keyword (BM25)" in a or "Keyword (BM25)" in b:
            other = b if "Keyword (BM25)" in a else a
            r = retr.loc[retr["Pair"].eq(other)].iloc[0]
            base = retr.loc[retr["Pair"].eq(a if "Keyword (BM25)" in a else b)].iloc[0]
            if r["Corpus"] != base["Corpus"]:
                st.info(
                    (
                        "Saved intervals compare methods within the same passage version; no "
                        "cross-version interval is available."
                    )
                )
            else:
                ci = t["retrieval_bootstrap_vs_keyword.csv"]
                ci = ci.loc[ci["Retriever"].eq(r["Retriever"]) & ci["Corpus"].eq(r["Corpus"])]
                st.dataframe(ci, hide_index=True) if not ci.empty else st.info(
                    "No saved interval for this pair."
                )


RULES = [
    ("1", "Multi-step wording", "Which of those are still unresolved?", "Database path"),
    ("2", "Complete explicit database request", "What component is bug 1770351?", "Database path"),
    ("3", "Count wording", "How many bugs match this condition?", "Database path"),
    (
        "4",
        "Bug ID and reason wording",
        "What reason is in the cited comment for bug 1708248?",
        "Bug dossier; cited comment first when stated",
    ),
    ("5", "Relationship wording", "Which bugs block bug 1771951?", "Database path"),
    ("6", "No explicit bug ID", "Which report describes a broken Pocket section?", "Smart search"),
    (
        "7",
        "Structured field or history wording",
        "When was bug 1794818 first fixed?",
        "Database path",
    ),
    (
        "8",
        "Ambiguous explicit-ID question",
        "Tell me about bug 1770351.",
        "Bounded model classifier",
    ),
]


def how(t):
    st.write(
        (
            "The router sees only the question text. It does not see the answer or the "
            "question-type label."
        )
    )
    st.dataframe(
        pd.DataFrame(RULES, columns=["Order", "Check", "Example", "Route"]), hide_index=True
    )
    routes = t["routing_by_family.csv"].copy()
    routes["Final generation count"] = (
        routes["Final generation count"]
        .astype(str)
        .str.replace(
            "N/A: native-turn count not separately recorded", "not separately recorded", regex=False
        )
    )
    st.dataframe(routes, hide_index=True, use_container_width=True)
    st.caption(
        (
            "This is what the recorded run actually used, including model answers "
            "preserved from its earlier attempt."
        )
    )
    st.write(
        "Answer model: gpt-oss-20b on Groq. Semantic search: all-MiniLM-L6-v2. "
        "Reranking: ms-marco-MiniLM-L-6-v2 cross-encoder. Keyword search: BM25. "
        "Structured lookups: DuckDB. Reasons judge: "
        + str(t["judge_agreement.csv"]["External judge"].iloc[0])
        + "."
    )
    for label, url in links().items():
        st.link_button(label, url)


def render(t):
    st.title("Bugzilla development results")
    st.caption("Nine ways to answer the same 122 development questions.")
    tabs = st.tabs(["Results", "Compare", "How it works & links"])
    with tabs[0]:
        results(t)
    with tabs[1]:
        compare(t)
    with tabs[2]:
        how(t)
