"""Import saved semantic verdicts bound to existing dev references and answers."""

import hashlib
import json
from pathlib import Path

VERSION = "f5-semantic-v1"
DEFAULT_VERDICTS = Path("outputs/mlops/f5_gold/verdicts.jsonl")


def fingerprint(row):
    fields = {
        k: row.get(k)
        for k in (
            "review_id",
            "dataset",
            "qid",
            "system_id",
            "question",
            "model_answer",
            "reference_answer",
        )
    }
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def pending_rows(reviews):
    result = [r for r in reviews if r["family"] == "F5" and not r.get("answer_verdict", "").strip()]
    groups = {}
    for row in result:
        if not row.get("reference_answer", "").strip():
            raise ValueError("F5 row has no reference or verdict: " + row["review_id"])
        key = (row["dataset"], row["qid"])
        reference = groups.setdefault(key, row["reference_answer"])
        if reference != row["reference_answer"]:
            raise ValueError("F5 reference differs across systems")
    return result


def load_verdicts(reviews, path=DEFAULT_VERDICTS, *, require_complete=True):
    rows = pending_rows(reviews)
    expected = {r["review_id"]: r for r in rows}
    path = Path(path)
    if not path.is_file():
        raise ValueError(
            "Run the capped F5 grading job first; saved verdicts missing: " + str(path)
        )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    if any(r.get("packet_sha256") for r in records):
        from bugzilla_serving.experiments.f5_packet import validate_external

        validate_external(records)
        records = [r for r in records if r["review_id"] in expected]
    result = {}
    for row in records:
        rid = row["review_id"]
        if rid not in expected or rid in result:
            raise ValueError("Duplicate or out-of-scope F5 verdict")
        if row.get("fingerprint") != fingerprint(expected[rid]) or row.get("version") != VERSION:
            raise ValueError("F5 verdict is stale or bound to a different answer/reference")
        if (
            row.get("verdict") not in ("CORRECT", "INCORRECT")
            or not row.get("judge_model")
            or not row.get("reason")
        ):
            raise ValueError("Invalid saved LLM verdict/provenance")
        result[rid] = row
    if require_complete and result.keys() != expected.keys():
        raise ValueError(
            f"F5 verdict coverage incomplete: {len(result)}/{len(expected)}; no partial scoring"
        )
    return result
