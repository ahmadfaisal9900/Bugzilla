#!/usr/bin/env python3
"""Backfill saved dev scores. Default dry-run creates no MLflow client."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.tracking.backfill import answer_runs
from bugzilla_serving.tracking.client import TrackingClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "outputs/evaluation/phase11/pilot125")
    parser.add_argument("--mode", choices=["auto", "ledgers", "review-only"], default="auto")
    parser.add_argument("--f5-gold", choices=["human", "llm"], default="human")
    parser.add_argument("--f5-verdicts", type=Path)
    parser.add_argument("--tracking-uri")
    parser.add_argument("--scorer-version", choices=["1", "2"], default="1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--resume", action="store_true", help="Resume remote checkpoints (also enabled by default)"
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    plans, info = answer_runs(
        args.source,
        args.mode,
        f5_gold=args.f5_gold,
        f5_verdicts=args.f5_verdicts,
        scorer_version=args.scorer_version,
    )
    plans = plans[: args.limit] if args.limit else plans
    tracking = TrackingClient(args.tracking_uri) if args.apply else None
    table = []
    for index, plan in enumerate(plans, 1):
        prior = []
        if tracking and args.scorer_version == "2":
            prior = [
                r
                for r in tracking.runs(plan["experiment"])
                if r.data.tags.get("scorer_version", "1") == "1"
                and r.data.tags.get("source") == "backfill"
                and r.data.tags.get("eval_set") == plan["tags"]["eval_set"]
                and r.data.params.get("config_hash") == plan["params"]["config_hash"]
            ]
        rid = tracking.log_run(**plan) if tracking else None
        for old in prior:
            tracking.client.set_tag(old.info.run_id, "superseded_by", rid)
        if tracking:
            print(f"[{index}/{len(plans)}] {tracking.last_action}: {rid}", flush=True)
        table.append(
            dict(
                system=plan["params"]["system_id"],
                run_id=rid,
                metrics=plan["metrics"],
                tags=plan["tags"],
            )
        )
    print(
        json.dumps(dict(state="APPLIED" if args.apply else "DRY_RUN", **info, runs=table), indent=2)
    )


if __name__ == "__main__":
    main()
