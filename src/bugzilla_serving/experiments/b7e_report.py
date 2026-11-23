"""Bounded offline B7e inventory, parser coverage, source scores and resume plan."""

import csv
import json
from collections import Counter
from pathlib import Path

from bugzilla_qa.answering_v2.json_tools import preparse
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.experiments.preflight import usage
from bugzilla_serving.experiments.scorer_v2 import grade
from bugzilla_serving.experiments.v2_jobs import context, load_eval_set, plan
from bugzilla_serving.tracking.backfill import sha


def generate(root=ROOT, source=None, bundle=None):
    root = Path(root)
    source = Path(source or root / "outputs/predictions/v2/dev/run-cf2c6f2cf859a3c6/S8v2.jsonl")
    bundle = Path(bundle or root / "serving_bundle")
    output = root / "outputs/analysis/b7e"
    output.mkdir(parents=True, exist_ok=True)
    before = sha(source)
    items, questions, _, backend, llm, _, _ = context(root, bundle)
    selected, _ = load_eval_set("pilot122-v2", root=root)
    roster = {(i["dataset"], i["qid"]): i for i in selected}
    coverage = []
    for family in ("F2", "F3", "F4", "MH"):
        group = [i for i in selected if i["family"] == family]
        coverage.append(
            dict(
                family=family,
                fully_parsed=sum(
                    preparse(questions[i["dataset"], i["qid"]])["complete"] for i in group
                ),
                total=len(group),
            )
        )
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    fresh = [p for p in rows if not p.get("carried_forward") and p["family"] != "F5"]
    score_rows = []
    for p in fresh:
        key = p["dataset"], p["qid"]
        i = roster[key]
        score_rows.append(
            dict(
                dataset=key[0],
                qid=key[1],
                family=i["family"],
                new=grade(i, p)["verdict"],
                s8_v1=grade(i, backend.saved[key])["verdict"],
                status=p["status"],
                errors=p.get("errors", []),
            )
        )
    table = []
    for family in ("F2", "F3", "F4", "MH"):
        new = [s for s in score_rows if s["family"] == family]
        all_items = [i for i in selected if i["family"] == family]
        table.append(
            dict(
                family=family,
                new_correct=sum(s["new"] == "CORRECT" for s in new),
                new_total=len(new),
                same_qids_s8_correct=sum(s["s8_v1"] == "CORRECT" for s in new),
                full_s8_correct=sum(
                    grade(i, backend.saved[i["dataset"], i["qid"]])["verdict"] == "CORRECT"
                    for i in all_items
                ),
                full_s8_total=len(all_items),
            )
        )
    budget = usage(RunConfig(system_id="S8"), llm, root)
    result = plan(root, bundle, "S8v2", "pilot122-v2", "changed", source)
    families = Counter(
        d["family"]
        for d in result["details"]
        if not d.get("carried_forward") and not d.get("preserved_from_v2")
    )
    report = dict(
        state="OFFLINE_ONLY",
        actual_api_calls=0,
        parser_coverage=coverage,
        source_scores=table,
        budget=budget,
        run_set=dict(families),
        plan=result,
        source_sha256=before,
    )
    (output / "summary.json").write_text(json.dumps(report, indent=2))
    (output / "resume-plan.json").write_text(json.dumps(result, indent=2))
    (output / "superseded_rows.json").write_text(
        json.dumps(result["resume"]["superseded"], indent=2)
    )
    with (output / "source_scores.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(score_rows[0]))
        writer.writeheader()
        writer.writerows(score_rows)
    lines = [
        "# B7e offline findings",
        "",
        "## Parser coverage",
        "",
        "| Family | Fully parsed | Total |",
        "| --- | ---: | ---: |",
    ]
    lines += [f"| {r['family']} | {r['fully_parsed']} | {r['total']} |" for r in coverage]
    lines += [
        "",
        "## Existing new rows scored offline with scorer v2",
        "",
        "| Family | S8v2 new | S8 v1 same questions | S8 v1 full eligible family |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {r['family']} | {r['new_correct']}/{r['new_total']} | "
        f"{r['same_qids_s8_correct']}/{r['new_total']} | "
        f"{r['full_s8_correct']}/{r['full_s8_total']} |"
        for r in table
    ]
    lines += [
        "",
        "Budget (Pacific quota date " + budget["date"] + "):",
        "",
        json.dumps(budget, indent=2),
        "",
        "Completed source rows: " + str(len(rows)) + "; non-F5 new rows: " + str(len(fresh)) + ".",
        "Rows labelled ok with repair errors are superseded too. Source files stay unchanged.",
        "",
        "Resume run-set: " + json.dumps(dict(families), sort_keys=True),
        "Preserved new answers: "
        + str(result["preserved_from_v2"])
        + "; carried S8 v1: "
        + str(result["carried_forward"]),
        "Fresh calls estimate/upper: "
        + str(result["fresh_calls_estimate"])
        + "/"
        + str(result["fresh_calls_upper"]),
        "Tokens estimate/upper (50% margin): "
        + str(result["reserved_tokens_estimate"])
        + "/"
        + str(result["reserved_tokens_upper"]),
        "No new answer quality is claimed; the new route has only fixture tests, not a live run.",
    ]
    text = "\n".join(lines) + "\n"
    (output / "README.md").write_text(text)
    assert sha(source) == before
    print(text)
    return report


if __name__ == "__main__":
    generate()
