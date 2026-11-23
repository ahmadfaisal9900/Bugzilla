"""Bounded, offline diagnosis of the existing development pilot (no inference)."""

import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

from bugzilla_qa.evaluation import systems as scorer
from bugzilla_serving.tracking.backfill import (
    _ledger_scores,
    discover_ledgers,
    load_dev_items,
    read,
    review_rows,
    sha,
)
from bugzilla_serving.tracking.f5_gold import load_verdicts

FAMILIES = ("F2", "F3", "F5", "MH")
CAUSES = ("SCORER", "GOLD", "SCOPE", "RETRIEVAL", "ABSTAIN", "REASONING", "TOOL")


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def record_ids(chunks):
    """C1:<source record ID>:<segment> is the corpus's explicit chunk identity."""
    return {c.split(":", 1)[1].rsplit(":", 1)[0] for c in chunks if c.startswith("C1:")}


def numeric_candidate(item, answer):
    """Diagnostic only; never changes a scorer verdict, run or ledger."""
    value = answer.get("answer")
    rule = []
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
        rule.append("singleton")
    if isinstance(value, bool) or value is None:
        return None, []
    unit = answer.get("answer_type", "").lower()
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*(hours?|hrs?|days?|bugs?)?\s*", value)
        if not match:
            return None, []
        value = match[1]
        if match[2]:
            unit = match[2]
            rule.append("explicit_units")
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None, []
    if not math.isfinite(value):
        return None, []
    if item["kind"] in ("calendar_duration", "calendar_hours"):
        if unit in ("days", "day", "calendar_days"):
            value *= 24
        elif unit not in ("hours", "hour", "hrs", "hr", "calendar_hours", "calendar_duration"):
            if not re.search(r"\bhours?\b", item["question"], re.I):
                return None, []
            rule.append("question_hours_unit")
    return value, rule


def primary_cause(item, pred, correct, hit):
    """One primary diagnosis, in documented priority order; retain trace qualifiers."""
    if correct:
        return "", "Existing verdict retained"
    scope = item["scope"].get("original_scope", item["scope"])
    if scope.get("partition") == "test":
        return (
            "GOLD",
            "Dev-labeled aggregate retains test-population scope; conflicts with dev-only v2",
        )
    answer = pred.get("answer", {})
    if item["kind"] in ("integer", "calendar_duration", "calendar_hours"):
        value, rules = numeric_candidate(item, answer)
        tolerance = 1 if item["kind"] != "integer" else 0
        if value is not None and rules and abs(value - item["expected"]) <= tolerance:
            return "SCORER", "Numerically matches gold after " + "+".join(rules)
    tools = pred.get("tools", [])
    if item["family"] == "MH" and any(
        t.get("name") == "get_links" and t.get("arguments", {}).get("link_type") == "blocks"
        for t in tools
    ):
        return (
            "SCOPE",
            "Outgoing blocks queried for incoming blockers; empty result cannot prove none",
        )
    if any(
        t.get("result", {}).get("error")
        or t.get("result", {}).get("known") is False
        or t.get("result", {}).get("targets") == []
        for t in tools
    ):
        return "TOOL", "Saved tool error, unknown target or empty result (see exact trace)"
    if pred.get("status") != "ok" or any(
        "rejected tool call" in e or "provider_failure" in e for e in pred.get("errors", [])
    ):
        return (
            "TOOL",
            "Recorded execution/provider/tool-call rejection; no successful evidence path",
        )
    if item["family"] == "F3":
        counts = [t["result"].get("count") for t in tools if t.get("name") == "count_bugs"]
        if counts and item["expected"] in counts:
            return (
                "ABSTAIN" if answer.get("abstain") else "REASONING"
            ), "Correct count in saved tool result"
        return (
            "SCOPE",
            "No scoped aggregate result supplied; top-k passages cannot establish population count",
        )
    if not hit:
        return (
            "RETRIEVAL",
            "At least one gold record absent from final prompt IDs; record presence is necessary",
        )
    if answer.get("abstain"):
        return (
            "ABSTAIN",
            "All gold record IDs reached prompt but answer declined; truncation may still matter",
        )
    return (
        "REASONING",
        "All gold record IDs reached prompt; answer wrong; inspect text/truncation caveat",
    )


