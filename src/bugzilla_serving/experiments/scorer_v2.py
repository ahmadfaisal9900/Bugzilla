"""Versioned format-only adapter. Frozen research scorer and ledgers stay untouched."""

import math
import re
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
VERSION = "2"


def exclusions(root=ROOT):
    return yaml.safe_load((Path(root) / "configs/scoring_exclusions.yaml").read_text())


def excluded(item, root=ROOT):
    scope = item.get("scope", {})
    scope = scope.get("original_scope", scope)
    return item["qid"] in exclusions(root)["qids"] or (
        item.get("family") == "F3" and scope.get("partition") == "test"
    )


def normalize(item, prediction):
    pred = deepcopy(prediction)
    rules = []
    if not pred or pred.get("status") != "ok":
        return pred, rules
    answer = pred.get("answer", {})
    if answer.get("abstain") or item["kind"] not in (
        "integer",
        "calendar_hours",
        "calendar_duration",
        "number",
        "float",
    ):
        return pred, rules
    value = answer.get("answer")
    if isinstance(value, list) and len(value) == 1 and type(value[0]) in (int, float):
        if math.isfinite(value[0]):
            value = value[0]
            rules.append("singleton_number")
    if isinstance(value, str):
        match = re.fullmatch(
            r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+(hours?|hrs?|days?|bugs?)\s*", value, re.I
        )
        if match:
            unit = match[2].lower()
            question = item["question"].lower()
            hours = unit in ("hour", "hours", "hr", "hrs")
            days = unit in ("day", "days")
            duration = item["kind"] in ("calendar_duration", "calendar_hours", "number", "float")
            matches = (
                (duration and hours and bool(re.search(r"\bhours?\b", question)))
                or (duration and days and bool(re.search(r"\bdays?\b", question)))
                or (
                    unit in ("bug", "bugs")
                    and item["kind"] == "integer"
                    and item.get("family") in ("F3", "MH")
                    and bool(re.search(r"\bbugs\b|\bbug ids\b|\bbug count\b", question))
                )
            )
            if matches:
                value = float(match[1])
                rules.append("explicit_matching_unit")
                if item["kind"] in ("calendar_duration", "calendar_hours"):
                    answer["answer_type"] = "days" if days else "hours"
    stated_hours = bool(
        re.search(r"\bin hours\b|\bhow many (?:calendar )?hours\b", item["question"], re.I)
    )
    if (
        item["kind"] in ("calendar_duration", "calendar_hours")
        and stated_hours
        and type(value) in (int, float)
        and math.isfinite(value)
        and answer.get("answer_type") in (None, "number", "integer", "float")
    ):
        answer["answer_type"] = "hours"
        rules.append("question_stated_hours")
    answer["answer"] = value
    return pred, rules


def grade(item, prediction):
    from bugzilla_qa.evaluation.systems import grade as legacy_grade

    if excluded(item):
        return dict(
            qid=item["qid"],
            dataset=item["dataset"],
            family=item["family"],
            cluster_id=item["cluster_id"],
            verdict="EXCLUDED",
            reason="f3_test_scope_v1",
            normalization_rules=[],
            scorer_version=VERSION,
        )
    pred, rules = normalize(item, prediction)
    answer = (pred or {}).get("answer", {})
    if (
        item["kind"] in ("calendar_duration", "calendar_hours")
        and re.search(r"\bin hours\b|\bhow many (?:calendar )?hours\b", item["question"], re.I)
        and answer.get("answer_type") in ("days", "calendar_days")
        and not answer.get("abstain")
        and pred.get("status") == "ok"
    ):
        # Preserve legacy contract/citation validation while preventing its days
        # conversion. This adapter never converts an incompatible unit.
        answer["answer_type"] = "incompatible_unit"
        result = legacy_grade(item, pred)
        if result["reason"] == "ambiguous_duration_unit":
            result.update(verdict="INCORRECT", reason="incompatible_duration_unit")
    else:
        result = legacy_grade(item, pred)
    return {**result, "normalization_rules": rules, "scorer_version": VERSION}
