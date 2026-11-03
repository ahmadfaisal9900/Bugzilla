"""Phase 6: deterministic scoring. F1-F4 and F6 are computed; F5 goes to a human.

No model judges anything here. Scores are computed only after predictions exist, and gold never
reaches a method.
"""
import math
import random
import re
from collections import defaultdict

from bugzilla_qa.methods.contract import NO_INTENT, OK, PARSE_ERROR

CORRECT = "CORRECT"
INCORRECT = "INCORRECT"
NEEDS_HUMAN = "NEEDS_HUMAN"
# The roadmap's tolerance for rounded answers. `exact` also records the gold's stricter tolerance.
DURATION_TOLERANCE_HOURS = 1.0
Z_95 = 1.959963984540054


def _normal(text):
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ids(value):
    if not isinstance(value, list) or any(isinstance(x, bool) for x in value):
        return None
    return {str(x).strip() for x in value}


def _result(item, answer, verdict, reason, **extra):
    return {"qid": item["qid"], "method": answer["method"], "family": item["family"],
            "gold_type": item["gold"]["type"], "verdict": verdict, "reason": reason, **extra}


def score(item, answer):
    assert item["qid"] == answer["qid"], "Answer scored against the wrong question"
    gold, kind = item["gold"], item["gold"]["type"]
    if answer["status"] != OK:
        return _result(item, answer, INCORRECT, answer["status"])
    if kind in ("unknown", "unanswerable"):
        if answer["abstained"] and answer["value"] is None:
            if item["family"] == "F5":
                return _result(item, answer, NEEDS_HUMAN, "f5_abstention_requires_context_review")
            return _result(item, answer, CORRECT, "correct_abstention")
        return _result(item, answer, INCORRECT, "answered_unanswerable")
    if answer["abstained"]:
        return _result(item, answer, INCORRECT, "false_abstention")
    if kind == "supported_explanation":
        return _result(item, answer, NEEDS_HUMAN, "human_graded_rubric")
    value = answer["value"]
    if kind == "string":
        right = value is not None and _normal(value) == _normal(gold["value"])
        return _result(item, answer, CORRECT if right else INCORRECT, "normalized_string")
    if kind == "integer":
        number = _number(value)
        right = number is not None and number == gold["value"]
        return _result(item, answer, CORRECT if right else INCORRECT, "exact_integer")
    if kind == "calendar_duration":
        hours = _number(value)
        if hours is None:
            return _result(item, answer, INCORRECT, "no_duration", exact=False)
        error = abs(hours - gold["hours"])
        return _result(item, answer, CORRECT if error <= DURATION_TOLERANCE_HOURS else INCORRECT, "duration_tolerance",
                       exact=error * 3600 <= gold["tolerance_seconds"])
    if kind == "id_set":
        got, want = _ids(value), {str(x) for x in gold["value"]}
        if got is None:
            return _result(item, answer, INCORRECT, "no_id_set", precision=0.0, recall=0.0, f1=0.0)
        hit = len(got & want)
        precision, recall = hit / len(got) if got else 0.0, hit / len(want) if want else 0.0
        f1 = 2 * precision * recall / (precision + recall) if hit else 0.0
        return _result(item, answer, CORRECT if got == want else INCORRECT, "complete_id_set",
                       precision=precision, recall=recall, f1=f1)
    raise ValueError("Unknown gold type: " + kind)


def wilson(successes, total):
    if not total:
        return None
    p, z2 = successes / total, Z_95 ** 2
    centre = (p + z2 / (2 * total)) / (1 + z2 / total)
    half = Z_95 * math.sqrt(p * (1 - p) / total + z2 / (4 * total ** 2)) / (1 + z2 / total)
    return [max(0.0, centre - half), min(1.0, centre + half)]


def summarize(results):
    """Per method and family. NEEDS_HUMAN stays out of the accuracy denominator and is reported."""
    cells = defaultdict(list)
    for r in results:
        cells[r["method"], r["family"]].append(r)
    table = []
    for (method, family), rows in sorted(cells.items()):
        graded = [r for r in rows if r["verdict"] != NEEDS_HUMAN]
        right = sum(r["verdict"] == CORRECT for r in graded)
        table.append({"method": method, "family": family, "questions": len(rows), "auto_scored": len(graded),
                      "correct": right, "accuracy": right / len(graded) if graded else None,
                      "wilson_95": wilson(right, len(graded)),
                      "needs_human": len(rows) - len(graded),
                      "false_abstentions": sum(r["reason"] == "false_abstention" for r in rows),
                      "correct_abstentions": sum(r["reason"] == "correct_abstention" for r in rows),
                      "answered_unanswerable": sum(r["reason"] == "answered_unanswerable" for r in rows),
                      "failed_to_answer": sum(r["reason"] in (NO_INTENT, PARSE_ERROR) for r in rows)})
    return table


def paired_bootstrap(results_a, results_b, seed=317, rounds=2000):
    """Accuracy difference a-b, resampling question IDs. Only questions both methods auto-scored."""
    a = {r["qid"]: r["verdict"] == CORRECT for r in results_a if r["verdict"] != NEEDS_HUMAN}
    b = {r["qid"]: r["verdict"] == CORRECT for r in results_b if r["verdict"] != NEEDS_HUMAN}
    shared = sorted(set(a) & set(b))
    if not shared:
        return None
    gaps = [a[q] - b[q] for q in shared]
    rng, n = random.Random(seed), len(gaps)
    means = sorted(sum(rng.choices(gaps, k=n)) / n for _ in range(rounds))
    return {"questions": n, "difference": sum(gaps) / n,
            "bootstrap_95": [means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1]]}