def table(rows):
    counts = Counter((r["cause"], r["family"], r["system"]) for r in rows if r["cause"])
    lines = [
        "| Cause | Family | " + " | ".join(scorer.SYSTEMS) + " | Total |",
        "| --- | --- | " + " | ".join(["---:"] * 10) + " |",
    ]
    for cause in CAUSES:
        for family in FAMILIES:
            values = [counts[cause, family, s] for s in scorer.SYSTEMS]
            lines.append(
                f"| {cause} | {family} | " + " | ".join(map(str, values + [sum(values)])) + " |"
            )
    return "\n".join(lines)


def build(root, source, output, verdicts):
    root, source, output = Path(root), Path(source), Path(output)
    reviews = review_rows(source, include_all=True)
    directories = discover_ledgers(source, root)
    if set(directories) != {"natural", "phase05", "v3"}:
        raise ValueError("Exact pilot ledger provenance required")
    selection = read(source / "pilot125_selection.json")["qids"]
    expected_roster = {(d, q) for d, ids in selection.items() for q in ids}
    actual_roster = {(r["dataset"], r["qid"]) for r in reviews}
    if actual_roster != expected_roster or len(actual_roster) != 125:
        raise ValueError("Review roster differs from exact pilot125 selection")
    f5 = load_verdicts(reviews, verdicts)
    scores, _, _, pins = _ledger_scores(reviews, directories, root, source, f5)
    score_map = {(r["dataset"], s, r["qid"]): r for s, rs in scores.items() for r in rs}
    roster = {(r["dataset"], r["qid"]) for r in reviews}
    review_map = {(r["dataset"], r["system_id"], r["qid"]): r for r in reviews}
    rows = []
    for dataset, directory in sorted(directories.items()):
        items, item_pins = load_dev_items(root, read(root / "configs/retrieval_v3.yaml"), dataset)
        pins.update(item_pins)
        selected, _, prediction_pins = scorer.select_predictions(directory, items, scorer.SYSTEMS)
        pins.update(prediction_pins)
        for item in items:
            if item["family"] not in FAMILIES or (dataset, item["qid"]) not in roster:
                continue
            if item["split"] != "dev":
                raise ValueError("Non-dev row refused")
            refs = [e["id"] if isinstance(e, dict) else e for e in item["evidence"]]
            for system in scorer.SYSTEMS:
                pred = selected[system].get(item["qid"], {})
                result = score_map[dataset, system, item["qid"]]
                if result["verdict"] not in ("CORRECT", "INCORRECT"):
                    raise ValueError("Unresolved score: " + item["qid"])
                review = review_map[dataset, system, item["qid"]]
                retrieved = pred.get("retrieved_chunk_ids", [])
                context = pred.get("context_chunk_ids", [])
                in_prompt = record_ids(context)
                hit = bool(refs) and set(refs) <= in_prompt
                answer = pred.get("answer", {})
                correct = result["verdict"] == "CORRECT"
                cause, note = primary_cause(item, pred, correct, hit)
                value, rules = numeric_candidate(item, answer)
                normal = value if rules and value is not None else answer.get("answer")
                row = dict(
                    qid=item["qid"],
                    family=item["family"],
                    dataset=dataset,
                    system=system,
                    route=pred.get("route"),
                    abstained=answer.get("abstain"),
                    raw_answer=encoded(pred.get("raw_output")),
                    normalised_answer=encoded(normal),
                    gold=encoded(item["expected"]),
                    grading_reference=review.get("reference_answer", ""),
                    grading_reason=f5.get(review["review_id"], {}).get("reason", ""),
                    scored_correct=correct,
                    retrieved_chunk_ids=encoded(retrieved),
                    evidence_hit=hit,
                    tool_calls=encoded(
                        [
                            {k: t.get(k) for k in ("name", "arguments")}
                            for t in pred.get("tools", [])
                        ]
                    ),
                    tool_results=encoded([t.get("result") for t in pred.get("tools", [])]),
                    error=encoded(pred.get("errors", [])),
                    cause=cause,
                    diagnosis=note,
                    question=item["question"],
                    answer=encoded(answer.get("answer")),
                    rationale=answer.get("rationale", ""),
                    gold_evidence_record_ids=encoded(refs),
                    context_chunk_ids=encoded(context),
                    retrieved_evidence_hit=bool(refs) and set(refs) <= record_ids(retrieved),
                    evidence_any_hit=bool(set(refs) & in_prompt),
                    evidence_applicable=bool(refs),
                    source_verdict=result["source_verdict"],
                    score_reason=result["reason"],
                    review_id=review["review_id"],
                    population=item["scope"].get("original_scope", item["scope"]).get("partition"),
                )
                rows.append(row)
    if len(rows) != 333 or len({(r["dataset"], r["qid"]) for r in rows}) != 37:
        raise ValueError("Expected fixed 37-question / 333-row pilot audit")
    if any((not r["scored_correct"]) != (r["cause"] in CAUSES) for r in rows):
        raise ValueError("Each incorrect row requires exactly one cause")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    corpus = root / "serving_bundle/indexes/C1/corpus.jsonl"
    observation = dict(state="UNAVAILABLE", scope="Current corpus, not historical prompt replay")
    if corpus.is_file():
        targets = {
            ref
            for r in rows
            if r["family"] == "F5"
            for ref in json.loads(r["gold_evidence_record_ids"])
        }
        found, in_text = set(), set()
        with corpus.open(encoding="utf-8") as stream:
            for line in stream:
                chunk = json.loads(line)
                ref = chunk["record_id"]
                if ref in targets and chunk.get("visibility") == "public":
                    found.add(ref)
                    if ref in chunk["text"]:
                        in_text.add(ref)
        pins[str(corpus)] = sha(corpus)
        observation.update(
            state="INSPECTED",
            target_records=len(targets),
            public_records_found=len(found),
            full_hash_in_text=len(in_text),
        )
    (output / "comment_lookup.json").write_text(encoded(observation) + "\n")
    pins[str(Path(verdicts))] = sha(verdicts)
    for name in ("START_HERE.html", "REVIEW.csv", "pilot125_selection.json", "latest.json"):
        pins[str(source / name)] = sha(source / name)
    (output / "provenance.json").write_text(encoded(pins) + "\n")
    return rows


