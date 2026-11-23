"""Bounded offline B7b reports; writes only new analysis outputs."""

import csv
import difflib
import json
from collections import Counter
from pathlib import Path

from bugzilla_qa.evaluation.review import plain
from bugzilla_serving.experiments.scorer_v2 import exclusions
from bugzilla_serving.tracking.backfill import (
    _ledger_scores,
    answer_runs,
    discover_ledgers,
    load_dev_items,
    read,
    review_rows,
)
from bugzilla_serving.tracking.f5_gold import load_verdicts


def generate(root):
    root = Path(root)
    source = root / "outputs/evaluation/phase11/pilot125"
    output = root / "outputs/analysis/b7b"
    output.mkdir(parents=True, exist_ok=True)
    reviews = review_rows(source, include_all=True)
    dirs = discover_ledgers(source, root)
    f5 = load_verdicts(reviews, root / "outputs/mlops/f5_gold/verdicts.jsonl")
    omit = set(exclusions()["qids"])
    scores = {}
    for version in ("1", "2"):
        raw, _, _, _ = _ledger_scores(reviews, dirs, root, source, f5, version)
        scores[version] = {
            (system, r["dataset"], r["qid"]): r
            for system, rows in raw.items()
            for r in rows
            if r["qid"] not in omit
        }
    table = [
        "| System | F1 | F2 | F3 | F4 | F5 | F6 | KI | MH | F6H |",
        "| --- | " + " | ".join(["---:"] * 9) + " |",
    ]
    for system in [f"S{i}" for i in range(9)]:
        cells = []
        for family in ("F1", "F2", "F3", "F4", "F5", "F6", "KI", "MH", "F6H"):
            cells.append(
                "→".join(
                    str(
                        sum(
                            r["verdict"] == "CORRECT"
                            for key, r in scores[v].items()
                            if key[0] == system and r["family"] == family
                        )
                    )
                    for v in ("1", "2")
                )
            )
        table.append("| " + system + " | " + " | ".join(cells) + " |")
    changes = []
    for key, new in scores["2"].items():
        old = scores["1"][key]
        if old["verdict"] != new["verdict"]:
            changes.append(
                dict(
                    system=key[0],
                    dataset=key[1],
                    qid=key[2],
                    family=new["family"],
                    old=old["verdict"],
                    new=new["verdict"],
                    rules="+".join(new["normalization_rules"]),
                )
            )
    with (output / "changed_rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["system", "dataset", "qid", "family", "old", "new", "rules"]
        )
        writer.writeheader()
        writer.writerows(changes)
    items, _ = load_dev_items(root, read(root / "configs/retrieval_v3.yaml"), "phase05")
    claims = {i["qid"]: plain(i["expected"]) for i in items if i["family"] == "F5"}
    comparisons = []
    for qid in sorted(claims):
        row = next(r for r in reviews if r["qid"] == qid)
        ref = row["reference_answer"]
        comparisons.append(
            dict(
                qid=qid,
                equal=ref == claims[qid],
                diff="\n".join(
                    difflib.unified_diff(
                        claims[qid].splitlines(),
                        ref.splitlines(),
                        fromfile="frozen claim",
                        tofile="grading reference",
                        lineterm="",
                    )
                ),
            )
        )
    # Audit TOOL is a primary diagnosis; expose all coexisting saved error strings/results.
    audit = list(csv.DictReader((root / "outputs/analysis/failure_audit/audit.csv").open()))
    errors = Counter()
    for row in audit:
        if row["cause"] != "TOOL":
            continue
        events = set(json.loads(row["error"]))
        for result in json.loads(row["tool_results"]):
            if result.get("error"):
                events.add("tool_result:" + str(result["error"]))
            if result.get("known") is False:
                events.add("known=false:" + result.get("reason", ""))
        for event in events or {"No saved error message"}:
            errors[event] += 1
    plans, _ = answer_runs(source, "ledgers", root, f5_gold="llm", scorer_version="2")
    from scripts.preview_promotion import preview

    policy = preview(plans)
    summary = dict(
        state="OFFLINE_RESCORED",
        actual_api_calls=0,
        exclusion_version="f3_test_scope_v1",
        scored_questions=122,
        changed_rows=len(changes),
        f5_comparison=comparisons,
        tool_error_breakdown=dict(errors),
        promotion=policy,
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("\n".join(table))
    print("F5 frozen claim comparison:")
    print("| qid | equal |\n| --- | --- |")
    for c in comparisons:
        print(f"| {c['qid']} | {'yes' if c['equal'] else 'no'} |\n" + c["diff"])
    print("TOOL error breakdown (row incidence; overlaps allowed):")
    for error, n in sorted(errors.items()):
        print(f"{n}: {error}")
    print("Changed rows:")
    for c in changes:
        print(json.dumps(c))
    print("Promotion selected:", policy["selected"])
    (output / "score_table.md").write_text("\n".join(table) + "\n")
    return summary


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[3])
