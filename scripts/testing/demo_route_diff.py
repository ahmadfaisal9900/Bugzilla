#!/usr/bin/env python3
"""Compare router rules on the fixed dev roster, without calling a classifier."""

import argparse
import datetime as dt
import json
from pathlib import Path

from bugzilla_qa.answering_v2.graph import route_v2
from bugzilla_serving.experiments.data import load_eval_set
from bugzilla_serving.routing import route_serving


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=122)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 122:
        parser.error("--limit must be 1..122")
    if args.dry_run:
        print(
            json.dumps(dict(state="DRY_RUN", roster="pilot122-v2", limit=args.limit, llm_calls=0))
        )
        return
    items, _ = load_eval_set("pilot122-v2", args.limit)
    changed = []
    for row in items:
        old, new = route_v2(row["question"]), route_serving(row["question"])
        if old != new:
            changed.append(
                dict(
                    dataset=row["dataset"],
                    qid=row["qid"],
                    question=row["question"],
                    old_route=old[0],
                    old_rule=old[1],
                    new_route=new[0],
                    new_rule=new[1],
                )
            )
    result = dict(
        state="COMPLETE",
        utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        n=len(items),
        changes=changed,
        llm_calls=0,
        limitation="Old null routes require a classifier; actual old LLM routes are unknown.",
    )
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