def report(root, rows):
    """Render observed examples and copy the generator paths verbatim."""
    counts = Counter(r["cause"] or "CORRECT" for r in rows)
    observation = read(root / "outputs/analysis/failure_audit/comment_lookup.json")
    text = [
        "# B7 development pilot failure audit",
        "",
        "Completed Part 1 only. **STOP: the audit contradicts the proposed implementation plan.**",
        "No inference, remote tracking, LangSmith, or model calls were made. No gold, ledger, "
        "research source, contracts, or existing staged work was changed. This is a pilot "
        "diagnosis, not a new evaluation or proof of future accuracy.",
        "",
        "## Expected → found",
        "",
        "| Expected | Found |",
        "| --- | --- |",
        "| Project / feature/mlops | Existing root and branch confirmed; "
        "substantial B6 staged edits preserved |",
        "| B contracts, tracking, experiments, dashboard, fixtures | Present; reused |",
        "| Exact pilot provenance | Three exact manifest-referenced dev ledgers "
        "verified; 125 × 9 review identities |",
        "| Four affected families | F2=8, F3=15, F5=6, MH=8; 37 questions × 9 = 333 rows |",
        "| Partition-blind count tool | **Contradicted:** existing count uses "
        "sample_membership, conflict exclusions and frozen partition functions |",
        "| Lifecycle arithmetic absent | **Contradicted:** existing "
        "get_lifecycle returns computed first_fixed_hours and verified-history safeguards |",
        "| Dev-only populations | **Contradicted:** three v3 dev-labeled F3 "
        "items retain original_scope.partition=test |",
        "| Historical runtime available | official_runtime absent; ledger "
        "IDs/results preserved; historical prompt text cannot be fully replayed |",
        "",
        "## Stop findings",
        "",
        "`src/bugzilla_qa/answering/tools.py:101–134` already restricts cohort membership, "
        "excludes metadata conflicts and applies `phase05.partition` or `bank.partition`. "
        "`answering/sources.py:60–62` injects the declared partition scheme. In the saved trace, "
        "natural_14dea18947f819a165f2 S7/S8 count_bugs returns count=29, partition=dev; the "
        "answer is [29]. The whole-cohort hypothesis does not explain this failure.",
        "",
        "`answering/tools.py:136–157` already computes elapsed hours through classify_first_fixed. "
        "For natural_45e9307006cfa002436c, S7 returns first_fixed_hours=9316.653055555555 "
        "and emits that value as a singleton array. A new lifecycle arithmetic implementation "
        "would duplicate existing capability.",
        "",
        "The dev-labeled F3 scope conflicts are `v3_32a15a37c79becf4fcfa7085`, "
        "`v3_3e67864a44bf9484ad5f5a8a`, and `v3_f0f6f6f8844506e3e480ec86`. "
        "Their original aggregate population is the expanded-v2 test partition (denominator 2118). "
        "They are present in dev release files; no test-split file was decoded. This audit retains "
        "those existing dev rows for fidelity, flags the scope conflict, and does not recompute "
        "test populations. A dev-only v2 refusing test populations cannot "
        "answer all 37 as planned. "
        "GOLD here means a question/scope-policy conflict, **not proven erroneous numeric gold**. "
        "The one existing correct row remains correct and still carries population=test.",
        "",
        "## Scoring and attribution protocol",
        "",
        "Scores reuse the existing manifest/hash-checked backfill, balanced-pending-v1 failure "
        "policy and all 54 fingerprint-verified saved f5-semantic-v1 verdicts. CORRECT rows "
        "have blank cause. Every other row has exactly one primary cause. F2 source "
        "NEEDS_HUMAN/ambiguous_duration_unit is incorrect under the established failure policy, "
        "with source_verdict and score_reason retained. F5 verdicts are model judgments against "
        "the supplied reference, not independent source verification.",
        "",
        "Priority: dev/test-population conflict → demonstrably matching numeric format → "
        "incoming/outgoing scope mismatch → recorded tool/error path → unavailable aggregate "
        "scope → missing prompt evidence → abstention with evidence → reasoning with evidence. "
        "These are reproducible **primary diagnoses inferred from saved "
        "traces**, not experimentally "
        "isolated causes. Error lists and complete tool results preserve coexisting problems. "
        "For example, a matching [0] can be SCORER even if the wrong link direction also occurred; "
        "fixing its format does not validate its evidence.",
        "",
        "`raw_answer` stores raw_output; `answer` is the final answer value. normalised_answer "
        "is diagnostic only (singleton numeric unwrapping, explicit numeric units, or an hours "
        "unit stated by the question); it never changes scored_correct. No scorer v2 was applied. "
        "Wrong numbers remain wrong; duration comparisons use the existing one-hour tolerance.",
        "",
        "`retrieved_chunk_ids` is the original retrieval field; "
        "`context_chunk_ids` is what reached "
        "the final prompt. C1:<record_id>:<segment> maps chunk IDs to records "
        "by the existing corpus "
        "identity. evidence_hit requires a nonempty gold record set and **all** "
        "IDs in final context; "
        "retrieved_evidence_hit and evidence_any_hit are separate. Empty gold sets are N/A "
        "(evidence_applicable=false), never vacuous hits. Tool answers can have a correct computed "
        "count without population-record IDs. Population receipts are provenance, not enumerable "
        "passages: their absence alone is not a retrieval failure. ID presence cannot establish "
        "that a truncated passage contained every required fact. Historical runtime is absent, "
        "so ABSTAIN/REASONING with evidence means record presence, with this explicit limitation.",
        "",
        "## Cause × family × system",
        "",
        table(rows),
        "",
        f"Total: {len(rows)} rows; {counts['CORRECT']} correct; {len(rows) - counts['CORRECT']} "
        f"incorrect.",
        "",
        "## Real examples (two per observed cause)",
    ]
    for cause in CAUSES:
        candidates = [r for r in rows if r["cause"] == cause]
        chosen = []
        for r in candidates:
            if r["qid"] not in {x["qid"] for x in chosen}:
                chosen.append(r)
            if len(chosen) == 2:
                break
        if len(chosen) < 2:
            chosen += [r for r in candidates if r not in chosen][: 2 - len(chosen)]
        text += ["", f"### {cause}", ""]
        if not chosen:
            text.append("No observed rows; no examples fabricated.")
        for r in chosen:
            text += [
                f"- **{r['dataset']} / {r['qid']} / {r['system']}**: {r['question']}",
                f"  Gold: `{r['gold']}`. Answer: `{r['answer']}`.",
                f"  Grading reference: {r['grading_reference']}",
                f"  Gold evidence IDs: `{r['gold_evidence_record_ids']}`.",
                f"  Prompt chunk IDs: `{r['context_chunk_ids']}`.",
                f"  Diagnosis: {r['diagnosis']}. Rationale: {r['rationale']}",
            ]
    text += [
        "",
        "## F3 gold computation — copied generator code",
        "",
        "Phase 5: sampled canonical bugs joined to sample_membership/source_records; "
        "metadata-conflict parents excluded. SHA256(seed, bug_id) modulo 5 assigns dev=0. "
        "The dev population denominator is 592. Count DISTINCT canonical IDs in that "
        "population filtered by component, snapshot status or filing year; SQL must equal "
        "the independently constructed Python ID set. Full code below.",
        "",
    ]
    for path, start, end in (
        ("src/bugzilla_qa/benchmark/phase05.py", 53, 56),
        ("src/bugzilla_qa/benchmark/phase05.py", 248, 265),
        ("src/bugzilla_qa/benchmark/phase05.py", 345, 377),
        ("src/bugzilla_qa/eval_extension/bank.py", 14, 15),
        ("src/bugzilla_qa/eval_extension/bank.py", 69, 91),
        ("src/bugzilla_qa/eval_extension/bank.py", 109, 137),
    ):
        text += [
            f"`{path}:{start}–{end}` (verbatim):",
            "",
            "```python",
            "\n".join((root / path).read_text().splitlines()[start - 1 : end]),
            "```",
            "",
        ]
    text += [
        "Expanded-v2: sample_membership seed=317, non-conflicted canonical "
        "records whose normalized "
        "fields/hash match; SHA256([seed,'expanded-v2',str(bug)])[:12] modulo 10 <3 is dev. "
        "The 882-ID dev population is counted by component/status/resolution/filing year. "
        "Natural questions preserve this population; v3 F3 preserves original_scope, including "
        "three test-population aggregates despite its dev label. No population "
        "was recomputed here.",
        "",
        "## F5 reference production and grading",
        "",
        "The original Phase 5 generator (phase05.py:396–423) selects public CSV comments on "
        "FIXED-selected bugs, extracts an explicit-rationale candidate snippet and attaches "
        "a supported_explanation claim with an evidence ID. Freeze requires human rationale "
        "review/correction. The assisted-review protocol documents interactive model suggestions "
        "bound to comment/packet hashes; these are advice, not independent annotation.",
        "",
        "The pilot HTML/CSV contains six reference strings shared across systems. B6's semantic "
        "grader explicitly calls these LLM-written and not human-checked. The exact model, prompt "
        "and response provenance that wrote those six strings is **not recorded by the grading "
        "artifacts**; do not invent it or equate those strings with a newly verified gold source. "
        "Original frozen supported_explanation claims and the grading reference are distinct "
        "fields; audit.csv.gold retains the frozen claim; grading_reference and grading_reason "
        "retain the actual semantic grading reference and saved judge reason. "
        "No reference was regenerated.",
        "",
        "Research systems.grade returns NEEDS_HUMAN/explanation_review for F5. B6 "
        "experiments/f5_grade.py instead submits one question/reference and nine anonymous "
        "candidate answers per batch. Its instruction requires the same substantive reason, "
        "allows faithful paraphrase, rejects contradictions/generic overlap and rejects "
        "abstention when the reference gives a reason. Saved records identify "
        "openai/gpt-oss-20b, f5-semantic-v1, timestamp, reason and SHA256 fingerprint over "
        "review_id/dataset/qid/system/question/answer/reference. load_verdicts verifies all "
        "54 fingerprints and refuses partial coverage. Existing results: S5=1/6, S8=1/6, "
        "all other systems=0/6. No grading call occurred in this audit.",
        "",
        "Current corpus lookup observation (also saved in comment_lookup.json; corpus hash "
        "pinned in provenance.json): `" + encoded(observation) + "`. No comment text was copied "
        "by this lookup. This is separate from historical prompt evidence.",
        "",
        "The F5 question hash identifies the comment; exact gold record IDs measure access. "
        "Some S5/S8 prompts already contain that record and still fail: pinning the comment "
        "may reduce retrieval loss but is not sufficient evidence of a reasoning fix.",
        "",
        "## Top three supported fixes (estimates, not achieved results)",
        "",
    ]
    scorer_rows = [r for r in rows if r["cause"] == "SCORER"]
    mh = {r["qid"] for r in rows if r["family"] == "MH" and r["cause"] in ("SCOPE", "TOOL")}
    f5 = {r["qid"] for r in rows if r["family"] == "F5" and r["cause"] == "RETRIEVAL"}
    text += [
        "Implementation cost is an explicit rough relative unit (1=small adapter/tests, "
        "2=bounded route/tool extension); quota would be measured in 10K-token units. Ranking "
        "uses distinct affected questions/(cost+quota), **not promised questions fixed**. "
        "Actual fresh tokens cannot be established without the amended run plan "
        "and cache inspection.",
        "",
        "| Rank | Candidate | Distinct questions / answer rows | Cost | Quota | "
        "Opportunity ratio |",
        "| --- | --- | ---: | ---: | --- | --- |",
        f"| 1 | Versioned numeric-format scorer adapter | {len({r['qid'] for r in scorer_rows})} "
        f"/ {len(scorer_rows)} | 1 | 0 calls, 0 tokens | 13/1 = 13 |",
        f"| 2 | Direction-aware cohort-filtered MH target lookup | {len(mh)} / "
        f"trace-dependent | 2 | Requires bounded inference; unknown fresh tokens | ≤{len(mh)}/2 |",
        f"| 3 | Resolve/pin public cited F5 comment, preserving reference "
        f"provenance | {len(f5)} / trace-dependent | 2 | "
        f"Requires bounded inference; unknown fresh tokens | ≤{len(f5)}/2 |",
        "",
        "Only rank 1 has directly measurable format-only opportunities from saved answers. "
        "MH direction/cohort issues are primary on six questions, plus one secondary "
        "SCORER case; F5 access "
        "loss affects all six questions in at least one system, but existing evidence-present "
        "failures limit any guarantee. The two quota-dependent ranking positions are provisional. "
        "Do not invent a quota-normalized guarantee before a plan exists.",
        "",
        "## Re-score diff / remaining parts",
        "",
        "**Not applied.** No scorer_version=2, re-score, MLflow run, v2 "
        "tool/router, catalog change, "
        "held-out set, evaluation plan or snapshot rebuild was implemented: the binding stop "
        "condition was met. Original counts remain unchanged. SCORER diagnoses above are "
        "format-only opportunities, not a re-score diff. ORACLE already exists in the research "
        "graph; F3 population receipts and absent v3 aggregate evidence mean passage-only "
        "ORACLE cannot automatically supply complete aggregate gold evidence.",
        "",
        "## Open questions",
        "",
        "1. Should the three dev-labeled test-population aggregates be excluded from v2's "
        "development-only selection, with original gold/ledgers left intact?",
        "2. Approve an amended plan that reuses existing partition and lifecycle computation "
        "and starts with a versioned format adapter rather than duplicating those tools.",
        "3. Where is the creation provenance for the six LLM-written pilot grading references? "
        "Source-based validation must distinguish them from frozen human-reviewed claims.",
        "4. Restore the exact archived runtime/corpus hashes if byte-accurate historical "
        "prompt replay, rather than record-ID-level diagnosis, is required.",
    ]
    return "\n".join(text) + "\n"


