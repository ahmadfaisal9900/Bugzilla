#!/usr/bin/env python3
"""Offline historical execute validation and the unchanged promotion-policy preview."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.tracking.backfill import answer_runs, read
from bugzilla_serving.tracking.policy import assess


def preview(plans):
    peers = [
        SimpleNamespace(
            info=SimpleNamespace(run_id=p["params"]["config_hash"]),
            data=SimpleNamespace(metrics=p["metrics"], tags=p["tags"]),
        )
        for p in plans
    ]
    policy = read(ROOT / "configs/promotion.yaml")
    result = []
    for plan, peer in zip(plans, peers):
        values = {}
        for k in RunConfig.model_fields:
            v = plan["params"][k]
            try:
                values[k] = json.loads(v)
            except (TypeError, ValueError):
                values[k] = v
        try:
            RunConfig(**values).validate_against()
            execute = dict(passes=True, reason="")
        except ValueError as exc:
            execute = dict(passes=False, reason=str(exc))
        assessment = assess(peer, peers, policy)
        result.append(
            dict(
                system=values["system_id"],
                execute=execute,
                policy=assessment,
                macro=plan["metrics"].get("answer.macro"),
                macro_excl_F5=plan["metrics"].get("answer.macro_excl_F5"),
            )
        )
    allowed = [r["system"] for r in result if r["execute"]["passes"] and r["policy"]["allowed"]]
    return dict(
        selected=allowed[0] if len(allowed) == 1 else None,
        systems=result,
        policy=policy,
        published=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=ROOT / "outputs/evaluation/phase11/pilot125")
    p.add_argument("--f5-gold", choices=["human", "llm"], default="human")
    p.add_argument("--f5-verdicts", type=Path)
    p.add_argument("--scorer-version", choices=["1", "2"], default="1")
    a = p.parse_args()
    plans, _ = answer_runs(
        a.source,
        "ledgers",
        f5_gold=a.f5_gold,
        f5_verdicts=a.f5_verdicts,
        scorer_version=a.scorer_version,
    )
    print(json.dumps(preview(plans), indent=2))


if __name__ == "__main__":
    main()
