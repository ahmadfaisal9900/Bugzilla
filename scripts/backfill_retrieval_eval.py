#!/usr/bin/env python3
"""Backfill saved dev retrieval aggregates; default zero-write dry-run."""

import argparse
import glob
import json
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.tracking.backfill import retrieval_runs
from bugzilla_serving.tracking.client import TrackingClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", default=[str(ROOT / "outputs/retrieval/v3/run-*")])
    parser.add_argument("--tracking-uri")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    dirs = sorted(
        {
            p
            for pattern in args.runs
            for p in glob.glob(pattern)
            if (Path(p) / "summary.json").exists()
        }
    )
    if not dirs:
        parser.error("No saved summaries found")
    plans = retrieval_runs(dirs)
    plans = plans[: args.limit] if args.limit else plans
    tracking = TrackingClient(args.tracking_uri) if args.apply else None
    table = []
    for plan in plans:
        rid = tracking.log_run(**plan) if tracking else None
        table.append(
            dict(
                retriever=plan["params"]["retriever"],
                corpus=plan["params"]["corpus"],
                run_id=rid,
                selected=plan["tags"]["selected"],
                metric_count=len(plan["metrics"]),
            )
        )
    print(json.dumps(dict(state="APPLIED" if args.apply else "DRY_RUN", runs=table), indent=2))


if __name__ == "__main__":
    main()
