"""Frozen dev-only experiment inputs; gold never enters engine calls."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

import yaml

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.tracking.backfill import load_dev_items, read


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def catalog(root=ROOT, retrieval_config=None):
    root = Path(root)
    config = retrieval_config or read(root / "configs/retrieval_v3.yaml")
    items, pins = [], {}
    for dataset in ("phase05", "natural", "v3"):
        rows, hashes = load_dev_items(root, config, dataset)
        if any(r.get("split") != "dev" or r.get("dataset") != dataset for r in rows):
            raise ValueError("Only verified dev items are permitted")
        items.extend(rows)
        pins.update(hashes)
    identities = [(r["dataset"], r["qid"]) for r in items]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate dev dataset/qid identity")
    from bugzilla_serving.experiments.scorer_v2 import excluded

    return [i for i in items if not excluded(i)], pins


def validate_members(members, items):
    available = {(r["dataset"], r["qid"]): r for r in items}
    seen, selected = set(), []
    for member in members:
        if set(member) != {"dataset", "qid"}:
            raise ValueError("Eval set entries contain only dataset and qid")
        key = (member["dataset"], member["qid"])
        if key not in available or available[key].get("split") != "dev":
            raise ValueError("Eval set qid is not in a verified dev file")
        if key in seen:
            raise ValueError("Duplicate eval set member")
        seen.add(key)
        selected.append(available[key])
    return selected


def make_sets(items, seed=317):
    if any(r.get("split") != "dev" for r in items):
        raise ValueError("Refusing non-dev input")
    groups = defaultdict(list)
    rng = random.Random(seed)
    for row in sorted(items, key=lambda r: (r["dataset"], r["qid"])):
        groups[row["family"]].append({"dataset": row["dataset"], "qid": row["qid"]})
    for rows in groups.values():
        rng.shuffle(rows)
    families = sorted(groups)
    rng.shuffle(families)
    # Round robin gives every available family a turn before adding a second item.
    stratified = [
        groups[f][i]
        for i in range(max(map(len, groups.values()), default=0))
        for f in families
        if i < len(groups[f])
    ]
    sets = {"smoke-5": stratified[:5], "smoke-20": stratified[:20]}
    sets.update({f"family-{f}": groups[f][:20] for f in sorted(groups)})
    for members in sets.values():
        validate_members(members, items)
    return {
        "version": 1,
        "seed": seed,
        "sets": {name: [dict(member) for member in members] for name, members in sets.items()},
    }


def load_eval_set(eval_set, limit=None, *, root=ROOT, sets_path=None):
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be positive")
    root = Path(root)
    spec = yaml.safe_load(Path(sets_path or root / "configs/eval_sets.yaml").read_text())
    if eval_set not in spec["sets"]:
        raise ValueError("Unknown eval set")
    items, pins = catalog(root)
    selected = validate_members(spec["sets"][eval_set], items)
    selected = selected[:limit] if limit else selected
    if not selected:
        raise ValueError("Eval set is empty")
    return selected, dict(
        input_sha256=pins,
        roster_hash=digest(
            [
                {"dataset": r["dataset"], "qid": r["qid"], "freeze_id": r["freeze_id"]}
                for r in selected
            ]
        ),
    )
