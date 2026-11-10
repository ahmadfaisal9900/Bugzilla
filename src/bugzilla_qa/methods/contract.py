"""Define the answer format used by every method.

Keep failed responses separate from abstentions so failures cannot earn credit
on questions whose correct answer is unknown.
"""
import json
import math

OK = "OK"
NO_INTENT = "NO_INTENT"
PARSE_ERROR = "PARSE_ERROR"
MODEL_KEYS = {"answer", "abstained", "value", "evidence"}
EVIDENCE_KEYS = {"bug_id", "record_id", "url"}
ANSWER_SCHEMA = {
    "type": "object",
    "required": sorted(MODEL_KEYS),
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "abstained": {"type": "boolean"},
        "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"},
                            {"type": "array", "items": {"type": ["string", "integer"]}}]},
        "evidence": {"type": "array", "items": {
            "type": "object",
            "required": sorted(EVIDENCE_KEYS),
            "additionalProperties": False,
            "properties": {"bug_id": {"type": ["string", "integer", "null"]},
                           "record_id": {"type": ["string", "null"]}, "url": {"type": ["string", "null"]}},
        }},
    },
}


def make_answer(qid, method, text, abstained=False, value=None, evidence=(), status=OK, trace=None, raw=None):
    return {"qid": qid, "method": method, "answer": text, "abstained": abstained, "value": value,
            "evidence": list(evidence), "status": status, "trace": trace, "raw": raw}


def _valid_value(value):
    if value is None or isinstance(value, str):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return isinstance(value, list) and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in value)


def _valid_evidence(evidence):
    return isinstance(evidence, list) and all(isinstance(e, dict) and set(e) == EVIDENCE_KEYS for e in evidence)


def parse_model_output(qid, method, raw):
    """Strict JSON only. The raw text is kept for audit whether or not it parses."""
    failed = make_answer(qid, method, "", status=PARSE_ERROR, raw=raw)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return failed
    if not isinstance(data, dict) or set(data) != MODEL_KEYS:
        return failed
    text, abstained, value, evidence = data["answer"], data["abstained"], data["value"], data["evidence"]
    if not isinstance(text, str) or not isinstance(abstained, bool):
        return failed
    if not _valid_value(value) or not _valid_evidence(evidence) or (abstained and value is not None):
        return failed
    return make_answer(qid, method, text, abstained, value, evidence, raw=raw)
