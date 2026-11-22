"""Adapt shared AnswerRecords to the partner's saved-prediction scorer."""

from __future__ import annotations

import re

from bugzilla_serving.tracking.backfill import aggregate


def prediction(item, record, system_id):
    data = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
    return dict(
        qid=item["qid"],
        dataset=item["dataset"],
        split="dev",
        family=item["family"],
        freeze_id=item["freeze_id"],
        system_id=system_id,
        status="error" if data["errors"] else "ok",
        answer=data["answer"],
        context_chunk_ids=[e["chunk_id"] for e in data["evidence"]],
        config_hash=data["config_hash"],
        llm_calls=data["llm_calls"],
        tokens=data["tokens"],
        latency_ms=data["latency_ms"],
        errors=data["errors"],
        route=data["route"],
        route_rule=data["route_rule"],
    )


def fallback(item, pred):
    value = pred["answer"]["answer"]
    expected, family = item["expected"], item["family"]
    if family not in ("F1", "F3", "F4", "F6", "F6H", "KI"):
        return dict(verdict="NOT_SCORED", reason="unsupported_family")
    if pred["status"] != "ok":
        return dict(verdict="INCORRECT", reason="execution_failure")
    if family in ("F6", "F6H"):
        score = float(pred["answer"]["abstain"])
    elif pred["answer"]["abstain"]:
        return dict(verdict="INCORRECT", reason="false_abstention")
    elif family == "F1":

        def norm(v):
            return re.sub(r"\s+", " ", str(v).strip()).casefold()

        score = float(norm(value) == norm(expected))
    elif family == "F3":
        score = float(type(value) in (int, float) and value == expected)
    elif family == "F4":
        if not isinstance(value, list) or any(isinstance(x, bool) for x in value):
            score = 0.0
        else:
            got, wanted = set(map(str, value)), set(map(str, expected))
            score = 2 * len(got & wanted) / (len(got) + len(wanted)) if got or wanted else 1.0
    elif family == "KI":
        got = value if isinstance(value, list) else [value]
        score = float(len(got) == 1 and str(got[0]) in set(map(str, item["acceptable_bug_ids"])))
    else:
        return dict(verdict="NOT_SCORED", reason="unsupported_family")
    return dict(verdict="CORRECT" if score == 1 else "INCORRECT", reason="fallback", score=score)


def score_predictions(items, predictions, *, partner=True):
    scorer = None
    if partner:
        try:
            from bugzilla_qa.evaluation import systems as scorer
        except ImportError:
            pass
    results = []
    for item in items:
        if item.get("split") != "dev":
            raise ValueError("Scoring is dev-only")
        key = (item["dataset"], item["qid"])
        pred = predictions[key]
        if pred.get("split") != "dev":
            raise ValueError("Prediction is not dev")
        if scorer is not None:
            try:
                result = scorer.grade(item, pred)
                by = "bugzilla_qa.evaluation.systems"
            except ValueError as exc:
                if not str(exc).startswith("Unsupported gold type:"):
                    raise
                result, by = fallback(item, pred), "serving-fallback-v1"
            if result["verdict"] == "NEEDS_HUMAN":
                result["verdict"] = "NOT_SCORED"
        else:
            result, by = fallback(item, pred), "serving-fallback-v1"
        results.append(
            dict(
                result,
                family=item["family"],
                dataset=item["dataset"],
                qid=item["qid"],
                scorer=by,
                score=(
                    result.get("score", float(result["verdict"] == "CORRECT"))
                    if result["verdict"] != "NOT_SCORED"
                    else None
                ),
            )
        )
    metrics, families = aggregate(results)
    # Fallback relation scoring is explicitly set-F1, not exact correctness.
    for family in families:
        scored = [
            r
            for r in results
            if r["family"] == family["family"] and r["verdict"] in ("CORRECT", "INCORRECT")
        ]
        if scored:
            family["score"] = sum(r["score"] for r in scored) / len(scored)
            metrics[f"answer.{family['family']}.score"] = family["score"]
        family["scorer"] = ",".join(
            sorted({r["scorer"] for r in results if r["family"] == family["family"]})
        )
    if "answer.macro" in metrics:
        metrics["answer.macro"] = sum(f["score"] for f in families if f["scored_n"]) / sum(
            bool(f["scored_n"]) for f in families
        )
    metrics["fail.rate"] = sum(p["status"] != "ok" for p in predictions.values()) / len(items)
    for unknown, name in [(True, "correct"), (False, "false")]:
        subset = [
            i for i in items if (i["kind"] in ("unknown", "unanswerable", "abstain")) == unknown
        ]
        if subset:
            metrics[f"abstain.{name}_rate"] = sum(
                predictions[(i["dataset"], i["qid"])]["answer"]["abstain"] for i in subset
            ) / len(subset)
    return results, families, metrics