def main():
    import argparse
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=37)
    parser.add_argument("--max-requests", type=int, default=0)
    args = parser.parse_args()
    if args.limit != 37 or args.max_requests != 0 or (args.apply and args.dry_run):
        parser.error("Fixed audit requires --limit 37 --max-requests 0; choose dry-run or apply")
    root = Path(__file__).resolve().parents[3]
    output = root / "outputs/analysis/failure_audit"
    started = datetime.now(timezone.utc).isoformat()
    summary = dict(
        state="DRY_RUN",
        questions=37,
        rows=333,
        actual_api_calls=0,
        max_requests=0,
        started_at=started,
        output=str(output),
        resume="Deterministic rebuild from immutable, hash-verified inputs; no API work",
        log_path=str(output / "audit.log"),
    )
    if args.apply:
        rows = build(
            root,
            root / "outputs/evaluation/phase11/pilot125",
            output,
            root / "outputs/mlops/f5_gold/verdicts.jsonl",
        )
        content = report(root, rows)
        (output / "README.md").write_text(content)
        (root / "docs/mlops/FAILURE_AUDIT.md").write_text(content)
        summary.update(
            state="COMPLETE_PART1_STOP",
            correct=sum(r["scored_correct"] for r in rows),
            incorrect=sum(not r["scored_correct"] for r in rows),
            causes=dict(Counter(r["cause"] for r in rows if r["cause"])),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        summary["checkpoint"] = sha(output / "provenance.json")
        (output / "summary.json").write_text(encoded(summary) + "\n")
        (output / "audit.log").write_text(encoded(summary) + "\n")
        print(table(rows))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
