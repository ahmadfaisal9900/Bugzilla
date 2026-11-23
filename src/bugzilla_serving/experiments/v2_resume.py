"""Immutable-ledger resume: preserve successful new answers, supersede failures."""

import json
from pathlib import Path

from bugzilla_serving.experiments.data import digest
from bugzilla_serving.tracking.backfill import read, sha


def selection(selected, run_keys, source=None):
    if source is None:
        return selected, run_keys, {}, {}
    source = Path(source)
    manifest = read(source.parent / "manifest.json")
    if manifest["system"] != "S8v2" or manifest["sha256"][source.name] != sha(source):
        raise ValueError("Resume source checksum/system mismatch")
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    allowed = {(i["dataset"], i["qid"]) for i in selected}
    if len({(p["dataset"], p["qid"]) for p in rows}) != len(rows):
        raise ValueError("Duplicate source predictions")
    if any(
        p.get("split") != "dev"
        or p.get("system_id") != "S8v2"
        or (p["dataset"], p["qid"]) not in allowed
        for p in rows
    ):
        raise ValueError("Out-of-scope resume source")
    prior = {(p["dataset"], p["qid"]): p for p in rows}
    keep = {
        k: p
        for k, p in prior.items()
        if p["status"] == "ok"
        and not p.get("carried_forward")
        and (p["family"] == "F5" or not p.get("errors"))
    }
    failures = {
        k: p
        for k, p in prior.items()
        if p["status"] != "ok" or (not p.get("carried_forward") and p.get("errors"))
    }
    failure_sources = {k: source.name for k in failures}
    attempts = source.parent / "attempts.jsonl"
    if attempts.exists():
        if sha(attempts) != manifest["sha256"].get(attempts.name):
            raise ValueError("Resume attempt ledger checksum mismatch")
        for p in map(json.loads, attempts.read_text().splitlines()):
            key = p["dataset"], p["qid"]
            if key not in allowed or p.get("split") != "dev" or p.get("system_id") != "S8v2":
                raise ValueError("Out-of-scope resume attempt")
            if (p["status"] != "ok" or p.get("errors")) and key not in keep:
                failures[key] = p
                failure_sources[key] = attempts.name
    keys = (run_keys | set(failures)) - set(keep)

    def order(item):
        key = item["dataset"], item["qid"]
        family = item["family"]
        stage = (
            0
            if family == "MH"
            else 1
            if key in failures and family in ("F2", "F3", "F4")
            else 2
            if family in ("F2", "F3", "F4")
            else 3
            if family == "F5"
            else 5
            if family in ("F1", "F6H")
            else 4
        )
        return stage, item["dataset"], item["qid"]

    info = dict(
        source_ledger=str(source),
        source_sha256=sha(source),
        preserved=len(keep),
        preserved_f5=sum(p["family"] == "F5" for p in keep.values()),
        superseded=[
            dict(
                dataset=k[0],
                qid=k[1],
                old_run_id=source.parent.name,
                old_row_sha256=digest(p),
                source_artifact=failure_sources[k],
                status="superseded",
                reason="native_tool_route_replaced_by_json_tools_v2",
            )
            for k, p in sorted(failures.items())
        ],
    )
    return sorted(selected, key=order), keys, keep, info


def seed_rows(path, selected, keep, identity, system, source):
    """Create only a new ledger; original prediction and attempt bytes stay fixed."""
    if path.exists():
        return
    rows = []
    for item in selected:
        key = item["dataset"], item["qid"]
        if key in keep:
            old = keep[key]
            rows.append(
                dict(
                    old,
                    config_hash=identity,
                    system_id=system,
                    preserved_from_v2=True,
                    source_run_id=Path(source).parent.name,
                    answer_source_config_hash=old.get(
                        "answer_source_config_hash", old["config_hash"]
                    ),
                    source_prediction_sha256=digest(old),
                    call_count=0,
                    llm_calls=0,
                    tokens=dict(input=0, output=0, usage_missing=False),
                )
            )
    if rows:
        temp = path.with_suffix(".seed.tmp")
        temp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        temp.replace(path)
